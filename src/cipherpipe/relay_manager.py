#!/usr/bin/env python3
"""Dynamic relay pool manager with RTT probing."""
import asyncio, json, os, time, structlog
import websockets

from config import RELAYS as DEFAULT_RELAYS, RELAY_CONFIG

logger = structlog.get_logger("cipherpipe.relay")


def load_relays():
    if os.path.exists(RELAY_CONFIG):
        with open(RELAY_CONFIG) as f:
            return json.load(f)
    return list(DEFAULT_RELAYS)


async def measure_rtt(url, timeout=5):
    try:
        t0 = time.time()
        ws = await asyncio.wait_for(websockets.connect(url), timeout=timeout)
        rtt = (time.time() - t0) * 1000
        await ws.close()
        return rtt
    except Exception:
        return float("inf")


async def select_best_relays(relay_urls, top_n=5):
    tasks = [measure_rtt(url) for url in relay_urls]
    results = await asyncio.gather(*tasks)
    ranked = sorted(zip(relay_urls, results), key=lambda x: x[1])
    active = [u for u, r in ranked[:top_n] if r < float("inf")]
    logger.info("Relay RTT ranking", ranking=[{"url": u, "rtt": round(r)} for u, r in ranked[:len(active)]])
    return active
