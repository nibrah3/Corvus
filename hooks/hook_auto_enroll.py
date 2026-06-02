#!/usr/bin/env python3
"""
hook_auto_enroll.py - PostToolUse stub (COMING SOON)
Will fire after a future mcp__schools__start_auto_enroll tool that runs
school discovery -> confirmation -> PDF report -> enrollment end-to-end
with zero human gates.

Planned behaviour (when implemented):
  - Run discover_schools with configured criteria
  - Wait for results (poll get_discovery_status internally)
  - For each confirmed school above score threshold: fill enrollment form via CDP
  - Telegram photo of each completion; no AskUserQuestion at any step
  - On queue empty: summary to Telegram, hook re-surfaces Main Menu

Current status: STUB - tool does not yet exist.
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Wire this when mcp__schools__start_auto_enroll is implemented:
#   "matcher": "mcp__schools__start_auto_enroll"

print(
    "[AUTO-ENROLL - COMING SOON]\n"
    "Tell the user warmly: \"Full auto-enrollment is on the roadmap! "
    "Right now I can discover schools and send the reports to your phone - "
    "use the Schools menu to get started. "
    "Hands-free enrollment end-to-end is coming soon.\"\n"
    "Then show the System sub-menu via AskUserQuestion."
)
sys.exit(0)

if __name__ == "__main__":
    pass
