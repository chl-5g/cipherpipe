#!/usr/bin/env python3
"""CipherPipe CLI — terminal chat client (thin)."""
import asyncio, json, os, sys, threading, websockets
from datetime import datetime
from backend.core.config import PORT, KEY_FILE as DEFAULT_KEYFILE
from backend.core.crypto import load_or_create_key

_ts = lambda: datetime.now().strftime("%H:%M")
_lock = threading.Lock()
_prompt = "> "
_display = asyncio.Queue()


def _print(msg):
    with _lock:
        sys.stdout.write(f"\r\033[K{msg}\n{_prompt}")
        sys.stdout.flush()


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--peer", help="Peer pubkey")
    parser.add_argument("--connect-lan", help="Proxy address")
    parser.add_argument("--keyfile", default=DEFAULT_KEYFILE)
    args = parser.parse_args()

    sk = load_or_create_key(args.keyfile)
    pubkey = sk.public_key.format().hex()
    peer = args.peer or ""

    addr = args.connect_lan or "localhost"
    if ":" not in addr:
        addr = f"{addr}:{PORT}"
    ws = await websockets.connect(f"ws://{addr}", proxy=None)
    await ws.recv()  # identity
    await ws.send(json.dumps({"type": "lan_hello", "pubkey": pubkey}))
    await asyncio.wait_for(ws.recv(), 5)  # ack

    # ── Display loop ──
    async def display_loop():
        while True:
            msg = await _display.get()
            _print(msg)
    asyncio.create_task(display_loop())

    # ── Receiver ──
    async def receiver():
        try:
            async for raw in ws:
                frame = json.loads(raw)
                t = frame.get("type", "")
                frm = frame.get("from", "")
                if t == "read_receipt":
                    await _display.put("\033[34m✓ 对方已读\033[0m")
                    continue
                if t == "msg" and frm == "me":
                    txt = frame.get("text","")
                    if frame.get("delivered"):
                        await _display.put(f"\033[34m✓ 已送达\033[0m")
                    continue
                if t == "msg" and frm:
                    text = frame.get('text','')
                    msg_id = frame.get('id','')
                    await _display.put(f"\033[36m{frm}\033[0m \033[2m{_ts()}\033[0m  {text}")
                    if msg_id:
                        await ws.send(json.dumps({"type": "read_receipt", "event_id": msg_id, "peer": frm}))
                elif t == "file":
                    await _display.put(f"\033[36m{frm}\033[0m \033[2m{_ts()}\033[0m  [file: {frame.get('name','')} ({frame.get('size',0)}B)]")
                elif t == "reaction":
                    await _display.put(f"\033[36m{frm}\033[0m \033[2m{_ts()}\033[0m  {frame.get('emoji','')}")
        except Exception:
            pass
    asyncio.create_task(receiver())

    # ── Sender (stdin thread) ──
    send_queue = asyncio.Queue()

    def stdin_reader():
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                send_queue.put_nowait(None)
                return
            send_queue.put_nowait(line.strip())

    threading.Thread(target=stdin_reader, daemon=True).start()

    print(f"\033[2J\033[H\033[2mchatting with {peer[:12]}...  /send <file>  /quit\033[0m")
    print(_prompt, end="", flush=True)

    while True:
        text = await send_queue.get()
        if text is None:
            break
        if not text:
            _print("")
            continue
        if text in ("/quit", "/exit"):
            _print("\033[2mbye\033[0m")
            break
        if text.startswith("/send "):
            filepath = text[6:].strip()
            if os.path.isfile(filepath):
                name = os.path.basename(filepath)
                size = os.path.getsize(filepath)
                _print(f"\033[2m{_ts()} → [send: {name}]\033[0m")
                with open(filepath, "rb") as f:
                    data = f.read()
                await ws.send(json.dumps({"type": "file", "name": name, "size": size, "to": peer}))
                await ws.send(data)
            else:
                _print(f"\033[31mfile not found: {filepath}\033[0m")
            continue
        _print(f"\033[2m{_ts()}\033[0m {text}")
        await ws.send(json.dumps({"type": "msg", "text": text, "to": peer}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
