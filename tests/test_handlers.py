#!/usr/bin/env python3
"""Handler unit tests: message dispatch with fake websockets and mock ctx."""
import asyncio, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coincurve
import pytest

from backend.hub.session import ClientSession
from backend.hub.handlers import HANDLERS, HubContext, on_msg, on_lan_hello, on_peer_status


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    import backend.core.store as store
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "test.db"))
    store.init_db()


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data) if isinstance(data, str) else data)

    def last(self):
        return self.sent[-1] if self.sent else None


def make_ctx(**overrides):
    sk = coincurve.PrivateKey()
    published = []

    async def nostr_publish(event):
        published.append(event)

    async def resubscribe_all():
        pass

    def log_event(ev, **kw):
        pass

    class FakeLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass

    ctx = HubContext(
        sk=sk, pubkey=sk.public_key.format().hex(),
        lan_clients={}, browsers=set(), watched_pubkeys=set(),
        nostr_publish=nostr_publish, resubscribe_all=resubscribe_all,
        log_event=log_event, logger=FakeLogger(),
    )
    ctx._published = published
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


def test_dispatch_table_covers_protocol():
    expected = {"lan_hello", "msg", "file", "file_end", "file_path", "file_send",
                "typing", "read_receipt", "reaction", "contacts", "create_identity",
                "peer_status", "delete_contact", "search", "history"}
    assert expected <= set(HANDLERS.keys())


async def test_lan_hello_registers_peer():
    ws = FakeWS()
    sess = ClientSession(ws)
    ctx = make_ctx()
    await on_lan_hello({"pubkey": "ab" * 32}, sess, ctx)
    assert not sess.is_browser
    assert sess.peer_pubkey == "ab" * 32
    assert ctx.lan_clients["ab" * 32] is ws
    assert ws.sent[0]["type"] == "lan_hello_ack"


async def test_browser_msg_to_lan_peer():
    sender, receiver = FakeWS(), FakeWS()
    peer_sk = coincurve.PrivateKey()
    peer_pk = peer_sk.public_key.format().hex()
    ctx = make_ctx()
    ctx.lan_clients[peer_pk] = receiver
    sess = ClientSession(sender)
    await on_msg({"text": "hi", "to": peer_pk}, sess, ctx)
    assert receiver.last()["text"] == "hi"
    assert receiver.last()["delivered"] is True
    assert sender.last()["delivered"] is True


async def test_browser_msg_to_relay_peer_publishes():
    ws = FakeWS()
    ctx = make_ctx()
    sess = ClientSession(ws)
    target = coincurve.PrivateKey().public_key.format().hex()
    await on_msg({"text": "via relay", "to": target}, sess, ctx)
    assert len(ctx._published) == 1
    assert ctx._published[0]["kind"] == 4
    assert ws.last()["delivered"] is False
    # New peer should now be watched
    from backend.core.crypto import to_nostr_pk
    assert to_nostr_pk(target) in ctx.watched_pubkeys


async def test_msg_empty_fields_ignored():
    ws = FakeWS()
    ctx = make_ctx()
    sess = ClientSession(ws)
    await on_msg({"text": "", "to": "x"}, sess, ctx)
    await on_msg({"text": "hi", "to": ""}, sess, ctx)
    assert ws.sent == []
    assert ctx._published == []


async def test_peer_status_online_offline():
    ws = FakeWS()
    ctx = make_ctx()
    sess = ClientSession(ws)
    pk = "ab" * 32
    await on_peer_status({"pubkey": pk}, sess, ctx)
    assert ws.last()["online"] is False
    ctx.lan_clients[pk] = FakeWS()
    await on_peer_status({"pubkey": pk}, sess, ctx)
    assert ws.last()["online"] is True


async def test_session_pending_file_cleanup(tmp_path):
    ws = FakeWS()
    sess = ClientSession(ws)
    f = open(tmp_path / "x.bin", "wb")
    sess.pending_file = {"fh": f}
    sess.close_pending_file()
    assert sess.pending_file is None
    assert f.closed
