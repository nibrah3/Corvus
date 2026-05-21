# MCP Server Restart Guide

When an MCP server stops responding you will receive a Telegram alert automatically.
Follow the steps for the affected server below.

---

## General steps (all servers)

1. Open a PowerShell terminal on your Windows machine.
2. Navigate to `D:\cb-core`.
3. Run the restart command for the affected server (see below).
4. Close and reopen Claude Code so it reconnects to the server.

---

## Per-server restart commands

### humanizer
```
cd D:\cb-core
python -m humanizer_mcp.server
```

### capture
```
cd D:\cb-core
python -m capture_mcp.server
```

### uia
```
cd D:\cb-core
python -m uia_mcp.server
```

### browser
```
cd D:\cb-core
python -m browser_mcp.server
```

### gemini
```
cd D:\cb-core
python -m gemini_mcp.server
```

### telegram
```
cd D:\cb-core
python -m telegram_mcp.server
```

### answer
```
cd D:\cb-core
python -m answer_mcp.server
```

### sqlite
```
cd D:\cb-core
python -m mcp_server_sqlite --db-path D:/cb-core/careerbridge.db
```

### memory (node)
```
node C:\Users\Mike\AppData\Roaming\npm\node_modules\@modelcontextprotocol\server-memory\dist\index.js
```

---

## If the restart command itself fails

- Make sure your Python venv is active: `D:\cb-core\.venv\Scripts\activate`
- Check for import errors: `python -c "import <server_module>"`
- Check `D:\cb-core\logs\mcp_<server>.err` for the error detail
- If the error mentions a missing package: `pip install -r D:\cb-core\requirements.txt`

---

## After restarting

Reload Claude Code (close and reopen the app or run `/reload` in the session).
The MCP server will reconnect automatically on next tool call.
