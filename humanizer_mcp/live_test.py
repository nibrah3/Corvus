"""
Live desktop test for humanizer_mcp.
Opens Notepad, clicks inside, types a paragraph with full timing model.
Watch the cursor move and keys press on screen.
"""
import sys
import subprocess
import time

sys.path.insert(0, 'D:/cb-core')

from humanizer_mcp._profile import BehaviorProfile
from humanizer_mcp._mouse import click as mouse_click, move as mouse_move
from humanizer_mcp._keyboard import type_text, press_key, hotkey
import random

# Open Notepad
print("Opening Notepad...")
subprocess.Popen(["notepad.exe"])
time.sleep(1.5)  # wait for window

# Profile with fixed seed for reproducibility
rng = random.Random(42)
profile = BehaviorProfile.default()
print(f"Profile: wpm={profile.wpm:.1f}, error_rate={profile.error_rate:.3f}")

# Click center of screen (Notepad text area is roughly there)
# Adjust these if Notepad opens elsewhere on your display
print("Clicking Notepad text area...")
mouse_click(640, 400, profile=profile, rng=rng)
time.sleep(0.3)

test_text = (
    "The quick brown fox jumps over the lazy dog. "
    "This is a live test of the humanizer timing model. "
    "Each character uses ex-Gaussian inter-keystroke intervals with bigram acceleration."
)

print(f"Typing {len(test_text)} characters with humanized timing...")
print("Watch the screen — cursor movement and typing should look human.")
type_text(test_text, profile=profile, rng=rng)

time.sleep(0.5)
print("Pressing Enter twice...")
press_key("enter", profile=profile, rng=rng)
press_key("enter", profile=profile, rng=rng)

type_text("Done. Fatigue chars_typed=" + str(profile.chars_typed), profile=profile, rng=rng)

print(f"\nTest complete. {profile.chars_typed} chars typed.")
print(f"Fatigue factor at end: {profile.fatigue_factor():.4f}x")
