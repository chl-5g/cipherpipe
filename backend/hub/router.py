#!/usr/bin/env python3
"""CipherPipe connection — unified routing layer. LAN first, relay fallback."""
import asyncio, json, os, sys, time, structlog

import websockets
from backend.core.crypto import load_or_create_key, sign_event, nip44_encrypt, nip44_decrypt
from backend.network.relay import load_relays, select_best_relays
from backend.core.config import PORT

log = structlog.get_logger("cipherpipe.connection")


class PeerRouter:
    """Server-side peer routing. Manages LAN clients and relay fallback."""

    def __init__(self, sk, relay_publish_fn=None):
        self.sk = sk
        self.pubkey = sk.public_key.format().hex()
        self.lan_clients = {}       # pubkey → websocket
        self.publish = relay_publish_fn  # async fn(event)

    def register_lan(self, pubkey, ws):
        self.lan_clients[pubkey] = ws

    def unregister_lan(self, pubkey):
        self.lan_clients.pop(pubkey, None)

    def has_lan(self, pubkey):
        return pubkey in self.lan_clients

    async def send(self, peer_pubkey, msg_dict):
        """Route a message to a peer. LAN if available, else relay."""
        if peer_pubkey in self.lan_clients:
            try:
                await self.lan_clients[peer_pubkey].send(json.dumps(msg_dict))
                return "lan"
            except Exception:
                self.unregister_lan(peer_pubkey)
        if self.publish:
            encrypted = nip44_encrypt(self.sk, peer_pubkey, json.dumps(msg_dict))
            await self.publish(sign_event(self.sk, 4, encrypted, [["p", peer_pubkey]]))
            return "relay"

    async def file_forward(self, peer_pubkey, file_data, filename):
        """Forward a file to a peer in chunks."""
        CHUNK = 256 * 1024
        total = max((len(file_data) + CHUNK - 1) // CHUNK, 1)
        if peer_pubkey in self.lan_clients:
            ws = self.lan_clients[peer_pubkey]
            await ws.send(json.dumps({"type": "file_start", "name": filename, "size": len(file_data), "total_chunks": total}))
            import base64
            for i in range(total):
                chunk = file_data[i*CHUNK:(i+1)*CHUNK]
                await ws.send(json.dumps({"type": "file_chunk", "index": i, "total": total, "name": filename, "data": base64.b64encode(chunk).decode()}))
            await ws.send(json.dumps({"type": "file_end", "name": filename}))
        elif self.publish:
            import base64
            for i in range(total):
                chunk = file_data[i*CHUNK:(i+1)*CHUNK]
                msg = json.dumps({"type": "file_chunk", "file_id": filename, "index": i, "total": total, "name": filename, "data": base64.b64encode(chunk).decode()})
                encrypted = nip44_encrypt(self.sk, peer_pubkey, msg)
                await self.publish(sign_event(self.sk, 4, encrypted, [["p", peer_pubkey]]))
                await asyncio.sleep(0.05)


class Connection:
    """Unified peer connection. Routes: LAN WS → relay fallback."""

    def __init__(self, keyfile, peer_pubkey=""):
        self.sk = load_or_create_key(keyfile)
        self.pubkey = self.sk.public_key.format().hex()
        self.peer = peer_pubkey
        self.ws = None
        self._on_msg = None

    def on_message(self, callback):
        self._on_msg = callback

    async def connect(self, lan_addr=None):
        """Connect via best path. Returns True on success."""
        # Try LAN first
        if lan_addr:
            if ":" not in lan_addr:
                lan_addr = f"{lan_addr}:{PORT}"
            try:
                ws = await websockets.connect(f"ws://{lan_addr}", proxy=None)
                await ws.recv()  # identity
                await ws.send(json.dumps({"type": "lan_hello", "pubkey": self.pubkey}))
                await asyncio.wait_for(ws.recv(), 5)  # ack
                self.ws = ws
                asyncio.create_task(self._listen_lan())
                return True
            except Exception:
                pass

        # Fallback: Nostr relay
        try:
            relay_urls = load_relays()
            active = await select_best_relays(relay_urls)
        except Exception:
            return False
        if not active:
            return False

        profile = json.dumps({"name": "cli", "about": "CipherPipe peer"})
        for url in active:
            try:
                ws = await websockets.connect(url)
                await ws.send(json.dumps(["EVENT", sign_event(self.sk, 0, profile, [])]))
                await ws.close()
            except Exception:
                pass
            asyncio.create_task(self._listen_relay(url))
        # Use first relay as publisher
        self._relays = active
        return True if active else False

    async def send(self, text):
        if self.ws:
            await self.ws.send(json.dumps({"type": "msg", "text": text, "to": self.peer}))
        elif hasattr(self, '_relays') and self._relays:
            from backend.core.crypto import nip44_encrypt
            encrypted = nip44_encrypt(self.sk, self.peer, text)
            event = sign_event(self.sk, 4, encrypted, [["p", self.peer]])
            msg = json.dumps(["EVENT", event])
            for url in self._relays:
                try:
                    ws = await websockets.connect(url)
                    await ws.send(msg)
                    await ws.close()
                except Exception:
                    pass

    async def send_file(self, filepath):
        if not self.ws:
            return
        import base64
        with open(filepath, "rb") as f:
            data = f.read()
        name = os.path.basename(filepath)
        CHUNK = 256 * 1024
        total = max((len(data) + CHUNK - 1) // CHUNK, 1)
        await self.ws.send(json.dumps({"type": "file_start", "name": name, "size": len(data), "total_chunks": total, "to": self.peer}))
        for i in range(total):
            chunk = data[i*CHUNK:(i+1)*CHUNK]
            await self.ws.send(json.dumps({"type": "file_chunk", "index": i, "total": total, "name": name, "data": base64.b64encode(chunk).decode()}))
        await self.ws.send(json.dumps({"type": "file_end", "name": name}))

    async def _listen_lan(self):
        try:
            async for raw in self.ws:
                frame = json.loads(raw)
                t = frame.get("type", "")
                frm = frame.get("from", "")
                if t == "msg" and frm and frm != "me":
                    if self._on_msg:
                        await self._on_msg("lan", frm, frame.get("text", ""))
                elif t == "file_end":
                    if self._on_msg:
                        await self._on_msg("lan", frm, f"[file: {frame.get('name','')}]")
        except Exception:
            self.ws = None

    async def _listen_relay(self, url):
        while True:
            try:
                ws = await websockets.connect(url, ping_interval=20, ping_timeout=10)
                sub = json.dumps(["REQ", "cp_cli", {"kinds": [0, 4, 5, 7, 1059], "#p": [self.pubkey], "since": int(time.time()) - 86400}])
                await ws.send(sub)
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if msg[0] != "EVENT" or len(msg) < 3 or msg[1] != "cp_cli":
                            continue
                        event = msg[2]
                        if event.get("kind") not in (4, 1059):
                            continue
                        pt = nip44_decrypt(self.sk, event["pubkey"], event["content"])
                        if self._on_msg:
                            await self._on_msg("relay", event["pubkey"][:12], pt)
                    except Exception:
                        pass
            except Exception:
                await asyncio.sleep(5)
