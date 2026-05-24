"""
Gemini File API + Video understanding client (google.genai SDK).

Upload flow for large files (>20MB):
  1. client.files.upload(file=path)       → FileObject (uri, state, name)
  2. Poll until file.state.name == "ACTIVE"
  3. client.models.generate_content(...)  → structured response

API key: GEMINI_API_KEY environment variable.
"""
from __future__ import annotations

import os
import time
from pathlib import Path


def _client():
    from google import genai
    # Always read from .env so key rotations take effect without restarting the server.
    api_key = ""
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


def upload_video(video_path: str) -> dict:
    """
    Upload an MP4 to Gemini File API. Polls until ACTIVE.

    Returns {uri, name, size_mb, state, upload_ms} or {error: str}.
    """
    try:
        client = _client()
        path   = Path(video_path)
        if not path.exists():
            return {"error": f"File not found: {video_path}"}

        t0       = time.monotonic()
        uploaded = client.files.upload(file=str(path))

        deadline = time.monotonic() + 120
        while uploaded.state.name != "ACTIVE":
            if time.monotonic() > deadline:
                return {"error": "Gemini file processing timed out after 120s"}
            time.sleep(3)
            uploaded = client.files.get(name=uploaded.name)

        upload_ms = int((time.monotonic() - t0) * 1000)
        return {
            "uri":       uploaded.uri,
            "name":      uploaded.name,
            "size_mb":   round(path.stat().st_size / (1024 * 1024), 2),
            "state":     uploaded.state.name,
            "upload_ms": upload_ms,
        }
    except Exception as exc:
        return {"error": str(exc)}


def analyse_video(file_uri: str, prompt: str, model: str = "gemini-2.0-flash") -> dict:
    """
    Send a previously uploaded video to Gemini with a prompt.

    Returns {text, model, elapsed_ms} or {error: str}.
    """
    try:
        from google.genai import types
        client = _client()
        t0     = time.monotonic()
        resp   = client.models.generate_content(
            model=model,
            contents=[types.Part.from_uri(file_uri=file_uri, mime_type="video/mp4"), prompt],
        )
        return {
            "text":       resp.text,
            "model":      model,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        return {"error": str(exc)}


def analyse_image(image_path: str, prompt: str, model: str = "gemini-2.0-flash") -> dict:
    """
    Send a local image file to Gemini inline (no upload needed for images).

    Returns {text, model, elapsed_ms} or {error: str}.
    """
    try:
        from google.genai import types
        import mimetypes
        client = _client()
        path   = Path(image_path)
        mime   = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        t0     = time.monotonic()
        img_bytes = path.read_bytes()
        resp   = client.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=img_bytes, mime_type=mime), prompt],
        )
        return {
            "text":       resp.text,
            "model":      model,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        return {"error": str(exc)}


def delete_file(file_name: str) -> dict:
    """Delete an uploaded file from Gemini File API to free quota."""
    try:
        client = _client()
        client.files.delete(name=file_name)
        return {"status": "deleted", "name": file_name}
    except Exception as exc:
        return {"error": str(exc)}
