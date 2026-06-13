"""CipherPipe crypto — AES-256-GCM room encryption."""
import os, secrets, base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_key() -> bytes:
    """Generate a new AES-256 key (32 bytes), return hex string."""
    key = AESGCM.generate_key(bit_length=256)
    return key.hex()


def encrypt(plaintext: str, key_hex: str) -> tuple[str, str]:
    """Encrypt plaintext with AES-256-GCM. Returns (ciphertext_b64, nonce_b64)."""
    key = bytes.fromhex(key_hex)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(ct).decode(), base64.b64encode(nonce).decode()


def decrypt(ciphertext_b64: str, nonce_b64: str, key_hex: str) -> str:
    """Decrypt ciphertext with AES-256-GCM. Returns plaintext string."""
    key = bytes.fromhex(key_hex)
    ct = base64.b64decode(ciphertext_b64)
    nonce = base64.b64decode(nonce_b64)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ct, None)
    return plaintext.decode("utf-8")


def load_key(path: str = "room.key") -> str:
    """Load room key from file, returns hex string."""
    with open(path) as f:
        data = f.read().strip()
    return data
