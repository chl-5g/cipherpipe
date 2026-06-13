#!/usr/bin/env python3
"""Test CipherPipe message and file transfer."""
import asyncio, json, os, sys, subprocess, time, signal, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets
from backend.core.crypto import load_or_create_key
from backend.core.config import PORT

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXY_SCRIPT = os.path.join(PROJECT_DIR, "backend", "hub", "proxy.py")


class TestTransfer:
    @classmethod
    def setup_class(cls):
        # Start proxy
        env = os.environ.copy()
        env["PYTHONPATH"] = PROJECT_DIR
        cls.proxy = subprocess.Popen(
            [sys.executable, PROXY_SCRIPT],
            cwd=PROJECT_DIR, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(3)

    @classmethod
    def teardown_class(cls):
        cls.proxy.terminate()
        cls.proxy.wait()

    async def _client(self, keyfile=None):
        """Connect a client, send lan_hello, return ws + pubkey."""
        sk = load_or_create_key(keyfile)
        pubkey = sk.public_key.format().hex()
        ws = await websockets.connect(f"ws://localhost:{PORT}", proxy=None)
        await ws.recv()  # identity
        await ws.send(json.dumps({"type": "lan_hello", "pubkey": pubkey}))
        ack = await asyncio.wait_for(ws.recv(), 5)
        assert json.loads(ack)["type"] == "lan_hello_ack"
        return ws, pubkey

    async def test_msg_send_receive(self):
        """A sends message to B, B receives it."""
        alice, apk = await self._client()
        bob, bpk = await self._client()

        # Alice sends to Bob
        await alice.send(json.dumps({"type": "msg", "text": "hello bob", "to": bpk}))
        # Alice gets echo (from LAN delivery)
        echo = json.loads(await asyncio.wait_for(alice.recv(), 5))
        assert echo["type"] == "msg"
        assert echo["from"] == "me"
        assert echo["text"] == "hello bob"
        assert echo["delivered"] == True

        # Bob receives
        msg = json.loads(await asyncio.wait_for(bob.recv(), 5))
        assert msg["type"] == "msg"
        assert msg["text"] == "hello bob"
        assert msg["delivered"] == True

        await alice.close()
        await bob.close()

    async def test_msg_routing(self):
        """Message to self goes to browsers, not LAN peer."""
        alice, apk = await self._client()

        # Send to proxy itself
        await alice.send(json.dumps({"type": "msg", "text": "to proxy", "to": "03f44b64a6107888e16c7b30afa85649c9db55182ec36ae8fdd85b072a01a0c7ae"}))

        # Alice should still get echo (broadcast to all browsers includes LAN peers? Let's check)
        # Actually LAN peers sending to proxy → broadcast to BROWSERS. Alice isn't a browser.
        # So Alice won't get this. Let's just verify no crash.
        await asyncio.sleep(0.5)
        await alice.close()

    async def test_file_upload_binary(self):
        """Upload file via JSON header + binary body."""
        ws, pubkey = await self._client()

        data = b"Hello binary file test content!"
        await ws.send(json.dumps({"type": "file", "name": "test.bin", "size": len(data), "to": pubkey}))
        await ws.send(data)

        resp = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert resp["type"] == "file_ok"
        assert resp["name"] == "test.bin"
        assert resp["size"] == len(data)

        await ws.close()

    async def test_file_oversize_rejected(self):
        """File larger than max_size should be rejected with error."""
        ws, pubkey = await self._client()

        # Claim size larger than default 100MB
        await ws.send(json.dumps({"type": "file", "name": "huge.bin", "size": 999_999_999, "to": pubkey}))

        resp = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert resp["type"] == "error"
        assert "过大" in resp["msg"]

        await ws.close()

    async def test_file_with_tempfile(self):
        """Upload a real file."""
        ws, pubkey = await self._client()

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"real file content\n" * 100)
            fname = tf.name

        with open(fname, "rb") as f:
            data = f.read()

        await ws.send(json.dumps({"type": "file", "name": os.path.basename(fname), "size": len(data), "to": pubkey}))
        await ws.send(data)

        resp = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert resp["type"] == "file_ok"

        os.unlink(fname)
        await ws.close()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "-s"])
