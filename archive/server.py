#!/usr/bin/env python3
"""CipherPipe server — WebSocket relay + HTTP for dashboard/API."""
import argparse, asyncio, json, logging, os, time
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import structlog
import websockets
from websockets.asyncio.server import serve
from websockets.http11 import Response as HTTPResponse
from websockets.datastructures import Headers

from db import init_db, create_room, list_rooms, insert_message, get_messages

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
ROOMS = {}  # room_id -> set of websocket connections
START_TIME = time.time()

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


# ── HTTP (dashboard + API) ──

def json_resp(data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode()
    return HTTPResponse(status_code=status, reason_phrase="OK",
                        headers=Headers({"Content-Type": "application/json; charset=utf-8",
                                         "Access-Control-Allow-Origin": "*"}), body=body)

def serve_html(path):
    try:
        with open(os.path.join(BASE_DIR, path), "rb") as f:
            return HTTPResponse(status_code=200, reason_phrase="OK",
                                headers=Headers({"Content-Type": "text/html; charset=utf-8"}), body=f.read())
    except FileNotFoundError:
        return HTTPResponse(status_code=404, reason_phrase="Not Found", headers=Headers({}), body=b"Not found")


async def process_request(connection, request):
    p = request.path
    db = process_request.db

    # Dashboard
    if p == "/":
        return serve_html("dashboard.html")

    # List rooms
    if p == "/rooms":
        rooms = list_rooms(db)
        return json_resp({"rooms": rooms})

    # Message history
    if p.startswith("/messages"):
        qs = parse_qs(urlparse(p).query)
        room = qs.get("room", [None])[0]
        if not room:
            return json_resp({"error": "missing room"}, 400)
        limit = int(qs.get("limit", [50])[0])
        msgs = get_messages(db, room, limit)
        return json_resp({"messages": msgs})

    # Health
    if p == "/health":
        return json_resp({
            "uptime": time.time() - START_TIME,
            "rooms": list(ROOMS.keys()),
            "connections": sum(len(v) for v in ROOMS.values())
        })

    # Everything else → WebSocket upgrade
    return None


# ── WebSocket ──

async def ws_handler(websocket):
    p = websocket.request.path
    qs = parse_qs(urlparse(p).query)
    room = qs.get("room", [None])[0]
    sender = qs.get("from", ["anon"])[0]

    if not room:
        await websocket.close(4000, "missing room")
        return

    db = ws_handler.db
    create_room(db, room)

    ROOMS.setdefault(room, set()).add(websocket)
    online = len(ROOMS[room])
    logger.info(f"[{room}] {sender} joined ({online} online)")
    log_event("agent_joined", room=room, sender=sender, online=online)

    try:
        async for raw in websocket:
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue

            t = frame.get("type", "")

            # Create room via WS
            if t == "create_room":
                rname = frame.get("name", "")
                import uuid
                new_room = uuid.uuid4().hex[:8]
                create_room(db, new_room, rname)
                logger.info(f"Room created: {new_room}")
                log_event("room_created", room_id=new_room, name=rname)
                await websocket.send(json.dumps({
                    "type": "room_created", "room_id": new_room
                }))
                continue

            # Message
            if t == "msg":
                ct = frame.get("ciphertext", "")
                nc = frame.get("nonce", "")
                insert_message(db, room, sender, ct, nc)

                out = json.dumps({
                    "type": "msg",
                    "room_id": room,
                    "from": sender,
                    "ciphertext": ct,
                    "nonce": nc,
                    "received_at": time.time()
                })
                for peer in ROOMS.get(room, set()):
                    if peer is not websocket:
                        try:
                            await peer.send(out)
                        except Exception:
                            pass
    finally:
        ROOMS[room].discard(websocket)
        if not ROOMS[room]:
            del ROOMS[room]
        logger.info(f"[{room}] {sender} left ({len(ROOMS.get(room, set()))} online)")
        log_event("agent_left", room=room, sender=sender)


# ── Main ──

async def main():
    parser = argparse.ArgumentParser(description="CipherPipe server")
    parser.add_argument("--port", type=int, default=8700)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    db = init_db()
    process_request.db = db
    ws_handler.db = db

    logger.info(f"CipherPipe starting on {args.host}:{args.port}")
    log_event("server_start", host=args.host, port=args.port)
    async with serve(ws_handler, args.host, args.port, process_request=process_request):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
