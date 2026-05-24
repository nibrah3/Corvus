"""Try to open IXBrowser profiles and find a working one."""
import sys, os, json
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import requests

profile_id = int(sys.argv[1]) if len(sys.argv) > 1 else 14
resp = requests.post(
    "http://127.0.0.1:53200/api/v2/profile-open",
    json={"profile_id": profile_id},
    timeout=60,
)
data = resp.json()
print(json.dumps(data, indent=2))
