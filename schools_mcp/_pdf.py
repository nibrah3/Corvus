"""Generate PDF reports for confirmed schools — individual and batch."""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from ._analyzer import CRITERIA, CRITERIA_LABELS

_W, _H = A4

_SCORE_COLORS = {
    6: colors.HexColor("#27ae60"),   # green  — all 6
    5: colors.HexColor("#2ecc71"),   # light green
    4: colors.HexColor("#2980b9"),   # blue
    3: colors.HexColor("#e67e22"),   # orange
    2: colors.HexColor("#e67e22"),
    1: colors.HexColor("#e74c3c"),   # red
    0: colors.HexColor("#95a5a6"),   # grey
}

_TICK  = "✓"
_CROSS = "✗"


def _styles():
    s = getSampleStyleSheet()
    base = s["Normal"]
    title = ParagraphStyle(
        "SchoolTitle", parent=base,
        fontSize=18, fontName="Helvetica-Bold",
        spaceAfter=4, textColor=colors.HexColor("#2c3e50"),
    )
    subtitle = ParagraphStyle(
        "SchoolSub", parent=base,
        fontSize=11, fontName="Helvetica",
        textColor=colors.HexColor("#7f8c8d"), spaceAfter=10,
    )
    body = ParagraphStyle(
        "Body", parent=base,
        fontSize=9, leading=13,
    )
    label = ParagraphStyle(
        "Label", parent=base,
        fontSize=9, fontName="Helvetica-Bold",
    )
    small = ParagraphStyle(
        "Small", parent=base,
        fontSize=8, textColor=colors.HexColor("#555555"),
    )
    return title, subtitle, body, label, small


def generate(school: dict) -> bytes:
    """Return PDF bytes for a single confirmed school."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )
    title_style, sub_style, body_style, label_style, small_style = _styles()
    story = []

    name     = school.get("name", "Unknown School")
    score    = school.get("criteria_score", 0)
    stype    = school.get("type", "University / College")
    city     = school.get("city", "")
    state    = school.get("state", "")
    url      = school.get("url", "")
    enroll   = school.get("enrollment_url", "")
    evidence = school.get("evidence", {})

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph(name, title_style))
    location = ", ".join(filter(None, [stype, city, state]))
    story.append(Paragraph(location, sub_style))

    # Score badge
    badge_color = _SCORE_COLORS.get(score, _SCORE_COLORS[0])
    badge_text  = f"Score: {score}/6 criteria met"
    badge = Table(
        [[Paragraph(badge_text, ParagraphStyle(
            "badge", fontSize=12, fontName="Helvetica-Bold",
            textColor=colors.white,
        ))]],
        colWidths=[12*cm],
    )
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), badge_color),
        ("ROUNDEDCORNERS", [6]),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(badge)
    story.append(Spacer(1, 12))

    # ── Criteria table ────────────────────────────────────────────────────────
    story.append(Paragraph("Criteria Assessment", label_style))
    story.append(Spacer(1, 4))

    header_row = [
        Paragraph("Criterion", label_style),
        Paragraph("Met", label_style),
        Paragraph("Evidence", label_style),
    ]
    rows = [header_row]

    for c in CRITERIA:
        met     = school.get(c, False)
        ev_text = ""
        if isinstance(evidence, dict):
            ev_text = evidence.get(c, "not stated")
        elif isinstance(evidence, str):
            ev_text = evidence

        tick_color = colors.HexColor("#27ae60") if met else colors.HexColor("#e74c3c")
        tick_style = ParagraphStyle(
            "tick", fontSize=11, fontName="Helvetica-Bold",
            textColor=tick_color, alignment=1,
        )
        rows.append([
            Paragraph(CRITERIA_LABELS[c], body_style),
            Paragraph(_TICK if met else _CROSS, tick_style),
            Paragraph(str(ev_text)[:300], small_style),
        ])

    tbl = Table(rows, colWidths=[5*cm, 1.5*cm, 8.5*cm])
    tbl.setStyle(TableStyle([
        # Header
        ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 9),
        # Grid
        ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 14))

    # ── URLs ──────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Links", label_style))
    if url:
        story.append(Paragraph(f"Website: <a href='{url}'>{url}</a>", body_style))
    if enroll and enroll != url:
        story.append(Paragraph(f"Enrollment: <a href='{enroll}'>{enroll}</a>", body_style))
    story.append(Spacer(1, 10))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 4))
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(
        f"Discovered by Corvus_Careebridge · {ts}",
        ParagraphStyle("footer", fontSize=7, textColor=colors.HexColor("#aaaaaa")),
    ))

    doc.build(story)
    return buf.getvalue()


def generate_batch(schools: list[dict]) -> bytes:
    """Return a single PDF summarising all schools in one discovery run."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )
    _, sub_style, body_style, label_style, small_style = _styles()
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    cover_title = ParagraphStyle(
        "CoverTitle", fontSize=20, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#2c3e50"), spaceAfter=6,
    )
    story = [
        Paragraph("School Discovery Report", cover_title),
        Paragraph(f"{len(schools)} school(s) found &bull; {ts}", sub_style),
        Spacer(1, 10),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2c3e50")),
        Spacer(1, 10),
    ]

    # Summary table
    header = [
        Paragraph("School", label_style),
        Paragraph("Location", label_style),
        Paragraph("Score", label_style),
        Paragraph("Criteria Met", label_style),
        Paragraph("Official URL", label_style),
    ]
    rows = [header]
    for s in schools:
        name     = s.get("name", "Unknown")[:50]
        city     = s.get("city", "")
        state    = s.get("state", "")
        loc      = ", ".join(p for p in [city, state] if p) or "—"
        score    = s.get("criteria_score", 0)
        met      = s.get("filters") or []
        criteria = ", ".join(CRITERIA_LABELS.get(f, f) for f in met) or "none"
        url      = s.get("url", "")[:60]

        badge_color = _SCORE_COLORS.get(score, _SCORE_COLORS[0])
        score_style = ParagraphStyle(
            f"sc{score}", fontSize=8, fontName="Helvetica-Bold",
            textColor=badge_color, alignment=1,
        )
        rows.append([
            Paragraph(name, small_style),
            Paragraph(loc, small_style),
            Paragraph(f"{score}/6", score_style),
            Paragraph(criteria, small_style),
            Paragraph(url, small_style),
        ])

    tbl = Table(rows, colWidths=[4.5*cm, 2.5*cm, 1.2*cm, 5*cm, 4.3*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  colors.HexColor("#2c3e50")),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0),  8),
        ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ("LEFTPADDING",    (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Corvus_Careebridge · {ts}",
        ParagraphStyle("footer", fontSize=7, textColor=colors.HexColor("#aaaaaa")),
    ))

    doc.build(story)
    return buf.getvalue()
