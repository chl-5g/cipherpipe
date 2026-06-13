#!/usr/bin/env python3
"""CipherPipe proxy — Nostr bridge. Keypair holder, relay connector, dashboard server."""
import asyncio, json, logging, os, sys, time, hashlib, secrets, base64
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import structlog
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

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
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger("cipherpipe")

log_file = os.path.join(LOGS_DIR, f"cipherpipe-{datetime.now():%Y-%m-%d}.jsonl")
json_fh = logging.FileHandler(log_file)
json_fh.setLevel(logging.DEBUG)
file_logger = logging.getLogger("cipherpipe.file")
file_logger.addHandler(json_fh)
file_logger.setLevel(logging.DEBUG)

def log_event(event: str, **kwargs):
    file_logger.info(json.dumps({"event": event, "ts": time.time(), **kwargs}, ensure_ascii=False))

# ── Nostr relay list ──
RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]

PROXY_PORT = 8701
KEY_FILE = os.path.join(BASE_DIR, "nostr.key")

# ── Key management ──

def load_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f:
            return ec.generate_private_key(ec.SECP256K1())  # placeholder
    # Generate new secp256k1 keypair
    sk = ec.generate_private_key(ec.SECP256K1())
    pub = sk.public_key()
    pub_hex = pub.public_bytes(Encoding.X962, PublicFormat.CompressedPoint).hex()
    with open(KEY_FILE, "w") as f:
        f.write(sk.private_numbers().private_value.to_bytes(32).hex())
    logger.info(f"New identity: {pub_hex[:16]}...")
    log_event("key_created", pubkey=pub_hex[:16])
    return sk, pub_hex

# ── NIP-44 encryption (simplified) ──

def nip44_encrypt(sender_sk, recipient_pub_hex: str, plaintext: str) -> str:
    """NIP-44 v2: XChaCha20-Poly1305 with ECDH key exchange."""
    recipient_pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256K1(), bytes.fromhex("02" + recipient_pub_hex) if len(recipient_pub_hex) == 64 else bytes.fromhex(recipient_pub_hex))
    shared = sender_sk.exchange(ec.ECDH(), recipient_pub)

    # HKDF to derive conversation key
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"")
    convo_key = hkdf.derive(shared)

    nonce = secrets.token_bytes(12)
    chacha = ChaCha20Poly1305(convo_key)
    ct = chacha.encrypt(nonce, plaintext.encode(), None)

    payload = nonce + ct
    return base64.b64encode(payload).decode()

def nip44_decrypt(receiver_sk, sender_pub_hex: str, encrypted_b64: str) -> str:
    """Decrypt NIP-44 message."""
    sender_pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256K1(), bytes.fromhex("02" + sender_pub_hex) if len(sender_pub_hex) == 64 else bytes.fromhex(sender_pub_hex))
    shared = receiver_sk.exchange(ec.ECDH(), sender_pub)

    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"")
    convo_key = hkdf.derive(shared)

    payload = base64.b64decode(encrypted_b64)
    nonce, ct = payload[:12], payload[12:]
    chacha = ChaCha20Poly1305(convo_key)
    return chacha.decrypt(nonce, ct, None).decode()


# ── Nostr relay connection ──

PEERS = {}  # pubkey -> websocket connection

async def nostr_subscribe():
    """Connect to Nostr relays and listen for encrypted DMs (kind 4 and 1059)."""
    while True:
        for relay_url in RELAYS:
            try:
                ws = await websockets.connect(relay_url)
                logger.info(f"Connected to {relay_url}")
                # Subscribe to encrypted DMs
                sub = json.dumps(["REQ", "cipherpipe", {"kinds": [4, 1059], "since": int(time.time())}])
                await ws.send(sub)

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if msg[0] == "EVENT":
                            event = msg[2]
                            yield event
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Relay {relay_url}: {e}")
                await asyncio.sleep(5)

async def nostr_publish(event: dict):
    """Publish an event to all connected relays."""
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
    return None


# ── Browser WebSocket ──

BROWSERS = set()

async def ws_handler(websocket):
    BROWSERS.add(websocket)
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
                # Encrypt and publish to Nostr
                encrypted = nip44_encrypt(SK, peer, text)
                event = {
                    "kind": 4,
                    "content": encrypted,
                    "tags": [["p", peer]],
                    "created_at": int(time.time()),
                    "pubkey": PUBKEY,
                }
                # Sign and publish
                await nostr_publish(event)

                # Also echo to browser
                out = json.dumps({"type": "msg", "from": "me", "text": text})
                await websocket.send(out)
    finally:
        BROWSERS.discard(websocket)


async def nostr_relay_to_browsers():
    """Listen to Nostr, decrypt, forward to browsers."""
    async for event in nostr_subscribe():
        try:
            content = event.get("content", "")
            pubkey = event.get("pubkey", "")
            pt = nip44_decrypt(SK, pubkey, content)
            out = json.dumps({"type": "msg", "from": pubkey[:8], "text": pt})
            for bw in BROWSERS:
                try:
                    await bw.send(out)
                except Exception:
                    pass
        except Exception:
            pass


# ── Main ──

SK = None
PUBKEY = None

async def main():
    global SK, PUBKEY
    SK, PUBKEY = load_or_create_key()

    logger.info(f"CipherPipe Nostr bridge on :{PROXY_PORT}")
    logger.info(f"Nostr identity: {PUBKEY[:16]}...")

    asyncio.create_task(nostr_relay_to_browsers())

    async with serve(ws_handler, "0.0.0.0", PROXY_PORT, process_request=process_request):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
