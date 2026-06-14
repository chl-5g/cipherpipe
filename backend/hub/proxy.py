#!/usr/bin/env python3
"""CipherPipe — single-port Nostr bridge."""
import asyncio, json, logging, os, sys, time, hashlib, base64, socket, uuid
from datetime import datetime

import structlog
import coincurve
import websockets
from websockets.asyncio.server import serve
from websockets.http11 import Response as HTTPResponse
from websockets.datastructures import Headers

from backend.core.crypto import load_or_create_key, sign_event, verify_event, nip44_encrypt, nip44_decrypt, to_nostr_pk
from backend.core.store import init_db, add_message, get_messages, search_messages, upsert_contact, list_contacts, delete_contact, get_state, set_state, mark_delivered
from backend.network.relay import load_relays, select_best_relays
from backend.core.config import PORT, RELAYS as DEFAULT_RELAYS, KEY_FILE, PROJECT_DIR, FILE_MAX_SIZE
from backend.file.transfer import FileReceiver, make_file_offer, ACTIVE_TOKENS, DOWNLOAD_DIR, forward_file

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
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    if msg[0] == "EVENT" and msg[1] == "cp_sub":
                        event = msg[2]
                        log_event("relay_event_rcv", id=event.get("id","")[:16], kind=event.get("kind"), pubkey=event.get("pubkey","")[:16])
                        if not verify_event(event):
                            log_event("relay_event_bad_sig", id=event.get("id","")[:16])
                            continue
                        kind = event["kind"]
                        if kind == 0: await _handle_profile(event); continue
                        if kind == 5: await _handle_deletion(event); continue
                        if kind == 7: await _handle_reaction(event); continue
                        if kind in (4, 1059):
                            try:
                                pt = nip44_decrypt(sk, event["pubkey"], event["content"])
                                parsed = _parse(pt)
                                await EVENT_QUEUE.put({"event_id": event["id"], "pubkey": event["pubkey"],
                                    "text": pt, "msg_type": parsed.get("type", "msg"), "parsed": parsed, "created_at": event["created_at"]})
                                set_state("last_received_at", event["created_at"])
                                add_message(event["id"], event["pubkey"], pt, "in", created_at=event["created_at"])
                                log_event("relay_msg_decrypted", from_pk=event["pubkey"][:16], text=pt[:100])
                            except Exception as e:
                                log_event("relay_decrypt_fail", from_pk=event["pubkey"][:16], error=str(e)[:80])
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

# ── Unified WebSocket handler (browser + LAN + file xfer, all on :8701) ──
async def ws_handler(websocket):
    is_browser = True  # distinguish browser from LAN peer
    peer_pubkey = None
    BROWSERS.add(websocket)
    await websocket.send(json.dumps({"type": "identity", "pubkey": PUBKEY}))
    # Handle file upload via same WS (token-verified chunks)
    uploading_file = {"token": None, "chunks": [], "token_info": None}
    browser_file = {"active": False, "name": "", "chunks": [], "peer": ""}
    pending_file = None  # {name, size, to, fh, received, chunks} — streaming upload
    try:
        async for raw in websocket:
            # Binary frame = file chunk (streaming)
            if isinstance(raw, bytes):
                if pending_file:
                    pf = pending_file
                    pf["fh"].write(raw)
                    pf["received"] += 1
                    continue
                continue

            try: frame = json.loads(raw)
            except json.JSONDecodeError: continue
            t = frame.get("type", "")

            # ── LAN peer registration ──
            if t == "lan_hello":
                is_browser = False
                peer_pubkey = frame.get("pubkey", "")
                LAN_CLIENTS[peer_pubkey] = websocket
                BROWSERS.discard(websocket)
                nostr_pk = to_nostr_pk(peer_pubkey)
                new_pubkey = nostr_pk not in WATCHED_PUBKEYS
                WATCHED_PUBKEYS.add(nostr_pk)
                await websocket.send(json.dumps({"type": "lan_hello_ack", "pubkey": PUBKEY}))
                log_event("lan_peer_joined", pubkey=peer_pubkey[:12])
                if new_pubkey:
                    await resubscribe_all()
                continue

            # ── LAN peer → browser relay ──
            if t == "msg" and not is_browser:
                target = frame.get("to", "")
                text = frame.get("text", "")
                eid = f"lan_{int(time.time()*1000)}"
                if target in LAN_CLIENTS:
                    out = json.dumps({"type": "msg", "id": eid, "from": peer_pubkey, "text": text, "delivered": True})
                    await LAN_CLIENTS[target].send(out)
                    await websocket.send(json.dumps({"type": "msg", "id": eid, "from": "me", "text": text, "delivered": True}))
                    add_message(eid, target, text, "in", delivered=1)
                elif target == PUBKEY:
                    out = json.dumps({"type": "msg", "id": eid, "from": peer_pubkey, "text": text, "delivered": True})
                    for bw in list(BROWSERS):
                        try: await bw.send(out)
                        except Exception: BROWSERS.discard(bw)
                    add_message(eid, peer_pubkey, text, "in", delivered=1)
                else:
                    encrypted = nip44_encrypt(SK, target, text)
                    event = sign_event(SK, 4, encrypted, [["p", to_nostr_pk(target)]])
                    await nostr_publish(event)
                    await websocket.send(json.dumps({"type": "msg", "id": event["id"], "from": "me", "text": text, "delivered": False}))
                    add_message(event["id"], target, text, "out")
                    log_event("msg_sent", to=target[:12])
                continue

            # ── Unified file: JSON header → binary chunks → file_end ──
            if t == "file":
                size = frame.get("size", 0)
                if size > FILE_MAX_SIZE:
                    await websocket.send(json.dumps({"type":"error","msg":f"文件过大 ({size} > {FILE_MAX_SIZE})"}))
                    continue
                name = frame.get("name", "")
                save_path = os.path.join(DOWNLOAD_DIR, name)
                fh = open(save_path, "wb")
                pending_file = {"name": name, "size": size, "to": frame.get("to",""), "fh": fh, "received": 0}
                continue

            if t == "file_end" and pending_file:
                pf = pending_file
                pf["fh"].close()
                save_path = os.path.join(DOWNLOAD_DIR, pf["name"])
                logger.info("File received", name=pf["name"], size=os.path.getsize(save_path), chunks=pf["received"])
                await websocket.send(json.dumps({"type":"file_ok","name":pf["name"],"size":os.path.getsize(save_path)}))
                peer = pf.get("to", "")
                if peer:
                    route = await forward_file(save_path, peer, LAN_CLIENTS, SK, nostr_publish)
                    add_message(f"file_{int(time.time()*1000)}", peer, pf["name"], "out", msg_type="file", delivered=1 if route=="lan" else 0)
                pending_file = None
                continue

            # ── LAN peer file send via path (CLI compat) ──
            if t == "file_path" and not is_browser:
                filepath = frame.get("path", "")
                target = frame.get("to", "")
                if filepath and target and os.path.isfile(filepath):
                    route = await forward_file(filepath, target, LAN_CLIENTS, SK, nostr_publish)
                    add_message(f"file_{int(time.time()*1000)}", target, os.path.basename(filepath), "out", msg_type="file", delivered=1 if route == "lan" else 0)
                continue

            # ── Browser file upload: chunked (legacy) ──
            if t == "file_start":
                browser_file = {"active": True, "name": frame.get("name",""),
                                "chunks": [], "peer": frame.get("to",""),
                                "total": frame.get("total_chunks", 0)}
                await websocket.send(json.dumps({"type": "file_start_ack"}))
                continue

            if t == "file_chunk" and browser_file["active"]:
                browser_file["chunks"].append((frame.get("index",0), base64.b64decode(frame.get("data",""))))
                continue

            if t == "file_end" and browser_file["active"]:
                bf = browser_file
                bf["chunks"].sort(key=lambda x: x[0])
                file_data = b"".join(c[1] for c in bf["chunks"])
                save_path = os.path.join(DOWNLOAD_DIR, bf["name"])
                with open(save_path, "wb") as f: f.write(file_data)
                logger.info("File received (chunked)", name=bf["name"], size=len(file_data), chunks=len(bf["chunks"]))
                log_event("file_received", name=bf["name"], size=len(file_data))
                await websocket.send(json.dumps({"type":"file_ok","name":bf["name"],"size":len(file_data)}))
                add_message(f"file_{int(time.time()*1000)}", bf.get("peer",""), bf["name"], "out", msg_type="file")
                peer = bf["peer"]
                if peer:
                    await forward_file(save_path, peer, LAN_CLIENTS, SK, nostr_publish)
                browser_file = {"active": False, "name": "", "chunks": [], "peer": ""}
                continue

            # ── File upload: hello ──
            if t == "file_hello":
                token = frame.get("token", "")
                if token in ACTIVE_TOKENS:
                    uploading_file["token"] = token
                    uploading_file["token_info"] = ACTIVE_TOKENS.pop(token)
                    await websocket.send(json.dumps({"type": "file_hello_ack"}))
                else:
                    await websocket.send(json.dumps({"type": "error", "msg": "invalid token"}))
                continue

            # ── File upload: chunk ──
            if t == "file_chunk_upload":
                if uploading_file["token_info"]:
                    uploading_file["chunks"].append(base64.b64decode(frame.get("data","")))
                continue

            # ── File upload: done ──
            if t == "file_done":
                if uploading_file["token_info"]:
                    file_data = b"".join(uploading_file["chunks"])
                    info = uploading_file["token_info"]
                    if hashlib.sha256(file_data).hexdigest() != info["sha256"]:
                        await websocket.send(json.dumps({"type": "error", "msg": "sha256 mismatch"}))
                    else:
                        path = os.path.join(DOWNLOAD_DIR, info["name"])
                        with open(path, "wb") as f: f.write(file_data)
                        await websocket.send(json.dumps({"type": "file_ok"}))
                        logger.info("File received", name=info["name"], size=len(file_data))
                uploading_file = {"token": None, "chunks": [], "token_info": None}
                continue

            # ── Browser messages ──
            if t == "msg":
                text, peer = frame.get("text", ""), frame.get("to", "")
                if not text or not peer: continue
                # Route: LAN first, then Nostr
                if peer in LAN_CLIENTS:
                    eid = f"lan_{int(time.time()*1000)}"
                    out = json.dumps({"type": "msg", "id": eid, "from": "me", "text": text, "delivered": True})
                    await LAN_CLIENTS[peer].send(out)
                    await websocket.send(out)
                    add_message(eid, peer, text, "out", delivered=1)
                    log_event("msg_sent_lan", to=peer[:12])
                    continue
                encrypted = nip44_encrypt(SK, peer, text)
                event = sign_event(SK, 4, encrypted, [["p", to_nostr_pk(peer)]])
                await nostr_publish(event)
                await websocket.send(json.dumps({"type": "msg", "id": event["id"], "from": "me", "text": text, "delivered": False}))
                add_message(event["id"], peer, text, "out")
                add_message(event["id"], peer, text, "out")
                log_event("msg_sent", to=peer[:12])
            elif t == "file_send":
                peer = frame.get("to", "")
                filepath = frame.get("path", "")
                if filepath and peer:
                    offer = make_file_offer(filepath, peer in LAN_CLIENTS)
                    encrypted = nip44_encrypt(SK, peer, json.dumps(offer))
                    event = sign_event(SK, 4, encrypted, [["p", to_nostr_pk(peer)]])
                    await nostr_publish(event)
                    await websocket.send(json.dumps({"type": "file_offer_sent", "file_id": offer["file_id"]}))
                # Browser sends inline file data (name + data) instead of path
                name = frame.get("name", "")
                data_b64 = frame.get("data", "")
                if name and data_b64 and peer:
                    file_data = base64.b64decode(data_b64)
                    save_path = os.path.join(DOWNLOAD_DIR, name)
                    with open(save_path, "wb") as f:
                        f.write(file_data)
                    logger.info("File saved from browser", name=name, size=len(file_data))
                    log_event("file_received", name=name, size=len(file_data))
                    # Notify peer via LAN first, then Nostr
                    notify = json.dumps({"type":"file_offer","name":name,"size":len(file_data),"path":save_path})
                    if peer in LAN_CLIENTS:
                        await LAN_CLIENTS[peer].send(json.dumps({"type":"msg","from":PUBKEY[:12],"text":notify}))
                        log_event("file_offer_sent_lan", to=peer[:12])
                    else:
                        encrypted = nip44_encrypt(SK, peer, notify)
                        await nostr_publish(sign_event(SK, 4, encrypted, [["p", to_nostr_pk(peer)]]))
                    await websocket.send(json.dumps({"type":"file_sent","name":name,"size":len(file_data)}))
            elif t == "typing":
                peer = frame.get("to", "")
                if peer:
                    out = json.dumps({"type": "typing", "from": PUBKEY[:12]})
                    if peer in LAN_CLIENTS:
                        await LAN_CLIENTS[peer].send(out)
                    else:
                        encrypted = nip44_encrypt(SK, peer, json.dumps({"type": "typing"}))
                        await nostr_publish(sign_event(SK, 4, encrypted, [["p", to_nostr_pk(peer)]]))
            elif t == "read_receipt":
                peer, eid = frame.get("peer", ""), frame.get("event_id", "")
                if peer and eid:
                    out = json.dumps({"type": "read_receipt", "event_id": eid})
                    if peer in LAN_CLIENTS:
                        await LAN_CLIENTS[peer].send(out)
                    else:
                        encrypted = nip44_encrypt(SK, peer, json.dumps({"type": "read_receipt", "event_id": eid, "read_at": int(time.time())}))
                        await nostr_publish(sign_event(SK, 4, encrypted, [["p", to_nostr_pk(peer)]]))
            elif t == "reaction":
                peer, eid, emoji = frame.get("peer",""), frame.get("event_id",""), frame.get("emoji","")
                if peer and eid and emoji:
                    out = json.dumps({"type": "reaction", "event_id": eid, "emoji": emoji, "from": PUBKEY[:12]})
                    if peer in LAN_CLIENTS:
                        await LAN_CLIENTS[peer].send(out)
                    else:
                        encrypted = nip44_encrypt(SK, peer, json.dumps({"type": "reaction", "event_id": eid, "emoji": emoji}))
                        await nostr_publish(sign_event(SK, 4, encrypted, [["p", to_nostr_pk(peer)], ["e", eid]]))
                    # Persist with dedup via unique event_id
                    add_message(f"rxn_{PUBKEY[:12]}_{eid}_{emoji}", peer, emoji, "out", msg_type="reaction")
            elif t == "contacts":
                await websocket.send(json.dumps({"type": "contacts", "data": list_contacts()}))
            elif t == "create_identity":
                import coincurve
                sk = coincurve.PrivateKey()
                await websocket.send(json.dumps({"type":"identity_created","pubkey":sk.public_key.format().hex()}))
            elif t == "peer_status":
                pk = frame.get("pubkey", "")
                if pk:
                    online = pk in LAN_CLIENTS
                    await websocket.send(json.dumps({"type":"peer_status","pubkey":pk,"online":online}))
            elif t == "delete_contact":
                pk = frame.get("pubkey", "")
                if pk: delete_contact(pk)
            elif t == "search":
                query = frame.get("query", "").strip()
                if query:
                    try:
                        results = search_messages(query + "*")
                    except Exception:
                        results = []
                    await websocket.send(json.dumps({"type": "search_results", "data": results}))
            elif t == "history":
                peer, before, limit = frame.get("peer",""), frame.get("before"), frame.get("limit", 50)
                if peer:
                    await websocket.send(json.dumps({"type": "history", "data": get_messages(peer, limit=limit, before=before)}))
    finally:
        BROWSERS.discard(websocket)
        if peer_pubkey:
            LAN_CLIENTS.pop(peer_pubkey, None)

# ── Queue → browsers ──
async def queue_to_browsers():
    while True:
        msg = await EVENT_QUEUE.get()
        parsed = msg.get("parsed", {})
        out = {"type": "msg", "from": msg["pubkey"][:12], "text": msg["text"], "msg_type": msg["msg_type"], "event_id": msg.get("event_id","")}
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
