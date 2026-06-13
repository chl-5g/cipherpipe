#!/usr/bin/env python3
"""CipherPipe proxy — Nostr bridge + LAN fast-path. Persistent relay connections."""
import asyncio, json, logging, os, sys, time, hashlib, secrets, base64, socket
from datetime import datetime

import structlog
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.asymmetric import ec

import coincurve
import websockets
from websockets.asyncio.server import serve
from websockets.http11 import Response as HTTPResponse
from websockets.datastructures import Headers

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# ── Logging ──
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

# ── Config ──
RELAYS = ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.nostr.band"]
PROXY_PORT = 8701
LAN_WS_PORT = 8702
KEY_FILE = os.path.join(BASE_DIR, "nostr.key")
RELAY_POOL = {}  # url -> ws
EVENT_QUEUE = asyncio.Queue()

# ── Key ──
def load_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f: return coincurve.PrivateKey.from_hex(f.read().strip())
    pk = coincurve.PrivateKey()
    with open(KEY_FILE, "w") as f: f.write(pk.format().hex())
    return pk

# ── Nostr events ──
def sign_event(sk, kind, content, tags):
    pubkey = sk.public_key.format().hex()
    created_at = int(time.time())
    s = json.dumps([0, pubkey, created_at, kind, tags, content], separators=(",", ":"))
    eid = hashlib.sha256(s.encode()).hexdigest()
    return {"id": eid, "pubkey": pubkey, "created_at": created_at, "kind": kind, "tags": tags, "content": content, "sig": sk.schnorr_sign(bytes.fromhex(eid)).hex()}

def verify_event(e):
    s = json.dumps([0, e["pubkey"], e["created_at"], e["kind"], e["tags"], e["content"]], separators=(",", ":"))
    return e.get("id") == hashlib.sha256(s.encode()).hexdigest() and coincurve.PublicKey.from_hex(e["pubkey"]).schnorr_verify(bytes.fromhex(e["id"]), bytes.fromhex(e["sig"]))

# ── NIP-44 ──
def _ec_priv(sk): return ec.derive_private_key(int(sk.format().hex(), 16), ec.SECP256K1())
def _ec_pub(h): return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), bytes.fromhex(h))

def nip44_encrypt(sk, to_pub, text):
    shared = _ec_priv(sk).exchange(ec.ECDH(), _ec_pub(to_pub))
    key = HKDF(algorithm=crypto_hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"").derive(shared)
    nonce = secrets.token_bytes(12)
    ct = ChaCha20Poly1305(key).encrypt(nonce, text.encode(), None)
    return base64.b64encode(nonce + ct).decode()

def nip44_decrypt(sk, from_pub, blob):
    shared = _ec_priv(sk).exchange(ec.ECDH(), _ec_pub(from_pub))
    key = HKDF(algorithm=crypto_hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"").derive(shared)
    payload = base64.b64decode(blob)
    return ChaCha20Poly1305(key).decrypt(payload[:12], payload[12:], None).decode()

# ── Persistent relay pool ──
async def relay_connect(url, sk):
    """Persistent connection to one relay. Read + write on the same WS."""
    pubkey = sk.public_key.format().hex()
    while True:
        try:
            ws = await websockets.connect(url, ping_interval=20, ping_timeout=10)
            RELAY_POOL[url] = ws
            logger.info(f"Connected to {url}")
            log_event("relay_connected", url=url)
            # Subscribe to our DMs
            await ws.send(json.dumps(["REQ", "cp_sub", {"kinds": [4, 1059], "#p": [pubkey], "since": int(time.time())}]))
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    if msg[0] == "EVENT" and msg[1] == "cp_sub":
                        event = msg[2]
                        if not verify_event(event): continue
                        try:
                            pt = nip44_decrypt(sk, event["pubkey"], event["content"])
                            await EVENT_QUEUE.put({"pubkey": event["pubkey"], "text": pt})
                        except Exception: pass
                except Exception: pass
        except Exception as e:
            RELAY_POOL.pop(url, None)
            logger.warning(f"Relay {url}: {e}")
            await asyncio.sleep(5)

async def start_relay_pool(sk):
    """Connect to all relays in parallel."""
    for url in RELAYS:
        asyncio.create_task(relay_connect(url, sk))

async def nostr_publish(event):
    """Publish to all persistent relay connections instantly."""
    msg = json.dumps(["EVENT", event])
    for url, ws in list(RELAY_POOL.items()):
        try: await ws.send(msg)
        except Exception: RELAY_POOL.pop(url, None)

# ── LAN WebSocket (fast path) ──
async def lan_handler(websocket):
    try:
        async for raw in websocket:
            try: frame = json.loads(raw)
            except json.JSONDecodeError: continue
            if frame.get("type") == "msg":
                pt = frame.get("text", "")
                out = json.dumps({"type":"msg","from":"lan","text":pt})
                await websocket.send(out)
                log_event("lan_msg")
    except Exception: pass

# ── Browser WebSocket ──
BROWSERS = set()

async def ws_handler(websocket):
    BROWSERS.add(websocket)
    await websocket.send(json.dumps({"type":"identity","pubkey":PUBKEY[:16]+"..."}))
    try:
        async for raw in websocket:
            try: frame = json.loads(raw)
            except json.JSONDecodeError: continue
            t = frame.get("type","")
            if t == "msg":
                text, peer = frame.get("text",""), frame.get("to","")
                if not text or not peer: continue
                encrypted = nip44_encrypt(SK, peer, text)
                event = sign_event(SK, 4, encrypted, [["p", peer]])
                await nostr_publish(event)
                await websocket.send(json.dumps({"type":"msg","from":"me","text":text}))
                log_event("msg_sent", to=peer[:12])
    finally: BROWSERS.discard(websocket)

# ── Queue → browsers ──
async def queue_to_browsers():
    while True:
        msg = await EVENT_QUEUE.get()
        out = json.dumps({"type":"msg","from":msg["pubkey"][:12],"text":msg["text"]})
        for bw in list(BROWSERS):
            try: await bw.send(out)
            except Exception: BROWSERS.discard(bw)

# ── HTTP ──
def serve_html(p):
    try:
        with open(os.path.join(BASE_DIR,p),"rb") as f:
            return HTTPResponse(200,"OK",Headers({"Content-Type":"text/html; charset=utf-8"}),f.read())
    except FileNotFoundError: return HTTPResponse(404,"Not Found",Headers({}),b"Not found")
async def process_request(c, r):
    if r.path == "/": return serve_html("dashboard.html")
    return None

# ── Main ──
SK = None; PUBKEY = None

async def main():
    global SK, PUBKEY
    SK = load_or_create_key(); PUBKEY = SK.public_key.format().hex()
    logger.info(f"CipherPipe :{PROXY_PORT} | LAN WS :{LAN_WS_PORT} | Identity: {PUBKEY[:16]}...")
    log_event("server_start", port=PROXY_PORT, lan_port=LAN_WS_PORT)

    await start_relay_pool(SK)
    asyncio.create_task(queue_to_browsers())

    lan_server = await websockets.serve(lan_handler, "0.0.0.0", LAN_WS_PORT)
    async with serve(ws_handler, "0.0.0.0", PROXY_PORT, process_request=process_request):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
