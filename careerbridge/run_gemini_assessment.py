# run_gemini_assessment.py — Gemini Flash standalone assessment loop
# SCHEMA_VERSION: 2
#
# Drives a full assessment using Gemini Flash vision only.
# Supports: navigation, clicking, typing prose, scrolling.
#
# Usage:
#   python run_gemini_assessment.py --input-file C:\tmp\gemini_assess_input.json

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import pyautogui

# Load OPENROUTER_API_KEY from shared .env if not already set
_ENV_FILE = r"E:\careerbridge\runtime\.env"
if not os.getenv("OPENROUTER_API_KEY") and os.path.exists(_ENV_FILE):
    with open(_ENV_FILE, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("OPENROUTER_API_KEY=") and "=" in _line:
                os.environ["OPENROUTER_API_KEY"] = _line.split("=", 1)[1].strip()
                break

sys.path.insert(0, r"E:\cb-core")

from careerbridge.capture import CaptureSession
from careerbridge.reasoning.gemini_agent import decide

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = True

_MAX_STEPS       = 60
_SETTLE_S        = 1.5    # wait after click for UI to settle
_SCROLL_SETTLE_S = 0.8
_TYPE_DELAY_S    = 0.04   # seconds per character (human-like typing speed)


def _load_payload(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_personality(payload: dict) -> dict | None:
    p = payload.get("profile")
    if not p:
        return None
    return {
        "openness":                 p["big_five"]["openness"],
        "conscientiousness":        p["big_five"]["conscientiousness"],
        "extraversion":             p["big_five"]["extraversion"],
        "agreeableness":            p["big_five"]["agreeableness"],
        "neuroticism":              p["big_five"]["neuroticism"],
        "extreme_answer_rate":      p["response_bias"]["extreme_answer_rate"],
        "neutral_preference":       p["response_bias"]["neutral_preference"],
        "social_desirability_bias": p["response_bias"]["social_desirability_bias"],
        "consistency_strength":     p["response_bias"]["consistency_strength"],
    }


def _human_click(x: int, y: int) -> None:
    pyautogui.moveTo(x, y, duration=0.35)
    time.sleep(0.05)
    pyautogui.click()


def _human_type(text: str) -> None:
    """Type text character by character with human-like timing variation."""
    import random
    for char in text:
        pyautogui.typewrite(char, interval=0)
        time.sleep(random.uniform(0.04, 0.12))


def run(payload: dict) -> dict:
    window_title = payload.get("window_title", "Chromium")
    mode         = payload.get("mode", "comprehension")
    personality  = _build_personality(payload)

    import pywinauto

    def _focus_main_window() -> None:
        """Bring the main browser window to OS foreground without touching DOM focus."""
        try:
            app = pywinauto.Application(backend="uia").connect(
                title_re=f"(?i).*{window_title}.*", timeout=3
            )
            app.top_window().set_focus()
            time.sleep(0.2)
        except Exception:
            pass

    def _close_unexpected_windows(known_titles: set) -> set:
        """Close any new windows that appeared since last check. Returns updated title set."""
        import pygetwindow as gw
        current = {w.title for w in gw.getAllWindows() if w.title.strip()}
        new_windows = current - known_titles
        for title in new_windows:
            if window_title.lower() not in title.lower():
                # Not our main browser window — close it
                try:
                    wins = gw.getWindowsWithTitle(title)
                    if wins:
                        wins[0].close()
                        print(f"[runner] closed unexpected window: {title!r}", flush=True)
                except Exception:
                    pass
        return current

    steps:   list[dict] = []
    outcome: str        = "incomplete"
    total_latency_ms: int = 0
    consecutive_scrolls: int = 0

    import pygetwindow as gw
    known_windows: set = {w.title for w in gw.getAllWindows() if w.title.strip()}

    with CaptureSession() as session:
        for step in range(_MAX_STEPS):
            # Capture current browser state
            try:
                frame = session.grab(window_title)
            except Exception as e:
                outcome = f"capture_error: {e}"
                break

            win_x = frame.window_bbox.x
            win_y = frame.window_bbox.y

            # Ask Gemini what to do
            try:
                action = decide(
                    frame.data, win_x, win_y,
                    personality=personality,
                    mode=mode,
                )
            except Exception as e:
                outcome = f"gemini_error: {e}"
                break

            total_latency_ms += action.get("_latency_ms", 0)
            steps.append({"step": step, **action})

            act = action.get("action", "wait")

            if act == "complete":
                outcome = "complete"
                break

            elif act == "click":
                x, y = action.get("x"), action.get("y")
                if x is None or y is None:
                    print(f"[runner] step {step}: click with no coords — skipping", flush=True)
                    time.sleep(_SETTLE_S)
                    continue
                screen_w, screen_h = pyautogui.size()
                if not (0 <= x < screen_w and 0 <= y < screen_h):
                    print(f"[runner] step {step}: ({x},{y}) off-screen — skipping", flush=True)
                    time.sleep(_SETTLE_S)
                    continue
                print(f"[runner] step {step}: click ({x},{y}) — {action.get('target','')}", flush=True)
                _human_click(x, y)
                time.sleep(_SETTLE_S)
                consecutive_scrolls = 0
                known_windows = _close_unexpected_windows(known_windows)

            elif act == "type":
                text = action.get("text", "")
                x, y = action.get("x"), action.get("y")
                if not text:
                    print(f"[runner] step {step}: type with no text — skipping", flush=True)
                    continue
                # Click the field first if coordinates given
                if x is not None and y is not None:
                    screen_w, screen_h = pyautogui.size()
                    if 0 <= x < screen_w and 0 <= y < screen_h:
                        _human_click(x, y)
                        time.sleep(0.3)
                print(f"[runner] step {step}: typing {len(text)} chars: {text[:60]!r}", flush=True)
                _human_type(text)
                time.sleep(_SETTLE_S)
                consecutive_scrolls = 0

            elif act == "scroll":
                direction = action.get("scroll_direction", "down")
                amount    = min(int(action.get("scroll_amount", 2)), 2)
                consecutive_scrolls += 1
                # Focus OS window via pywinauto — NOT a DOM click — to avoid trapping
                # Page Down inside a scrollable div (the DOM focus trap bug).
                _focus_main_window()
                key = "pagedown" if direction == "down" else "pageup"
                for _ in range(amount):
                    pyautogui.press(key)
                    time.sleep(0.05)
                print(f"[runner] step {step}: {key} x{amount} (consec={consecutive_scrolls}) — {action.get('target','')}", flush=True)
                time.sleep(_SCROLL_SETTLE_S)
                # Escape scroll loop: if stuck scrolling, jump to end then back up slightly
                if consecutive_scrolls >= 8:
                    print(f"[runner] step {step}: scroll loop detected — Ctrl+End to jump to bottom", flush=True)
                    _focus_main_window()
                    pyautogui.hotkey("ctrl", "end")
                    time.sleep(0.8)
                    consecutive_scrolls = 0

            elif act == "wait":
                print(f"[runner] step {step}: waiting — {action.get('reasoning','')}", flush=True)
                time.sleep(2.0)

            else:
                print(f"[runner] step {step}: unknown action {act!r} — skipping", flush=True)
                time.sleep(_SETTLE_S)

        else:
            outcome = "max_steps_reached"

    avg_latency = round(total_latency_ms / len(steps)) if steps else 0
    print(f"\n[runner] done — outcome={outcome} steps={len(steps)} avg_gemini_latency={avg_latency}ms total_latency={total_latency_ms}ms", flush=True)

    return {
        "outcome": outcome,
        "steps_taken": len(steps),
        "avg_gemini_latency_ms": avg_latency,
        "total_gemini_latency_ms": total_latency_ms,
        "steps": steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", required=True)
    args = parser.parse_args()

    payload = _load_payload(args.input_file)
    result  = run(payload)
    print(json.dumps({k: v for k, v in result.items() if k != "steps"}, indent=2))


if __name__ == "__main__":
    main()
