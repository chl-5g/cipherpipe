#!/usr/bin/env python3
"""CipherPipe CLI — light peer client. Connect to proxy or relay, log incoming messages."""
import asyncio, json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import structlog
import websockets
from cipherpipe.config import PORT, RELAYS as DEFAULT_RELAYS, KEY_FILE as DEFAULT_KEYFILE
from cipherpipe.nostr_crypto import load_or_create_key, sign_event, nip44_encrypt, nip44_decrypt
from cipherpipe.relay_manager import load_relays, select_best_relays

structlog.configure(
    processors=[structlog.stdlib.add_log_level, structlog.processors.TimeStamper(fmt="iso"), structlog.dev.ConsoleRenderer()],
    wrapper_class=structlog.stdlib.BoundLogger, context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(), cache_logger_on_first_use=True,
)
log = structlog.get_logger("cipherpipe.cli")


async def listen_relay(relay_url, sk, pubkey):
    while True:
        try:
            ws = await websockets.connect(relay_url, ping_interval=20, ping_timeout=10)
            sub = json.dumps(["REQ", "cp_cli", {"kinds": [0, 4, 5, 7, 1059], "#p": [pubkey], "since": int(time.time()) - 86400}])
            await ws.send(sub)
            log.info("Subscribed", relay=relay_url)
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    if msg[0] != "EVENT" or len(msg) < 3 or msg[1] != "cp_cli":
                        continue
                    event = msg[2]
                    if not event.get("pubkey") or event.get("kind") not in (4, 1059):
                        continue
                    try:
                        pt = nip44_decrypt(sk, event["pubkey"], event["content"])
                    except Exception:
                        continue
                    log.info("Relay message", from_pubkey=event["pubkey"][:16], text=pt[:200])
                except Exception:
                    pass
        except Exception as e:
            log.warning("Relay disconnected", relay=relay_url, error=str(e))
            await asyncio.sleep(5)


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="CipherPipe CLI — peer client")
    parser.add_argument("--peer", help="Peer pubkey to send to")
    parser.add_argument("--name", default="cli", help="Display name")
    parser.add_argument("--connect-lan", help="Connect to proxy via LAN (ip:port or just 'localhost')")
    parser.add_argument("--keyfile", default=DEFAULT_KEYFILE, help="Key file path")
    parser.add_argument("--relay", action="append", help="Additional relay URL")
    args = parser.parse_args()

    sk = load_or_create_key(args.keyfile)
    pubkey = sk.public_key.format().hex()
    peer = args.peer or ""

    relay_urls = load_relays()
    if args.relay:
        relay_urls.extend(args.relay)
    active_relays = await select_best_relays(relay_urls)
    if not active_relays:
        active_relays = DEFAULT_RELAYS

    log.info("Starting", pubkey=pubkey[:16], name=args.name)

    # Publish profile
    profile = json.dumps({"name": args.name, "about": "CipherPipe peer"})
    for url in active_relays:
        try:
            ws = await websockets.connect(url)
            await ws.send(json.dumps(["EVENT", sign_event(sk, 0, profile, [])]))
            await ws.close()
        except Exception:
            pass

    # Start relay listeners
    for url in active_relays:
        asyncio.create_task(listen_relay(url, sk, pubkey))

    # LAN connection
    lan_ws = None
    if args.connect_lan:
        try:
            addr = args.connect_lan
            if ":" not in addr:
                addr = f"{addr}:{PORT}"
            lan_ws = await websockets.connect(f"ws://{addr}", proxy=None)
            await lan_ws.recv()  # skip identity
            await lan_ws.send(json.dumps({"type": "lan_hello", "pubkey": pubkey}))
            ack = json.loads(await asyncio.wait_for(lan_ws.recv(), 5))
            log.info("LAN connected", addr=addr)

            # LAN listener
            async def listen_lan():
                try:
                    async for raw in lan_ws:
                        frame = json.loads(raw)
                        if frame.get("type") == "msg" and frame.get("from") != "me":
                            log.info("LAN message", from_pubkey=frame.get("from",""), text=frame.get("text","")[:200])
                except Exception as e:
                    log.warning("LAN disconnected", error=str(e))
            asyncio.create_task(listen_lan())
        except Exception as e:
            log.warning("LAN connection failed", error=str(e))

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
