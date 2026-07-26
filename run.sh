#!/bin/bash
# CipherPipe — Nostr bridge runner
cd "$(dirname "$0")"

# Auto-install deps if missing
python3 -c "import websockets, cryptography, structlog, coincurve" 2>/dev/null || {
    echo "[CipherPipe] Installing dependencies..."
    pip3 install -r requirements.txt --break-system-packages 2>/dev/null || pip3 install -r requirements.txt
}

# Load .env
[ -f .env ] && export $(grep -v '^#' .env | grep -v '^$' | xargs)

PORT="${CP_PORT:-80}"
OLD_PID=$(sudo lsof -ti :"$PORT" 2>/dev/null)
[ -n "$OLD_PID" ] && sudo kill -9 $OLD_PID 2>/dev/null && sleep 1

export PYTHONPATH="$(dirname "$0"):$PYTHONPATH"
echo "[$(date '+%H:%M:%S')] CipherPipe on :$PORT → http://localhost:$PORT"

# Port < 1024 requires root
if [ "$PORT" -lt 1024 ]; then
    sudo -E python3 backend/hub/proxy.py
else
    python3 backend/hub/proxy.py
fi
