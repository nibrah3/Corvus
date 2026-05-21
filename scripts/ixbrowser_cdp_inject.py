# scripts/ixbrowser_cdp_inject.py
#
# Step 1 of the CDP plan: inject --remote-debugging-port=9222 into ixBrowser
# so cdp_executor can attach via WebSocket.
#
# ixBrowser is an Electron antidetect browser. Profile launch args are stored
# server-side, not in local JSON files. The injection therefore has two modes:
#
#   Mode A — JSON file injection (GoLogin, Multilogin, generic Chromium-based):
#     Scans known config roots for JSON files with args/flags arrays and patches
#     them directly. Idempotent — safe to re-run.
#
#   Mode B — ixBrowser (Electron, server-side config):
#     Cannot patch local files. Instead:
#     1. Checks whether a Chromium process launched by ixBrowser is already
#        listening on a debugging port (psutil scan).
#     2. If not found, prints exact manual steps to add the flag via the
#        ixBrowser profile settings UI.
#
# Usage:
#   python scripts/ixbrowser_cdp_inject.py          # auto-detect + inject/report
#   python scripts/ixbrowser_cdp_inject.py --dry-run # scan only, no writes
#   python scripts/ixbrowser_cdp_inject.py --check   # only check if CDP is live

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CDP_FLAG = "--remote-debugging-port=9222"
CDP_PORT = 9222

SEARCH_ROOTS = [
    Path(os.environ.get("APPDATA", ""), "ixBrowser"),
    Path(os.environ.get("LOCALAPPDATA", ""), "ixBrowser"),
    Path("C:/Program Files/ixBrowser"),
    Path("C:/Program Files (x86)/ixBrowser"),
    Path(os.environ.get("APPDATA", ""), "IXBrowser"),
    Path(os.environ.get("LOCALAPPDATA", ""), "IXBrowser"),
    Path(os.environ.get("APPDATA", ""), "GoLogin"),
    Path(os.environ.get("LOCALAPPDATA", ""), "GoLogin"),
    Path(os.environ.get("APPDATA", ""), "Multilogin"),
]

IXBROWSER_MARKERS = [
    Path("C:/Program Files/ixBrowser/ixBrowser.exe"),
    Path("C:/Program Files (x86)/ixBrowser/ixBrowser.exe"),
]


def is_ixbrowser_installed() -> bool:
    return any(p.exists() for p in IXBROWSER_MARKERS)


def is_electron_based(root: Path) -> bool:
    """Heuristic: ixBrowser and similar Electron apps store no patchable JSON launch configs."""
    app_asar = root.parent / "resources" / "app.asar"
    # Check install dir
    for marker in IXBROWSER_MARKERS:
        install = marker.parent
        if (install / "resources" / "app.asar").exists():
            return True
    return False


def find_json_configs() -> list[Path]:
    hits = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.json"):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                if any(kw in text for kw in ('"args"', '"flags"', '"chromium"', '"launch"', '"extraArgs"', '"extra_args"')):
                    hits.append(p)
            except (PermissionError, OSError):
                pass
    return hits


def inject_flag_into_json(path: Path, dry_run: bool) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False

    modified = False

    def inject_into_list(lst: list) -> bool:
        if CDP_FLAG not in lst:
            lst.append(CDP_FLAG)
            return True
        return False

    def walk(obj):
        nonlocal modified
        if isinstance(obj, dict):
            for key in ("args", "flags", "extraArgs", "extra_args", "launchArgs", "launch_args", "chromiumArgs"):
                if key in obj and isinstance(obj[key], list):
                    if inject_into_list(obj[key]):
                        modified = True
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    if modified:
        print(f"  [INJECT] {path}")
        if not dry_run:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        if CDP_FLAG in path.read_text(encoding="utf-8", errors="ignore"):
            print(f"  [ALREADY] {path}")
        else:
            print(f"  [SKIP]   {path}  (no args array found)")

    return modified


def check_cdp_live() -> int | None:
    """
    Scan running processes for a Chromium subprocess already listening on a
    remote-debugging port. Returns the port number if found, else None.
    """
    try:
        import psutil
    except ImportError:
        print("  psutil not installed — cannot scan processes.")
        return None

    for proc in psutil.process_iter(["name", "cmdline", "pid"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmdline = proc.info["cmdline"] or []
            if name not in ("chrome.exe", "chromium.exe", "ixbrowser_chromium.exe", "browser.exe"):
                continue
            for arg in cmdline:
                m = re.search(r"--remote-debugging-port=(\d+)", arg)
                if m:
                    return int(m.group(1))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None


def print_ixbrowser_manual_steps():
    print("""
  ixBrowser stores profile launch arguments server-side.
  To enable CDP for a profile:

  1. Open ixBrowser and log in.
  2. In the profile list, click the three-dot menu (...) next to the profile.
  3. Select "Edit Profile" (or "Profile Settings").
  4. Find the "Custom Arguments" or "Additional Browser Flags" field.
  5. Add this flag:
       --remote-debugging-port=9222
  6. Save and close the profile settings.
  7. Launch the profile — Chrome will now expose CDP on port 9222.
  8. Run: python scripts/test_cdp.py

  Note: Only one profile can use port 9222 at a time.
  For multiple profiles use 9222, 9223, 9224 etc. and update CDP_PORT in cdp_executor.py.
""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Scan only, no writes")
    parser.add_argument("--check",   action="store_true", help="Only check if CDP port is live")
    args = parser.parse_args()

    print("=== ixBrowser CDP Injection ===")
    print(f"Flag to inject: {CDP_FLAG}\n")

    # ── Check if CDP is already live ─────────────────────────────────────────
    print("Scanning running processes for active CDP port...")
    live_port = check_cdp_live()
    if live_port:
        print(f"  [LIVE] CDP already active on port {live_port} — cdp_executor can connect now.")
        if args.check:
            return
    else:
        print("  [NONE] No Chromium process found with --remote-debugging-port.")

    if args.check:
        sys.exit(1)

    # ── ixBrowser Electron detection ─────────────────────────────────────────
    if is_ixbrowser_installed():
        print("\nixBrowser detected (Electron app — server-side profile config).")
        print("Cannot patch local files. Manual setup required:")
        print_ixbrowser_manual_steps()

    # ── JSON file injection for other browser managers ────────────────────────
    print("Scanning for patchable JSON configs (GoLogin, Multilogin, generic)...")
    configs = find_json_configs()
    if not configs:
        print("  No patchable JSON config files found.")
    else:
        print(f"  Found {len(configs)} candidate file(s):")
        for p in configs:
            inject_flag_into_json(p, dry_run=args.dry_run)

    if args.dry_run:
        print("\n[dry-run] No files were written.")


if __name__ == "__main__":
    main()
