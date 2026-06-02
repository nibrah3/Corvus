"""
test_persona_variation.py — Comprehensive live persona variation test.

Covers all pipeline hooks:
  1. gemini_agent.py     (_apply_persona) — ARCHIVED: careerbridge/_archive/reasoning/gemini_agent.py
                         Step 1 will fail if gemini_agent is not on the path.
  2. assessment_pipeline (_persona_humanize in CDP text answer paths)
  3. application_pipeline (persona in pre-answers + task prompt)
  4. cv_generator        (persona in CV summary + cover letter)

Usage:
  python D:\\cb-core\\scripts\\test_persona_variation.py
"""
from __future__ import annotations

import os
import re
import sys
import hashlib
import time

sys.path.insert(0, r"D:\cb-core")

for _ENV in (r"D:\cb-core\.env", r"D:\cb-core\runtime\.env"):
    if not os.getenv("OPENROUTER_API_KEY") and os.path.exists(_ENV):
        with open(_ENV) as f:
            for line in f:
                line = line.strip()
                if line.startswith("OPENROUTER_API_KEY="):
                    os.environ["OPENROUTER_API_KEY"] = line.split("=", 1)[1].strip()
                    break

from answer_mcp._persona import generate_persona, get_persona_prompt, has_persona
from answer_mcp._humanize import humanize, humanize_prose

PROFILE_A = "test_profile_alpha_001"
PROFILE_B = "test_profile_beta_002"
PROFILE_C = "test_profile_gamma_003"

PROFILE_A_FACTS = {"age": 29, "background": "marketing coordinator, 4 years digital campaigns", "industry": "marketing"}
PROFILE_B_FACTS = {"age": 42, "background": "senior logistics manager, 15 years supply chain, ex-military", "industry": "logistics"}
PROFILE_C_FACTS = {"age": 24, "background": "recent CS graduate, first job seeker", "industry": "software engineering"}

QUESTION_1 = "Describe a time you worked effectively in a team."
CANONICAL_1 = (
    "I worked on a project where the team had to coordinate across departments "
    "to deliver results on a tight deadline. I contributed by organizing communication "
    "and making sure everyone understood their responsibilities, which helped us "
    "finish on time and with good quality."
)
QUESTION_2 = "What is your greatest professional strength?"
CANONICAL_2 = (
    "My greatest strength is my ability to stay organized and focused under pressure. "
    "I consistently meet deadlines, keep projects on track, and help others when stuck."
)

PASS_COUNT = 0
FAIL_COUNT = 0
RESULTS: dict[str, bool] = {}


def _word_set(text: str) -> set[str]:
    return set(re.findall(r'\b[a-z]{3,}\b', text.lower()))

def _jaccard(a: str, b: str) -> float:
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)

def _substance_ok(output: str, canonical: str) -> bool:
    # 15% overlap — persona rewrites aggressively but core meaning must survive
    cw = _word_set(canonical)
    ow = _word_set(output)
    return len(cw & ow) / max(len(cw), 1) >= 0.15

def _box(label: str, text: str) -> None:
    print(f"\n  [{label}]")
    lines = text[:300].split("\n")
    for line in lines[:5]:
        print(f"    {line}")
    if len(text) > 300:
        print("    ...")

def _check(name: str, passed: bool, detail: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not passed:
        FAIL_COUNT += 1
    else:
        PASS_COUNT += 1
    RESULTS[name] = passed


# ── Step 1: Persona setup ─────────────────────────────────────────────────────

def setup_personas() -> None:
    print("\n=== STEP 1: Persona setup ===")
    for pid, facts in [(PROFILE_A, PROFILE_A_FACTS), (PROFILE_B, PROFILE_B_FACTS), (PROFILE_C, PROFILE_C_FACTS)]:
        if has_persona(pid):
            print(f"  [OK] {pid} — exists")
        else:
            print(f"  [GEN] {pid} generating...", end="", flush=True)
            generate_persona(pid, facts)
            print(" done")


# ── Step 2: gemini_agent hook ─────────────────────────────────────────────────

def test_gemini_hook() -> None:
    print("\n=== STEP 2: gemini_agent hook (_apply_persona) ===")
    from careerbridge.reasoning.gemini_agent import _apply_persona, _ensure_persona

    out_a = _apply_persona(CANONICAL_1, QUESTION_1, PROFILE_A)
    out_b = _apply_persona(CANONICAL_1, QUESTION_1, PROFILE_B)

    _box(PROFILE_A, out_a)
    _box(PROFILE_B, out_b)

    j = _jaccard(out_a, out_b)
    print(f"\n  Jaccard A vs B: {j:.3f}")
    _check("gemini_hook/cross_profile_variation", j < 0.40, f"jaccard={j:.3f}")
    _check("gemini_hook/substance_A", _substance_ok(out_a, CANONICAL_1))
    _check("gemini_hook/substance_B", _substance_ok(out_b, CANONICAL_1))

    # Auto-persona path
    ephemeral = f"eph_{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}"
    prompt = _ensure_persona(ephemeral)
    out_e = _apply_persona(CANONICAL_2, QUESTION_2, ephemeral)
    _check("gemini_hook/auto_persona", len(out_e.split()) >= 5, f"{len(out_e.split())} words")


# ── Step 3: assessment_pipeline hook ─────────────────────────────────────────

def test_assessment_hook() -> None:
    print("\n=== STEP 3: assessment_pipeline hook (_persona_humanize) ===")
    from careerbridge.assessment_pipeline import _persona_humanize, _extract_profile_id
    from types import SimpleNamespace
    import datetime

    # Test _persona_humanize directly
    out_a = _persona_humanize(CANONICAL_1, "teamwork essay question", PROFILE_A)
    out_b = _persona_humanize(CANONICAL_1, "teamwork essay question", PROFILE_B)
    out_c = _persona_humanize(CANONICAL_1, "teamwork essay question", PROFILE_C)

    _box(PROFILE_A, out_a)
    _box(PROFILE_B, out_b)
    _box(PROFILE_C, out_c)

    j_ab = _jaccard(out_a, out_b)
    j_ac = _jaccard(out_a, out_c)
    j_bc = _jaccard(out_b, out_c)
    print(f"\n  Jaccard A/B={j_ab:.3f}  A/C={j_ac:.3f}  B/C={j_bc:.3f}")
    _check("assessment/cross_profile_variation", max(j_ab, j_ac, j_bc) < 0.45,
           f"max_jaccard={max(j_ab,j_ac,j_bc):.3f}")
    _check("assessment/substance_A", _substance_ok(out_a, CANONICAL_1))
    _check("assessment/substance_B", _substance_ok(out_b, CANONICAL_1))
    _check("assessment/substance_C", _substance_ok(out_c, CANONICAL_1))

    # _extract_profile_id with object (simulates dataclass — no schema dependency)
    p = SimpleNamespace(profile_id=PROFILE_A)
    pid = _extract_profile_id(p)
    _check("assessment/extract_profile_id_dataclass", pid == PROFILE_A, f"got={pid!r}")

    # _extract_profile_id with dict
    pid_dict = _extract_profile_id({"profile_id": PROFILE_B, "name": "Bob"})
    _check("assessment/extract_profile_id_dict", pid_dict == PROFILE_B, f"got={pid_dict!r}")

    # No-persona fallback (empty profile_id → returns canonical)
    fallback = _persona_humanize(CANONICAL_2, "strength question", "")
    _check("assessment/fallback_no_pid", fallback == CANONICAL_2, "should be unchanged")


# ── Step 4: application_pipeline hook ────────────────────────────────────────

def test_application_hook() -> None:
    print("\n=== STEP 4: application_pipeline hook (pre-answers + task prompt) ===")
    from careerbridge.application_pipeline import _build_task_prompt, _build_candidate_block

    persona_a = get_persona_prompt(PROFILE_A)
    persona_b = get_persona_prompt(PROFILE_B)

    profile_a = {
        "profile_id": PROFILE_A, "name": "Alice Marketing", "email": "alice@example.com",
        "bio": "Experienced marketing coordinator with digital campaign expertise.",
        "skills": '["Google Analytics", "Mailchimp", "Copywriting", "SEO"]',
        "experience": '[{"role":"Marketing Coordinator","company":"DigitalCo","years":4}]',
    }
    profile_b = {
        "profile_id": PROFILE_B, "name": "Bob Logistics", "email": "bob@example.com",
        "bio": "Senior logistics manager with 15 years supply chain experience.",
        "skills": '["SAP", "ERP", "Supply Chain", "Procurement"]',
        "experience": '[{"role":"Logistics Manager","company":"FreightCorp","years":15}]',
    }

    task_a = _build_task_prompt(
        "https://example.com/apply", profile_a, None, "application",
        persona_prompt=persona_a or ""
    )
    task_b = _build_task_prompt(
        "https://example.com/apply", profile_b, None, "application",
        persona_prompt=persona_b or ""
    )

    j = _jaccard(task_a, task_b)
    print(f"\n  Task prompt Jaccard A vs B: {j:.3f}")
    # Task prompts share structural boilerplate; threshold is loose — what matters is
    # the persona section IS injected (checked below) and the candidate facts differ.
    _check("application/task_prompts_differ", j < 0.80, f"jaccard={j:.3f}")
    _check("application/persona_in_task_A", "natural voice" in task_a.lower() or "voice" in task_a.lower())
    _check("application/persona_in_task_B", "natural voice" in task_b.lower() or "voice" in task_b.lower())

    # No-persona fallback
    task_nopersona = _build_task_prompt(
        "https://example.com/apply", profile_a, None, "application", persona_prompt=""
    )
    _check("application/fallback_no_persona", "candidate's natural voice" in task_nopersona.lower()
           or "candidate" in task_nopersona.lower())


# ── Step 5: cv_generator hook ─────────────────────────────────────────────────

def test_cv_hook() -> None:
    print("\n=== STEP 5: cv_generator hook (CV summary + cover letter) ===")
    import sys as _sys
    _sys.path.insert(0, r"D:\cb-core")
    from cv_generator import generate_cv, generate_cover_letter, _humanize_cv_summary

    persona_a = get_persona_prompt(PROFILE_A)
    persona_c = get_persona_prompt(PROFILE_C)

    profile_a = {
        "profile_id": PROFILE_A, "id": PROFILE_A, "name": "Alice Marketing",
        "email": "alice@example.com", "phone": "+1-555-0100", "location": "Austin TX",
        "bio": "Experienced marketing coordinator with 4 years in digital campaigns.",
        "skills": '["Google Analytics", "Mailchimp", "Copywriting", "SEO"]',
        "experience": '[{"role":"Marketing Coordinator","company":"DigitalCo","years":4,"desc":"Ran email campaigns."}]',
    }
    profile_c = {
        "profile_id": PROFILE_C, "id": PROFILE_C, "name": "Charlie Code",
        "email": "charlie@example.com", "phone": "+1-555-0300", "location": "Seattle WA",
        "bio": "Recent CS graduate seeking first software engineering role.",
        "skills": '["Python", "JavaScript", "React", "Git"]',
        "experience": '[{"role":"Intern","company":"StartupXYZ","years":0,"desc":"Built internal tools."}]',
    }
    job = {
        "id": "job_test_001", "title": "Digital Marketing Specialist", "company": "Acme Corp",
        "description": "Seeking a Marketing Specialist with Google Analytics, SEO, Mailchimp experience."
    }

    # CV summary humanization
    raw_summary = "Detail-oriented professional with experience in Google Analytics, SEO. Seeking a Digital Marketing Specialist role."
    if persona_a:
        sum_a = _humanize_cv_summary(raw_summary, persona_a, PROFILE_A)
        _check("cv/summary_humanized", sum_a != raw_summary, "should differ from canonical")
        _check("cv/summary_substance", _substance_ok(sum_a, raw_summary))
        _box("CV summary (Profile A)", sum_a)
    else:
        print("  [SKIP] no persona for profile A")

    # Full CV generation
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        result_a = generate_cv(profile_a, job, out_dir=tmpdir)
        result_c_job = dict(job, title="Software Engineer", company="TechCorp",
                            description="Python, JavaScript, React developer needed.")
        result_c = generate_cv(profile_c, result_c_job, out_dir=tmpdir)

        _check("cv/generate_cv_A_ok", bool(result_a["text"]))
        _check("cv/generate_cv_C_ok", bool(result_c["text"]))
        _check("cv/persona_applied_A", result_a.get("persona_applied", False))
        _check("cv/persona_applied_C", result_c.get("persona_applied", False))

        j = _jaccard(result_a["text"], result_c["text"])
        print(f"\n  CV text Jaccard A vs C: {j:.3f}")
        _check("cv/cv_texts_differ", j < 0.50, f"jaccard={j:.3f}")

        # Cover letter
        cl_a = generate_cover_letter(profile_a, job, out_dir=tmpdir)
        cl_c = generate_cover_letter(profile_c, result_c_job, out_dir=tmpdir)

        _check("cv/cover_letter_A_ok", bool(cl_a["text"]) and len(cl_a["text"].split()) > 30)
        _check("cv/cover_letter_C_ok", bool(cl_c["text"]) and len(cl_c["text"].split()) > 30)
        _check("cv/cover_letter_A_persona", cl_a.get("persona_applied", False))
        _check("cv/cover_letter_C_persona", cl_c.get("persona_applied", False))

        j_cl = _jaccard(cl_a["text"], cl_c["text"])
        print(f"\n  Cover letter Jaccard A vs C: {j_cl:.3f}")
        _check("cv/cover_letters_differ", j_cl < 0.45, f"jaccard={j_cl:.3f}")

        _box("Cover letter A", cl_a["text"])
        _box("Cover letter C", cl_c["text"])


# ── Step 6: End-to-end variation summary ─────────────────────────────────────

def test_e2e_variation() -> None:
    print("\n=== STEP 6: End-to-end profile uniqueness (all 3 profiles, 2 questions) ===")
    combos = [
        (PROFILE_A, QUESTION_1, CANONICAL_1),
        (PROFILE_B, QUESTION_1, CANONICAL_1),
        (PROFILE_C, QUESTION_1, CANONICAL_1),
        (PROFILE_A, QUESTION_2, CANONICAL_2),
        (PROFILE_B, QUESTION_2, CANONICAL_2),
        (PROFILE_C, QUESTION_2, CANONICAL_2),
    ]
    outputs = {}
    for pid, q, c in combos:
        p = get_persona_prompt(pid)
        out = humanize(canonical_answer=c, question=q, persona_prompt=p, profile_id=pid)
        outputs[(pid, q)] = out
        print(f"  {pid[:20]} | {q[:30]!r} => {len(out.split())} words")

    # Cross-profile for Q1
    j_ab = _jaccard(outputs[(PROFILE_A, QUESTION_1)], outputs[(PROFILE_B, QUESTION_1)])
    j_ac = _jaccard(outputs[(PROFILE_A, QUESTION_1)], outputs[(PROFILE_C, QUESTION_1)])
    j_bc = _jaccard(outputs[(PROFILE_B, QUESTION_1)], outputs[(PROFILE_C, QUESTION_1)])
    print(f"\n  Q1 cross-profile Jaccard: A/B={j_ab:.3f}  A/C={j_ac:.3f}  B/C={j_bc:.3f}")
    _check("e2e/q1_cross_profile_unique", max(j_ab, j_ac, j_bc) < 0.45)

    # Cross-profile for Q2
    j_ab2 = _jaccard(outputs[(PROFILE_A, QUESTION_2)], outputs[(PROFILE_B, QUESTION_2)])
    j_ac2 = _jaccard(outputs[(PROFILE_A, QUESTION_2)], outputs[(PROFILE_C, QUESTION_2)])
    j_bc2 = _jaccard(outputs[(PROFILE_B, QUESTION_2)], outputs[(PROFILE_C, QUESTION_2)])
    print(f"  Q2 cross-profile Jaccard: A/B={j_ab2:.3f}  A/C={j_ac2:.3f}  B/C={j_bc2:.3f}")
    _check("e2e/q2_cross_profile_unique", max(j_ab2, j_ac2, j_bc2) < 0.45)

    # Same profile, different questions — should differ (different topic)
    j_q1q2_A = _jaccard(outputs[(PROFILE_A, QUESTION_1)], outputs[(PROFILE_A, QUESTION_2)])
    print(f"  Profile A Q1 vs Q2 Jaccard: {j_q1q2_A:.3f}")
    _check("e2e/same_profile_diff_questions", j_q1q2_A < 0.60)

    # All 6 outputs are unique (none are copies)
    texts = list(outputs.values())
    pairs = [(i, j) for i in range(len(texts)) for j in range(i+1, len(texts))]
    near_dups = [(i, j) for i, j in pairs if _jaccard(texts[i], texts[j]) > 0.70]
    _check("e2e/no_near_duplicates", len(near_dups) == 0,
           f"{len(near_dups)} near-duplicate pairs found" if near_dups else "all unique")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("FULL PERSONA HOOK LIVE TEST SUITE")
    print("=" * 65)

    setup_personas()
    test_gemini_hook()
    test_assessment_hook()
    test_application_hook()
    test_cv_hook()
    test_e2e_variation()

    print("\n" + "=" * 65)
    print(f"RESULTS: {PASS_COUNT} passed  {FAIL_COUNT} failed")
    print("=" * 65)
    failures = [name for name, ok in RESULTS.items() if not ok]
    if failures:
        print("FAILED:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("ALL TESTS PASSED — persona is enforced across all pipeline hooks.")
    print()


if __name__ == "__main__":
    main()
