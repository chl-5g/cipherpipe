#!/usr/bin/env python3
"""Message handlers for the unified WebSocket endpoint.

Each handler: async def fn(frame, sess, ctx) — sess is the ClientSession,
ctx is the HubContext with shared hub state and callbacks.
"""
import asyncio, base64, json, os, time

import coincurve

from backend.core.crypto import sign_event, e2e_encrypt, to_nostr_pk
from backend.core.store import (
    add_message, get_messages, get_recent_messages, search_messages,
    list_contacts, delete_contact,
)
from backend.core.config import FILE_MAX_SIZE
from backend.file.transfer import forward_file, safe_download_path

HANDLERS = {}


def handler(msg_type):
    def deco(fn):
        HANDLERS[msg_type] = fn
        return fn
    return deco


class HubContext:
    """Shared hub state passed to every handler."""

    def __init__(self, *, sk, pubkey, lan_clients, browsers, watched_pubkeys,
                 nostr_publish, resubscribe_all, log_event, logger):
        self.sk = sk
        self.pubkey = pubkey
        self.lan_clients = lan_clients
        self.browsers = browsers
        self.watched_pubkeys = watched_pubkeys
        self.nostr_publish = nostr_publish
        self.resubscribe_all = resubscribe_all
        self.log_event = log_event
        self.logger = logger

    def _resolve_peer(self, short_pk):
        """Resolve 12-char pubkey prefix → full 66-char pubkey."""
        # Already full-length
        if len(short_pk) >= 64:
            return short_pk
        # Check active lan clients
        for full in self.lan_clients:
            if full.startswith(short_pk):
                return full
        # Check watched pubkeys (Nostr 64-char format)
        for npk in self.watched_pubkeys:
            full = "02" + npk
            if full.startswith(short_pk):
                return full
        return short_pk

    async def ensure_watched(self, peer):
        """Subscribe relays to a new peer pubkey if not already watched."""
        peer = self._resolve_peer(peer)
        nostr_pk = to_nostr_pk(peer)
        if nostr_pk not in self.watched_pubkeys:
            self.watched_pubkeys.add(nostr_pk)
            await self.resubscribe_all()
        return nostr_pk

    async def send_encrypted(self, peer, payload, extra_tags=None):
        """Encrypt payload for peer and publish via Nostr relays."""
        peer = self._resolve_peer(peer)
        nostr_pk = await self.ensure_watched(peer)
        encrypted = e2e_encrypt(self.sk, peer, payload)
        tags = [["p", nostr_pk]] + (extra_tags or [])
        event = sign_event(self.sk, 4, encrypted, tags)
        await self.nostr_publish(event)
        return event

    async def broadcast_browsers(self, out_json):
        for bw in list(self.browsers):
            try:
                await bw.send(out_json)
            except Exception:
                self.browsers.discard(bw)


# ── LAN peer registration ──

@handler("lan_hello")
async def on_lan_hello(frame, sess, ctx):
    sess.is_browser = False
    sess.peer_pubkey = frame.get("pubkey", "")
    ctx.lan_clients[sess.peer_pubkey] = sess.ws
    ctx.browsers.discard(sess.ws)
    nostr_pk = to_nostr_pk(sess.peer_pubkey)
    new_pubkey = nostr_pk not in ctx.watched_pubkeys
    ctx.watched_pubkeys.add(nostr_pk)
    await sess.ws.send(json.dumps({"type": "lan_hello_ack", "pubkey": ctx.pubkey}))
    ctx.log_event("lan_peer_joined", pubkey=sess.peer_pubkey[:12])
    if new_pubkey:
        await ctx.resubscribe_all()
    # Push recent messages from DB (catches events that arrived before peer connected)
    for row in get_recent_messages(limit=20):
        try:
            await sess.ws.send(json.dumps({
                "type": "msg", "id": row.get("event_id", ""),
                "from": row["pubkey"][:12], "text": row["content"], "delivered": True,
            }))
        except Exception:
            break


# ── Chat message ──

@handler("msg")
async def on_msg(frame, sess, ctx):
    text = frame.get("text", "")
    peer = frame.get("to", "")
    if not text or not peer:
        return

    if not sess.is_browser:
        # LAN peer → route: other LAN peer / hub's browsers / Nostr relay
        eid = f"lan_{int(time.time()*1000)}"
        if peer in ctx.lan_clients:
            out = json.dumps({"type": "msg", "id": eid, "from": sess.peer_pubkey, "text": text, "delivered": True})
            await ctx.lan_clients[peer].send(out)
            await sess.ws.send(json.dumps({"type": "msg", "id": eid, "from": "me", "text": text, "delivered": True}))
            add_message(eid, peer, text, "in", delivered=1)
        elif peer == ctx.pubkey:
            out = json.dumps({"type": "msg", "id": eid, "from": sess.peer_pubkey, "text": text, "delivered": True})
            await ctx.broadcast_browsers(out)
            add_message(eid, sess.peer_pubkey, text, "in", delivered=1)
        else:
            event = await ctx.send_encrypted(peer, text)
            await sess.ws.send(json.dumps({"type": "msg", "id": event["id"], "from": "me", "text": text, "delivered": False}))
            add_message(event["id"], peer, text, "out")
            ctx.log_event("msg_sent", to=peer[:12])
        return

    # Browser → route: LAN first, then Nostr
    if peer in ctx.lan_clients:
        eid = f"lan_{int(time.time()*1000)}"
        out = json.dumps({"type": "msg", "id": eid, "from": "me", "text": text, "delivered": True})
        await ctx.lan_clients[peer].send(out)
        await sess.ws.send(out)
        add_message(eid, peer, text, "out", delivered=1)
        ctx.log_event("msg_sent_lan", to=peer[:12])
        return
    event = await ctx.send_encrypted(peer, text)
    await sess.ws.send(json.dumps({"type": "msg", "id": event["id"], "from": "me", "text": text, "delivered": False}))
    add_message(event["id"], peer, text, "out")
    ctx.log_event("msg_sent", to=peer[:12])


# ── Unified file transfer: {type:"file"} → binary frames → {type:"file_end"} ──

@handler("file")
async def on_file(frame, sess, ctx):
    size = frame.get("size", 0)
    if size > FILE_MAX_SIZE:
        await sess.ws.send(json.dumps({"type": "error", "msg": f"文件过大 ({size} > {FILE_MAX_SIZE})"}))
        return
    save_path = safe_download_path(frame.get("name", ""))
    sess.pending_file = {
        "name": os.path.basename(save_path), "save_path": save_path,
        "size": size, "to": frame.get("to", ""),
        "fh": open(save_path, "wb"), "received": 0,
    }


async def on_binary_frame(raw, sess):
    """Binary WS frame = file chunk for the active streaming upload."""
    if sess.pending_file:
        sess.pending_file["fh"].write(raw)
        sess.pending_file["received"] += 1


@handler("file_end")
async def on_file_end(frame, sess, ctx):
    if not sess.pending_file:
        return
    pf = sess.pending_file
    sess.pending_file = None
    pf["fh"].close()
    size = os.path.getsize(pf["save_path"])
    ctx.logger.info("File received", name=pf["name"], size=size, chunks=pf["received"])
    ctx.log_event("file_received", name=pf["name"], size=size)
    await sess.ws.send(json.dumps({"type": "file_ok", "name": pf["name"], "size": size}))
    peer = pf.get("to", "")
    if peer:
        route = await forward_file(pf["save_path"], peer, ctx.lan_clients, ctx.sk, ctx.nostr_publish)
        add_message(f"file_{int(time.time()*1000)}", peer, pf["name"], "out",
                    msg_type="file", delivered=1 if route == "lan" else 0)


# ── LAN peer file send via local path (CLI compat) ──

@handler("file_path")
async def on_file_path(frame, sess, ctx):
    if sess.is_browser:
        return
    filepath = frame.get("path", "")
    target = frame.get("to", "")
    if filepath and target and os.path.isfile(filepath):
        route = await forward_file(filepath, target, ctx.lan_clients, ctx.sk, ctx.nostr_publish)
        add_message(f"file_{int(time.time()*1000)}", target, os.path.basename(filepath),
                    "out", msg_type="file", delivered=1 if route == "lan" else 0)


# ── Browser inline file send (small files, base64 in one frame) ──

@handler("file_send")
async def on_file_send(frame, sess, ctx):
    peer = frame.get("to", "")
    name = frame.get("name", "")
    data_b64 = frame.get("data", "")
    if not (name and data_b64 and peer):
        return
    file_data = base64.b64decode(data_b64)
    save_path = safe_download_path(name)
    with open(save_path, "wb") as f:
        f.write(file_data)
    ctx.logger.info("File saved from browser", name=name, size=len(file_data))
    ctx.log_event("file_received", name=name, size=len(file_data))
    route = await forward_file(save_path, peer, ctx.lan_clients, ctx.sk, ctx.nostr_publish)
    add_message(f"file_{int(time.time()*1000)}", peer, name, "out",
                msg_type="file", delivered=1 if route == "lan" else 0)
    await sess.ws.send(json.dumps({"type": "file_sent", "name": name, "size": len(file_data)}))


# ── Ephemeral signals: typing / read_receipt / reaction ──

@handler("typing")
async def on_typing(frame, sess, ctx):
    peer = frame.get("to", "")
    if not peer:
        return
    if peer in ctx.lan_clients:
        await ctx.lan_clients[peer].send(json.dumps({"type": "typing", "from": ctx.pubkey[:12]}))
    else:
        try:
            await ctx.send_encrypted(peer, json.dumps({"type": "typing"}))
        except ValueError:
            pass


@handler("read_receipt")
async def on_read_receipt(frame, sess, ctx):
    peer, eid = frame.get("peer", ""), frame.get("event_id", "")
    if not (peer and eid):
        return
    if peer in ctx.lan_clients:
        await ctx.lan_clients[peer].send(json.dumps({"type": "read_receipt", "event_id": eid}))
    else:
        try:
            await ctx.send_encrypted(peer, json.dumps({
                "type": "read_receipt", "event_id": eid, "read_at": int(time.time()),
            }))
        except ValueError:
            pass


@handler("reaction")
async def on_reaction(frame, sess, ctx):
    peer, eid, emoji = frame.get("peer", ""), frame.get("event_id", ""), frame.get("emoji", "")
    if not (peer and eid and emoji):
        return
    if peer in ctx.lan_clients:
        await ctx.lan_clients[peer].send(json.dumps({
            "type": "reaction", "event_id": eid, "emoji": emoji, "from": ctx.pubkey[:12],
        }))
    else:
        try:
            await ctx.send_encrypted(
                peer,
                json.dumps({"type": "reaction", "event_id": eid, "emoji": emoji}),
                extra_tags=[["e", eid]],
            )
        except ValueError:
            pass
    add_message(f"rxn_{ctx.pubkey[:12]}_{eid}_{emoji}", peer, emoji, "out", msg_type="reaction")


# ── Queries: contacts / identity / status / search / history ──

@handler("contacts")
async def on_contacts(frame, sess, ctx):
    await sess.ws.send(json.dumps({"type": "contacts", "data": list_contacts()}))


@handler("create_identity")
async def on_create_identity(frame, sess, ctx):
    sk = coincurve.PrivateKey()
    await sess.ws.send(json.dumps({"type": "identity_created", "pubkey": sk.public_key.format().hex()}))


@handler("peer_status")
async def on_peer_status(frame, sess, ctx):
    pk = frame.get("pubkey", "")
    if pk:
        await sess.ws.send(json.dumps({
            "type": "peer_status", "pubkey": pk, "online": pk in ctx.lan_clients,
        }))


@handler("delete_contact")
async def on_delete_contact(frame, sess, ctx):
    pk = frame.get("pubkey", "")
    if pk:
        delete_contact(pk)


@handler("search")
async def on_search(frame, sess, ctx):
    query = frame.get("query", "").strip()
    if not query:
        return
    try:
        results = search_messages(query + "*")
    except Exception:
        results = []
    await sess.ws.send(json.dumps({"type": "search_results", "data": results}))


@handler("history")
async def on_history(frame, sess, ctx):
    peer = frame.get("peer", "")
    if peer:
        await sess.ws.send(json.dumps({
            "type": "history",
            "data": get_messages(peer, limit=frame.get("limit", 50), before=frame.get("before")),
        }))
