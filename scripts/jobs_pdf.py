#!/usr/bin/env python3
"""
jobs_pdf.py — Batch PDF generator for discovered jobs.
Produces a single discovery report with one row per job.
"""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

_W, _H = A4

_QUALITY_COLOR = {
    True:  colors.HexColor("#27ae60"),   # green — official URL confirmed
    False: colors.HexColor("#e67e22"),   # orange — quality warning
}


def _styles():
    from reportlab.lib.styles import getSampleStyleSheet
    s = getSampleStyleSheet()
    base = s["Normal"]
    cover = ParagraphStyle(
        "CoverTitle", parent=base, fontSize=20, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#2c3e50"), spaceAfter=6,
    )
    sub = ParagraphStyle(
        "Sub", parent=base, fontSize=11, textColor=colors.HexColor("#7f8c8d"),
        spaceAfter=10,
    )
    label = ParagraphStyle(
        "Label", parent=base, fontSize=9, fontName="Helvetica-Bold",
    )
    small = ParagraphStyle(
        "Small", parent=base, fontSize=8, leading=11,
    )
    tiny = ParagraphStyle(
        "Tiny", parent=base, fontSize=7, textColor=colors.HexColor("#555555"), leading=10,
    )
    return cover, sub, label, small, tiny


def generate_batch(jobs: list[dict]) -> bytes:
    """Return a PDF batch report for the given list of job dicts."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )
    cover_style, sub_style, label_style, small_style, tiny_style = _styles()
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    ok_count  = sum(1 for j in jobs if j.get("official_url"))
    bad_count = len(jobs) - ok_count

    story = [
        Paragraph("Job Discovery Report", cover_style),
        Paragraph(
            f"{len(jobs)} job(s) found &bull; {ts} &bull; "
            f"Official URL confirmed: {ok_count} &bull; "
            f"Quality warnings: {bad_count}",
            sub_style,
        ),
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2c3e50")),
        Spacer(1, 8),
    ]

    # Table header
    header = [
        Paragraph("Title", label_style),
        Paragraph("Company", label_style),
        Paragraph("Source (platform)", label_style),
        Paragraph("Official URL", label_style),
        Paragraph("Status", label_style),
    ]
    rows = [header]

    for job in jobs:
        title      = (job.get("title") or "Unknown role")[:55]
        company    = (job.get("company") or "Unknown")[:35]
        src_url    = (job.get("url") or "")[:55]
        off_url    = (job.get("official_url") or "")[:55]
        issue      = job.get("quality_issue") or ""

        has_off = bool(off_url)
        status_color = _QUALITY_COLOR[has_off]
        status_text  = "Confirmed" if has_off else ("No URL" if not issue else issue.replace("_", " ").title())

        status_style = ParagraphStyle(
            f"st_{id(job)}", fontSize=8, fontName="Helvetica-Bold",
            textColor=status_color,
        )
        rows.append([
            Paragraph(title, small_style),
            Paragraph(company, small_style),
            Paragraph(src_url, tiny_style),
            Paragraph(off_url or "—", tiny_style),
            Paragraph(status_text, status_style),
        ])

    tbl = Table(rows, colWidths=[4.5*cm, 3*cm, 3.8*cm, 3.8*cm, 2.4*cm])
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

    # Per-job description blocks for jobs with official description
    for job in jobs:
        off_url  = job.get("official_url")
        off_desc = job.get("official_description") or ""
        if not off_url or not off_desc:
            continue

        title   = job.get("title") or "Unknown role"
        company = job.get("company") or "Unknown"
        snippet = off_desc[:600].replace("\n", " ")

        detail_title = ParagraphStyle(
            "dtitle", fontSize=9, fontName="Helvetica-Bold",
            textColor=colors.HexColor("#2c3e50"), spaceBefore=12, spaceAfter=2,
        )
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"{title} — {company}", detail_title))
        story.append(Paragraph(f"<i>{off_url}</i>", tiny_style))
        story.append(Paragraph(snippet + ("…" if len(off_desc) > 600 else ""), small_style))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Corvus_Careebridge &bull; {ts}",
        ParagraphStyle("footer", fontSize=7, textColor=colors.HexColor("#aaaaaa")),
    ))

    doc.build(story)
    return buf.getvalue()


if __name__ == "__main__":
    # Smoke test — generates a sample PDF
    import json, sys
    from pathlib import Path
    sample = [
        {"id": 1, "title": "Data Labeling Specialist", "company": "WorkSpark Inc",
         "url": "https://workspark.com/jobs/123",
         "official_url": "https://jobs.lever.co/workspark/abc123",
         "official_description": "We are looking for a detail-oriented data labeling specialist...",
         "quality_issue": None},
        {"id": 2, "title": "Remote QA Tester", "company": "Acme Corp",
         "url": "https://linkedin.com/jobs/view/456",
         "official_url": None,
         "official_description": None,
         "quality_issue": "no_official_url"},
    ]
    pdf = generate_batch(sample)
    out = Path("test_jobs_report.pdf")
    out.write_bytes(pdf)
    print(f"Written {len(pdf):,} bytes to {out}")
