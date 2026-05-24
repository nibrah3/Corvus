"""Test assessment LLM call with real page context."""
import sys, os, json, time
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

page_context = """Free Personality Test
Question 1 of 60: You regularly make new friends.
Question 2 of 60: Complex and novel ideas excite you more than simple and straightforward ones.
Question 3 of 60: You usually feel more persuaded by what resonates emotionally with you.
Question 4 of 60: Your living and working spaces are clean and organized.
Question 5 of 60: You usually stay calm, even under a lot of pressure.
Question 6 of 60: You find the idea of networking or promoting yourself to strangers very daunting."""

options = ["I strongly agree", "I moderately agree", "I agree", "I am not sure", "I disagree", "I moderately disagree", "I strongly disagree"]
element_list = []
nid = 200
for q_num in range(1, 7):
    for opt in options:
        element_list.append({"node_id": str(nid), "role": "radio", "text": opt})
        nid += 1
element_list.append({"node_id": str(nid), "role": "button", "text": "Go to the next set of questions"})

profile_summary = "Name: James Okafor | Big Five: O=0.65 C=0.70 E=0.55 A=0.75 N=0.35"
payload = json.dumps({
    "candidate": profile_summary,
    "page_context": page_context[:3000],
    "page_elements": element_list,
}, ensure_ascii=False)

print(f"Payload: {len(payload)} chars, {len(element_list)} elements")
resp = client.chat.completions.create(
    model=_MODEL,
    max_tokens=1024,
    messages=[
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": payload},
    ],
)
content = resp.choices[0].message.content
full = content or ""
print(f"Content length: {len(full)}")
# Try to find JSON array in the response
import re
json_match = re.search(r'\[.*?\]', full, re.DOTALL)
if json_match:
    print("Found JSON:", json_match.group()[:200])
else:
    print("No JSON found. First 300 chars:", full[:300].encode('ascii','replace').decode())
print("Finish:", resp.choices[0].finish_reason)
if content:
    try:
        import re
        raw = content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
        print(f"Parsed OK: {len(parsed)} actions")
        for act in parsed[:3]:
            print(f"  {act}")
    except Exception as e:
        print(f"Parse error: {e}")
