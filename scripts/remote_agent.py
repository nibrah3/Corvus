"""
CareerBridge Remote Agent
Tiny HTTP command server — listens on localhost:7070.
Accepts authenticated POST /exec, runs PowerShell or Python, returns output.
Started by start_remote_agent.ps1 via SSH reverse tunnel through VPS.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

AUTH_TOKEN = "cb-remote-2026-xk9"
CB_DIR     = r"D:\cb-core"
PYTHON     = r"C:\Python314\python.exe"
PORT       = 7071


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass  # silence access log

    def do_GET(self):
        if self.path == "/ping":
            self._respond(200, b"pong", "text/plain")

    def do_POST(self):
        if self.headers.get("X-Auth") != AUTH_TOKEN:
            self._respond(403, b"forbidden", "text/plain")
            return

        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length))
        cmd    = body.get("cmd", "")
        shell  = body.get("shell", "powershell")

        if shell == "python":
            argv = [PYTHON, "-c", cmd]
        elif shell == "cmd":
            argv = ["cmd", "/c", cmd]
        else:
            argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]

        try:
            r = subprocess.run(
                argv, capture_output=True, text=True,
                timeout=120, cwd=CB_DIR,
            )
            result = {"stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}
        except subprocess.TimeoutExpired:
            result = {"stdout": "", "stderr": "TIMEOUT after 120s", "returncode": -1}
        except Exception as exc:
            result = {"stdout": "", "stderr": str(exc), "returncode": -1}

        self._respond(200, json.dumps(result).encode(), "application/json")

    def _respond(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"CareerBridge remote agent listening on :{PORT}", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
