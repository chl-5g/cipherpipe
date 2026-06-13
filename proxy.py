#!/usr/bin/env python3
"""CipherPipe proxy — Nostr bridge with Schnorr event signing."""
import asyncio, json, logging, os, sys, time, hashlib, secrets, base64
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import structlog
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

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
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger("cipherpipe")
log_file = os.path.join(LOGS_DIR, f"cipherpipe-{datetime.now():%Y-%m-%d}.jsonl")
json_fh = logging.FileHandler(log_file); json_fh.setLevel(logging.DEBUG)
file_logger = logging.getLogger("cipherpipe.file"); file_logger.addHandler(json_fh); file_logger.setLevel(logging.DEBUG)

def log_event(event: str, **kwargs):
    file_logger.info(json.dumps({"event": event, "ts": time.time(), **kwargs}, ensure_ascii=False))


# ── Config ──
RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]
PROXY_PORT = 8701
KEY_FILE = os.path.join(BASE_DIR, "nostr.key")


# ── Key (coincurve, secp256k1) ──
def load_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f:
            hexkey = f.read().strip()
        pk = coincurve.PrivateKey.from_hex(hexkey)
        return pk, pk.public_key.format().hex()
    pk = coincurve.PrivateKey()
    pub_hex = pk.public_key.format().hex()
    with open(KEY_FILE, "w") as f:
        f.write(pk.format().hex())
    logger.info(f"New identity: {pub_hex[:16]}...")
    log_event("key_created", pubkey=pub_hex[:16])
    return pk, pub_hex


# ── Nostr event signing (Schnorr) ──
def sign_event(sk: coincurve.PrivateKey, kind: int, content: str, tags: list) -> dict:
    """Create and sign a Nostr event."""
    pubkey = sk.public_key.format().hex()
    created_at = int(time.time())
    serialized = json.dumps([0, pubkey, created_at, kind, tags, content], separators=(",", ":"))
    event_id = hashlib.sha256(serialized.encode()).hexdigest()
    sig = sk.schnorr_sign(bytes.fromhex(event_id)).hex()
    return {
        "id": event_id, "pubkey": pubkey, "created_at": created_at,
        "kind": kind, "tags": tags, "content": content, "sig": sig
    }


def verify_event(event: dict) -> bool:
    """Verify a Nostr event signature."""
    serialized = json.dumps([0, event["pubkey"], event["created_at"],
                              event["kind"], event["tags"], event["content"]], separators=(",", ":"))
    event_id = hashlib.sha256(serialized.encode()).hexdigest()
    if event.get("id", "") != event_id:
        return False
    pub = coincurve.PublicKey.from_hex(event["pubkey"])
    return pub.schnorr_verify(bytes.fromhex(event_id), bytes.fromhex(event["sig"]))


# ── NIP-44 ──
def nip44_encrypt(privkey, recipient_pub_hex: str, plaintext: str) -> str:
    pkb = bytes.fromhex(recipient_pub_hex)
    pub_ec = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), pkb)
    sk_ec = ec.derive_private_key(int(privkey.format().hex(), 16), ec.SECP256K1())
    shared = sk_ec.exchange(ec.ECDH(), pub_ec)
    hkdf = HKDF(algorithm=crypto_hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"")
    key = hkdf.derive(shared)
    nonce = secrets.token_bytes(12)
    chacha = ChaCha20Poly1305(key)
    ct = chacha.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()

def nip44_decrypt(privkey, sender_pub_hex: str, encrypted_b64: str) -> str:
    pkb = bytes.fromhex(sender_pub_hex)
    pub_ec = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), pkb)
    sk_ec = ec.derive_private_key(int(privkey.format().hex(), 16), ec.SECP256K1())
    shared = sk_ec.exchange(ec.ECDH(), pub_ec)
    hkdf = HKDF(algorithm=crypto_hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"")
    key = hkdf.derive(shared)
    payload = base64.b64decode(encrypted_b64)
    nonce, ct = payload[:12], payload[12:]
    chacha = ChaCha20Poly1305(key)
    return chacha.decrypt(nonce, ct, None).decode()


# ── Nostr relay ──
async def nostr_subscribe(sk):
    """Connect to relays, listen for encrypted DMs, verify + decrypt."""
    while True:
        for relay_url in RELAYS:
            try:
                ws = await websockets.connect(relay_url)
                logger.info(f"Connected to {relay_url}")
                log_event("relay_connected", url=relay_url)
                sub = json.dumps(["REQ", "cp_sub", {"kinds": [4, 1059], "since": int(time.time())}])
                await ws.send(sub)
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if msg[0] == "EVENT" and msg[1] == "cp_sub":
                            event = msg[2]
                            if not verify_event(event):
                                continue
                            try:
                                pt = nip44_decrypt(sk, event["pubkey"], event["content"])
                                yield {"pubkey": event["pubkey"], "text": pt, "event": event}
                            except Exception:
                                pass  # not for us
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Relay {relay_url}: {e}")
                await asyncio.sleep(5)


async def nostr_publish(event: dict):
    msg = json.dumps(["EVENT", event])
    for relay_url in RELAYS:
        try:
            async with websockets.connect(relay_url) as ws:
                await ws.send(msg)
        except Exception:
            pass


# ── HTTP ──
def serve_html(path):
    try:
        with open(os.path.join(BASE_DIR, path), "rb") as f:
            return HTTPResponse(200, "OK", Headers({"Content-Type": "text/html; charset=utf-8"}), f.read())
    except FileNotFoundError:
        return HTTPResponse(404, "Not Found", Headers({}), b"Not found")

async def process_request(connection, request):
    if request.path == "/":
        return serve_html("dashboard.html")
    return None  # WebSocket upgrade


# ── Browser WebSocket ──
BROWSERS = set()

async def ws_handler(websocket):
    BROWSERS.add(websocket)
    # Send identity to browser
    await websocket.send(json.dumps({"type": "identity", "pubkey": PUBKEY[:16] + "..."}))
    try:
        async for raw in websocket:
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = frame.get("type", "")
            if t == "msg":
                text = frame.get("text", "")
                peer = frame.get("to", "")
                if not text or not peer:
                    continue
                encrypted = nip44_encrypt(SK, peer, text)
                event = sign_event(SK, 4, encrypted, [["p", peer]])
                await nostr_publish(event)
                await websocket.send(json.dumps({"type": "msg", "from": "me", "text": text}))
                log_event("msg_sent", to=peer[:12])
    finally:
        BROWSERS.discard(websocket)


async def nostr_relay_to_browsers(sk):
    """Nostr → decrypt → browser."""
    async for msg in nostr_subscribe(sk):
        out = json.dumps({"type": "msg", "from": msg["pubkey"][:12], "text": msg["text"]})
        for bw in list(BROWSERS):
            try:
                await bw.send(out)
            except Exception:
                BROWSERS.discard(bw)


# ── Main ──
SK = None
PUBKEY = None

async def main():
    global SK, PUBKEY
    SK, PUBKEY = load_or_create_key()
    logger.info(f"CipherPipe Nostr bridge on :{PROXY_PORT}")
    logger.info(f"Identity: {PUBKEY[:16]}...")
    log_event("server_start", port=PROXY_PORT)

    asyncio.create_task(nostr_relay_to_browsers(SK))
    async with serve(ws_handler, "0.0.0.0", PROXY_PORT, process_request=process_request):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
