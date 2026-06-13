#!/usr/bin/env python3
"""Load .env into os.environ, provide typed config access."""
import os

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(SRC_DIR))
DATA_DIR = os.path.join(PROJECT_DIR, "data")

_ENV_PATH = os.path.join(PROJECT_DIR, ".env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

PORT = int(os.environ.get("CP_PORT", "8700"))
RELAYS = [u.strip() for u in os.environ.get("CP_RELAYS", "").split(",") if u.strip()]
if not RELAYS:
    RELAYS = ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.nostr.band"]
KEY_FILE = os.path.join(DATA_DIR, os.environ.get("CP_KEY_FILE", "nostr.key"))
RELAY_CONFIG = os.path.expanduser(os.environ.get("CP_RELAY_CONFIG", os.path.join(DATA_DIR, "relays.json")))
