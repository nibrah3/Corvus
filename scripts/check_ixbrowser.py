"""
check_ixbrowser.py — Check if IXBrowser is running; launch it if not.

Called by Claude Code when [Launch IXBrowser] is selected in AskUserQuestion.

Output (JSON to stdout):
  { "running": bool, "launched": bool, "message": str }

Usage:
  python scripts/check_ixbrowser.py [--launch]
"""
import json
import os
import socket
import sys
import time
from pathlib import Path

CB_DIR = Path(__file__).resolve().parent.parent

_ENV_LOADED = False


def _load_env():
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = CB_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    _ENV_LOADED = True


def is_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 53200), timeout=2):
            return True
    except Exception:
        return False


def find_ixbrowser_exe() -> str | None:
    _load_env()

    # 1. Explicit override in .env
    explicit = os.environ.get("IXBROWSER_EXE_PATH", "")
    if explicit and os.path.isfile(explicit):
        return explicit

    # 2. Common install paths
    candidates = [
        r"C:\Program Files\IXBrowser\IXBrowser.exe",
        r"C:\Program Files (x86)\IXBrowser\IXBrowser.exe",
        os.path.expanduser(r"~\AppData\Local\IXBrowser\IXBrowser.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\IXBrowser\IXBrowser.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    # 3. Registry lookup (HKCU\Software\IXBrowser)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\IXBrowser") as key:
            exe, _ = winreg.QueryValueEx(key, "InstallPath")
            candidate = os.path.join(exe, "IXBrowser.exe")
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass

    return None


def launch_and_wait(timeout: int = 60) -> bool:
    exe = find_ixbrowser_exe()
    if not exe:
        return False

    import subprocess
    # Use CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS so IXBrowser owns its own console
    # and is not killed when this script exits.
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([exe], creationflags=flags, close_fds=True,
                         cwd=os.path.dirname(exe))
    except Exception:
        # Fallback: use shell=True to let Windows resolve the exe normally
        subprocess.Popen(exe, shell=True)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_running():
            return True
        time.sleep(2)
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", action="store_true",
                        help="Launch IXBrowser if not running, then wait for it")
    args = parser.parse_args()

    if is_running():
        print(json.dumps({"running": True, "launched": False,
                          "message": "IXBrowser is running (port 53200 available)."}))
        return

    if not args.launch:
        exe = find_ixbrowser_exe()
        print(json.dumps({
            "running": False,
            "launched": False,
            "message": f"IXBrowser not running. Exe found at: {exe}" if exe
                       else "IXBrowser not running and exe not found. Set IXBROWSER_EXE_PATH in E:\\cb-core\\.env",
        }))
        return

    print("Launching IXBrowser...", file=sys.stderr)
    launched = launch_and_wait()
    if launched:
        print(json.dumps({"running": True, "launched": True,
                          "message": "IXBrowser launched and ready."}))
    else:
        exe = find_ixbrowser_exe()
        print(json.dumps({
            "running": False,
            "launched": False,
            "message": f"Could not start IXBrowser. Exe: {exe or 'not found'}. "
                       "Set IXBROWSER_EXE_PATH in E:\\cb-core\\.env if installed elsewhere.",
        }))


if __name__ == "__main__":
    main()
