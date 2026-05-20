"""
Gemini Video MCP server — screen recording + Gemini 2.0 Flash video analysis.

Tools:
  start_recording    Start DXcam screen capture (background thread)
  stop_recording     Stop recording, save MP4
  upload_video       Upload MP4 to Gemini File API
  analyse_video      Ask Gemini about an uploaded video
  analyse_image      Ask Gemini about a local screenshot (inline, no upload)
  delete_file        Remove file from Gemini quota

Primary use case — video/image annotation assessments:
  Alison and similar platforms sometimes show a short video clip or image and ask
  "what is the person doing?" or "identify the object at timestamp X."
  Claude Code cannot watch video directly. This MCP records the screen while
  the video plays, uploads the recording to Gemini Flash, and asks Gemini
  for a structured description — which Claude Code then uses to answer.

Workflow:
  start_recording(fps=5)
  [user presses Play on assessment video]
  stop_recording(output_path="C:/tmp/clip.mp4")
  upload_video("C:/tmp/clip.mp4")                → {uri: "files/xxx"}
  analyse_video(uri, "Describe what happens")    → {text: "A person is ..."}
  delete_file("files/xxx")                        → cleanup

For image annotations (no recording needed):
  screenshot() from capture MCP → save to disk
  analyse_image("C:/tmp/frame.jpg", "What is shown?")

Requirements:
  pip install google-generativeai
  GEMINI_API_KEY environment variable set to your Gemini API key.
"""
from __future__ import annotations

from typing import Optional

from _minmcp import MinMCP

mcp = MinMCP("gemini")


@mcp.tool()
def start_recording(fps: int = 5, region: Optional[str] = None) -> dict:
    """
    Start recording the screen with DXcam.

    Args:
        fps:    Frames per second (default 5 — sufficient for UI/video content,
                keeps file size small). Max 30.
        region: Optional crop as "left,top,right,bottom" pixel coordinates.
                None = full screen.

    Returns:
        {status: "recording", fps: int}
        On error: {error: str}
    """
    try:
        from gemini_mcp._recorder import start_recording as _start
        parsed_region = None
        if region:
            parts = [int(x.strip()) for x in region.split(",")]
            if len(parts) != 4:
                return {"error": "region must be 'left,top,right,bottom'"}
            parsed_region = tuple(parts)
        return _start(fps=min(fps, 30), region=parsed_region)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def stop_recording(output_path: str) -> dict:
    """
    Stop the active screen recording and save to MP4.

    Args:
        output_path: Full path for the output .mp4 file.
                     Example: "C:/tmp/assessment_clip.mp4"

    Returns:
        {output_path, frame_count, fps, duration_s, resolution, size_mb}
        On error: {error: str}
    """
    try:
        from gemini_mcp._recorder import stop_recording as _stop
        return _stop(output_path=output_path)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def upload_video(video_path: str) -> dict:
    """
    Upload an MP4 to Gemini File API. Waits until processing is ACTIVE.

    Required before calling analyse_video(). Large files (>100MB) may take
    30–60 seconds to process.

    Args:
        video_path: Path to local .mp4 file.

    Returns:
        {uri, name, size_mb, state, upload_ms}
        uri and name are needed for analyse_video() and delete_file().
    """
    try:
        from gemini_mcp._gemini import upload_video as _upload
        return _upload(video_path=video_path)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def analyse_video(file_uri: str, prompt: str, model: str = "gemini-2.0-flash") -> dict:
    """
    Ask Gemini 2.0 Flash to analyse an uploaded video.

    Args:
        file_uri: URI from upload_video() — e.g. "https://generativelanguage.googleapis.com/v1beta/files/xxx"
        prompt:   What to ask about the video.
                  Example: "This is a screen recording of an assessment video.
                  Describe exactly what is happening, what objects appear, and
                  any text visible. Be specific about timestamps."
        model:    Gemini model ID. Default: "gemini-2.0-flash"

    Returns:
        {text: str, model: str, elapsed_ms: int}
    """
    try:
        from gemini_mcp._gemini import analyse_video as _analyse
        return _analyse(file_uri=file_uri, prompt=prompt, model=model)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def analyse_image(image_path: str, prompt: str, model: str = "gemini-2.0-flash") -> dict:
    """
    Ask Gemini 2.0 Flash about a local image file (inline — no upload needed).

    Use this for screenshot-based questions:
      - "What text is visible in this screenshot?"
      - "What objects are shown in this image?"
      - "Describe the graph/chart shown."

    Args:
        image_path: Local path to PNG or JPEG.
        prompt:     What to ask about the image.
        model:      Gemini model ID. Default: "gemini-2.0-flash"

    Returns:
        {text: str, model: str, elapsed_ms: int}
    """
    try:
        from gemini_mcp._gemini import analyse_image as _analyse
        return _analyse(image_path=image_path, prompt=prompt, model=model)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def delete_file(file_name: str) -> dict:
    """
    Delete an uploaded file from Gemini File API to free quota.

    Args:
        file_name: The 'name' field from upload_video() result
                   (e.g. "files/abc123xyz"). NOT the URI.

    Returns:
        {status: "deleted", name: str}
    """
    try:
        from gemini_mcp._gemini import delete_file as _delete
        return _delete(file_name=file_name)
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run()
