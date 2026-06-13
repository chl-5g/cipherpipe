#!/usr/bin/env python3
"""CipherPipe CLI — Nostr client with Schnorr signing, for humans and AI agents."""
import asyncio, json, os, sys, time, hashlib, secrets, base64

import coincurve
import websockets
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]


def load_key(path="nostr.key"):
    if os.path.exists(path):
        with open(path) as f:
            return coincurve.PrivateKey.from_hex(f.read().strip())
    pk = coincurve.PrivateKey()
    print(f"New identity: {pk.public_key.format().hex()[:16]}...")
    return pk


def sign_event(sk, kind, content, tags):
    pubkey = sk.public_key.format().hex()
    created_at = int(time.time())
    serialized = json.dumps([0, pubkey, created_at, kind, tags, content], separators=(",", ":"))
    event_id = hashlib.sha256(serialized.encode()).hexdigest()
    sig = sk.schnorr_sign(bytes.fromhex(event_id)).hex()
    return {"id": event_id, "pubkey": pubkey, "created_at": created_at,
            "kind": kind, "tags": tags, "content": content, "sig": sig}


# ── NIP-44 ──
def _to_ec_priv(sk):
    return ec.derive_private_key(int(sk.format().hex(), 16), ec.SECP256K1())

def nip44_encrypt(sk, recipient_pub_hex, plaintext):
    pub_ec = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), bytes.fromhex(recipient_pub_hex))
    shared = _to_ec_priv(sk).exchange(ec.ECDH(), pub_ec)
    hkdf = HKDF(algorithm=crypto_hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"")
    key = hkdf.derive(shared)
    nonce = secrets.token_bytes(12)
    chacha = ChaCha20Poly1305(key)
    ct = chacha.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()

def nip44_decrypt(sk, sender_pub_hex, encrypted_b64):
    pub_ec = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), bytes.fromhex(sender_pub_hex))
    shared = _to_ec_priv(sk).exchange(ec.ECDH(), pub_ec)
    hkdf = HKDF(algorithm=crypto_hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"")
    key = hkdf.derive(shared)
    payload = base64.b64decode(encrypted_b64)
    nonce, ct = payload[:12], payload[12:]
    chacha = ChaCha20Poly1305(key)
    return chacha.decrypt(nonce, ct, None).decode()


async def publish(relay_url, event):
    try:
        ws = await websockets.connect(relay_url)
        await ws.send(json.dumps(["EVENT", event]))
        await ws.close()
    except Exception:
        pass


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="CipherPipe CLI — Nostr")
    parser.add_argument("--peer", required=True, help="Peer pubkey (hex)")
    parser.add_argument("--name", default="cli")
    parser.add_argument("--no-stdin", action="store_true", help="Agent mode")
    args = parser.parse_args()

    sk = load_key()
    pubkey = sk.public_key.format().hex()
    peer = args.peer
    print(f"CipherPipe CLI — {pubkey[:12]}... ↔ {peer[:12]}...")
    print("Connected." if args.no_stdin else "Type messages (Ctrl+C to quit)")

    # Subscribe to our DMs
    async def listen():
        while True:
            for relay_url in RELAYS:
                try:
                    ws = await websockets.connect(relay_url)
                    sub = json.dumps(["REQ", "cp_cli", {"kinds": [4, 1059], "#p": [pubkey], "since": int(time.time())}])
                    await ws.send(sub)
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            if msg[0] == "EVENT":
                                event = msg[2]
                                try:
                                    pt = nip44_decrypt(sk, event["pubkey"], event["content"])
                                    print(f"\n[{event['pubkey'][:8]}] {pt}")
                                    if not args.no_stdin:
                                        print("> ", end="", flush=True)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    await asyncio.sleep(5)

    reader = asyncio.create_task(listen())

    if args.no_stdin:
        await reader
    else:
        loop = asyncio.get_event_loop()

        async def send_msg(text):
            encrypted = nip44_encrypt(sk, peer, text)
            event = sign_event(sk, 4, encrypted, [["p", peer]])
            for relay_url in RELAYS:
                await publish(relay_url, event)
            print("> ", end="", flush=True)

        def on_input():
            line = sys.stdin.readline()
            if line:
                asyncio.ensure_future(send_msg(line.strip()))

        loop.add_reader(sys.stdin, on_input)
        try:
            print("> ", end="", flush=True)
            await reader
        except KeyboardInterrupt:
            pass
        finally:
            loop.remove_reader(sys.stdin)
            print("\nDisconnected.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDisconnected.")
