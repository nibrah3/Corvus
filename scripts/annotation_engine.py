"""
annotation_engine.py — Gemini-powered image/video annotation engine.

Supports:
  - Image classification      (what category is this?)
  - Object detection          (bounding boxes + labels)
  - Attribute annotation      (color, size, orientation, etc.)
  - Scene description         (full description of the scene)
  - Video frame analysis      (frame-by-frame breakdown)
  - Comparison tasks          (which image matches X?)
  - Binary yes/no tasks       (does this image contain X?)

Usage:
  python annotation_engine.py --test        # run built-in production tests
  python annotation_engine.py --image URL   # annotate a single image
"""

from __future__ import annotations
import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

# ── Config ────────────────────────────────────────────────────────────────────
CB_DIR = Path(__file__).resolve().parent.parent
_ENV   = CB_DIR / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip()  # .env always wins over stale system env vars

GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL   = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
)

# ── Core API call ─────────────────────────────────────────────────────────────

def _gemini(prompt: str, image_b64: str | None = None,
            mime: str = "image/jpeg", retries: int = 3) -> str:
    """Call Gemini and return the text response."""
    parts: list[dict] = [{"text": prompt}]
    if image_b64:
        parts.append({"inline_data": {"mime_type": mime, "data": image_b64}})

    body = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }).encode()

    req = urllib.request.Request(
        GEMINI_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
                return d["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return ""


def _load_image_b64(source: str) -> tuple[str, str]:
    """Load image from URL or file path, return (base64, mime_type)."""
    if source.startswith("http://") or source.startswith("https://"):
        import requests as _req
        r = _req.get(
            source,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CareerBridge/1.0)"},
            timeout=20,
            allow_redirects=True,
        )
        r.raise_for_status()
        data = r.content
        ct   = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not ct.startswith("image/"):
            ct = "image/jpeg"
    else:
        data = Path(source).read_bytes()
        ext  = Path(source).suffix.lower().lstrip(".")
        ct   = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")
    return base64.b64encode(data).decode(), ct


# ── Annotation task types ─────────────────────────────────────────────────────

def classify(image_source: str, categories: list[str], instructions: str = "") -> dict:
    """Classify image into one of the given categories."""
    cats = "\n".join(f"  - {c}" for c in categories)
    prompt = f"""You are an expert image classifier for a data annotation platform.

Task: Choose the SINGLE best category for this image.
Categories:
{cats}
{f'Additional instructions: {instructions}' if instructions else ''}

IMPORTANT: Respond with ONLY a valid JSON object, no markdown fences:
{{
  "category": "<exact category name from list>",
  "confidence": <0.0-1.0>,
  "reasoning": "<one sentence>"
}}"""
    b64, mime = _load_image_b64(image_source)
    raw = _gemini(prompt, b64, mime)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def detect_objects(image_source: str, target_classes: list[str] | None = None,
                   instructions: str = "") -> dict:
    """Detect objects and return bounding boxes as percentages (0-100) of image size."""
    cls_hint = ""
    if target_classes:
        cls_hint = f"\nFocus on these object types: {', '.join(target_classes)}"
    prompt = f"""You are an expert object detection annotator for a data annotation platform.

Task: Detect all significant objects in this image and provide bounding boxes.{cls_hint}
{f'Additional instructions: {instructions}' if instructions else ''}

For each object provide its bounding box as percentages (0-100) of image width/height.
Format: top-left-x, top-left-y, width, height  (all as % of image dimensions)

IMPORTANT: Respond with ONLY a valid JSON object, no markdown fences:
{{
  "objects": [
    {{
      "label": "<object class>",
      "confidence": <0.0-1.0>,
      "bbox": {{"x": <float>, "y": <float>, "width": <float>, "height": <float>}},
      "attributes": {{}}
    }}
  ],
  "scene_context": "<one-line scene description>",
  "image_quality": "<clear|blurry|occluded|partial>"
}}"""
    b64, mime = _load_image_b64(image_source)
    raw = _gemini(prompt, b64, mime)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def annotate_attributes(image_source: str, attribute_schema: dict,
                        instructions: str = "") -> dict:
    """Fill in structured attribute labels for an image (color, condition, type, etc.)."""
    schema_str = json.dumps(attribute_schema, indent=2)
    prompt = f"""You are an expert data annotator for a machine learning platform.

Task: Fill in all attributes for the main subject of this image.
Attribute schema (key → allowed values):
{schema_str}
{f'Additional instructions: {instructions}' if instructions else ''}

IMPORTANT: Respond with ONLY a valid JSON object matching the schema keys, no markdown fences.
Example: {{"color": "red", "condition": "new", "type": "sedan"}}"""
    b64, mime = _load_image_b64(image_source)
    raw = _gemini(prompt, b64, mime)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def binary_check(image_source: str, question: str) -> dict:
    """Answer a yes/no question about the image."""
    prompt = f"""You are a precise image quality checker for a data annotation platform.

Question: {question}

Answer yes or no based ONLY on what you can see in the image.
IMPORTANT: Respond with ONLY a valid JSON object, no markdown fences:
{{"answer": "yes" or "no", "confidence": <0.0-1.0>, "reason": "<one sentence>"}}"""
    b64, mime = _load_image_b64(image_source)
    raw = _gemini(prompt, b64, mime)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def describe_scene(image_source: str, instructions: str = "") -> dict:
    """Generate a detailed scene description / caption."""
    prompt = f"""You are an expert image captioner for a data annotation platform.

Task: Describe this image in detail for a machine learning training dataset.
{f'Additional instructions: {instructions}' if instructions else ''}

IMPORTANT: Respond with ONLY a valid JSON object, no markdown fences:
{{
  "caption": "<2-3 sentence detailed description>",
  "main_subject": "<primary subject of the image>",
  "setting": "<indoor|outdoor|studio|other>",
  "people_count": <integer or null>,
  "contains_text": <true|false>,
  "tags": ["<tag1>", "<tag2>", ...]
}}"""
    b64, mime = _load_image_b64(image_source)
    raw = _gemini(prompt, b64, mime)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def analyze_video_frames(frame_sources: list[str], task_description: str) -> dict:
    """Analyze multiple video frames and produce a temporal annotation."""
    # For video: analyze first frame fully, then track changes across frames
    results = []
    prev_objects: list = []

    for i, src in enumerate(frame_sources):
        frame_prompt = f"""You are an expert video annotator for a data annotation platform.

Task: {task_description}
Frame: {i+1} of {len(frame_sources)}
{f'Previous frame objects: {json.dumps(prev_objects)}' if prev_objects else ''}

Analyze this video frame. Track object positions across frames.
IMPORTANT: Respond with ONLY a valid JSON object, no markdown fences:
{{
  "frame_index": {i},
  "objects": [
    {{
      "id": "<object_id e.g. car_1>",
      "label": "<class>",
      "bbox": {{"x": <float>, "y": <float>, "width": <float>, "height": <float>}},
      "action": "<stationary|moving_left|moving_right|moving_toward|moving_away>",
      "confidence": <0.0-1.0>
    }}
  ],
  "scene_change": <true|false>,
  "keyframe": <true|false>
}}"""
        b64, mime = _load_image_b64(src)
        raw = _gemini(frame_prompt, b64, mime)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        frame_data = json.loads(raw)
        results.append(frame_data)
        prev_objects = frame_data.get("objects", [])

    return {
        "total_frames": len(frame_sources),
        "frames": results,
        "unique_objects": list({o["id"] for f in results for o in f.get("objects", [])}),
    }


def solve_annotation_task(task: dict) -> dict:
    """
    Universal dispatcher — given a platform task dict, call the right annotator.

    task fields (standardized):
      type: "classify" | "detect" | "attributes" | "binary" | "describe" | "video"
      image_url: str (or image_urls: list for video)
      categories: list[str]  (for classify)
      target_classes: list[str]  (for detect)
      attribute_schema: dict  (for attributes)
      question: str  (for binary)
      instructions: str
    """
    t = task.get("type", "describe")
    img = task.get("image_url", "")
    instr = task.get("instructions", "")

    if t == "classify":
        return classify(img, task.get("categories", []), instr)
    elif t == "detect":
        return detect_objects(img, task.get("target_classes"), instr)
    elif t == "attributes":
        return annotate_attributes(img, task.get("attribute_schema", {}), instr)
    elif t == "binary":
        return binary_check(img, task.get("question", "Is this image valid?"))
    elif t == "video":
        return analyze_video_frames(task.get("image_urls", [img]), instr or "Annotate objects")
    else:
        return describe_scene(img, instr)


# ── Production tests ──────────────────────────────────────────────────────────

TEST_IMAGES = {
    # Google-hosted images — always available, no auth, direct bytes
    "street_scene":   "https://www.gstatic.com/webp/gallery3/1.png",       # dog portrait
    "traffic":        "https://www.gstatic.com/webp/gallery/4.sm.jpg",      # outdoor scene
    "nature":         "https://www.gstatic.com/webp/gallery3/3.png",        # flowers/nature
    "frame2":         "https://www.gstatic.com/webp/gallery3/4.png",        # video frame 2
    "frame3":         "https://www.gstatic.com/webp/gallery/1.sm.jpg",      # video frame 3
}

def run_production_tests() -> None:
    if not GEMINI_KEY:
        print("ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(1)

    print("=" * 60)
    print("ANNOTATION ENGINE — PRODUCTION TEST SUITE")
    print(f"Model: {GEMINI_MODEL}")
    print("=" * 60)
    passed = failed = 0

    # ── Test 1: Image Classification ─────────────────────────────────────────
    print("\n[TEST 1] Image Classification")
    try:
        result = classify(
            TEST_IMAGES["nature"],
            categories=["Flower/Plant", "Animal/Wildlife", "Vehicle", "Person", "Building", "Food", "Other"],
            instructions="Focus on the primary subject of the image."
        )
        print(f"  Category:   {result['category']}")
        print(f"  Confidence: {result['confidence']:.0%}")
        print(f"  Reasoning:  {result['reasoning']}")
        assert "category" in result and "confidence" in result
        print("  STATUS: PASS [OK]")
        passed += 1
    except Exception as e:
        print(f"  STATUS: FAIL — {e}")
        failed += 1

    # ── Test 2: Object Detection ──────────────────────────────────────────────
    print("\n[TEST 2] Object Detection with Bounding Boxes")
    try:
        result = detect_objects(
            TEST_IMAGES["traffic"],
            target_classes=["ant", "insect", "leg", "body"],
            instructions="Annotate the main insect and its body parts if visible."
        )
        print(f"  Objects found: {len(result.get('objects', []))}")
        for obj in result.get("objects", [])[:3]:
            bb = obj["bbox"]
            print(f"    - {obj['label']} | conf={obj['confidence']:.0%} | "
                  f"bbox=({bb['x']:.1f},{bb['y']:.1f},{bb['width']:.1f},{bb['height']:.1f})")
        print(f"  Scene: {result.get('scene_context','')}")
        assert "objects" in result
        print("  STATUS: PASS [OK]")
        passed += 1
    except Exception as e:
        print(f"  STATUS: FAIL — {e}")
        failed += 1

    # ── Test 3: Binary Check ──────────────────────────────────────────────────
    print("\n[TEST 3] Binary Quality Check")
    try:
        result = binary_check(
            TEST_IMAGES["nature"],
            question="Is this image suitable for an outdoor advertising campaign? (no violence, no explicit content, good quality)"
        )
        print(f"  Answer:     {result['answer']}")
        print(f"  Confidence: {result['confidence']:.0%}")
        print(f"  Reason:     {result['reason']}")
        assert result["answer"] in ("yes", "no")
        print("  STATUS: PASS [OK]")
        passed += 1
    except Exception as e:
        print(f"  STATUS: FAIL — {e}")
        failed += 1

    # ── Test 4: Attribute Annotation ─────────────────────────────────────────
    print("\n[TEST 4] Structured Attribute Annotation")
    try:
        result = annotate_attributes(
            TEST_IMAGES["nature"],
            attribute_schema={
                "time_of_day":  ["dawn", "morning", "midday", "afternoon", "dusk", "night", "unknown"],
                "weather":      ["sunny", "cloudy", "overcast", "rainy", "foggy", "unknown"],
                "setting":      ["urban", "rural", "nature", "indoor", "studio"],
                "image_quality":["high", "medium", "low"],
            },
            instructions="Assess the outdoor conditions visible in the image."
        )
        print(f"  Attributes: {json.dumps(result, indent=4)}")
        assert len(result) >= 2
        print("  STATUS: PASS [OK]")
        passed += 1
    except Exception as e:
        print(f"  STATUS: FAIL — {e}")
        failed += 1

    # ── Test 5: Scene Description / Caption ──────────────────────────────────
    print("\n[TEST 5] Scene Description & Captioning")
    try:
        result = describe_scene(
            TEST_IMAGES["traffic"],
            instructions="Write a description suitable for an alt-text accessibility caption."
        )
        print(f"  Caption:      {result.get('caption','')[:120]}...")
        print(f"  Main subject: {result.get('main_subject','')}")
        print(f"  Setting:      {result.get('setting','')}")
        print(f"  Tags:         {result.get('tags',[][:5])}")
        assert "caption" in result
        print("  STATUS: PASS [OK]")
        passed += 1
    except Exception as e:
        print(f"  STATUS: FAIL — {e}")
        failed += 1

    # ── Test 6: Universal Task Dispatcher ────────────────────────────────────
    print("\n[TEST 6] Universal Task Dispatcher (simulated platform task)")
    try:
        platform_task = {
            "type":       "classify",
            "image_url":  TEST_IMAGES["nature"],
            "categories": ["Sunflower", "Rose", "Tulip", "Daisy", "Other flower"],
            "instructions": "Identify the specific flower species.",
        }
        result = solve_annotation_task(platform_task)
        print(f"  Dispatched task type: classify")
        print(f"  Result: {json.dumps(result)}")
        assert "category" in result
        print("  STATUS: PASS [OK]")
        passed += 1
    except Exception as e:
        print(f"  STATUS: FAIL — {e}")
        failed += 1

    # ── Test 7: Video Frame Analysis ─────────────────────────────────────────
    print("\n[TEST 7] Video Frame Analysis (3-frame sequence)")
    try:
        frames = [TEST_IMAGES["street_scene"], TEST_IMAGES["frame2"], TEST_IMAGES["frame3"]]
        result = analyze_video_frames(
            frames,
            task_description="Track all animals and people across frames. Annotate movement direction."
        )
        print(f"  Total frames analyzed: {result['total_frames']}")
        print(f"  Unique tracked objects: {result['unique_objects']}")
        for f in result["frames"]:
            objs = f.get("objects", [])
            print(f"    Frame {f['frame_index']}: {len(objs)} object(s), "
                  f"scene_change={f.get('scene_change')}, keyframe={f.get('keyframe')}")
            for o in objs[:2]:
                bb = o["bbox"]
                print(f"      [{o['id']}] {o['label']} | {o.get('action','?')} | "
                      f"conf={o['confidence']:.0%} | bbox=({bb['x']:.1f},{bb['y']:.1f})")
        assert result["total_frames"] == 3
        assert "frames" in result
        print("  STATUS: PASS [OK]")
        passed += 1
    except Exception as e:
        print(f"  STATUS: FAIL — {e}")
        failed += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
    if failed == 0:
        print("ALL TESTS PASSED — Annotation engine ready for production.")
    else:
        print(f"WARNING: {failed} test(s) failed. Check API key and connectivity.")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini annotation engine")
    parser.add_argument("--test",   action="store_true", help="Run production test suite")
    parser.add_argument("--image",  help="Annotate a single image URL or file path")
    parser.add_argument("--type",   default="describe",
                        choices=["classify", "detect", "attributes", "binary", "describe"],
                        help="Annotation type (default: describe)")
    parser.add_argument("--categories", nargs="+", help="Category list for classification")
    parser.add_argument("--question",   help="Question for binary check")
    args = parser.parse_args()

    if args.test:
        run_production_tests()
    elif args.image:
        task: dict[str, Any] = {"type": args.type, "image_url": args.image}
        if args.categories:
            task["categories"] = args.categories
        if args.question:
            task["question"] = args.question
        result = solve_annotation_task(task)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
