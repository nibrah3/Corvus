"""
careerbridge/gemini_vision.py — Image and video perception via Gemini Flash.

Routing priority (both image and video):
  1. Direct Google Gemini API  (requires GEMINI_API_KEY)
       Image: types.Part.from_uri / types.Part.from_bytes  → no resize needed
       Video: Files API upload → poll ACTIVE → generate
  2. OpenRouter fallback       (requires OPENROUTER_API_KEY, no GEMINI_API_KEY)
       Image: inline image_url  (CDN URLs + data URIs)
       Video: 3 keyframes via cv2 → inline image_url

All calls happen entirely in the Python process. The browser tab only sees
idle time followed by a single click — no tab blur, no clipboard, no JS fetch.

Direct model:    GEMINI_DIRECT_MODEL  env var (default: gemini-2.0-flash)
OpenRouter img:  GEMINI_IMAGE_MODEL   env var (default: google/gemini-3.5-flash)
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

log = logging.getLogger(__name__)

_OPENROUTER_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
_GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
_DIRECT_MODEL    = os.environ.get("GEMINI_DIRECT_MODEL", "gemini-2.0-flash")
_IMAGE_MODEL     = os.environ.get("GEMINI_IMAGE_MODEL", "google/gemini-3.5-flash")


# ── Image annotation ──────────────────────────────────────────────────────────

def annotate_image(
    image_url: str,
    question: str,
    options: list[str],
    context: str = "",
) -> Optional[str]:
    """
    Classify an image from a public URL.

    Primary: direct Gemini API (GEMINI_API_KEY) — Gemini fetches the URL itself.
    Fallback: OpenRouter inline image_url.
    """
    if _GEMINI_API_KEY:
        try:
            return _image_direct_url(image_url, question, options, context)
        except Exception as e:
            log.warning("Direct Gemini URL image failed (%s) — trying OpenRouter", e)

    return _image_openrouter_url(image_url, question, options, context)


def annotate_image_b64(
    image_b64: str,
    mime_type: str,
    question: str,
    options: list[str],
    context: str = "",
) -> Optional[str]:
    """
    Classify an image from raw base64 data (e.g. CDP Page.captureScreenshot).

    Primary: direct Gemini API (GEMINI_API_KEY) — Part.from_bytes, no size limit.
    Fallback: OpenRouter data-URI inline.
    """
    if _GEMINI_API_KEY:
        try:
            return _image_direct_b64(image_b64, mime_type, question, options, context)
        except Exception as e:
            log.warning("Direct Gemini b64 image failed (%s) — trying OpenRouter", e)

    return _image_openrouter_b64(image_b64, mime_type, question, options, context)


# ── Video annotation ──────────────────────────────────────────────────────────

def annotate_video(
    video_url: str,
    question: str,
    options: list[str],
    context: str = "",
) -> Optional[str]:
    """
    Analyze a video URL.

    Primary: Gemini Files API (GEMINI_API_KEY) — full video understanding.
    Fallback: 3 keyframes via cv2 → annotate_image_b64.
    """
    if _GEMINI_API_KEY:
        try:
            return _video_files_api(video_url, question, options, context)
        except Exception as e:
            log.warning("Files API failed (%s) — falling back to frames", e)

    return _video_via_frames(video_url, question, options, context)


# ── Direct Gemini API helpers ─────────────────────────────────────────────────

def _gemini_client():
    from google import genai
    return genai.Client(api_key=_GEMINI_API_KEY)


def _image_direct_url(
    image_url: str, question: str, options: list[str], context: str
) -> Optional[str]:
    import base64
    import mimetypes
    import urllib.request
    mime = mimetypes.guess_type(image_url)[0] or "image/jpeg"
    req  = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        img_bytes = r.read()
    img_b64 = base64.b64encode(img_bytes).decode()
    return _image_direct_b64(img_b64, mime, question, options, context)


def _image_direct_b64(
    image_b64: str, mime_type: str, question: str, options: list[str], context: str
) -> Optional[str]:
    import base64
    from google.genai import types
    client    = _gemini_client()
    img_bytes = base64.b64decode(image_b64)
    prompt    = _build_prompt(question, options, context)
    resp      = client.models.generate_content(
        model=_DIRECT_MODEL,
        contents=[types.Part.from_bytes(data=img_bytes, mime_type=mime_type), prompt],
    )
    raw = (resp.text or "").strip()
    log.debug("Direct Gemini b64 image raw: %r", raw)
    return _match_option(raw, options)


def _video_files_api(
    video_url: str, question: str, options: list[str], context: str
) -> Optional[str]:
    import tempfile
    import time
    import urllib.request
    from google.genai import types

    client = _gemini_client()

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        urllib.request.urlretrieve(video_url, tmp_path)

        uploaded = client.files.upload(file=tmp_path)

        deadline = time.monotonic() + 120
        while uploaded.state.name != "ACTIVE":
            if time.monotonic() > deadline:
                raise TimeoutError("Gemini file processing timed out after 120s")
            time.sleep(3)
            uploaded = client.files.get(name=uploaded.name)

        prompt = _build_prompt(question, options, context)
        resp   = client.models.generate_content(
            model=_DIRECT_MODEL,
            contents=[types.Part.from_uri(file_uri=uploaded.uri, mime_type="video/mp4"), prompt],
        )
        raw = (resp.text or "").strip()

        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass

        return _match_option(raw, options)
    finally:
        import os as _os
        try:
            _os.unlink(tmp_path)
        except Exception:
            pass


# ── OpenRouter fallback helpers ───────────────────────────────────────────────

def _image_openrouter_url(
    image_url: str, question: str, options: list[str], context: str
) -> Optional[str]:
    from openai import OpenAI
    client = OpenAI(api_key=_OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
    prompt = _build_prompt(question, options, context)
    try:
        resp = client.chat.completions.create(
            model=_IMAGE_MODEL,
            max_tokens=80,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text",      "text": prompt},
                ],
            }],
        )
        raw = (resp.choices[0].message.content or "").strip()
        log.debug("OpenRouter image answer: %r", raw)
        return _match_option(raw, options)
    except Exception as e:
        log.warning("OpenRouter image annotation failed: %s", e)
        return None


def _image_openrouter_b64(
    image_b64: str, mime_type: str, question: str, options: list[str], context: str
) -> Optional[str]:
    from openai import OpenAI
    client   = OpenAI(api_key=_OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
    data_url = f"data:{mime_type};base64,{image_b64}"
    prompt   = _build_prompt(question, options, context)
    try:
        resp = client.chat.completions.create(
            model=_IMAGE_MODEL,
            max_tokens=80,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text",      "text": prompt},
                ],
            }],
        )
        raw = (resp.choices[0].message.content or "").strip()
        return _match_option(raw, options)
    except Exception as e:
        log.warning("OpenRouter b64 annotation failed: %s", e)
        return None


def _video_via_frames(
    video_url: str, question: str, options: list[str], context: str
) -> Optional[str]:
    """Extract 3 keyframes from video and pass them as images to Gemini."""
    import base64
    import tempfile
    import urllib.request

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        urllib.request.urlretrieve(video_url, tmp_path)

        try:
            import cv2
        except ImportError:
            log.warning("opencv-python not installed — cannot extract frames")
            return None

        cap   = cv2.VideoCapture(tmp_path)
        total = max(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 1)
        frames_b64: list[str] = []
        for pos in [total // 4, total // 2, 3 * total // 4]:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if ret:
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                frames_b64.append(base64.b64encode(buf.tobytes()).decode())
        cap.release()

        if not frames_b64:
            log.warning("No frames extracted from video")
            return None

        combined_b64 = frames_b64[len(frames_b64) // 2]
        extra_ctx = "These are frames from a video (start, middle, end). " + context
        return annotate_image_b64(combined_b64, "image/jpeg", question, options, extra_ctx)
    finally:
        import os as _os
        try:
            _os.unlink(tmp_path)
        except Exception:
            pass


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_prompt(question: str, options: list[str], context: str = "") -> str:
    opts  = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(options))
    parts = []
    if context:
        parts.append(context)
    parts.append(f"Task: {question}")
    parts.append(f"Options:\n{opts}")
    parts.append("Reply with ONLY the exact option text, nothing else.")
    return "\n\n".join(parts)


def _match_option(raw: str, options: list[str]) -> Optional[str]:
    """
    Map Gemini's free-text answer to the closest option string.

    Priority:
      1. Exact match (case-insensitive)
      2. Option number ("1" or "1.")
      3. Substring containment (either direction)
      4. Highest word-overlap score
    """
    if not raw or not options:
        return None

    clean = raw.lower().strip().rstrip(".")

    # 1. Exact
    for opt in options:
        if opt.lower().strip() == clean:
            return opt

    # 2. Option number
    m = re.match(r"^(\d+)", clean)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(options):
            return options[idx]

    # 3. Substring
    for opt in options:
        if clean in opt.lower() or opt.lower() in clean:
            return opt

    # 4. Word overlap
    raw_words = set(clean.split())
    scored    = [(len(raw_words & set(o.lower().split())), o) for o in options]
    best_score, best_opt = max(scored, key=lambda x: x[0])
    if best_score > 0:
        return best_opt

    log.warning("No option match for %r in %s", raw, options)
    return None
