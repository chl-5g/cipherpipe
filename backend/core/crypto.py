#!/usr/bin/env python3
"""NIP-44 ChaCha20-Poly1305 + BIP-340 Schnorr for CipherPipe."""
import json, time, hashlib, secrets, base64, os

import coincurve
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.asymmetric import ec


from backend.core.config import KEY_FILE as _DEFAULT_KEYFILE

def load_or_create_key(keyfile=None):
    if keyfile is None:
        keyfile = _DEFAULT_KEYFILE
    if os.path.exists(keyfile):
        with open(keyfile) as f:
            raw = f.read().strip()
            if raw:
                return coincurve.PrivateKey.from_hex(raw)
    pk = coincurve.PrivateKey()
    with open(keyfile, "w") as f:
        f.write(pk.to_hex())
    return pk


def sign_event(sk, kind, content, tags):
    pubkey = sk.public_key.format().hex()
    created_at = int(time.time())
    s = json.dumps([0, pubkey, created_at, kind, tags, content], separators=(",", ":"))
    eid = hashlib.sha256(s.encode()).hexdigest()
    return {"id": eid, "pubkey": pubkey, "created_at": created_at,
            "kind": kind, "tags": tags, "content": content,
            "sig": sk.sign_schnorr(bytes.fromhex(eid)).hex()}


def verify_event(e):
    s = json.dumps([0, e["pubkey"], e["created_at"], e["kind"], e["tags"], e["content"]], separators=(",", ":"))
    if e.get("id") != hashlib.sha256(s.encode()).hexdigest():
        return False
    return coincurve.PublicKey.from_hex(e["pubkey"]).public_key_xonly.verify(
        bytes.fromhex(e["sig"]), bytes.fromhex(e["id"]))


def _ec_priv(sk):
    return ec.derive_private_key(int(sk.to_hex(), 16), ec.SECP256K1())


def _ec_pub(h):
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), bytes.fromhex(h))


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
