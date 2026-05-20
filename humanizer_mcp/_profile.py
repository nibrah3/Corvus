"""
BehaviorProfile — typing and mouse timing parameters for one session.
Small per-session variation baked in so repeated sessions don't produce
identical statistical signatures.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field


@dataclass
class BehaviorProfile:
    # Typing
    wpm: float = 62.0          # base words-per-minute
    iki_k: float = 1.67        # ex-Gaussian shape (K) for inter-keystroke interval
    iki_scale: float = 0.055   # ex-Gaussian scale (sigma) for IKI in seconds
    error_rate: float = 0.025  # fraction of chars that produce a typo+correction
    hold_k: float = 0.8        # ex-Gaussian K for key hold duration
    hold_scale: float = 0.020  # ex-Gaussian scale for hold in seconds (mean ~80ms)

    # Mouse
    mouse_speed: float = 0.30  # base duration (s) for a ~400px move
    pre_click_k: float = 1.2   # ex-Gaussian K for pre-click hover pause
    pre_click_scale: float = 0.035  # scale for pre-click pause (~150ms mean)
    overshoot_prob: float = 0.30    # probability of overshoot on long moves (>300px)

    # Scroll
    scroll_steps_min: int = 2
    scroll_steps_max: int = 5

    # Session-level fatigue
    chars_typed: int = field(default=0, repr=False)

    @classmethod
    def default(cls) -> "BehaviorProfile":
        """Create a default profile with ±10% session variation."""
        rng = random.Random()
        return cls(
            wpm=rng.gauss(62.0, 5.0),
            iki_scale=rng.gauss(0.055, 0.005),
            error_rate=rng.gauss(0.025, 0.003),
            mouse_speed=rng.gauss(0.30, 0.03),
        )

    def fatigue_factor(self) -> float:
        """Slow down 0.05% per character typed — matches HumanTyping research."""
        return 1.0 + self.chars_typed * 0.0005
