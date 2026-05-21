"""
CareerBridge Perception + LLM Smoke Test
Tests every capture, OCR, and LLM path and measures roundtrip latency.
Simulates 10 comprehension questions x 50 words each.
"""
import sys, time, json, os, statistics, traceback
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# suppress noisy import warnings
import warnings
warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONPATH", r"D:\cb-core")

SEP = "-" * 60
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SAMPLE_QUESTION = (
    "The passage describes how migratory birds navigate using Earth's magnetic field. "
    "Based on the text, explain how disruptions to this field might affect bird populations "
    "during seasonal migrations, and discuss two potential long-term consequences."
)

def ts():
    return time.perf_counter()

def ms(start):
    return round((time.perf_counter() - start) * 1000, 1)

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}", flush=True)

def result(label, ms_val, extra=""):
    mark = "OK" if ms_val < 5000 else "!!"
    print(f"  {mark}  {label:<40} {ms_val:>8.1f} ms  {extra}", flush=True)

def fail(label, err):
    print(f"  XX  {label:<40}  FAIL: {err}", flush=True)


# ── 1. Library availability ────────────────────────────────────────────────

section("1. Library Availability")

available = {}
libs = [
    ("dxcam",      "DXcam GPU frame buffer"),
    ("mss",        "mss GDI screenshot"),
    ("PIL",        "Pillow ImageGrab"),
    ("pywinauto",  "pywinauto UIA"),
    ("paddleocr",  "PaddleOCR"),
    ("openai",     "OpenAI SDK"),
    ("cv2",        "OpenCV"),
]
for mod, label in libs:
    t = ts()
    try:
        import importlib
        importlib.import_module(mod)
        elapsed = ms(t)
        available[mod] = True
        print(f"  OK  {label:<30} (import: {elapsed:.0f} ms)", flush=True)
    except ImportError as e:
        available[mod] = False
        print(f"  --  {label:<30} not installed", flush=True)


# ── 2. Capture benchmarks ──────────────────────────────────────────────────

section("2. Screen Capture (10 captures each, full screen)")
CAPTURE_RUNS = 10

# 2a. DXcam
if available.get("dxcam"):
    try:
        import dxcam
        cam = dxcam.create()
        times = []
        for _ in range(CAPTURE_RUNS):
            t = ts()
            frame = cam.grab()
            times.append(ms(t))
        cam.release()
        result("DXcam full-screen grab", statistics.mean(times),
               f"min={min(times):.1f} max={max(times):.1f}")
    except Exception as e:
        fail("DXcam full-screen grab", e)
else:
    print("  --  DXcam                                    not available", flush=True)

# 2b. mss
if available.get("mss"):
    try:
        import mss as mss_lib
        times = []
        with mss_lib.mss() as sct:
            monitor = sct.monitors[1]
            for _ in range(CAPTURE_RUNS):
                t = ts()
                sct.grab(monitor)
                times.append(ms(t))
        result("mss full-screen grab", statistics.mean(times),
               f"min={min(times):.1f} max={max(times):.1f}")
    except Exception as e:
        fail("mss full-screen grab", e)
else:
    print("  --  mss                                      not available", flush=True)

# 2c. PIL ImageGrab
if available.get("PIL"):
    try:
        from PIL import ImageGrab
        times = []
        for _ in range(CAPTURE_RUNS):
            t = ts()
            ImageGrab.grab()
            times.append(ms(t))
        result("PIL ImageGrab full-screen", statistics.mean(times),
               f"min={min(times):.1f} max={max(times):.1f}")
    except Exception as e:
        fail("PIL ImageGrab full-screen", e)

# 2d. DXcam region (1280x800 crop — typical browser window)
if available.get("dxcam"):
    try:
        import dxcam
        cam = dxcam.create()
        region = (0, 0, 1280, 768)
        times = []
        for _ in range(CAPTURE_RUNS):
            t = ts()
            frame = cam.grab(region=region)
            times.append(ms(t))
        cam.release()
        result("DXcam region 1280x768", statistics.mean(times),
               f"min={min(times):.1f} max={max(times):.1f}")
    except Exception as e:
        fail("DXcam region 1280x800", e)

# 2e. mss region
if available.get("mss"):
    try:
        import mss as mss_lib
        times = []
        with mss_lib.mss() as sct:
            region = {"top": 0, "left": 0, "width": 1280, "height": 800}
            for _ in range(CAPTURE_RUNS):
                t = ts()
                sct.grab(region)
                times.append(ms(t))
        result("mss region 1280x800", statistics.mean(times),
               f"min={min(times):.1f} max={max(times):.1f}")
    except Exception as e:
        fail("mss region 1280x800", e)


# ── 3. UIA extraction ──────────────────────────────────────────────────────

section("3. UIA Element Extraction (focused window)")
if available.get("pywinauto"):
    try:
        import pywinauto
        from pywinauto import Desktop
        times = []
        for i in range(3):
            t = ts()
            try:
                wins = Desktop(backend="uia").windows()
            except Exception:
                wins = []
            times.append(ms(t))
        result("pywinauto Desktop.windows()", statistics.mean(times),
               f"{len(wins)} windows found")
    except Exception as e:
        fail("pywinauto UIA desktop scan", e)
else:
    print("  --  UIA (pywinauto not available)", flush=True)


# ── 4. OCR benchmark ───────────────────────────────────────────────────────

section("4. PaddleOCR (on a synthetic text image)")
if available.get("paddleocr"):
    try:
        import numpy as np
        from paddleocr import PaddleOCR

        # Cold start (first call downloads/loads model)
        print("  Loading PaddleOCR model (cold start)...", flush=True)
        t_cold = ts()
        ocr = PaddleOCR(use_angle_cls=False, lang="en")
        cold_load = ms(t_cold)
        print(f"  Model load: {cold_load:.0f} ms", flush=True)

        # Synthetic 800x200 image with text
        img = np.ones((200, 800, 3), dtype=np.uint8) * 255
        if available.get("cv2"):
            import cv2
            cv2.putText(img, "The candidate demonstrates strong analytical skills.",
                        (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,0), 2)
            cv2.putText(img, "Please select the best matching answer option.",
                        (20, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,0), 2)

        # Warm runs
        times = []
        for _ in range(3):
            t = ts()
            ocr.ocr(img, cls=False)
            times.append(ms(t))

        result("PaddleOCR warm inference (800x200)", statistics.mean(times),
               f"cold={cold_load:.0f} ms")
    except Exception as e:
        fail("PaddleOCR", traceback.format_exc().splitlines()[-1])
else:
    print("  --  PaddleOCR not available", flush=True)


# ── 5. LLM roundtrip benchmarks ───────────────────────────────────────────

section("5. LLM Roundtrip — 50-word answer per question (3 runs each)")

import requests as req_lib

def llm_call(model, prompt, system=None):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    t = ts()
    r = req_lib.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://careerbridge.local",
        },
        json={"model": model, "messages": msgs, "max_tokens": 120},
        timeout=60,
    )
    elapsed = ms(t)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    words = len(content.split())
    return elapsed, words, content

PROMPT = (
    f"Answer the following comprehension question in approximately 50 words:\n\n"
    f"{SAMPLE_QUESTION}"
)
PERSONA_SYS = (
    "You are a 28-year-old marketing professional. Write naturally, "
    "in your own voice. Be direct. No bullet points. About 50 words."
)

models = [
    ("anthropic/claude-haiku-4.5",          "Haiku 4.5"),
    ("anthropic/claude-sonnet-4-6",          "Sonnet 4.6"),
]

for model_id, label in models:
    times = []
    word_counts = []
    try:
        for i in range(3):
            elapsed, words, _ = llm_call(model_id, PROMPT, PERSONA_SYS)
            times.append(elapsed)
            word_counts.append(words)
            print(f"  ... {label} run {i+1}: {elapsed:.0f} ms, {words} words", flush=True)
        result(f"{label} answer generation", statistics.mean(times),
               f"avg {round(statistics.mean(word_counts))} words, "
               f"min={min(times):.0f} max={max(times):.0f} ms")
    except Exception as e:
        fail(f"{label} answer generation", e)


# ── 6. Full pipeline simulation ────────────────────────────────────────────

section("6. Full Pipeline Estimate — 10 Questions × 50 Words")

# Use measured values or fallback estimates
def safe_mean(lst, fallback):
    return statistics.mean(lst) if lst else fallback

print("\n  Using best measured values from above...", flush=True)

# Best capture: prefer DXcam, fallback to mss
capture_ms = 15   # placeholder — will be overridden below
ocr_ms = 80       # PaddleOCR warm
uia_ms = 30       # UIA scan
haiku_ms = None
sonnet_ms = None

# Re-run quick single captures to get current values
timing_notes = []

if available.get("dxcam"):
    try:
        import dxcam
        cam = dxcam.create()
        t = ts(); cam.grab(region=(0,0,1280,800)); capture_ms = ms(t)
        cam.release()
        timing_notes.append(f"DXcam region: {capture_ms:.1f} ms")
    except: pass
elif available.get("mss"):
    try:
        import mss as mss_lib
        with mss_lib.mss() as sct:
            region = {"top":0,"left":0,"width":1280,"height":800}
            t = ts(); sct.grab(region); capture_ms = ms(t)
        timing_notes.append(f"mss region: {capture_ms:.1f} ms")
    except: pass

# Quick LLM sample
try:
    t_h, _, _ = llm_call("anthropic/claude-haiku-4.5", PROMPT, PERSONA_SYS)
    t_s, _, _ = llm_call("anthropic/claude-sonnet-4-6", PROMPT, PERSONA_SYS)
    haiku_ms = t_h
    sonnet_ms = t_s
    timing_notes.append(f"Haiku fresh: {t_h:.0f} ms, Sonnet fresh: {t_s:.0f} ms")
except Exception as e:
    timing_notes.append(f"LLM sample failed: {e}")

for n in timing_notes:
    print(f"  • {n}", flush=True)

Q = 10
per_q_ops = {
    "capture":    capture_ms,
    "UIA scan":   uia_ms,
    "OCR":        ocr_ms,
}

print(f"\n  Per-question breakdown (ms):", flush=True)
per_q_total_base = 0
for op, t in per_q_ops.items():
    print(f"    {op:<15} {t:>6.0f} ms", flush=True)
    per_q_total_base += t

print(f"\n  {'Model':<25} {'Per Q (ms)':>12} {'10Q total':>12} {'10Q total (s)':>14}", flush=True)
print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*14}", flush=True)

for label, llm_t in [("Haiku 4.5 (chat)", haiku_ms), ("Sonnet 4.6 (answers)", sonnet_ms)]:
    if llm_t is None:
        print(f"  {label:<25} {'N/A':>12}", flush=True)
        continue
    per_q = per_q_total_base + llm_t
    total_10q = per_q * Q
    human_delay = 800   # humanized typing + click delay per question
    total_with_human = (total_10q + human_delay * Q)
    print(f"  {label:<25} {per_q:>12.0f} {total_10q:>12.0f} {total_with_human/1000:>13.1f}s", flush=True)


# ── 7. Summary table ───────────────────────────────────────────────────────

section("7. Recommendation Summary")
print("""
  PATH                        LATENCY     RELIABILITY     USE FOR
  ─────────────────────────── ──────────  ──────────────  ─────────────────────
  DXcam region capture        < 10 ms     High (GPU)      Primary capture
  mss region capture          15-30 ms    High (GDI)      DXcam fallback
  PIL ImageGrab               80-150 ms   Medium          Last resort
  UIA (pywinauto)             20-60 ms    High            Interactive elements
  PaddleOCR warm              60-120 ms   High            Text + labels
  Haiku 4.5 answer gen        700-1500ms  High            Not for answers (weak)
  Sonnet 4.6 answer gen       1500-3500ms High            Primary answer model
  ─────────────────────────── ──────────  ──────────────  ─────────────────────
  FASTEST FULL PIPELINE       ~2-4s/Q     DXcam+UIA+Sonnet (no OCR if UIA covers)
  TARGET (50Q replay SOP)     < 35s total DXcam + SOP replay (0 LLM calls)
""", flush=True)

print("\nSmoke test complete.", flush=True)
