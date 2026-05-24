"""Dump FULL axtree (including text/heading roles) for a URL."""
import sys, os, json, time
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from careerbridge.ixbrowser_connector import ix_open_profile
from careerbridge.cdp_executor import CDPExecutor

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.16personalities.com/free-personality-test"

cdp_url = ix_open_profile(12)
cdp = CDPExecutor()
cdp.connect_ws(cdp_url)
cdp.navigate(url)
time.sleep(3)

# Get raw axtree without filtering
import websocket as _ws_mod
result = cdp._send("Accessibility.getFullAXTree")
nodes = result.get("nodes", [])

# Show all roles
print(f"Total raw nodes: {len(nodes)}")
print("\nAll roles with names (non-empty):")
role_counts = {}
for n in nodes:
    role = n.get("role", {}).get("value", "")
    name_obj = n.get("name", {})
    name = name_obj.get("value", "") if isinstance(name_obj, dict) else str(name_obj)
    if name and role:
        role_counts[role] = role_counts.get(role, 0) + 1
for role, count in sorted(role_counts.items(), key=lambda x: -x[1]):
    print(f"  {role:<25} {count}")

print("\nStaticText + heading nodes (first 30):")
shown = 0
for n in nodes:
    role = n.get("role", {}).get("value", "")
    name_obj = n.get("name", {})
    name = name_obj.get("value", "") if isinstance(name_obj, dict) else str(name_obj)
    if role in ("StaticText", "heading", "paragraph", "text") and name:
        print(f"  [{role}] {name[:100]}")
        shown += 1
        if shown >= 30:
            break

cdp.disconnect()
