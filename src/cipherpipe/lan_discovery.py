#!/usr/bin/env python3
"""mDNS LAN peer discovery for CipherPipe."""
import asyncio, json, socket, time, structlog, uuid
from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
from config import PORT

SERVICE_TYPE = "_cipherpipe._tcp.local."
logger = structlog.get_logger("cipherpipe.lan")

LAN_PEERS = {}


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


async def start_lan_discovery(pubkey, port=None):
    if port is None:
        port = PORT
    local_ip = get_local_ip()

    def _run_sync():
        zc = Zeroconf()
        info = ServiceInfo(
            SERVICE_TYPE, f"{pubkey[:8]}-{uuid.uuid4().hex[:6]}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip)], port=port,
            properties={b"pubkey": pubkey.encode(), b"version": b"1"}
        )
        zc.register_service(info)
        zc.add_service_listener(SERVICE_TYPE, [lambda zc, st, name, sc: _on_add(zc, st, name, sc, pubkey, port)])
        return zc

    zc = await asyncio.to_thread(_run_sync)
    logger.info("LAN discovery started", ip=local_ip, port=port)

    async def cleanup():
        while True:
            await asyncio.sleep(30)
            now = time.time()
            for pk in list(LAN_PEERS):
                if now - LAN_PEERS[pk]["last_seen"] > 60:
                    del LAN_PEERS[pk]

    asyncio.create_task(cleanup())


def _on_add(zc, service_type, name, state_change, pubkey, port):
    svc = zc.get_service_info(service_type, name)
    if svc and svc.addresses:
        ip = socket.inet_ntoa(svc.addresses[0])
        pk = svc.properties.get(b"pubkey", b"").decode()
        if pk and pk != pubkey:
            LAN_PEERS[pk] = {"ip": ip, "port": port, "last_seen": time.time()}


def is_lan_reachable(pubkey):
    return pubkey in LAN_PEERS


def get_lan_addr(pubkey):
    peer = LAN_PEERS.get(pubkey)
    return f"ws://{peer['ip']}:{peer['port']}" if peer else None
