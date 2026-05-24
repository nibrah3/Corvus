"""
Capture MCP — smoke test and benchmark for all 5 backends.

Runs N captures per backend, measures timing, validates output,
saves one sample PNG per backend, prints comparison table.
"""
import sys, time, io, os, traceback
sys.path.insert(0, 'D:/cb-core')

from PIL import Image

N_RUNS   = 8          # captures per backend for timing
OUT_DIR  = "D:/cb-core/capture_mcp/samples"
os.makedirs(OUT_DIR, exist_ok=True)

# ── Backend registry ──────────────────────────────────────────────────────────

from capture_mcp._backend_pyautogui import (
    NAME as N_PA,  available as av_pa,  capture as cap_pa,
)
from capture_mcp._backend_mss import (
    NAME as N_MS,  available as av_ms,  capture as cap_ms,
)
from capture_mcp._backend_dxcam import (
    NAME as N_DX,  available as av_dx,  capture as cap_dx,
)
from capture_mcp._backend_gdi import (
    NAME as N_GD,  available as av_gd,  capture as cap_gd,
)
from capture_mcp._backend_wgc import (
    NAME as N_WG,  available as av_wg,  capture as cap_wg,
)

BACKENDS = [
    (N_PA, av_pa, cap_pa),
    (N_MS, av_ms, cap_ms),
    (N_DX, av_dx, cap_dx),
    (N_GD, av_gd, cap_gd),
    (N_WG, av_wg, cap_wg),
]

# ── Benchmark loop ────────────────────────────────────────────────────────────

print(f"\n{'='*62}")
print(f"  Capture backend benchmark  ({N_RUNS} runs each)")
print(f"{'='*62}\n")

results = []

for name, av_fn, cap_fn in BACKENDS:
    row = {"name": name, "available": False, "error": None,
           "times": [], "size_kb": None, "dims": None}

    if not av_fn():
        row["error"] = "import failed / not installed"
        results.append(row)
        print(f"  [{name:12s}]  UNAVAILABLE")
        continue

    row["available"] = True
    times = []

    for i in range(N_RUNS):
        try:
            t0 = time.perf_counter()
            png = cap_fn()
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000)

            # Validate on first run
            if i == 0:
                img = Image.open(io.BytesIO(png))
                row["dims"] = img.size
                row["size_kb"] = len(png) / 1024
                # Save sample
                with open(f"{OUT_DIR}/{name}_sample.png", "wb") as f:
                    f.write(png)

        except Exception as exc:
            row["error"] = f"run {i+1}: {exc}"
            traceback.print_exc()
            break

    if times:
        row["times"] = times
        avg = sum(times) / len(times)
        mn  = min(times)
        mx  = max(times)
        print(f"  [{name:12s}]  avg={avg:6.1f}ms  min={mn:6.1f}ms  max={mx:6.1f}ms  "
              f"size={row['size_kb']:6.1f}KB  dims={row['dims']}")
    elif row["error"]:
        print(f"  [{name:12s}]  ERROR: {row['error']}")

    results.append(row)

# ── Summary table ─────────────────────────────────────────────────────────────

print(f"\n{'='*62}")
print("  RANKING (by average capture time, lower = faster)")
print(f"{'='*62}")

ranked = sorted(
    [r for r in results if r["times"]],
    key=lambda r: sum(r["times"]) / len(r["times"])
)

for i, r in enumerate(ranked, 1):
    avg = sum(r["times"]) / len(r["times"])
    print(f"  #{i}  {r['name']:12s}  {avg:6.1f}ms avg")

failed = [r for r in results if not r["times"]]
if failed:
    print(f"\n  FAILED/UNAVAILABLE:")
    for r in failed:
        print(f"       {r['name']:12s}  {r['error'] or 'not available'}")

print(f"\nSample PNGs saved to: {OUT_DIR}")
print("Done.\n")
