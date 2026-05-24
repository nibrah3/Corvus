"""Quick helper to list IXBrowser profiles via local API."""
import sys, os
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import requests

resp = requests.post("http://127.0.0.1:53200/api/v2/profile-list", json={}, timeout=10)
data = resp.json()
profiles = data.get("data") or []
print(f"Total profiles: {len(profiles)}")
for p in profiles:
    pid = p.get("id", "?")
    name = p.get("name", "?")
    kernel = p.get("kernel_version", p.get("kernel", "?"))
    status = p.get("status", "?")
    proxy = p.get("proxy", {})
    proxy_str = ""
    if isinstance(proxy, dict):
        proxy_str = f"{proxy.get('type','')}:{proxy.get('host','')}:{proxy.get('port','')}"
    print(f"  id={pid:<5} name={name:<25} kernel={kernel:<5} status={status} proxy={proxy_str}")
