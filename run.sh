#!/bin/bash
# CipherPipe — Nostr bridge runner
cd "$(dirname "$0")"

# Load .env
[ -f .env ] && export $(grep -v '^#' .env | grep -v '^$' | xargs)

PORT="${CP_PORT:-8700}"
OLD_PID=$(lsof -ti :"$PORT" 2>/dev/null)
[ -n "$OLD_PID" ] && kill -9 $OLD_PID 2>/dev/null && sleep 1

export PYTHONPATH="$(dirname "$0"):$PYTHONPATH"
echo "[$(date '+%H:%M:%S')] CipherPipe on :$PORT → http://localhost:$PORT"
python3 backend/hub/proxy.py
