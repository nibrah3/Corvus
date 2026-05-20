"""
Bot detection live test.
1. Opens Chrome and navigates to 10fastfingers.com (typing speed + pattern analysis)
2. Takes screenshot to verify page state
3. Types using humanizer
4. Screenshots result
"""
import sys
import subprocess
import time
import random

sys.path.insert(0, 'E:/cb-core')

from humanizer_mcp._profile import BehaviorProfile
from humanizer_mcp._mouse import click as mouse_click, _get_position
from humanizer_mcp._keyboard import type_text, press_key, hotkey

import pyautogui

rng = random.Random(99)
profile = BehaviorProfile.default()
print(f"Session profile: wpm={profile.wpm:.1f}, error_rate={profile.error_rate:.3f}, mouse_speed={profile.mouse_speed:.2f}")

# ── 1. Open Chrome ────────────────────────────────────────────────────────────
print("\n[1] Opening Chrome...")
subprocess.Popen([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--new-window",
    "--window-size=1280,900",
    "--window-position=0,0",
])
time.sleep(2.5)

# ── 2. Navigate to 10fastfingers ──────────────────────────────────────────────
print("[2] Navigating to 10fastfingers.com...")
# Focus Chrome window by clicking its title bar area
mouse_click(640, 40, profile=profile, rng=rng)
time.sleep(0.3)

# Ctrl+L to focus address bar
hotkey("ctrl", "l", profile=profile, rng=rng)
time.sleep(0.4)

# Type URL
type_text("https://10fastfingers.com/typing-test/english", profile=profile, rng=rng)
time.sleep(0.2)
press_key("enter", profile=profile, rng=rng)
time.sleep(3.5)  # wait for page to load

# ── 3. Screenshot ─────────────────────────────────────────────────────────────
print("[3] Taking screenshot of loaded page...")
import mss
with mss.mss() as sct:
    sct.shot(output="E:/cb-core/humanizer_mcp/test_01_loaded.png")
print("    Saved: test_01_loaded.png")

# ── 4. Click the typing area and start test ───────────────────────────────────
# 10fastfingers typing area is roughly centered on the page, below the word display
print("[4] Clicking typing input area...")
# The input box on 10fastfingers is typically around y=450-500 at 1280 width
mouse_click(640, 460, profile=profile, rng=rng)
time.sleep(0.5)

# Take another screenshot to confirm focus
with mss.mss() as sct:
    sct.shot(output="E:/cb-core/humanizer_mcp/test_02_focused.png")
print("    Saved: test_02_focused.png")

# ── 5. Type for 60 seconds (10fastfingers default test duration) ──────────────
# We'll type for ~30s to demonstrate, not the full minute
# 10fastfingers feeds words one at a time as you type them + space
# At ~60 WPM, 5 chars/word average, that's ~5 words/s → we type words + space

test_words = (
    "the quick brown fox jumps over the lazy dog and then ran away from the field "
    "where the sun was shining bright and the birds were singing in the morning air "
    "as the children played outside on the green grass near the old oak tree "
    "that had stood for many years in the quiet village by the river "
    "where people came to rest and enjoy the peaceful sounds of nature "
)

print(f"[5] Typing {len(test_words)} chars of test text...")
print("    Watch the cursor and typing speed on screen.")
type_text(test_words, profile=profile, rng=rng)

time.sleep(1.0)

# ── 6. Screenshot the result ──────────────────────────────────────────────────
print("[6] Screenshotting mid-test result...")
with mss.mss() as sct:
    sct.shot(output="E:/cb-core/humanizer_mcp/test_03_typing.png")
print("    Saved: test_03_typing.png")

print(f"\nChars typed this session: {profile.chars_typed}")
print(f"Fatigue at end: {profile.fatigue_factor():.4f}x")
print("\nTest complete. Check screenshots in E:/cb-core/humanizer_mcp/")
