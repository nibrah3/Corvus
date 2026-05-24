import sys
sys.path.insert(0, 'D:/cb-core')

from humanizer_mcp._profile import BehaviorProfile
from humanizer_mcp._distributions import sample_iki, bigram_factor, typo_neighbor
from humanizer_mcp._scroll import scroll
import random

print("All humanizer modules import OK")

p = BehaviorProfile.default()
print(f"Profile: wpm={p.wpm:.1f}, error_rate={p.error_rate:.3f}, mouse_speed={p.mouse_speed:.2f}")

iki = sample_iki(p.iki_k, p.iki_scale)
print(f"Sample IKI: {iki*1000:.1f}ms")

print(f"Bigram 'th' factor: {bigram_factor('t', 'h')}")
print(f"Bigram 'qx' factor: {bigram_factor('q', 'x')}")

rng = random.Random(42)
neighbor = typo_neighbor('a', rng)
print(f"Typo neighbor of 'a': {neighbor!r}")

print("Smoke test passed")
