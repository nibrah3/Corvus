"""
cv_generator.py — ATS-optimised CV generator.

Extracts keywords from a job description and produces a plain-text + PDF CV
that mirrors the posting's language — maximising ATS keyword match score.

ATS rules followed:
  - No tables, columns, graphics, text boxes, headers/footers
  - Standard section headings recognised by Greenhouse, Lever, Workday, Taleo
  - Exact keyword phrasing from the job description woven into skills + bullets
  - PDF via reportlab (falls back to .txt only if unavailable)
"""
import re
import os
import json
import logging

log = logging.getLogger(__name__)

# ── HTML → plain text ──────────────────────────────────────────────────────────

def _strip_html(html):
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html or "", "html.parser").get_text(separator=" ")
    except ImportError:
        text = re.sub(r"<[^>]+>", " ", html or "")
        text = re.sub(r"&[a-z]+;", " ", text)
        return re.sub(r"\s+", " ", text).strip()


def _bullets(text):
    items = []
    for line in re.split(r"[\n\r]|(?<!\w)[•\-–\*]\s|(?:\d+\.)\s", text):
        line = line.strip(" \t.,;:")
        if 5 < len(line) < 250:
            items.append(line)
    return items


# ── Keyword extraction ─────────────────────────────────────────────────────────

SECTION_RE = re.compile(
    r"(requirement|qualification|must.have|what you.?ll need|"
    r"preferred|nice.to.have|responsibilit|what you.?ll do|"
    r"about the role|skills?|we.?re looking for|you will|you have)",
    re.I,
)

BLACKLIST = {
    "the", "and", "or", "to", "a", "an", "of", "in", "for", "on", "with",
    "you", "we", "our", "your", "will", "can", "be", "this", "that", "is",
    "are", "have", "has", "not", "but", "also", "as", "at", "by", "from",
    "their", "they", "it", "its", "if", "all", "do", "does", "how", "what",
    "when", "where", "who", "which", "more", "than", "up", "out", "so",
    "other", "any", "some", "such", "about", "into", "through", "during",
    "experience", "work", "working", "ability", "strong", "good", "great",
    "excellent", "team", "role", "position", "company", "job", "opportunity",
}


def extract_keywords(description):
    """
    Parse a job description (HTML or plain text).
    Returns:
      required   — must-have bullets
      preferred  — nice-to-have bullets
      tech       — tools / technologies (capitalised terms)
      full_text  — stripped plain text (up to 4000 chars)
    """
    plain = _strip_html(description)

    buckets = {"required": [], "preferred": [], "responsibilities": []}
    current = "required"

    for sentence in re.split(r"\.(?:\s|$)|\n", plain):
        m = SECTION_RE.search(sentence)
        if m:
            h = m.group(1).lower()
            if re.search(r"prefer|nice", h):
                current = "preferred"
            elif re.search(r"responsib|will do|you will", h):
                current = "responsibilities"
            else:
                current = "required"
        buckets[current].append(sentence)

    required_text = " ".join(buckets["required"])
    preferred_text = " ".join(buckets["preferred"])

    # Extract capitalised / technical terms
    tech = []
    seen_tech = set()
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9+#./\-]{1,25}|[A-Z]{2,12})\b", plain):
        word = m.group(1)
        low = word.lower()
        if low not in BLACKLIST and len(word) > 1 and low not in seen_tech:
            seen_tech.add(low)
            tech.append(word)

    return {
        "required":   _bullets(required_text)[:20],
        "preferred":  _bullets(preferred_text)[:15],
        "tech":       tech[:35],
        "full_text":  plain[:4000],
    }


# ── Profile → keyword match ────────────────────────────────────────────────────

def score_match(profile, keywords):
    """
    Returns (score 0-100, matched_keywords, missing_requirements).
    """
    profile_blob = " ".join(filter(None, [
        profile.get("skills", "") or "",
        profile.get("experience", "") or "",
        profile.get("bio", "") or "",
    ])).lower()

    all_kw = list(dict.fromkeys(keywords["tech"] + [
        w for b in keywords["required"] for w in b.split()
        if len(w) > 3 and w.lower() not in BLACKLIST
    ]))

    matched = [k for k in all_kw if k.lower() in profile_blob]
    missing = [
        b for b in keywords["required"]
        if not any(w.lower() in profile_blob for w in b.split() if len(w) > 3)
    ][:10]

    score = int(len(matched) / max(len(all_kw), 1) * 100)
    return score, matched[:20], missing


# ── Profile field parsers ──────────────────────────────────────────────────────

def _parse_skills(raw):
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(s) for s in parsed]
    except Exception:
        pass
    return [s.strip() for s in re.split(r"[,;|]", str(raw)) if s.strip()]


def _parse_experience(raw):
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    return [{"role": "Freelancer", "company": "Independent", "years": "", "desc": str(raw)}]


# ── CV text builder ────────────────────────────────────────────────────────────

def _humanize_cv_summary(summary: str, persona_prompt: str, profile_id: str) -> str:
    """Rewrite the CV summary section in the profile's natural voice."""
    try:
        from answer_mcp._humanize import humanize
        return humanize(
            canonical_answer=summary,
            question="Write a professional summary for my CV",
            persona_prompt=persona_prompt,
            profile_id=profile_id,
            target_words=min(80, len(summary.split()) + 10),
        )
    except Exception as e:
        log.warning("CV summary humanization failed: %s — using canonical", e)
        return summary


def _build_cv_text(profile, job, keywords, persona_prompt: str = ""):
    name     = (profile.get("name") or "").upper()
    email    = profile.get("email") or ""
    phone    = profile.get("phone") or ""
    location = profile.get("location") or ""
    bio      = profile.get("bio") or ""

    job_title   = job.get("title") or ""
    job_company = job.get("company") or ""

    profile_id     = profile.get("profile_id") or profile.get("id") or ""
    profile_skills = _parse_skills(profile.get("skills"))
    experience     = _parse_experience(profile.get("experience"))
    education_raw  = profile.get("education") or ""

    # Skills: job-matching tech first, then remaining profile skills
    matched_tech = [k for k in keywords["tech"]
                    if any(k.lower() in s.lower() for s in profile_skills)]
    remaining = [s for s in profile_skills
                 if not any(s.lower() in k.lower() or k.lower() in s.lower()
                            for k in matched_tech)]
    skill_list = matched_tech + remaining or profile_skills

    # Summary: mirror job title + top keywords
    top_kw = (matched_tech or keywords["tech"])[:3]
    kw_phrase = ", ".join(top_kw) if top_kw else ""
    if bio and len(bio) > 50:
        summary = bio[:450].rstrip(".")
        if job_title and job_title.lower() not in summary.lower():
            summary += f". Seeking {job_title} opportunities with {job_company}."
    else:
        summary = (
            f"Detail-oriented professional with experience in {kw_phrase}. "
            f"Seeking a {job_title} role with {job_company}."
        )

    # Humanize summary through persona — voice only, ATS keywords preserved in skills section
    if persona_prompt and profile_id:
        summary = _humanize_cv_summary(summary, persona_prompt, profile_id)

    L = []

    # Header
    L.append(name)
    L.append(" | ".join(p for p in [email, phone, location] if p))
    L.append("")

    # Summary
    L.append("PROFESSIONAL SUMMARY")
    L.append("-" * 50)
    L.append(summary)
    L.append("")

    # Core skills
    L.append("CORE SKILLS")
    L.append("-" * 50)
    for i in range(0, len(skill_list), 4):
        L.append("  " + " | ".join(skill_list[i:i + 4]))
    L.append("")

    # Experience
    L.append("PROFESSIONAL EXPERIENCE")
    L.append("-" * 50)
    for exp in experience:
        role    = exp.get("role") or ""
        company = exp.get("company") or ""
        years   = exp.get("years") or ""
        desc    = exp.get("desc") or ""
        dur = f"{years} year{'s' if str(years) != '1' else ''}" if years else ""
        header = " | ".join(p for p in [role, company, dur] if p)
        L.append(header)
        for bullet in re.split(r"\.\s+|\n", desc):
            bullet = bullet.strip()
            if bullet:
                L.append(f"  - {bullet}")
        L.append("")

    # Education
    if education_raw:
        L.append("EDUCATION")
        L.append("-" * 50)
        L.append(education_raw)
        L.append("")

    # Relevant qualifications (mirrors job requirements — ATS keyword section)
    if keywords["required"]:
        L.append("RELEVANT QUALIFICATIONS")
        L.append("-" * 50)
        for req in keywords["required"][:8]:
            L.append(f"  - {req}")
        L.append("")

    return "\n".join(L)


# ── PDF output ─────────────────────────────────────────────────────────────────

def _build_pdf(text, path):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT

        styles = getSampleStyleSheet()
        body = ParagraphStyle("body", parent=styles["Normal"],
                              fontSize=10, leading=14, fontName="Helvetica")
        bold = ParagraphStyle("bold", parent=styles["Normal"],
                              fontSize=11, leading=14, fontName="Helvetica-Bold")

        doc = SimpleDocTemplate(path, pagesize=A4,
                                leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        story = []
        for line in text.split("\n"):
            stripped = line.strip()
            if re.match(r"^[A-Z ]{4,}$", stripped):
                story.append(Paragraph(stripped, bold))
            elif stripped.startswith("-" * 10):
                story.append(Spacer(1, 4))
            elif stripped:
                story.append(Paragraph(stripped.replace("&", "&amp;"), body))
            else:
                story.append(Spacer(1, 6))
        doc.build(story)
        return True
    except Exception as e:
        log.warning(f"PDF generation failed: {e}")
        return False


# ── Public entry point ─────────────────────────────────────────────────────────

def _load_persona_for_cv(profile: dict) -> str:
    """Load or auto-generate persona_prompt for CV generation."""
    profile_id = profile.get("profile_id") or profile.get("id") or ""
    if not profile_id:
        return ""
    try:
        import sys
        _root = os.path.normpath(os.path.dirname(__file__))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from answer_mcp._persona import get_persona_prompt, generate_persona
        prompt = get_persona_prompt(profile_id)
        if not prompt:
            log.info("Auto-generating persona for CV profile %r", profile_id)
            prompt = generate_persona(profile_id, {
                "name": profile.get("name", ""),
                "background": profile.get("bio", "")[:200],
            })["persona_prompt"]
        return prompt
    except Exception as e:
        log.debug("Persona load for CV failed (non-fatal): %s", e)
        return ""


def generate_cv(profile, job, out_dir="/opt/corvus/cvs"):
    """
    Generate a keyword-tailored CV for the given job.

    Args:
        profile: dict with keys name, email, phone, location, bio, skills,
                 experience, education  (as stored in the profiles table)
        job:     dict with keys id, title, company, description
        out_dir: directory to write output files

    Returns dict:
        text      — plain-text CV string
        txt_path  — path to .txt file
        pdf_path  — path to .pdf file (None if reportlab unavailable)
        score     — 0-100 keyword match score
        matched   — list of matched keywords
        missing   — list of unmatched required bullets
        keywords  — raw extracted keyword dict
    """
    os.makedirs(out_dir, exist_ok=True)
    keywords = extract_keywords(job.get("description") or "")
    score, matched, missing = score_match(profile, keywords)
    persona_prompt = _load_persona_for_cv(profile)
    cv_text = _build_cv_text(profile, job, keywords, persona_prompt=persona_prompt)

    safe_p = re.sub(r"[^a-z0-9_-]", "_", (profile.get("id") or "profile").lower())
    safe_j = re.sub(r"[^a-z0-9_-]", "_", str(job.get("id") or "job").lower())
    base = os.path.join(out_dir, f"cv_{safe_p}_{safe_j}")

    txt_path = base + ".txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(cv_text)

    pdf_path = base + ".pdf"
    pdf_ok = _build_pdf(cv_text, pdf_path)

    return {
        "text":            cv_text,
        "txt_path":        txt_path,
        "pdf_path":        pdf_path if pdf_ok else None,
        "score":           score,
        "matched":         matched,
        "missing":         missing,
        "keywords":        keywords,
        "persona_applied": bool(persona_prompt),
    }


# ── Cover letter generator ─────────────────────────────────────────────────────

def generate_cover_letter(profile: dict, job: dict, out_dir: str = "/opt/corvus/cvs") -> dict:
    """
    Generate a persona-voiced cover letter for the given job.

    The letter is factually grounded (canonical content from profile+job), then
    rewritten through the profile's locked persona voice so every profile produces
    a letter that reads distinctly differently while containing the same key facts.

    Args:
        profile: dict with keys name, email, bio, skills, experience, profile_id/id
        job:     dict with keys id, title, company, description
        out_dir: directory to write output file

    Returns dict:
        text           — cover letter string
        txt_path       — path to .txt file
        persona_applied — True if persona humanization ran
    """
    name       = profile.get("name") or "Applicant"
    job_title  = job.get("title") or "the position"
    company    = job.get("company") or "your company"
    bio        = (profile.get("bio") or "")[:300]
    skills     = _parse_skills(profile.get("skills"))[:5]
    profile_id = profile.get("profile_id") or profile.get("id") or ""

    keywords   = extract_keywords(job.get("description") or "")
    top_reqs   = keywords["required"][:3]
    top_tech   = (keywords["tech"])[:4]

    # Canonical letter — factually correct, structured, ATS-safe
    skill_phrase = ", ".join(skills) if skills else "a range of relevant skills"
    req_phrase   = "; ".join(top_reqs[:2]) if top_reqs else "the listed requirements"
    tech_phrase  = ", ".join(top_tech) if top_tech else "relevant technologies"

    canonical = (
        f"Dear Hiring Manager,\n\n"
        f"I am writing to apply for the {job_title} role at {company}. "
        f"{bio + ' ' if bio else ''}"
        f"I bring hands-on experience with {skill_phrase}, and I am confident "
        f"I can meet {req_phrase}.\n\n"
        f"My background with {tech_phrase} aligns directly with your requirements. "
        f"I am motivated by the opportunity to contribute meaningfully to {company} "
        f"and grow within a team that values this work.\n\n"
        f"I would welcome the chance to discuss my application further. "
        f"Thank you for your time and consideration.\n\n"
        f"Sincerely,\n{name}"
    )

    # Humanize through persona
    persona_prompt = _load_persona_for_cv(profile)
    cover_text = canonical
    if persona_prompt and profile_id:
        try:
            import sys
            _root = os.path.normpath(os.path.dirname(__file__))
            if _root not in sys.path:
                sys.path.insert(0, _root)
            from answer_mcp._humanize import humanize
            cover_text = humanize(
                canonical_answer=canonical,
                question=f"Write a cover letter for the {job_title} position at {company}",
                persona_prompt=persona_prompt,
                profile_id=profile_id,
                target_words=220,
            )
        except Exception as e:
            log.warning("Cover letter humanization failed: %s — using canonical", e)

    os.makedirs(out_dir, exist_ok=True)
    safe_p   = re.sub(r"[^a-z0-9_-]", "_", (profile.get("id") or "profile").lower())
    safe_j   = re.sub(r"[^a-z0-9_-]", "_", str(job.get("id") or "job").lower())
    txt_path = os.path.join(out_dir, f"cover_{safe_p}_{safe_j}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(cover_text)

    return {
        "text":            cover_text,
        "txt_path":        txt_path,
        "persona_applied": bool(persona_prompt),
    }
