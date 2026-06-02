#!/usr/bin/env python3
"""
hook_menu_router.py — UserPromptSubmit hook (Module 1)
Detects greetings and open-ended messages, injects Main Menu instruction.
Never blocks — always exits 0.
"""
import io
import json
import sys
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MENU_INSTRUCTION = """\
[SYSTEM - MENU REQUIRED]
The user sent a greeting or open-ended message. Your ONLY response must be \
to call AskUserQuestion immediately with the Main Menu below. \
Do not write any text before the AskUserQuestion call.

question: "Welcome back! What would you like to do?"
header: "Main Menu"
options:
  - label: "Jobs & Assessments"  description: "Find and apply to job opportunities"
  - label: "Schools"             description: "Find and enroll in online schools"
  - label: "My Setup"            description: "Manage profiles, proxies, and your CV"
  - label: "System"              description: "Start or check your CareerBridge systems"
"""

GREETING_PATTERNS = [
    r"^$",
    r"^(hi|hello|hey|yo|sup|howdy|greetings|hiya)\b",
    r"^good\s+(morning|afternoon|evening|night|day)\b",
    r"^(menu|main menu|home|help|start|back|return|go back|restart)\b",
    r"^(what can you do|what do you do|options|show options|show menu)\b",
]

def is_menu_trigger(prompt: str) -> bool:
    p = prompt.strip().lower()
    return any(re.match(pat, p) for pat in GREETING_PATTERNS)

def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace").strip()
        data = json.loads(raw) if raw else {}
        prompt = data.get("prompt", "")
    except Exception:
        prompt = ""

    if is_menu_trigger(prompt):
        print(MENU_INSTRUCTION)

    sys.exit(0)

if __name__ == "__main__":
    main()
