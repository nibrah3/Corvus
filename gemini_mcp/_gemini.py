"""
Gemini File API + Video understanding client.

Gemini 2.0 Flash can analyse up to 1 hour of video from a local file.
We upload the MP4 via the File API, then call generateContent with the
file URI — Gemini processes the full video as context.

Use cases for CareerBridge:
  1. Video annotation assessments — "what is the person doing at 0:12?"
  2. Image description assessments — upload screenshot as image
  3. Audio transcription — Gemini Flash handles speech-to-text natively

Upload flow (required for files > ~20MB inline):
  1. client.files.upload(path=mp4_path)          → FileObject (uri, state)
  2. Poll until file.state == "ACTIVE"            → processing complete
  3. client.models.generate_content(              → structured response
       model="gemini-2.0-flash",
       contents=[{"role":"user", "parts":[
         {"file_data": {"mime_type":"video/mp4", "file_uri": file.uri}},
         {"text": prompt}
       ]}]
     )

API key: GEMINI_API_KEY environment variable.
"""
from __future__ import annotations

import os
import time
from pathlib import Path


def _client():
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    return genai


def upload_video(video_path: str) -> dict:
    """
    Upload an MP4 to Gemini File API. Polls until ACTIVE.

    Returns:
        {uri, name, size_mb, state, upload_ms}
        On error: {error: str}
    """
    try:
        genai = _client()
        path = Path(video_path)
        if not path.exists():
            return {"error": f"File not found: {video_path}"}

        t0 = time.monotonic()
        file_obj = genai.upload_file(path=str(path), mime_type="video/mp4")

        # Poll for ACTIVE state (processing can take 10–60s for large files)
        deadline = time.monotonic() + 120
        while file_obj.state.name != "ACTIVE":
            if time.monotonic() > deadline:
                return {"error": "Gemini file processing timed out after 120s"}
            time.sleep(3)
            file_obj = genai.get_file(file_obj.name)

        upload_ms = int((time.monotonic() - t0) * 1000)
        size_mb = path.stat().st_size / (1024 * 1024)

        return {
            "uri":       file_obj.uri,
            "name":      file_obj.name,
            "size_mb":   round(size_mb, 2),
            "state":     file_obj.state.name,
            "upload_ms": upload_ms,
        }
    except Exception as exc:
        return {"error": str(exc)}


def analyse_video(file_uri: str, prompt: str, model: str = "gemini-2.0-flash") -> dict:
    """
    Send a video (already uploaded) to Gemini with a prompt.

    Args:
        file_uri: URI from upload_video() result.
        prompt:   Instruction for Gemini (e.g. "Describe what happens at each timestamp").
        model:    Gemini model ID (default: gemini-2.0-flash).

    Returns:
        {text: str, model: str, elapsed_ms: int}
        On error: {error: str}
    """
    try:
        genai = _client()
        t0 = time.monotonic()
        model_obj = genai.GenerativeModel(model)
        response = model_obj.generate_content(
            [
                {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
                prompt,
            ]
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "text":       response.text,
            "model":      model,
            "elapsed_ms": elapsed_ms,
        }
    except Exception as exc:
        return {"error": str(exc)}


def analyse_image(image_path: str, prompt: str, model: str = "gemini-2.0-flash") -> dict:
    """
    Send a local image file to Gemini with a prompt (inline, no upload needed).

    Args:
        image_path: Path to PNG/JPEG on disk.
        prompt:     What to ask about the image.

    Returns:
        {text: str, model: str, elapsed_ms: int}
    """
    try:
        import PIL.Image
        genai = _client()
        img = PIL.Image.open(image_path)
        t0 = time.monotonic()
        model_obj = genai.GenerativeModel(model)
        response = model_obj.generate_content([img, prompt])
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "text":       response.text,
            "model":      model,
            "elapsed_ms": elapsed_ms,
        }
    except Exception as exc:
        return {"error": str(exc)}


def delete_file(file_name: str) -> dict:
    """Delete an uploaded file from Gemini File API to free quota."""
    try:
        genai = _client()
        genai.delete_file(file_name)
        return {"status": "deleted", "name": file_name}
    except Exception as exc:
        return {"error": str(exc)}
