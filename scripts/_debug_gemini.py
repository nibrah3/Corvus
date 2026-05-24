import os, json, requests
for line in open("D:/cb-core/.env").read().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("="); os.environ[k.strip()] = v.strip()

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"

query = "online community college monthly enrollment no ID verification no transcript"
body = {
    "contents": [{"parts": [{"text":
        f"List 8 real US universities or community colleges that match: '{query}'. "
        'Output a JSON array, each object with keys: name, url, enrollment_url. '
        'Example: [{"name":"Western Governors University","url":"https://wgu.edu","enrollment_url":"https://wgu.edu/admissions/apply"}] '
        "Output ONLY the JSON array, nothing else."
    }]}],
    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
}
resp = requests.post(GEMINI_URL, json=body, timeout=30)
print("Status:", resp.status_code)
if resp.ok:
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    print("Raw output:")
    print(raw)
else:
    print("Error:", resp.text[:500])
