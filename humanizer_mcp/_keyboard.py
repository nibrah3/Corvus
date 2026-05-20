"""
Humanized keyboard input.

Timing model: ex-Gaussian (exponnorm) inter-keystroke intervals
              + bigram speed factors from English corpus
              + fatigue: 0.05% slowdown per character typed
              + QWERTY physical neighbor typos at configurable error rate
              + realistic key hold duration (not instantaneous press/release)
Unicode:      pynput.keyboard.Controller.type() — correct on Windows, no admin needed
"""
from __future__ import annotations

import random
import time

from ._profile import BehaviorProfile
from ._distributions import (
    sample_iki,
    sample_hold,
    bigram_factor,
    typo_neighbor,
)

# ── Backend ───────────────────────────────────────────────────────────────────

_kb = None
_Key = None


def _ensure_kb() -> None:
    global _kb, _Key
    if _kb is not None:
        return
    try:
        from pynput.keyboard import Controller as _KC, Key as _K
        _kb = _KC()
        _Key = _K
    except Exception as exc:
        raise ImportError(f"pynput keyboard not available: {exc}. pip install pynput")


# ── Key injection primitives ──────────────────────────────────────────────────

def _press_char(char: str, hold_secs: float) -> None:
    """Press and release a single character with realistic hold duration."""
    _ensure_kb()
    _kb.press(char)
    time.sleep(hold_secs)
    _kb.release(char)


def _backspace(hold_secs: float) -> None:
    _ensure_kb()
    _kb.press(_Key.backspace)
    time.sleep(hold_secs)
    _kb.release(_Key.backspace)


def _press_key(key, hold_secs: float) -> None:
    """Press any pynput Key with hold duration."""
    _ensure_kb()
    _kb.press(key)
    time.sleep(hold_secs)
    _kb.release(key)


# ── High-level type() ─────────────────────────────────────────────────────────

def type_text(
    text: str,
    profile: BehaviorProfile | None = None,
    rng: random.Random | None = None,
) -> None:
    """
    Type text character-by-character with full human timing model:
      - ex-Gaussian IKI with bigram acceleration and fatigue
      - QWERTY-adjacent typos followed by backspace correction
      - Realistic key hold duration per character
      - Inter-word pauses slightly longer than inter-letter pauses
    """
    if not text:
        return
    if profile is None:
        profile = BehaviorProfile.default()
    if rng is None:
        rng = random.Random()

    prev_char = ""

    for i, char in enumerate(text):
        fatigue = profile.fatigue_factor()
        hold = sample_hold(profile.hold_k, profile.hold_scale)

        # Typo: with error_rate probability, press a QWERTY neighbor first
        if char.lower() in "abcdefghijklmnopqrstuvwxyz" and rng.random() < profile.error_rate:
            wrong = typo_neighbor(char, rng)
            if wrong and wrong != char.lower():
                _press_char(wrong, hold * 0.8)
                # Typo detection latency: 80-350ms before user notices and corrects
                detection_delay = max(0.08, min(0.35, rng.gauss(0.18, 0.06)))
                time.sleep(detection_delay)
                _backspace(hold * 0.7)
                # Brief pause after correction — cognitive reset
                time.sleep(max(0.03, rng.gauss(0.06, 0.02)))

        # Type the correct character
        try:
            _press_char(char, hold)
        except Exception:
            # Unicode char that pynput can't press directly — use type()
            try:
                _kb.type(char)
            except Exception:
                pass  # skip unmappable characters

        profile.chars_typed += 1

        # IKI: ex-Gaussian base × bigram factor × fatigue
        if i < len(text) - 1:
            bf = bigram_factor(prev_char, char) if prev_char else 1.0
            iki = sample_iki(profile.iki_k, profile.iki_scale, fatigue) * bf

            # Inter-word pause: space character gets a slightly longer pause
            if char == " ":
                iki *= rng.uniform(1.15, 1.45)

            # Post-punctuation pause: comma, period, etc.
            if char in ".,;:!?":
                iki *= rng.uniform(1.3, 1.8)

            time.sleep(iki)

        prev_char = char


def press_key(
    key_name: str,
    profile: BehaviorProfile | None = None,
    rng: random.Random | None = None,
) -> None:
    """
    Press a named key (enter, tab, escape, backspace, etc.) with hold duration.
    key_name: standard pynput Key name string.
    """
    if profile is None:
        profile = BehaviorProfile.default()
    if rng is None:
        rng = random.Random()

    hold = sample_hold(profile.hold_k, profile.hold_scale)
    _ensure_kb()

    key_map = {
        "enter":     _Key.enter,
        "tab":       _Key.tab,
        "escape":    _Key.esc,
        "backspace": _Key.backspace,
        "delete":    _Key.delete,
        "home":      _Key.home,
        "end":       _Key.end,
        "pageup":    _Key.page_up,
        "pagedown":  _Key.page_down,
        "up":        _Key.up,
        "down":      _Key.down,
        "left":      _Key.left,
        "right":     _Key.right,
        "f5":        _Key.f5,
    }

    key = key_map.get(key_name.lower())
    if key is None:
        return  # unknown key — skip silently

    _press_key(key, hold)


def hotkey(
    *keys: str,
    profile: BehaviorProfile | None = None,
    rng: random.Random | None = None,
) -> None:
    """
    Press a key combination (e.g. hotkey('ctrl', 'a')).
    Keys are pressed sequentially with small delays, not simultaneously.
    """
    if profile is None:
        profile = BehaviorProfile.default()
    if rng is None:
        rng = random.Random()

    _ensure_kb()
    modifier_map = {
        "ctrl":  _Key.ctrl,
        "shift": _Key.shift,
        "alt":   _Key.alt,
        "win":   _Key.cmd,
    }

    parsed = []
    for k in keys:
        mk = modifier_map.get(k.lower())
        parsed.append(mk if mk else k)

    hold = sample_hold(profile.hold_k, profile.hold_scale)
    inter_key_delay = max(0.015, rng.gauss(0.030, 0.008))

    # Press all keys down with slight delays between each
    for key in parsed:
        _kb.press(key)
        time.sleep(inter_key_delay)

    time.sleep(hold)

    # Release in reverse order
    for key in reversed(parsed):
        _kb.release(key)
        time.sleep(inter_key_delay * 0.5)
