# scripts/ixbrowser_cdp_inject.py
#
# Step 1 of the CDP plan: find ixBrowser's profile launch config and inject
# --remote-debugging-port=9222 so cdp_executor can attach.
#
# Run ONCE before opening the ixBrowser profile you want to automate.
# Re-run to verify the flag is present (idempotent).
#
# Usage:
#   python scripts/ixbrowser_cdp_inject.py          # scan + auto-inject
#   python scripts/ixbrowser_cdp_inject.py --dry-run # scan only, no writes

import argparse
import json
import os
import re
import sys
from pathlib import Path

CDP_FLAG = "--remote-debugging-port=9222"

# Candidate locations where ixBrowser stores profile/browser configs on Windows
SEARCH_ROOTS = [
    Path(os.environ.get("APPDATA", ""), "ixBrowser"),
    Path(os.environ.get("LOCALAPPDATA", ""), "ixBrowser"),
    Path("C:/Program Files/ixBrowser"),
    Path("C:/Program Files (x86)/ixBrowser"),
    Path(os.environ.get("APPDATA", ""), "IXBrowser"),
    Path(os.environ.get("LOCALAPPDATA", ""), "IXBrowser"),
]


def find_json_configs() -> list[Path]:
    """Walk candidate roots for JSON files that look like browser profile configs."""
    hits = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.json"):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                # Must reference Chrome args in some form
                if any(kw in text for kw in ('"args"', '"flags"', '"chromium"', '"launch"', '"extraArgs"', '"extra_args"')):
                    hits.append(p)
            except (PermissionError, OSError):
                pass
    return hits


def inject_flag_into_json(path: Path, dry_run: bool) -> bool:
    """
    Try to inject CDP_FLAG into a JSON config file.
    Returns True if the file was (or would be) modified.
    """
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
        # Check if flag already present
        if CDP_FLAG in path.read_text(encoding="utf-8", errors="ignore"):
            print(f"  [ALREADY] {path}")
        else:
            print(f"  [SKIP]   {path}  (no args array found)")

    return modified


def scan_for_raw_flag_files() -> list[Path]:
    """Also catch configs that store flags as plain strings / arrays in non-JSON formats."""
    hits = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.suffix in (".json", ".conf", ".cfg", ".ini", ".yaml", ".yml", ""):
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    if "remote-debugging" in text:
                        hits.append(p)
                except (PermissionError, OSError, IsADirectoryError):
                    pass
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Scan only, no writes")
    args = parser.parse_args()

    print("=== ixBrowser CDP Injection ===")
    print(f"Flag to inject: {CDP_FLAG}\n")

    # Phase 1: find and patch JSON configs
    configs = find_json_configs()
    if not configs:
        print("No JSON config files found in known ixBrowser locations.")
        print("Searched:")
        for r in SEARCH_ROOTS:
            print(f"  {r}  {'(exists)' if r.exists() else '(not found)'}")
    else:
        print(f"Found {len(configs)} candidate config file(s):")
        for p in configs:
            inject_flag_into_json(p, dry_run=args.dry_run)

    # Phase 2: report any file already containing the flag
    print("\n--- Files already containing remote-debugging flag ---")
    already = scan_for_raw_flag_files()
    if already:
        for p in already:
            print(f"  {p}")
    else:
        print("  (none)")

    if args.dry_run:
        print("\n[dry-run] No files were written.")
    else:
        print("\nDone. Restart the ixBrowser profile for the flag to take effect.")


if __name__ == "__main__":
    main()
