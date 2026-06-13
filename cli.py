#!/usr/bin/env python3
"""CipherPipe CLI — Nostr client for humans and AI agents."""
import asyncio, json, os, sys, time

# Use same crypto primitives as proxy
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]

# ── Key ──
def load_key(path="nostr.key"):
    try:
        with open(path) as f:
            hexkey = f.read().strip()
        return ec.derive_private_key(int(hexkey, 16), ec.SECP256K1())
    except FileNotFoundError:
        sk = ec.generate_private_key(ec.SECP256K1())
        pub = sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint).hex()
        print(f"New identity: {pub[:16]}...")
        return sk

# ── NIP-44 (mirror of proxy) ──
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
import secrets, base64

def nip44_encrypt(sk, recipient_pub_hex, plaintext):
    recipient_pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256K1(), bytes.fromhex(recipient_pub_hex))
    shared = sk.exchange(ec.ECDH(), recipient_pub)
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"")
    key = hkdf.derive(shared)
    nonce = secrets.token_bytes(12)
    chacha = ChaCha20Poly1305(key)
    ct = chacha.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()

def nip44_decrypt(sk, sender_pub_hex, encrypted_b64):
    sender_pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256K1(), bytes.fromhex(sender_pub_hex))
    shared = sk.exchange(ec.ECDH(), sender_pub)
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"nip44-v2", info=b"")
    key = hkdf.derive(shared)
    payload = base64.b64decode(encrypted_b64)
    nonce, ct = payload[:12], payload[12:]
    chacha = ChaCha20Poly1305(key)
    return chacha.decrypt(nonce, ct, None).decode()

# ── Main ──
async def main():
    import argparse
    parser = argparse.ArgumentParser(description="CipherPipe CLI — Nostr")
    parser.add_argument("--peer", required=True, help="Peer pubkey (hex)")
    parser.add_argument("--name", default="cli", help="Your display name")
    parser.add_argument("--no-stdin", action="store_true", help="Receive-only (agent mode)")
    args = parser.parse_args()

    sk = load_key()
    pubkey = sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint).hex()
    print(f"CipherPipe CLI — {pubkey[:12]}...")
    print(f"Connected. {'Type messages (Ctrl+C to quit)' if not args.no_stdin else 'Agent mode.'}")

    import websockets

    async def listen():
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
                                pass  # not for us
                    except Exception:
                        pass
            except Exception as e:
                await asyncio.sleep(5)

    reader = asyncio.create_task(listen())

    if args.no_stdin:
        await reader
    else:
        loop = asyncio.get_event_loop()
        import threading

        async def send_msg(text):
            encrypted = nip44_encrypt(sk, args.peer, text)
            event = {"kind": 4, "content": encrypted, "tags": [["p", args.peer]],
                     "created_at": int(time.time()), "pubkey": pubkey}
            msg = json.dumps(["EVENT", event])
            for relay_url in RELAYS:
                try:
                    ws = await websockets.connect(relay_url)
                    await ws.send(msg)
                    await ws.close()
                except Exception:
                    pass
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
