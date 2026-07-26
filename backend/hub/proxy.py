#!/usr/bin/env python3
"""CipherPipe — single-port Nostr bridge."""
import asyncio, json, logging, os, time
from datetime import datetime

import structlog
import websockets
from websockets.asyncio.server import serve
from websockets.http11 import Response as HTTPResponse
from websockets.datastructures import Headers

from backend.core.crypto import load_or_create_key, sign_event, verify_event, e2e_decrypt, to_nostr_pk
from backend.core.store import init_db, add_message, upsert_contact, get_state, set_state
from backend.network.relay import load_relays, select_best_relays
from backend.core.config import PORT, RELAYS as DEFAULT_RELAYS, KEY_FILE, PROJECT_DIR, FILE_MAX_SIZE
from backend.file.transfer import FileReceiver
from backend.hub.session import ClientSession
from backend.hub.handlers import HANDLERS, HubContext, on_binary_frame

LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

structlog.configure(
    processors=[structlog.stdlib.add_log_level, structlog.processors.TimeStamper(fmt="iso"), structlog.dev.ConsoleRenderer()],
    wrapper_class=structlog.stdlib.BoundLogger, context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(), cache_logger_on_first_use=True,
)
logger = structlog.get_logger("cipherpipe")
log_file = os.path.join(LOGS_DIR, f"cipherpipe-{datetime.now():%Y-%m-%d}.jsonl")
json_fh = logging.FileHandler(log_file); json_fh.setLevel(logging.DEBUG)
file_logger = logging.getLogger("cipherpipe.file"); file_logger.addHandler(json_fh); file_logger.setLevel(logging.DEBUG)
def log_event(ev, **kw): file_logger.info(json.dumps({"event":ev,"ts":time.time(),**kw},ensure_ascii=False))

RELAY_POOL = {}
EVENT_QUEUE = asyncio.Queue()
LAN_CLIENTS = {}
BROWSERS = set()
WATCHED_PUBKEYS = set()
file_receiver = FileReceiver(auto_accept=False)
SK = None
PUBKEY = None

# ── Nostr relay pool ──
async def relay_connect(url, sk):
    pubkey = sk.public_key.format().hex()
    while True:
        try:
            ws = await websockets.connect(url, ping_interval=20, ping_timeout=10)
            RELAY_POOL[url] = ws
            logger.info(f"Relay connected: {url}")
            log_event("relay_connected", url=url)
            since_ts = max(int(time.time()) - 86400, 0)
            last_ts = get_state("last_received_at")
            if last_ts:
                since_ts = min(since_ts, int(last_ts))
            watched = list(WATCHED_PUBKEYS) if WATCHED_PUBKEYS else [pubkey]
            await ws.send(json.dumps(["REQ", "cp_sub", {"kinds": [0, 4, 5, 7, 1059], "#p": watched, "since": since_ts}]))
            async def _process_event(event):
                if not verify_event(event):
                    log_event("relay_event_bad_sig", id=event.get("id","")[:16])
                    return
                kind = event["kind"]
                if kind == 0: await _handle_profile(event); return
                if kind == 5: await _handle_deletion(event); return
                if kind == 7: await _handle_reaction(event); return
                if kind in (4, 1059):
                    try:
                        pt = e2e_decrypt(sk, event["pubkey"], event["content"])
                        parsed = _parse(pt)
                        await EVENT_QUEUE.put({"event_id": event["id"], "pubkey": event["pubkey"],
                            "text": pt, "msg_type": parsed.get("type", "msg"), "parsed": parsed, "created_at": event["created_at"]})
                        log_event("relay_msg_decrypted", from_pk=event["pubkey"][:16], text=pt[:100])
                        set_state("last_received_at", event["created_at"])
                        try:
                            add_message(event["id"], event["pubkey"], pt, "in", created_at=event["created_at"])
                        except Exception as e:
                            log_event("relay_db_write_fail", error=str(e)[:80])
                    except Exception as e:
                        log_event("relay_decrypt_fail", from_pk=event["pubkey"][:16], error=str(e)[:80])

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    if msg[0] == "EVENT" and msg[1] == "cp_sub":
                        event = msg[2]
                        log_event("relay_event_rcv", id=event.get("id","")[:16], kind=event.get("kind"), pubkey=event.get("pubkey","")[:16])
                        asyncio.create_task(_process_event(event))
                        await asyncio.sleep(0)
                    elif msg[0] == "NOTICE":
                        log_event("relay_notice", message=str(msg)[:200])
                except Exception:
                    pass
        except Exception as e:
            RELAY_POOL.pop(url, None)
            logger.warning(f"Relay {url}: {e}")
            await asyncio.sleep(5)

def _parse(text):
    try:
        d = json.loads(text)
        if isinstance(d, dict) and "type" in d: return d
    except Exception: pass
    return {"type": "msg"}

async def _handle_profile(event):
    try:
        p = json.loads(event["content"])
        upsert_contact(event["pubkey"], display_name=p.get("name",""), about=p.get("about",""), picture=p.get("picture",""), nip05=p.get("nip05",""), last_seen=int(time.time()))
    except Exception: pass

async def _handle_deletion(event):
    for tag in event.get("tags", []):
        if tag[0] == "e":
            await EVENT_QUEUE.put({"event_id": event["id"], "pubkey": event["pubkey"], "text": "", "msg_type": "deletion", "parsed": {"type": "deletion", "target_id": tag[1]}})
            break

async def _handle_reaction(event):
    for tag in event.get("tags", []):
        if tag[0] == "e":
            await EVENT_QUEUE.put({"event_id": event["id"], "pubkey": event["pubkey"], "text": event["content"], "msg_type": "reaction", "parsed": {"type": "reaction", "target_id": tag[1], "emoji": event["content"]}})
            break

async def start_relay_pool(sk):
    relays = load_relays()
    best = await select_best_relays(relays)
    for url in best:
        asyncio.create_task(relay_connect(url, sk))
    async def periodic():
        while True:
            await asyncio.sleep(300)
            for url in await select_best_relays(relays):
                if url not in RELAY_POOL:
                    asyncio.create_task(relay_connect(url, sk))
    asyncio.create_task(periodic())

async def nostr_publish(event):
    msg = json.dumps(["EVENT", event])
    for url, ws in list(RELAY_POOL.items()):
        try: await ws.send(msg)
        except Exception: RELAY_POOL.pop(url, None)

async def resubscribe_all():
    """Re-send REQ to all relays with current WATCHED_PUBKEYS."""
    since_ts = max(int(time.time()) - 86400, 0)
    last_ts = get_state("last_received_at")
    if last_ts:
        since_ts = min(since_ts, int(last_ts))
    watched = list(WATCHED_PUBKEYS)
    req = json.dumps(["REQ", "cp_sub", {"kinds": [0, 4, 5, 7, 1059], "#p": watched, "since": since_ts}])
    for url, ws in list(RELAY_POOL.items()):
        try: await ws.send(req)
        except Exception: RELAY_POOL.pop(url, None)

# ── Unified WebSocket handler (browser + LAN + file xfer, single port) ──
def make_ctx():
    return HubContext(
        sk=SK, pubkey=PUBKEY,
        lan_clients=LAN_CLIENTS, browsers=BROWSERS, watched_pubkeys=WATCHED_PUBKEYS,
        nostr_publish=nostr_publish, resubscribe_all=resubscribe_all,
        log_event=log_event, logger=logger,
    )

async def ws_handler(websocket):
    sess = ClientSession(websocket)
    BROWSERS.add(websocket)
    await websocket.send(json.dumps({"type": "identity", "pubkey": PUBKEY}))
    ctx = make_ctx()
    try:
        async for raw in websocket:
            if isinstance(raw, bytes):
                await on_binary_frame(raw, sess)
                continue
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            fn = HANDLERS.get(frame.get("type", ""))
            if fn:
                try:
                    await fn(frame, sess, ctx)
                except Exception as e:
                    logger.warning("handler error", type=frame.get("type"), error=str(e)[:120])
    finally:
        sess.close_pending_file()
        BROWSERS.discard(websocket)
        if sess.peer_pubkey:
            LAN_CLIENTS.pop(sess.peer_pubkey, None)

# ── Queue → browsers ──
async def queue_to_browsers():
    while True:
        msg = await EVENT_QUEUE.get()
        parsed = msg.get("parsed", {})
        out = {"type": "msg", "from": msg["pubkey"], "text": msg["text"], "msg_type": msg["msg_type"], "event_id": msg.get("event_id","")}
        ptype = parsed.get("type","")
        if ptype in ("file_offer", "file_chunk"):
            result = file_receiver.on_message(parsed, msg["pubkey"])
            if result: out["text"] = json.dumps(parsed)
        elif ptype == "read_receipt":
            out["type"] = "read_receipt"; out["event_id"] = parsed.get("event_id","")
        elif ptype == "reaction":
            out["type"] = "reaction"; out["event_id"] = parsed.get("event_id",""); out["emoji"] = parsed.get("emoji","")
        elif ptype == "typing":
            out["type"] = "typing"
        out_json = json.dumps(out)
        for bw in list(BROWSERS):
            try: await bw.send(out_json)
            except Exception: BROWSERS.discard(bw)
        for pk, ws in list(LAN_CLIENTS.items()):
            try: await ws.send(out_json)
            except Exception: LAN_CLIENTS.pop(pk, None)

# ── HTTP ──
async def process_request(c, r):
    if r.path == "/" and r.headers.get("Upgrade","").lower() != "websocket":
        try:
            with open(os.path.join(PROJECT_DIR, "frontend", "web", "Dashboard.vue"), "rb") as f:
                return HTTPResponse(200, "OK", Headers({"Content-Type":"text/html; charset=utf-8"}), f.read())
        except FileNotFoundError:
            return HTTPResponse(404, "Not Found", Headers({}), b"Not found")
    return None

# ── Main ──
async def main():
    global SK, PUBKEY, WATCHED_PUBKEYS
    SK = load_or_create_key(KEY_FILE)
    PUBKEY = SK.public_key.format().hex()
    WATCHED_PUBKEYS = {to_nostr_pk(PUBKEY)}
    init_db()
    logger.info(f"CipherPipe :{PORT}  |  Identity: {PUBKEY[:16]}...")
    log_event("server_start", port=PORT)

    profile = json.dumps({"name": "CipherPipe", "about": "Encrypted pipe via Nostr"})
    profile_event = sign_event(SK, 0, profile, [])
    for url in DEFAULT_RELAYS:
        asyncio.create_task(_publish_profile(url, profile_event))

    await start_relay_pool(SK)
    asyncio.create_task(queue_to_browsers())

    async with serve(ws_handler, "0.0.0.0", PORT, process_request=process_request, max_size=FILE_MAX_SIZE):
        await asyncio.Future()

async def _publish_profile(url, event):
    try:
        ws = await websockets.connect(url)
        await ws.send(json.dumps(["EVENT", event]))
        await ws.close()
    except Exception: pass

if __name__ == "__main__":
    asyncio.run(main())
