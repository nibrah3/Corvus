# ufo_launcher.py — Launch UFO client with ZeroClaw's humanized executor
#
# Drop-in replacement for E:\UFO-test\ufo\client\client.py.
# Identical to UFO's stock launcher except UFOClient is replaced with
# HumanizedUFOClient, which routes action commands through ZeroClaw's
# pyautogui humanizer instead of UFO's native pywinauto execution.
#
# Usage (run from E:\UFO-test):
#   python E:\cb-core\careerbridge\ufo_launcher.py --ws --ws-server ws://localhost:5000/ws
#   python E:\cb-core\careerbridge\ufo_launcher.py --request "Open Chrome and navigate to ..."
#
# MUST be run from E:\UFO-test so UFO's relative config imports resolve.

import argparse
import asyncio
import logging
import os
import platform as platform_module
import sys
import tracemalloc

# ── Path setup ────────────────────────────────────────────────────────────────
_UFO_ROOT = os.path.dirname(os.path.abspath(__file__))  # E:\cb-core\careerbridge
_UFO_ROOT = r"E:\UFO-test"   # UFO package root
_ZC_ROOT  = r"E:\cb-core"    # ZeroClaw package root

for _p in (_UFO_ROOT, _ZC_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Imports (order matters — UFO first so its relative imports resolve) ───────
from ufo.client.computer import ComputerManager
from ufo.client.mcp.mcp_server_manager import MCPServerManager
from ufo.client.websocket import UFOWebSocketClient
from config.config_loader import get_ufo_config
from ufo.logging.setup import setup_logger

from careerbridge.ufo_executor import HumanizedUFOClient
from careerbridge.schema import BehaviorFingerprint
from careerbridge.types import MouseSpeed

tracemalloc.start()

# ── Args ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="UFO Web Client — ZeroClaw humanized")
parser.add_argument("--client-id",  dest="client_id",      default="client_001")
parser.add_argument("--ws-server",  dest="ws_server_url",  default="ws://localhost:5000/ws")
parser.add_argument("--ws",         action="store_true")
parser.add_argument("--max-retries",type=int, default=5,   dest="max_retries")
parser.add_argument("--request",    dest="request_text",   default=None)
parser.add_argument("--task_name",  dest="task_name",      default=None)
parser.add_argument("--log-level",  dest="log_level",      default="WARNING")
parser.add_argument("--platform",   dest="platform",       default=None,
                    choices=["windows", "linux", "mobile"])
parser.add_argument("--typing-wpm", dest="typing_wpm",     type=int, default=62,
                    help="Humanizer typing speed in WPM (default: 62)")
parser.add_argument("--mouse-speed",dest="mouse_speed",    default="medium",
                    choices=["slow", "medium", "fast"],
                    help="Humanizer mouse speed (default: medium)")
args = parser.parse_args()

if args.platform is None:
    detected = platform_module.system().lower()
    args.platform = detected if detected in ("windows", "linux", "mobile") else "windows"

setup_logger(args.log_level)
logger = logging.getLogger(__name__)

_MOUSE_SPEED_MAP = {"slow": MouseSpeed.SLOW, "medium": MouseSpeed.MEDIUM, "fast": MouseSpeed.FAST}


async def main() -> None:
    ufo_config = get_ufo_config()

    mcp_server_manager = MCPServerManager()
    computer_manager   = ComputerManager(ufo_config.to_dict(), mcp_server_manager)

    profile = BehaviorFingerprint(
        typing_wpm=args.typing_wpm,
        error_rate=0.03,
        mouse_speed=_MOUSE_SPEED_MAP[args.mouse_speed],
        pause_min_ms=80,
        pause_max_ms=350,
    )

    client = HumanizedUFOClient(
        profile=profile,
        mcp_server_manager=mcp_server_manager,
        computer_manager=computer_manager,
        client_id=args.client_id,
        platform=args.platform,
    )

    logger.info("HumanizedUFOClient ready — wpm=%d mouse=%s", args.typing_wpm, args.mouse_speed)

    ws_client = UFOWebSocketClient(args.ws_server_url, client, max_retries=args.max_retries)
    try:
        asyncio.create_task(ws_client.connect_and_listen())
    except Exception as exc:
        logger.error("WebSocket error: %s", exc, exc_info=True)
        sys.exit(1)

    if args.request_text:
        await ws_client.connected_event.wait()
        await ws_client.start_task(args.request_text, args.task_name)

    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
