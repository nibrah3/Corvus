"""
Head-to-head latency benchmark: DOM relay vs Screenshot pipeline.
Both pipelines answer the same question about the current browser tab.
Sends a real LLM request for each pipeline and records every timing step.

Run: python bench_dom_vs_screenshot.py
"""
from __future__ import annotations
import base64, io, json, time, urllib.request, os
import anthropic
from PIL import Image

API_KEY   = os.environ["ANTHROPIC_API_KEY"]
MODEL     = "claude-sonnet-4-6"
PROMPT    = "In one sentence, what is the main content or question visible on this page?"
DOM_MCP   = "http://127.0.0.1:8710/mcp"

client = anthropic.Anthropic(api_key=API_KEY)


def _mcp_call(method: str, params: dict) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req  = urllib.request.Request(DOM_MCP, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def bench_dom() -> dict:
    timings = {}

    # Step 1 — fetch DOM context
    t0 = time.perf_counter()
    resp = _mcp_call("tools/call", {"name": "get_page_context", "arguments": {}})
    dom_text = resp["result"]["content"][0]["text"]
    timings["dom_fetch_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    # Step 2 — LLM text round-trip
    t1 = time.perf_counter()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=80,
        messages=[{
            "role": "user",
            "content": f"{PROMPT}\n\nPage DOM context:\n{dom_text}"
        }]
    )
    timings["llm_ms"]   = round((time.perf_counter() - t1) * 1000, 1)
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    timings["answer"]   = msg.content[0].text.strip()
    timings["input_tokens"]  = msg.usage.input_tokens
    timings["output_tokens"] = msg.usage.output_tokens
    return timings


def bench_screenshot() -> dict:
    import mss
    from capture_mcp._backend_mss import capture as mss_capture
    timings = {}

    # Step 1 — MSS screenshot capture
    t0 = time.perf_counter()
    raw = mss_capture()
    timings["mss_capture_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    # Crop centre 60% (same as production pipeline)
    t1 = time.perf_counter()
    pil = Image.open(io.BytesIO(raw))
    pw, ph = pil.size
    margin = int(pw * 0.20)
    pil = pil.crop((margin, 0, pw - margin, ph))
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=72, optimize=True)
    img_b64 = base64.standard_b64encode(buf.getvalue()).decode()
    timings["encode_ms"]       = round((time.perf_counter() - t1) * 1000, 1)
    timings["image_size_kb"]   = round(len(buf.getvalue()) / 1024, 1)

    # Step 2 — LLM vision round-trip
    t2 = time.perf_counter()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=80,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                {"type": "text",  "text": PROMPT},
            ]
        }]
    )
    timings["llm_ms"]   = round((time.perf_counter() - t2) * 1000, 1)
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    timings["answer"]   = msg.content[0].text.strip()
    timings["input_tokens"]  = msg.usage.input_tokens
    timings["output_tokens"] = msg.usage.output_tokens
    return timings


def print_row(label: str, val: str, width: int = 28) -> None:
    print(f"  {label:<{width}} {val}")


if __name__ == "__main__":
    print("\n-- DOM RELAY PIPELINE -----------------------------")
    dom = bench_dom()
    print_row("DOM fetch:",        f"{dom['dom_fetch_ms']}ms")
    print_row("LLM (text):",       f"{dom['llm_ms']}ms")
    print_row("TOTAL:",            f"{dom['total_ms']}ms")
    print_row("Tokens in/out:",    f"{dom['input_tokens']} / {dom['output_tokens']}")
    print_row("Answer:",           dom['answer'])

    print("\n-- SCREENSHOT PIPELINE (MSS) ----------------------")
    ss = bench_screenshot()
    print_row("MSS capture:",      f"{ss['mss_capture_ms']}ms")
    print_row("Encode (JPEG 72):", f"{ss['encode_ms']}ms  [{ss['image_size_kb']}kb]")
    print_row("LLM (vision):",     f"{ss['llm_ms']}ms")
    print_row("TOTAL:",            f"{ss['total_ms']}ms")
    print_row("Tokens in/out:",    f"{ss['input_tokens']} / {ss['output_tokens']}")
    print_row("Answer:",           ss['answer'])

    reduction = round((1 - dom['total_ms'] / ss['total_ms']) * 100, 1)
    print(f"\n-- RESULT: DOM relay is {reduction}% faster end-to-end ({'faster' if reduction > 0 else 'slower'})\n")
