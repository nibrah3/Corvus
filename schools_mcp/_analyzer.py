"""
Criteria analysis: apply all 6 filters to crawled school content.
Primary: Claude Sonnet 4.6 via OpenRouter.  Fallback: precision heuristics.
"""
from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

CRITERIA = [
    "community_college",
    "no_id_verification",
    "no_transcript_required",
    "monthly_enrollment",
    "instant_acceptance",
    "monthly_refund",
]

CRITERIA_LABELS = {
    "community_college":      "Community College",
    "no_id_verification":     "No ID Verification",
    "no_transcript_required": "No Transcript Required",
    "monthly_enrollment":     "Monthly / Rolling Enrollment",
    "instant_acceptance":     "Instant Acceptance",
    "monthly_refund":         "Monthly Refund Policy",
}

_SYSTEM_PROMPT = (
    "You are an admissions policy analyst. Given text scraped from a school's website, "
    "evaluate each criterion ONLY on what is explicitly stated or clearly implied by the text. "
    "Do NOT assume a criterion is met just because it is not mentioned — absence of evidence is NOT evidence. "
    "Be conservative: if you are unsure, return false.\n\n"
    "Criteria to evaluate:\n"
    "1. community_college — explicitly a community college or two-year college\n"
    "2. no_id_verification — explicitly states students can enroll WITHOUT government-issued ID\n"
    "3. no_transcript_required — explicitly states no prior transcripts are required\n"
    "4. monthly_enrollment — explicitly states rolling or monthly start dates\n"
    "5. instant_acceptance — explicitly states applications are accepted immediately or same-day\n"
    "6. monthly_refund — explicitly describes a monthly or pro-rated refund policy\n\n"
    "Return ONLY a JSON object with no markdown fences:\n"
    "{\n"
    '  "community_college": true/false,\n'
    '  "no_id_verification": true/false,\n'
    '  "no_transcript_required": true/false,\n'
    '  "monthly_enrollment": true/false,\n'
    '  "instant_acceptance": true/false,\n'
    '  "monthly_refund": true/false,\n'
    '  "evidence": {\n'
    '    "community_college": "direct quote from text, or not stated",\n'
    '    "no_id_verification": "direct quote from text, or not stated",\n'
    '    "no_transcript_required": "direct quote from text, or not stated",\n'
    '    "monthly_enrollment": "direct quote from text, or not stated",\n'
    '    "instant_acceptance": "direct quote from text, or not stated",\n'
    '    "monthly_refund": "direct quote from text, or not stated"\n'
    "  }\n"
    "}"
)


def _call_claude(text: str) -> dict | None:
    """Call Claude for school criteria analysis. Prefers Anthropic SDK, falls back to OpenRouter."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    or_key        = os.environ.get("OPENROUTER_API_KEY", "")

    if not anthropic_key and not or_key:
        log.warning("No LLM API key set — falling back to heuristics")
        return None

    user_content = f"School website text:\n\n{text[:6000]}"

    try:
        if anthropic_key:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=900,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = (resp.content[0].text or "").strip()
        else:
            from openai import OpenAI
            client = OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
            resp = client.chat.completions.create(
                model="anthropic/claude-sonnet-4-6",
                max_tokens=900,
                temperature=0,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_content},
                ],
            )
            raw = (resp.choices[0].message.content or "").strip()

        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:])
            raw = raw[:raw.rfind("```")] if "```" in raw else raw
        return json.loads(raw.strip())
    except Exception as e:
        log.warning("Claude analysis failed: %s", e)
        return None


# ── Precision heuristics ───────────────────────────────────────────────────────
# Rule: require POSITIVE evidence. Absence of mention → False.
# Each entry: (positive_pattern, negative_override_pattern | None)

_H: dict[str, tuple[re.Pattern, re.Pattern | None]] = {
    "community_college": (
        re.compile(
            r"community\s+college|two[- ]year\s+college|2[- ]year\s+college|"
            r"\bjunior\s+college\b|associate[\'s]*\s+degree(?:\s+program)?|"
            r"\bA\.A\.\b|\bA\.S\.\b|\bA\.A\.S\.\b",
            re.I,
        ),
        None,
    ),
    "no_id_verification": (
        re.compile(
            r"no\s+(?:government[- ]issued\s+)?id\s+(?:required|needed|necessary)|"
            r"without\s+(?:photo|government)[- ]?id|"
            r"id\s+(?:verification\s+)?(?:not\s+required|waived|optional)|"
            r"enroll\s+without\s+(?:an?\s+)?(?:id|identity)\s+verification|"
            r"no\s+id\s+check",
            re.I,
        ),
        re.compile(
            r"government[- ]issued\s+(?:id|photo)|photo\s+id\s+required|"
            r"driver[\'s]*\s+licen(?:se|ce)\s+required|passport\s+required|"
            r"valid\s+(?:state\s+)?id\s+required|identity\s+verification\s+required",
            re.I,
        ),
    ),
    "no_transcript_required": (
        re.compile(
            r"no\s+(?:high[\s-]school\s+|prior\s+)?transcript|"
            r"transcript\s+(?:not\s+required|waived|optional|free)|"
            r"without\s+(?:a\s+)?transcript|"
            r"no\s+prior\s+academic\s+records?\s+(?:required|needed)|"
            r"transcript[- ]free\s+(?:enrollment|admission)|"
            r"open\s+enrollment[^.]{0,60}no\s+transcript",
            re.I,
        ),
        re.compile(
            r"official\s+transcript\s+(?:is\s+)?required|"
            r"(?:must\s+)?submit\s+(?:your\s+|official\s+)?transcripts?|"
            r"transcripts?\s+(?:must\s+be|are\s+required\s+to\s+be)\s+"
            r"(?:sent|submitted|provided|mailed|forwarded)",
            re.I,
        ),
    ),
    "monthly_enrollment": (
        re.compile(
            r"monthly\s+(?:enrollment|intake|start|cohort|admission|rolling)|"
            r"rolling\s+(?:admission|enrollment|intake)|"
            r"start\s+(?:every|each)\s+month|new\s+students?\s+(?:every|each)\s+month|"
            r"multiple\s+start\s+dates?(?:\s+per\s+year)?|"
            r"\d+\s+start\s+dates?\s+(?:per\s+year|annually)|"
            r"enroll\s+any\s+(?:time|month)|"
            r"open[- ]enrollment[^.]{0,40}rolling",
            re.I,
        ),
        None,
    ),
    "instant_acceptance": (
        re.compile(
            r"instant(?:ly)?\s+(?:accept|enroll|admit)|"
            r"immediate\s+(?:accept|enroll|decision|admission|approval)|"
            r"admitted\s+immediately|no\s+waiting\s+period|"
            r"apply\s+and\s+start\s+(?:today|immediately|right\s+away)|"
            r"same[- ]day\s+(?:accept|decision|admission|approval)|"
            r"decisions?\s+(?:within\s+)?24\s+hours?",
            re.I,
        ),
        None,
    ),
    "monthly_refund": (
        re.compile(
            r"monthly\s+refund|pro[- ]?rated\s+(?:monthly\s+)?refund|"
            r"refund\s+(?:schedule|policy)[^.]{0,80}month|"
            r"monthly\s+(?:tuition\s+)?refund\s+(?:schedule|policy)|"
            r"refund\s+(?:on\s+a\s+)?(?:monthly|30[- ]day)\s+basis",
            re.I,
        ),
        None,
    ),
}


def _extract_evidence(criterion: str, text: str) -> str:
    pos, neg = _H[criterion]
    if neg and neg.search(text):
        return "not stated (contradicting language found)"
    m = pos.search(text)
    if m:
        start = max(0, m.start() - 50)
        end   = min(len(text), m.end() + 120)
        return "…" + text[start:end].replace("\n", " ").strip() + "…"
    return "not stated"


def heuristic_analyze(text: str) -> dict:
    """Regex fallback. Requires positive evidence; absence → False."""
    results: dict = {}
    evidence: dict = {}
    for c in CRITERIA:
        pos, neg = _H[c]
        blocked = neg and neg.search(text)
        results[c] = False if blocked else bool(pos.search(text))
        evidence[c] = _extract_evidence(c, text)
    return {**results, "evidence": evidence}


def analyze(school: dict) -> dict:
    """
    Run criteria analysis on crawled_text using Claude Sonnet.
    Returns school dict enriched with criterion booleans, evidence,
    criteria_score, and filters list.
    """
    text = school.get("crawled_text", "")
    name = school.get("name", "")

    result = _call_claude(text)

    if not result:
        log.info("%s: Claude unavailable — heuristics", name[:40])
        result = heuristic_analyze(text)
    else:
        # Trust the College Scorecard community_college flag over LLM
        if school.get("is_community_college") and not result.get("community_college"):
            result["community_college"] = True
            ev = result.get("evidence", {})
            if isinstance(ev, dict):
                ev["community_college"] = (
                    "Confirmed by US College Scorecard "
                    "(predominant degree = associate's)"
                )

        # Sanity-check: if Claude says True but provides "not stated" evidence,
        # trust the evidence string — revert to False.
        ev = result.get("evidence", {})
        if isinstance(ev, dict):
            for c in ("no_id_verification", "no_transcript_required",
                      "instant_acceptance", "monthly_refund"):
                if result.get(c):
                    ev_text = ev.get(c, "").lower().strip()
                    if ev_text in ("not stated", "", "not stated (contradicting language found)"):
                        result[c] = False
                        ev[c] = "not stated"

    # Normalise evidence to per-criterion dict
    evidence = result.get("evidence", {})
    if isinstance(evidence, str):
        evidence = {c: evidence for c in CRITERIA}

    active_filters = [c for c in CRITERIA if result.get(c)]
    score = len(active_filters)

    return {
        **school,
        "community_college":      bool(result.get("community_college")),
        "no_id_verification":     bool(result.get("no_id_verification")),
        "no_transcript_required": bool(result.get("no_transcript_required")),
        "monthly_enrollment":     bool(result.get("monthly_enrollment")),
        "instant_acceptance":     bool(result.get("instant_acceptance")),
        "monthly_refund":         bool(result.get("monthly_refund")),
        "evidence":               evidence,
        "filters":                active_filters,
        "criteria_score":         score,
    }
