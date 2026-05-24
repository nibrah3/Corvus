"""
Per-page action plan benchmark — top 3 pipelines.

Takes one screenshot per pipeline, saves to file, reports capture+process time.
Claude Code then reads each image and produces a full action plan (the LLM step).
"""
import sys, io, time, os
sys.path.insert(0, 'D:/cb-core')

import numpy as np
from PIL import Image, ImageFilter
import mss

OUT = "D:/cb-core/capture_mcp/page_test"
os.makedirs(OUT, exist_ok=True)

def _mss_capture() -> Image.Image:
    with mss.MSS() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

def _png(img): buf = io.BytesIO(); img.save(buf,"PNG"); return buf.getvalue()
def _jpg(img, q=72): buf = io.BytesIO(); img.save(buf,"JPEG",quality=q,optimize=True); return buf.getvalue()

results = {}

# ── Pipeline F: crop centre + JPEG 72 ────────────────────────────────────────
t0 = time.perf_counter()
img = _mss_capture()
w, h = img.size
margin = int(w * 0.20)
cropped = img.crop((margin, 0, w - margin, h))
jpg = _jpg(cropped)
ms_F = (time.perf_counter() - t0) * 1000
with open(f"{OUT}/F_crop_jpeg.jpg", "wb") as f: f.write(jpg)
results["F"] = (ms_F, len(jpg)/1024, cropped.size)
print(f"F  capture+process={ms_F:5.0f}ms  payload={len(jpg)/1024:5.1f}KB  dims={cropped.size}")

# ── Pipeline A: single full PNG ───────────────────────────────────────────────
t0 = time.perf_counter()
img = _mss_capture()
png = _png(img)
ms_A = (time.perf_counter() - t0) * 1000
with open(f"{OUT}/A_full_png.png", "wb") as f: f.write(png)
results["A"] = (ms_A, len(png)/1024, img.size)
print(f"A  capture+process={ms_A:5.0f}ms  payload={len(png)/1024:5.1f}KB  dims={img.size}")

# ── Pipeline E: scroll-stitch ─────────────────────────────────────────────────
def _scroll():
    from pynput.keyboard import Controller as KB, Key
    kb = KB(); kb.press(Key.page_down); time.sleep(0.05); kb.release(Key.page_down); time.sleep(0.35)

t0 = time.perf_counter()
img1 = _mss_capture()
_scroll()
img2 = _mss_capture()
w, h = img1.size
stitched = Image.new("RGB", (w, h*2))
stitched.paste(img1,(0,0)); stitched.paste(img2,(0,h))
if stitched.height > 1400:
    ratio = 1400/stitched.height
    stitched = stitched.resize((int(w*ratio),1400), Image.LANCZOS)
png_e = _png(stitched)
ms_E = (time.perf_counter() - t0) * 1000
with open(f"{OUT}/E_stitch.png", "wb") as f: f.write(png_e)
results["E"] = (ms_E, len(png_e)/1024, stitched.size)
print(f"E  capture+process={ms_E:5.0f}ms  payload={len(png_e)/1024:5.1f}KB  dims={stitched.size}")

print(f"\nImages saved to {OUT}")
print("Now send each to Claude for action plan analysis.")
