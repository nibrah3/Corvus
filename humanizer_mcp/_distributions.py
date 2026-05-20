"""
Timing distributions and keyboard layout data.

Inter-keystroke interval (IKI) and key hold duration follow ex-Gaussian
(exponnorm) distributions — confirmed by Dhakal et al. 2018 (136M keystrokes).

Bigram speed factors from English corpus frequency.
QWERTY neighbor map for realistic typo generation.
"""
from __future__ import annotations

import ctypes
import math
import random

# ── Windows timer precision ───────────────────────────────────────────────────
# Sets timer resolution to 1ms (default is 10-15ms).
# Must be called once at process start. Reduces sleep jitter significantly.
try:
    ctypes.windll.winmm.timeBeginPeriod(1)
    _TIMER_SET = True
except Exception:
    _TIMER_SET = False


def _exgauss_rvs(k: float, scale: float) -> float:
    """
    Pure-Python ex-Gaussian sample: Normal(0, scale) + Exponential(mean=k*scale).
    Equivalent to scipy exponnorm.rvs(k, loc=0, scale=scale) but zero-dep.
    """
    gauss = random.gauss(0.0, scale)
    # expovariate takes rate = 1/mean
    exp = random.expovariate(1.0 / (k * scale)) if (k * scale) > 0 else 0.0
    return gauss + exp


def sample_iki(k: float, scale: float, fatigue: float = 1.0) -> float:
    """
    Sample one inter-keystroke interval in seconds.
    k, scale: ex-Gaussian parameters (K and sigma).
    fatigue: multiplier > 1.0 that slows typing over time.
    Hard floor at 40ms (physical key travel minimum).
    """
    raw = _exgauss_rvs(k, scale)
    return max(0.040, raw * fatigue)


def sample_hold(k: float, scale: float) -> float:
    """Sample key hold duration in seconds. Floor at 20ms."""
    raw = _exgauss_rvs(k, scale)
    return max(0.020, raw)


def sample_pre_click(k: float, scale: float) -> float:
    """Sample pre-click hover pause in seconds. Floor at 60ms."""
    raw = _exgauss_rvs(k, scale)
    return max(0.060, raw)


def sample_mouse_tremor(n_points: int, amplitude_px: float = 1.5):
    """
    Generate Gaussian tremor offsets for n_points.
    Returns (n_points, 2) array of (dx, dy) offsets in pixels.
    Amplitude matches physiological hand tremor (1-3px at 8-12Hz).
    """
    import numpy as np  # lazy — only needed during actual mouse moves
    return np.random.normal(0, amplitude_px, size=(n_points, 2))


# ── QWERTY physical neighbor map ─────────────────────────────────────────────
# Each key maps to its physically adjacent keys on a standard QWERTY layout.
# Used for realistic typo generation — real humans hit neighbors, not ASCII ±1.

QWERTY_NEIGHBORS: dict[str, list[str]] = {
    '1': ['2', 'q'],
    '2': ['1', '3', 'q', 'w'],
    '3': ['2', '4', 'w', 'e'],
    '4': ['3', '5', 'e', 'r'],
    '5': ['4', '6', 'r', 't'],
    '6': ['5', '7', 't', 'y'],
    '7': ['6', '8', 'y', 'u'],
    '8': ['7', '9', 'u', 'i'],
    '9': ['8', '0', 'i', 'o'],
    '0': ['9', 'o', 'p'],
    'q': ['1', '2', 'w', 'a'],
    'w': ['q', 'e', 'a', 's', '2', '3'],
    'e': ['w', 'r', 's', 'd', '3', '4'],
    'r': ['e', 't', 'd', 'f', '4', '5'],
    't': ['r', 'y', 'f', 'g', '5', '6'],
    'y': ['t', 'u', 'g', 'h', '6', '7'],
    'u': ['y', 'i', 'h', 'j', '7', '8'],
    'i': ['u', 'o', 'j', 'k', '8', '9'],
    'o': ['i', 'p', 'k', 'l', '9', '0'],
    'p': ['o', 'l', '0'],
    'a': ['q', 'w', 's', 'z'],
    's': ['a', 'w', 'e', 'd', 'z', 'x'],
    'd': ['s', 'e', 'r', 'f', 'x', 'c'],
    'f': ['d', 'r', 't', 'g', 'c', 'v'],
    'g': ['f', 't', 'y', 'h', 'v', 'b'],
    'h': ['g', 'y', 'u', 'j', 'b', 'n'],
    'j': ['h', 'u', 'i', 'k', 'n', 'm'],
    'k': ['j', 'i', 'o', 'l', 'm'],
    'l': ['k', 'o', 'p'],
    'z': ['a', 's', 'x'],
    'x': ['z', 's', 'd', 'c'],
    'c': ['x', 'd', 'f', 'v'],
    'v': ['c', 'f', 'g', 'b'],
    'b': ['v', 'g', 'h', 'n'],
    'n': ['b', 'h', 'j', 'm'],
    'm': ['n', 'j', 'k'],
    ' ': [' '],  # space bar — no useful neighbor
}


def typo_neighbor(char: str, rng: random.Random) -> str | None:
    """
    Return a QWERTY-adjacent key for char (lowercase).
    Returns None if char has no neighbor map entry.
    """
    c = char.lower()
    neighbors = QWERTY_NEIGHBORS.get(c)
    if not neighbors:
        return None
    return rng.choice(neighbors)


# ── Bigram speed factors ──────────────────────────────────────────────────────
# Common English bigrams typed faster (lower IKI multiplier).
# Rare/awkward bigrams typed slower (higher multiplier).
# Based on Dhakal 2018 and English digraph frequency corpus.

# Multiplier < 1.0 = faster (muscle memory for frequent pairs)
# Multiplier > 1.0 = slower (awkward reach or rare combination)

_FAST_BIGRAMS: dict[str, float] = {
    'th': 0.55, 'he': 0.60, 'in': 0.62, 'er': 0.58, 'an': 0.64,
    're': 0.60, 'on': 0.63, 'en': 0.65, 'at': 0.62, 'es': 0.64,
    'st': 0.60, 'nt': 0.66, 'ou': 0.65, 'to': 0.62, 'ea': 0.63,
    'nd': 0.62, 'ti': 0.64, 'io': 0.63, 'or': 0.62, 'is': 0.64,
    'it': 0.63, 'ar': 0.65, 'ng': 0.60, 'as': 0.64, 'ed': 0.63,
    'ha': 0.64, 've': 0.62, 'se': 0.63, 'al': 0.64, 'me': 0.65,
}

_SLOW_BIGRAMS: dict[str, float] = {
    'qx': 2.2, 'zx': 2.1, 'jq': 2.3, 'vx': 2.0, 'wx': 2.1,
    'xq': 2.2, 'zq': 2.3, 'xz': 2.1, 'qz': 2.2, 'jv': 1.9,
}


def bigram_factor(prev_char: str, curr_char: str) -> float:
    """Return IKI multiplier for this bigram. 1.0 = average speed."""
    bigram = (prev_char + curr_char).lower()
    if bigram in _FAST_BIGRAMS:
        return _FAST_BIGRAMS[bigram]
    if bigram in _SLOW_BIGRAMS:
        return _SLOW_BIGRAMS[bigram]
    # Same-finger penalty (rough approximation)
    same_col = {
        frozenset('qaz'): True, frozenset('wsx'): True,
        frozenset('edc'): True, frozenset('rfv'): True,
        frozenset('tgb'): True, frozenset('yhn'): True,
        frozenset('ujm'): True, frozenset('ik'): True,
        frozenset('ol'): True,
    }
    pair = frozenset([prev_char.lower(), curr_char.lower()])
    for col in same_col:
        if pair <= col:
            return 1.45  # same-finger = slower
    return 1.0
