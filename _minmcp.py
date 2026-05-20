"""
Minimal stdio MCP server — zero heavy dependencies.

Replaces FastMCP for servers that only need stdio transport.
Startup: ~0.5s vs ~8s for FastMCP (no anyio/httpx/uvicorn/pydantic).

Usage:
    from _minmcp import MinMCP
    mcp = MinMCP("my-server")

    @mcp.tool()
    def my_tool(x: int, name: str = "default") -> str:
        '''Tool description shown to Claude.'''
        return f"result: {x} {name}"

    if __name__ == "__main__":
        mcp.run()
"""
from __future__ import annotations

import inspect
import json
import sys
from typing import Any, Callable, Dict, Optional, get_args, get_origin

_MCP_VERSION = "2024-11-05"


# ── Type annotation → JSON Schema ─────────────────────────────────────────────

def _schema(tp: Any) -> dict:
    if tp is inspect.Parameter.empty or tp is None:
        return {"type": "string"}

    origin = get_origin(tp)
    args = get_args(tp)

    # Optional[X] = Union[X, None]
    try:
        from typing import Union
        if origin is Union:
            non_none = [a for a in args if a is not type(None)]
            return _schema(non_none[0]) if non_none else {"type": "string"}
    except ImportError:
        pass

    if origin is list:
        return {"type": "array", "items": _schema(args[0]) if args else {"type": "string"}}

    if origin is dict:
        return {"type": "object"}

    _MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}
    return {"type": _MAP.get(tp, "string")}


# ── Result → MCP content ──────────────────────────────────────────────────────

def _to_content(result: Any) -> list:
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        out = []
        for item in result:
            out.extend(_to_content(item))
        return out
    if not isinstance(result, str):
        result = json.dumps(result, default=str, indent=2)
    return [{"type": "text", "text": result}]


# ── MinMCP ────────────────────────────────────────────────────────────────────

class MinMCP:
    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self._tools: Dict[str, dict] = {}

    # ── Tool registration ──────────────────────────────────────────────────────

    def tool(self, fn: Callable | None = None, *, name: str | None = None, description: str | None = None):
        """Decorator that registers a function as an MCP tool."""
        def _register(f: Callable) -> Callable:
            tool_name = name or f.__name__
            tool_desc = description or (inspect.getdoc(f) or "").strip()

            sig = inspect.signature(f)
            try:
                hints = {k: v for k, v in f.__annotations__.items() if k != "return"}
            except Exception:
                hints = {}

            properties: dict = {}
            required: list[str] = []

            for pname, param in sig.parameters.items():
                tp = hints.get(pname, str)
                properties[pname] = _schema(tp)

                is_optional = param.default is not inspect.Parameter.empty
                if not is_optional:
                    # Also treat Optional[X] as optional
                    origin = get_origin(tp)
                    try:
                        from typing import Union
                        if origin is Union and type(None) in get_args(tp):
                            is_optional = True
                    except ImportError:
                        pass
                if not is_optional:
                    required.append(pname)

            self._tools[tool_name] = {
                "fn": f,
                "description": tool_desc,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
            return f

        return _register(fn) if fn is not None else _register

    # ── Protocol handlers ──────────────────────────────────────────────────────

    def _handle(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        req_id = msg.get("id")
        params = msg.get("params") or {}

        # Notifications have no id — no response required
        if req_id is None:
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": _MCP_VERSION,
                    "capabilities": {
                        "experimental": {},
                        "prompts":    {"listChanged": False},
                        "resources":  {"subscribe": False, "listChanged": False},
                        "tools":      {"listChanged": False},
                    },
                    "serverInfo": {"name": self.name, "version": self.version},
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            tools = [
                {"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                for n, t in self._tools.items()
            ]
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments  = params.get("arguments") or {}
            tool = self._tools.get(tool_name)

            if tool is None:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }
            try:
                result = tool["fn"](**arguments)
                content = _to_content(result)
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {"content": content, "isError": False},
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    },
                }

        # Unknown method
        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    # ── HTTP/SSE server ────────────────────────────────────────────────────────

    def run_http(self, port: int) -> None:
        """Run as Streamable HTTP server. Claude Code connects via type:http url:http://localhost:{port}/mcp"""
        import threading
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from socketserver import ThreadingMixIn

        mcp_ref = self

        class _Server(ThreadingMixIn, HTTPServer):
            daemon_threads = True

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                # Accept both /mcp and /sse (Claude Code path-stripping bug workaround)
                if self.path not in ("/mcp", "/sse", "/"):
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    msg = json.loads(body)
                except json.JSONDecodeError:
                    self.send_error(400, "Bad JSON")
                    return
                response = mcp_ref._handle(msg)
                if response is None:
                    # Notification — no response body needed
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                resp_bytes = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(resp_bytes)

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Mcp-Session-Id")
                self.end_headers()

            def log_message(self, *args):
                pass

        _Server(("127.0.0.1", port), _Handler).serve_forever()

    # ── Stdio run loop ─────────────────────────────────────────────────────────

    def run(self) -> None:
        """Stdio by default. Pass --http PORT to run as persistent HTTP+SSE server."""
        args = sys.argv[1:]
        if "--http" in args:
            idx = args.index("--http")
            if idx + 1 < len(args):
                try:
                    self.run_http(int(args[idx + 1]))
                    return
                except (ValueError, IndexError):
                    pass

        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self._handle(msg)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
