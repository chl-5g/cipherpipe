#!/usr/bin/env python3
"""Per-connection state for the unified WebSocket handler."""


class ClientSession:
    """State for one WebSocket connection (browser tab or LAN peer)."""

    def __init__(self, ws):
        self.ws = ws
        self.is_browser = True
        self.peer_pubkey = None
        # Streaming file upload: {name, size, to, fh, received, save_path}
        self.pending_file = None

    def close_pending_file(self):
        if self.pending_file:
            try:
                self.pending_file["fh"].close()
            except Exception:
                pass
            self.pending_file = None
