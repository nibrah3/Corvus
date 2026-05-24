"""Test LLM with 42 radio elements from 16personalities page."""
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

# Replicate the real 16personalities elements (6 questions × 7 options = 42 radios)
options = [
    "I strongly agree", "I moderately agree", "I agree",
    "I am not sure", "I disagree", "I moderately disagree", "I strongly disagree"
]
element_list = []
nid = 200
for q_num in range(1, 7):  # 6 questions
    for opt in options:
        element_list.append({"node_id": str(nid), "role": "radio", "text": opt})
        nid += 1

# Also add the button
element_list.append({"node_id": str(nid), "role": "button", "text": "Go to the next set of questions"})

profile_summary = "Name: James Okafor | Big Five: O=0.65 C=0.70 E=0.55 A=0.75 N=0.35"
payload = json.dumps({"candidate": profile_summary, "page_elements": element_list}, ensure_ascii=False)
print(f"Payload length: {len(payload)} chars, {len(element_list)} elements")

resp = client.chat.completions.create(
    model=_MODEL,
    max_tokens=512,
    messages=[
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": payload},
    ],
)
content = resp.choices[0].message.content
print("Raw content:", repr(content[:200] if content else None))
print("Finish:", resp.choices[0].finish_reason)
