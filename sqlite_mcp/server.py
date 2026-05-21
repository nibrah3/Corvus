"""
SQLite MCP server — HTTP wrapper for careerbridge.db using MinMCP.
Replaces the fragile inline python -c stdio approach.
Port: 8708
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from _minmcp import MinMCP

DB_PATH = os.environ.get("CB_DB_PATH", r"D:\cb-core\careerbridge.db")
mcp = MinMCP("sqlite")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@mcp.tool()
def read_query(query: str) -> dict:
    """
    Execute a SELECT query and return rows as a list of dicts.

    Args:
        query: SQL SELECT statement.

    Returns:
        {rows: list, count: int}
    """
    with _conn() as conn:
        try:
            cur = conn.execute(query)
            rows = [dict(r) for r in cur.fetchall()]
            return {"rows": rows, "count": len(rows)}
        except Exception as exc:
            return {"error": str(exc), "rows": [], "count": 0}


@mcp.tool()
def write_query(query: str) -> dict:
    """
    Execute an INSERT, UPDATE, or DELETE query.

    Args:
        query: SQL write statement.

    Returns:
        {rowcount: int, lastrowid: int}
    """
    with _conn() as conn:
        try:
            cur = conn.execute(query)
            conn.commit()
            return {"rowcount": cur.rowcount, "lastrowid": cur.lastrowid}
        except Exception as exc:
            return {"error": str(exc), "rowcount": 0}


@mcp.tool()
def list_tables() -> dict:
    """
    List all tables in the database.

    Returns:
        {tables: list[str]}
    """
    with _conn() as conn:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return {"tables": [r[0] for r in cur.fetchall()]}


@mcp.tool()
def describe_table(table: str) -> dict:
    """
    Return column info for a table.

    Args:
        table: Table name.

    Returns:
        {columns: list[{name, type, notnull, default, pk}]}
    """
    with _conn() as conn:
        cur = conn.execute(f"PRAGMA table_info({table})")
        cols = [{"name": r["name"], "type": r["type"],
                 "notnull": bool(r["notnull"]), "default": r["dflt_value"],
                 "pk": bool(r["pk"])} for r in cur.fetchall()]
        return {"columns": cols}


if __name__ == "__main__":
    mcp.run()
