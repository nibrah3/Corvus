"""Dump axtree for a URL via an open IXBrowser profile."""
import sys, os, json
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import time
from careerbridge.ixbrowser_connector import ix_open_profile
from careerbridge.cdp_executor import CDPExecutor
from careerbridge.assessment_pipeline import _ANSWERABLE_ROLES, _TEXT_INPUT_ROLES

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.16personalities.com/free-personality-test"
profile_id = int(sys.argv[2]) if len(sys.argv) > 2 else 12

print(f"Opening profile {profile_id} and navigating to {url}")
cdp_url = ix_open_profile(profile_id)
print(f"CDP URL: {cdp_url}")

cdp = CDPExecutor()
cdp.connect_ws(cdp_url)
cdp.navigate(url)
time.sleep(3)

tree = cdp.get_axtree()
print(f"\nTotal nodes: {len(tree)}")
print("\nAnswerable nodes:")
for n in tree:
    if n["role"] in _ANSWERABLE_ROLES:
        print(f"  {n['role']:<20} {n['name'][:60]}")
print("\nText input nodes:")
for n in tree:
    if n["role"] in _TEXT_INPUT_ROLES:
        print(f"  {n['role']:<20} {n['name'][:60]}")
print("\nButton/link nodes:")
for n in tree:
    if n["role"] in ("button", "link"):
        print(f"  {n['role']:<20} {n['name'][:60]}")
cdp.disconnect()
