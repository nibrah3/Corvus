"""
Memory MCP server — persistent key-value + knowledge graph store.
Replaces the node @modelcontextprotocol/server-memory with a Python HTTP server.
Data persists to memory_store.json in cb-core.
Port: 8709
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from _minmcp import MinMCP

STORE_PATH = os.environ.get("CB_MEMORY_PATH", r"E:\cb-core\memory_store.json")
mcp = MinMCP("memory")

_lock = threading.Lock()


def _load() -> dict:
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"entities": {}, "relations": []}


def _save(data: dict) -> None:
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@mcp.tool()
def create_entities(entities: list) -> dict:
    """
    Create or update entities in the memory store.

    Each entity: {"name": str, "entityType": str, "observations": [str]}

    Args:
        entities: List of entity dicts.

    Returns:
        {created: int, updated: int}
    """
    with _lock:
        data = _load()
        created, updated = 0, 0
        for e in entities:
            name = e.get("name", "")
            if not name:
                continue
            if name in data["entities"]:
                data["entities"][name]["observations"].extend(e.get("observations", []))
                updated += 1
            else:
                data["entities"][name] = {
                    "name": name,
                    "entityType": e.get("entityType", ""),
                    "observations": e.get("observations", []),
                }
                created += 1
        _save(data)
    return {"created": created, "updated": updated}


@mcp.tool()
def add_observations(entity_name: str, observations: list) -> dict:
    """
    Add observations to an existing entity.

    Args:
        entity_name:  Name of the entity to update.
        observations: List of observation strings to add.

    Returns:
        {ok: bool, total_observations: int}
    """
    with _lock:
        data = _load()
        if entity_name not in data["entities"]:
            return {"ok": False, "error": f"Entity '{entity_name}' not found"}
        data["entities"][entity_name]["observations"].extend(observations)
        total = len(data["entities"][entity_name]["observations"])
        _save(data)
    return {"ok": True, "total_observations": total}


@mcp.tool()
def create_relations(relations: list) -> dict:
    """
    Create relations between entities.

    Each relation: {"from": str, "to": str, "relationType": str}

    Args:
        relations: List of relation dicts.

    Returns:
        {created: int}
    """
    with _lock:
        data = _load()
        created = 0
        for r in relations:
            if r not in data["relations"]:
                data["relations"].append(r)
                created += 1
        _save(data)
    return {"created": created}


@mcp.tool()
def search_nodes(query: str) -> dict:
    """
    Search entities by name or observation content.

    Args:
        query: Search string (case-insensitive substring match).

    Returns:
        {entities: list}
    """
    with _lock:
        data = _load()
    q = query.lower()
    results = []
    for name, entity in data["entities"].items():
        if q in name.lower() or any(q in o.lower() for o in entity.get("observations", [])):
            results.append(entity)
    return {"entities": results}


@mcp.tool()
def read_graph() -> dict:
    """
    Return the full memory graph (all entities and relations).

    Returns:
        {entities: dict, relations: list}
    """
    with _lock:
        data = _load()
    return data


@mcp.tool()
def delete_entities(entity_names: list) -> dict:
    """
    Delete entities and any relations involving them.

    Args:
        entity_names: List of entity names to delete.

    Returns:
        {deleted: int}
    """
    with _lock:
        data = _load()
        deleted = 0
        for name in entity_names:
            if name in data["entities"]:
                del data["entities"][name]
                deleted += 1
        data["relations"] = [
            r for r in data["relations"]
            if r.get("from") not in entity_names and r.get("to") not in entity_names
        ]
        _save(data)
    return {"deleted": deleted}


if __name__ == "__main__":
    mcp.run()
