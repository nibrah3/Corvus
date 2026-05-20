"""
Bot detection live test v2.
Uses Chrome explicitly by finding its window after launch.
Closes any blocking dialogs, navigates to 10fastfingers.com, types.
"""
import sys
import subprocess
import time
import random

sys.path.insert(0, 'E:/cb-core')

from humanizer_mcp._profile import BehaviorProfile
from humanizer_mcp._mouse import click as mouse_click
from humanizer_mcp._keyboard import type_text, press_key, hotkey

import mss

rng = random.Random(77)
profile = BehaviorProfile.default()
print(f"Session profile: wpm={profile.wpm:.1f}, error_rate={profile.error_rate:.3f}")

# ── 1. Kill any leftover Chrome/Edge dialogs, then launch Chrome fresh ─────────
print("\n[1] Launching Chrome...")
subprocess.Popen([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--new-window",
    "--window-size=1280,900",
    "--window-position=50,50",
    "https://10fastfingers.com/typing-test/english"
])
# Chrome needs more time than Edge to open
time.sleep(4.0)

# Dismiss any "Make Chrome default" or Edge recommendation dialogs via Escape
print("[1b] Pressing Escape to close any dialogs...")
press_key("escape", profile=profile, rng=rng)
time.sleep(0.5)
press_key("escape", profile=profile, rng=rng)
time.sleep(1.5)

# Screenshot to see state
with mss.MSS() as sct:
    sct.shot(output="E:/cb-core/humanizer_mcp/t2_01_after_open.png")
print("[1c] Screenshot saved: t2_01_after_open.png")

# ── 2. Click the Chrome window to bring it to foreground ──────────────────────
# Chrome opened at position 50,50 with size 1280x900
# Title bar is at ~y=70 (50 + 20 for title)
print("[2] Clicking Chrome title bar to focus window...")
mouse_click(680, 70, profile=profile, rng=rng)
time.sleep(0.8)

# Wait for 10fastfingers to fully load (it has a CAPTCHA sometimes)
print("[2b] Waiting for page to load...")
time.sleep(3.0)

with mss.MSS() as sct:
    sct.shot(output="E:/cb-core/humanizer_mcp/t2_02_page_loaded.png")
print("    Screenshot saved: t2_02_page_loaded.png")

# ── 3. Click the typing input area ────────────────────────────────────────────
# 10fastfingers layout: word display is roughly y=350-400, input below at y=460-490
# Window starts at y=50, so adjust: page center x=680, typing input ~y=500
print("[3] Clicking typing input...")
mouse_click(680, 500, profile=profile, rng=rng)
time.sleep(0.6)

with mss.MSS() as sct:
    sct.shot(output="E:/cb-core/humanizer_mcp/t2_03_clicked_input.png")
print("    Screenshot saved: t2_03_clicked_input.png")

# ── 4. Type — 10fastfingers expects words separated by spaces ─────────────────
# These are common English words that appear in the 10fastfingers word list
words = (
    "the of and a to in is you that it he was for on are as with his they "
    "be at one have this from or had by hot but some what there we can out "
    "other were all your when up use word how said an each she which do their "
    "time if will way about many then them would write like so these her long "
    "make thing see him two has look more day could go come did my sound no "
    "most number who over know water than call first people may down side been "
    "now find any new take only little why look after well also around another "
    "came come work three word must because does part even place well such "
)

print(f"[4] Typing {len(words)} chars at ~{profile.wpm:.0f} WPM...")
print("    Watch 10fastfingers — words should highlight green as typed correctly.")
type_text(words, profile=profile, rng=rng)

time.sleep(1.5)

# ── 5. Final screenshot ────────────────────────────────────────────────────────
with mss.MSS() as sct:
    sct.shot(output="E:/cb-core/humanizer_mcp/t2_04_result.png")
print("[5] Screenshot saved: t2_04_result.png")

print(f"\nChars typed: {profile.chars_typed}")
print(f"Fatigue factor: {profile.fatigue_factor():.4f}x")
print("Done.")
