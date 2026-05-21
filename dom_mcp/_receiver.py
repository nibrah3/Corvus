"""HTTP receiver for the browser extension. Single responsibility: accept POST /dom and update the store."""
from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from ._store import DomStore


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _make_handler(store: DomStore) -> type:
    class _Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self.send_response(200)
            self._cors()
            self.end_headers()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                store.update(json.loads(body))
            except (json.JSONDecodeError, Exception):
                pass
            self.send_response(200)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def log_message(self, *args) -> None:  # silence access logs
            pass

    return _Handler


def start_receiver(store: DomStore, port: int = 8711) -> None:
    """Start the DOM receiver HTTP server in a daemon thread."""
    handler = _make_handler(store)
    server = _ThreadedHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
