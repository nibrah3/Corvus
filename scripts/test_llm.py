"""Quick LLM connectivity test via OpenRouter."""
import sys, os
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from openai import OpenAI
client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)
resp = client.chat.completions.create(
    model="anthropic/claude-sonnet-4-6",
    max_tokens=100,
    messages=[
        {"role": "system", "content": "You return JSON arrays only."},
        {"role": "user", "content": 'Return exactly: [{"node_id": "1", "action": "click"}]'},
    ],
)
content = resp.choices[0].message.content
print("Content:", repr(content))
print("Model:", resp.model)
print("Finish:", resp.choices[0].finish_reason)
