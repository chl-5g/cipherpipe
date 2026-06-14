#!/usr/bin/env python3
"""CipherPipe agent — WebSocket peer with optional auto-reply."""
import asyncio, json, os, sys, time, subprocess, base64

import structlog
import websockets
from backend.core.config import PORT, KEY_FILE as DEFAULT_KEYFILE, PROJECT_DIR
from backend.core.crypto import load_or_create_key

structlog.configure(
    processors=[structlog.stdlib.add_log_level, structlog.processors.TimeStamper(fmt="iso"), structlog.dev.ConsoleRenderer()],
    wrapper_class=structlog.stdlib.BoundLogger, context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(), cache_logger_on_first_use=True,
)
log = structlog.get_logger("cipherpipe.agent")

DATA_DIR = os.path.join(PROJECT_DIR, "data")
INBOX = os.path.join(DATA_DIR, "inbox.jsonl")
OUTBOX = os.path.join(DATA_DIR, "outbox.jsonl")
DL_DIR = os.path.join(DATA_DIR, "downloads")


def make_handler(mode):
    if mode == "echo":
        def echo_handler(text, sender):
            return f"[echo] {text}"
        return echo_handler
    if mode and mode.startswith("cmd:"):
        cmd = mode[4:]
        def cmd_handler(text, sender):
            try:
                r = subprocess.run(cmd, shell=True, input=text, capture_output=True, text=True, timeout=30)
                return r.stdout.strip() or r.stderr.strip()
            except Exception as e:
                return f"[cmd error: {e}]"
        return cmd_handler
    return None


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="CipherPipe agent")
    parser.add_argument("--proxy", default=f"localhost:{PORT}", help="Proxy address")
    parser.add_argument("--keyfile", default=DEFAULT_KEYFILE, help="Key file")
    parser.add_argument("--peer", help="Reply target pubkey (defaults to proxy)")
    parser.add_argument("--reply-mode", default="none", help="Reply mode: none, echo, cmd:<command>")
    args = parser.parse_args()

    sk = load_or_create_key(args.keyfile)
    pubkey = sk.public_key.format().hex()
    handler = make_handler(args.reply_mode)

    log.info("Agent starting", pubkey=pubkey[:16], proxy=args.proxy, reply_mode=args.reply_mode)

    while True:
        try:
            ws = await websockets.connect(f"ws://{args.proxy}", proxy=None)
            id_msg = json.loads(await ws.recv())
            proxy_pubkey = id_msg.get("pubkey", "")
            reply_target = args.peer or proxy_pubkey
            await ws.send(json.dumps({"type": "lan_hello", "pubkey": pubkey}))
            await ws.recv()  # ack
            log.info("Connected")

            async def receiver():
                file_pending = {"active": False, "chunks": {}, "name": "", "total": 0}
                async for raw in ws:
                    try:
                        frame = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    t = frame.get("type", "")

                    if t == "file_start":
                        file_pending = {"active": True, "chunks": {},
                                        "name": frame.get("name",""),
                                        "total": frame.get("total_chunks", 0)}
                        continue

                    if t == "file_chunk" and file_pending["active"]:
                        idx = frame.get("index", 0)
                        file_pending["chunks"][idx] = base64.b64decode(frame.get("data",""))
                        continue

                    if t == "file_end" and file_pending["active"]:
                        fp = file_pending
                        ordered = [fp["chunks"][i] for i in range(fp["total"])]
                        filedata = b"".join(ordered)
                        dl_dir = DL_DIR
                        os.makedirs(dl_dir, exist_ok=True)
                        save_path = os.path.join(dl_dir, fp["name"])
                        with open(save_path, "wb") as f:
                            f.write(filedata)
                        log.info("→ file saved", name=fp["name"], size=len(filedata))
                        with open(INBOX, "a") as f:
                            f.write(json.dumps({"ts": time.time(), "from": "proxy",
                                "text": f"[file: {fp['name']} ({len(filedata)} bytes)]"},
                                ensure_ascii=False) + "\n")
                        if handler:
                            reply = handler(f"[收到文件: {fp['name']}]", "proxy")
                            if reply:
                                await ws.send(json.dumps({"type": "msg", "text": reply, "to": reply_target}))
                                log.info("← auto-reply", text=reply[:100])
                        file_pending = {"active": False, "chunks": {}, "name": "", "total": 0}
                        continue

                    if t != "msg":
                        continue
                    text = frame.get("text", "")
                    sender = frame.get("from", "")
                    msg = {"ts": time.time(), "from": sender, "text": text}
                    with open(INBOX, "a") as f:
                        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                    log.info("→ inbox", text=text[:100])
                    # Auto-reply
                    if handler:
                        reply = handler(text, sender)
                        if reply:
                            await ws.send(json.dumps({"type": "msg", "text": reply, "to": reply_target}))
                            log.info("← auto-reply", text=reply[:100])

            async def sender():
                last_size = 0
                while True:
                    try:
                        sz = os.path.getsize(OUTBOX)
                    except OSError:
                        sz = 0
                    if sz < last_size:
                        last_size = 0
                    if sz > last_size:
                        with open(OUTBOX, "r") as f:
                            f.seek(last_size)
                            for line in f:
                                line = line.strip()
                                if line:
                                    await ws.send(json.dumps({"type": "msg", "text": line, "to": reply_target}))
                                    log.info("← sent", text=line[:100])
                        last_size = sz
                    await asyncio.sleep(0.5)

            await asyncio.gather(receiver(), sender())
        except Exception as e:
            log.warning("Disconnected", error=str(e))
            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
