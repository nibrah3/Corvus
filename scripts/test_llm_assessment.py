"""Debug: replicate exactly what assessment_pipeline._call_llm sends to the LLM."""
import sys, os, json
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from openai import OpenAI
from careerbridge.assessment_pipeline import _SYSTEM_PROMPT, _MODEL, _OPENROUTER_KEY

client = OpenAI(api_key=_OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

# Simulate a page with two radio buttons (like 16personalities scale)
element_list = [
    {"nodeId": "101", "role": "radio", "name": "Strongly Agree", "properties": {"checked": False}},
    {"nodeId": "102", "role": "radio", "name": "Agree", "properties": {"checked": False}},
    {"nodeId": "103", "role": "radio", "name": "Neutral", "properties": {"checked": False}},
    {"nodeId": "104", "role": "radio", "name": "Disagree", "properties": {"checked": False}},
    {"nodeId": "105", "role": "radio", "name": "Strongly Disagree", "properties": {"checked": False}},
]
profile_summary = "Name: James Okafor | Big Five: O=0.65 C=0.70 E=0.55 A=0.75 N=0.35"

payload = json.dumps({
    "candidate": profile_summary,
    "page_elements": element_list,
}, ensure_ascii=False)

print("System prompt:", repr(_SYSTEM_PROMPT[:80]))
print("Payload:", payload[:200])
print()

resp = client.chat.completions.create(
    model=_MODEL,
    max_tokens=512,
    messages=[
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": payload},
    ],
)
content = resp.choices[0].message.content
print("Raw content:", repr(content))
print("Finish:", resp.choices[0].finish_reason)
print("Model:", resp.model)
