"""
launch_browser.py — CLI step: ensure ixBrowser is running.

Usage:
    python launch_browser.py [--wait SECONDS]

Exits 0 with JSON on stdout:
    {"status": "launched"|"already_running"}
Exits 1 on failure with {"error": "..."}.

Window position and size are left exactly as-is (dev mode).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import argparse

_EXE = r"C:\Users\Mike\AppData\Roaming\ixBrowser-Resources\synchronizer\ixBrowser.exe"
_PROCESS_NAME = "ixBrowser.exe"


def _is_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {_PROCESS_NAME}", "/NH", "/FO", "CSV"],
        capture_output=True, text=True,
    )
    return _PROCESS_NAME.lower() in result.stdout.lower()


def launch(wait: int = 15) -> dict:
    if _is_running():
        return {"status": "already_running"}

    subprocess.Popen([_EXE])

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(1)
        if _is_running():
            time.sleep(1)  # let UI settle
            return {"status": "launched"}

    return {"error": f"ixBrowser process not found after {wait}s"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", type=int, default=15)
    args = parser.parse_args()

    result = launch(wait=args.wait)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    sys.exit(1 if "error" in result else 0)


if __name__ == "__main__":
    main()
