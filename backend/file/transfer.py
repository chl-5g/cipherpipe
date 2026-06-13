#!/usr/bin/env python3
"""File transfer — Nostr signal + chunked DM. LAN direct file chunks go over main WS."""
import asyncio, json, os, uuid, hashlib, base64, structlog
from backend.core.crypto import nip44_encrypt, sign_event
from backend.core.config import DATA_DIR

logger = structlog.get_logger("cipherpipe.file")
NOSTR_CHUNK_SIZE = 32 * 1024
DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

ACTIVE_TOKENS = {}


def make_file_offer(filepath, lan_available=False):
    token = uuid.uuid4().hex
    with open(filepath, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    ACTIVE_TOKENS[token] = {"name": os.path.basename(filepath), "size": len(data), "sha256": sha}
    return {
        "type": "file_offer",
        "file_id": uuid.uuid4().hex,
        "name": os.path.basename(filepath),
        "size": len(data),
        "method": "lan_direct" if lan_available else "nostr_chunked",
        "token": token,
        "sha256": sha,
    }


async def send_file_chunked(sk, peer_pubkey, filepath, publish_fn):
    file_id = uuid.uuid4().hex
    with open(filepath, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    total = (len(data) + NOSTR_CHUNK_SIZE - 1) // NOSTR_CHUNK_SIZE
    for i in range(total):
        chunk = data[i * NOSTR_CHUNK_SIZE:(i + 1) * NOSTR_CHUNK_SIZE]
        msg = json.dumps({
            "type": "file_chunk", "file_id": file_id, "index": i, "total": total,
            "name": os.path.basename(filepath), "data": base64.b64encode(chunk).decode(),
            "sha256": sha if i == total - 1 else None,
        })
        encrypted = nip44_encrypt(sk, peer_pubkey, msg)
        await publish_fn(sign_event(sk, 4, encrypted, [["p", peer_pubkey]]))
        await asyncio.sleep(0.05)
    logger.info("File sent via Nostr chunks", name=os.path.basename(filepath), chunks=total)


async def forward_file(filepath, peer_pubkey, lan_clients, sk, publish_fn, data_dir=DOWNLOAD_DIR):
    """Stream-chunk file to peer via LAN (binary frames) or Nostr relay."""
    name = os.path.basename(filepath)
    size = os.path.getsize(filepath)
    CHUNK = 256 * 1024
    total = max((size + CHUNK - 1) // CHUNK, 1)
    if peer_pubkey in lan_clients:
        ws = lan_clients[peer_pubkey]
        await ws.send(json.dumps({"type": "file_start", "name": name, "size": size, "chunks": total}))
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                await ws.send(chunk)
        await ws.send(json.dumps({"type": "file_end", "name": name}))
        return "lan"
    else:
        await send_file_chunked(sk, peer_pubkey, filepath, publish_fn)
        return "relay"


class FileReceiver:
    def __init__(self, auto_accept=False, downloads_dir=DOWNLOAD_DIR):
        self.auto_accept = auto_accept
        self.dir = downloads_dir
        self.pending = {}

    def on_message(self, msg_data, pubkey):
        t = msg_data.get("type", "")
        if t == "file_chunk":
            fid = msg_data["file_id"]
            if fid not in self.pending:
                self.pending[fid] = {"chunks": {}, "total": msg_data["total"], "name": msg_data["name"], "pubkey": pubkey}
            self.pending[fid]["chunks"][msg_data["index"]] = msg_data["data"]
            if msg_data.get("sha256"):
                return self._assemble(fid, msg_data["sha256"])
        elif t == "file_offer":
            if self.auto_accept: return True
        return None

    def _assemble(self, fid, expected_sha256):
        info = self.pending.pop(fid)
        ordered = [info["chunks"][i] for i in range(info["total"])]
        data = b"".join(base64.b64decode(c) for c in ordered)
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            logger.error("File checksum mismatch", file_id=fid)
            return None
        path = os.path.join(self.dir, info["name"])
        with open(path, "wb") as f:
            f.write(data)
        logger.info("File assembled", name=info["name"], size=len(data))
        return path
