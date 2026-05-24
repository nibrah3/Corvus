"""
LLM Round-Trip Benchmark — 6 screenshot pipelines, no API credits needed.

Measures the parts we control (capture + processing), estimates the LLM part,
and shows projected total round-trip and cost per call.

Pipelines:
  A  Single MSS → PNG → Claude vision (baseline)
  B  MSS → PaddleOCR → Claude text (image never sent)
  C  MSS → RapidOCR  → Claude text (lighter OCR)
  D  Rapid 5-frame capture → deduplicate → best frame → vision
  E  Scroll-and-stitch (2 frames) → vision (sees more page)
  F  MSS → crop centre → JPEG 72% → vision (smaller payload)

LLM latency estimate (Haiku 4.5, warm):
  vision call  ~600ms  (image tokens + decode)
  text call    ~400ms  (text tokens only)

Pricing (Haiku 4.5):
  input  $0.80/M tokens
  output $4.00/M tokens

Image token formula (Anthropic):
  tokens ≈ (width × height) / 750
"""
from __future__ import annotations

import sys, os, io, time, hashlib, base64, textwrap
sys.path.insert(0, 'D:/cb-core')

import numpy as np
from PIL import Image, ImageFilter
import mss

OUT_DIR = "D:/cb-core/capture_mcp/samples"
os.makedirs(OUT_DIR, exist_ok=True)

# Estimated LLM call latency (ms) — not measured, based on Haiku 4.5 benchmarks
LLM_VISION_MS = 600
LLM_TEXT_MS   = 400

PRICE_IN_PER_M  = 0.80
PRICE_OUT_PER_M = 4.00
AVG_OUT_TOKENS  = 60   # typical short answer

# ── Capture helpers ───────────────────────────────────────────────────────────

def _mss_capture() -> Image.Image:
    with mss.MSS() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

def _to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO(); img.save(buf, "PNG"); return buf.getvalue()

def _to_jpeg_bytes(img: Image.Image, q: int = 72) -> bytes:
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=q, optimize=True); return buf.getvalue()

def _img_tokens(w: int, h: int) -> int:
    return max(100, int(w * h / 750))

def _text_tokens(text: str) -> int:
    return max(50, len(text) // 4)

def _edge_density(img: Image.Image) -> float:
    g = img.convert("L").filter(ImageFilter.FIND_EDGES)
    return float(np.array(g).mean())

def _img_hash(img: Image.Image) -> str:
    return hashlib.md5(img.tobytes()).hexdigest()

# ── OCR helpers ───────────────────────────────────────────────────────────────

_paddle = None
def _ocr_paddle(img: Image.Image) -> tuple[str, float]:
    global _paddle
    t0 = time.perf_counter()
    if _paddle is None:
        from paddleocr import PaddleOCR
        import logging
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        _paddle = PaddleOCR(lang="en")
    arr = np.array(img)
    result = _paddle.ocr(arr)
    lines = []
    # PaddleOCR v3 returns list of pages; each page is list of [box, (text, conf)]
    pages = result if isinstance(result, list) else []
    for page in pages:
        if not page:
            continue
        for item in page:
            try:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    text_conf = item[1]
                    if isinstance(text_conf, (list, tuple)) and len(text_conf) >= 2:
                        text, conf = text_conf[0], text_conf[1]
                    else:
                        text = str(text_conf)
                        conf = 1.0
                    if float(conf) > 0.5:
                        lines.append(str(text))
            except Exception:
                continue
    return "\n".join(lines), (time.perf_counter() - t0) * 1000

_rapid = None
def _ocr_rapid(img: Image.Image) -> tuple[str, float]:
    global _rapid
    t0 = time.perf_counter()
    if _rapid is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapid = RapidOCR()
    arr = np.array(img)
    result, _ = _rapid(arr)
    lines = []
    if result:
        for item in result:
            if len(item) >= 2:
                lines.append(item[1])
    return "\n".join(lines), (time.perf_counter() - t0) * 1000

def _scroll_page_down():
    from pynput.keyboard import Controller as KB, Key
    kb = KB()
    kb.press(Key.page_down); time.sleep(0.05); kb.release(Key.page_down)
    time.sleep(0.35)

# ── Result row ────────────────────────────────────────────────────────────────

def _cost(inp: int) -> float:
    return (inp * PRICE_IN_PER_M + AVG_OUT_TOKENS * PRICE_OUT_PER_M) / 1_000_000

def _row(name, cap_ms, proc_ms, llm_est_ms, inp_tokens, payload_kb, notes=""):
    total = cap_ms + proc_ms + llm_est_ms
    cost  = _cost(inp_tokens)
    print(f"\n{'─'*68}")
    print(f"  Pipeline {name}")
    print(f"  capture={cap_ms:5.0f}ms  process={proc_ms:5.0f}ms  llm≈{llm_est_ms}ms  "
          f"total≈{total:5.0f}ms")
    print(f"  payload={payload_kb:6.1f}KB  tokens≈{inp_tokens:5d}  cost/call≈${cost:.5f}"
          + (f"  [{notes}]" if notes else ""))
    return total, cost

# ── Pipelines ─────────────────────────────────────────────────────────────────

def pipeline_A():
    t0 = time.perf_counter(); img = _mss_capture(); cap_ms = (time.perf_counter()-t0)*1000
    t0 = time.perf_counter(); png = _to_png_bytes(img); proc_ms = (time.perf_counter()-t0)*1000
    img.save(f"{OUT_DIR}/pipe_A_sample.png")
    tok = _img_tokens(*img.size)
    return _row("A: single MSS → PNG → vision", cap_ms, proc_ms, LLM_VISION_MS,
                tok, len(png)/1024, f"{img.size[0]}×{img.size[1]}")

def pipeline_B():
    t0 = time.perf_counter(); img = _mss_capture(); cap_ms = (time.perf_counter()-t0)*1000
    ocr_text, proc_ms = _ocr_paddle(img)
    tok = _text_tokens(ocr_text)
    return _row("B: MSS → PaddleOCR → text", cap_ms, proc_ms, LLM_TEXT_MS,
                tok, len(ocr_text.encode())/1024, f"{len(ocr_text)} chars extracted")

def pipeline_C():
    t0 = time.perf_counter(); img = _mss_capture(); cap_ms = (time.perf_counter()-t0)*1000
    ocr_text, proc_ms = _ocr_rapid(img)
    tok = _text_tokens(ocr_text)
    return _row("C: MSS → RapidOCR → text", cap_ms, proc_ms, LLM_TEXT_MS,
                tok, len(ocr_text.encode())/1024, f"{len(ocr_text)} chars extracted")

def pipeline_D():
    frames, hashes = [], set()
    t_cap = time.perf_counter()
    for _ in range(5):
        img = _mss_capture()
        h = _img_hash(img)
        if h not in hashes:
            frames.append(img); hashes.add(h)
        time.sleep(0.05)
    cap_ms = (time.perf_counter() - t_cap) * 1000

    t0 = time.perf_counter()
    best = max(frames, key=_edge_density)
    png  = _to_png_bytes(best)
    proc_ms = (time.perf_counter() - t0) * 1000
    best.save(f"{OUT_DIR}/pipe_D_sample.png")
    tok = _img_tokens(*best.size)
    return _row(f"D: 5-frame dedup ({len(frames)} unique) → vision",
                cap_ms, proc_ms, LLM_VISION_MS, tok, len(png)/1024)

def pipeline_E():
    t0 = time.perf_counter()
    img1 = _mss_capture()
    _scroll_page_down()
    img2 = _mss_capture()
    cap_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    w, h = img1.size
    stitched = Image.new("RGB", (w, h * 2))
    stitched.paste(img1, (0, 0)); stitched.paste(img2, (0, h))
    max_h = 1400
    if stitched.height > max_h:
        ratio = max_h / stitched.height
        stitched = stitched.resize((int(w*ratio), max_h), Image.LANCZOS)
    png = _to_png_bytes(stitched)
    proc_ms = (time.perf_counter() - t0) * 1000
    stitched.save(f"{OUT_DIR}/pipe_E_sample.png")
    tok = _img_tokens(*stitched.size)
    return _row("E: scroll-stitch 2fr → vision", cap_ms, proc_ms, LLM_VISION_MS,
                tok, len(png)/1024, f"stitched {stitched.size[0]}×{stitched.size[1]}")

def pipeline_F():
    t0 = time.perf_counter(); img = _mss_capture(); cap_ms = (time.perf_counter()-t0)*1000
    t0 = time.perf_counter()
    w, h = img.size
    margin = int(w * 0.20)
    cropped = img.crop((margin, 0, w - margin, h))
    jpg = _to_jpeg_bytes(cropped, q=72)
    proc_ms = (time.perf_counter() - t0) * 1000
    cropped.save(f"{OUT_DIR}/pipe_F_sample.jpg", quality=72)
    tok = _img_tokens(*cropped.size)
    return _row("F: crop 60%w + JPEG 72% → vision", cap_ms, proc_ms, LLM_VISION_MS,
                tok, len(jpg)/1024, f"→ {cropped.size[0]}×{cropped.size[1]}")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*68}")
    print("  LLM Round-Trip Benchmark  (capture + process measured; LLM estimated)")
    print(f"  Haiku 4.5: vision~600ms, text~400ms | ${PRICE_IN_PER_M}/M in  ${PRICE_OUT_PER_M}/M out")
    print(f"{'='*68}")

    print("\nWarming up OCR models (first run downloads weights)...")
    _warmup = _mss_capture()
    try:
        _ocr_rapid(_warmup); print("  RapidOCR ready")
    except Exception as e:
        print(f"  RapidOCR failed: {e}")
    try:
        _ocr_paddle(_warmup); print("  PaddleOCR ready")
    except Exception as e:
        print(f"  PaddleOCR failed: {e}")

    print("\nRunning pipelines against current screen...\n")

    totals = {}
    costs  = {}
    for label, fn in [
        ("A", pipeline_A), ("B", pipeline_B), ("C", pipeline_C),
        ("D", pipeline_D), ("E", pipeline_E), ("F", pipeline_F),
    ]:
        try:
            total_ms, cost = fn()
            totals[label] = total_ms
            costs[label]  = cost
        except Exception as exc:
            print(f"\n  Pipeline {label} FAILED: {exc}")
            import traceback; traceback.print_exc()

    print(f"\n\n{'='*68}")
    print("  RANKING by projected total round-trip (capture + process + LLM est.)")
    print(f"{'='*68}")
    for label, ms in sorted(totals.items(), key=lambda x: x[1]):
        bar = "#" * int(ms / 100)
        print(f"  {label}  {ms:6.0f}ms  {bar}")

    print(f"\n{'='*68}")
    print("  RANKING by cost per call")
    print(f"{'='*68}")
    for label, cost in sorted(costs.items(), key=lambda x: x[1]):
        print(f"  {label}  ${cost:.5f}/call")

    print(f"\nSample images saved to: {OUT_DIR}\n")
