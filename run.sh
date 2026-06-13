#!/bin/bash
# CipherPipe — Nostr bridge runner
cd "$(dirname "$0")"

PROXY_PORT="${1:-8701}"
OLD_PID=$(lsof -ti :"$PROXY_PORT" 2>/dev/null)
[ -n "$OLD_PID" ] && kill -9 $OLD_PID 2>/dev/null && sleep 1

echo "[$(date '+%H:%M:%S')] CipherPipe Nostr bridge on :$PROXY_PORT → http://localhost:$PROXY_PORT"
python3 proxy.py
