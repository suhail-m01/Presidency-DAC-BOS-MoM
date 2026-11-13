"""The Action Taken Report rendered on the university's own template.

Layout follows ``DAC ATR_Template.pdf`` exactly:

    Action Taken Report
    SCHOOL OF …
    DEPARTMENT OF …
    Ref No. PU/School-Dept/DAC-xx/<Academic Year>/<Even>/ATR-xx          Date: DD.MM.YYYY
    ACTION TAKEN REPORT (ATR)
    For the ___ Meeting of the Departmental Academic Committee (DAC)
    ATR of the Action Items recorded in the Minutes of the ___ Meeting of the
    Departmental Academic Committee (DAC) meeting held on DD.MM.YYYY.

    Agenda No | Action Item(s) (as per previous MoM) | Person(s) Responsible |
    Target Date | Status (Completed/In Progress) | Action Taken / Implementation
    Details / Reasons for Pending

    Note: 1 … 4

    Name and Signature of Member Secretary    Name and Signature of Chairperson

The house style is the one the request form and the minutes already use (Cambria metrics,
11 pt body, 1.15 line spacing, continuous ``Page X of Y`` footer).
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import committees as committee_registry
from doc_theme import BODY_SIZE, pdf_font, leading as themed_leading
from request_form import (
    _escape,
    _official_department,
    _official_school,
    _readable_stamp,
    _signature_cell,
    _styles,
)

try:
    from zoneinfo import ZoneInfo
    COLLEGE_TZ = ZoneInfo("Asia/Kolkata")
except Exception:                                        # pragma: no cover
    COLLEGE_TZ = None

NOTES = (
    "The Agenda No., Action Item(s), Person(s) Responsible and Target Date shall be carried "
    "forward from the Action Items table of the previous meeting minutes.",
    "Action items arising from agenda points that were not approved, deferred or require "
    "further action may also be included, wherever applicable.",
    "Mention the actual action taken with relevant supporting details and annexure/document "
    "references, wherever applicable.",
    "For pending or in progress actions, mention the reasons and proposed timeline for "
    "completion in the Action Taken / Implementation Details column.",
)


def _dmy(value: Any) -> str:
    """A stored date → DD.MM.YYYY, the way the template writes dates."""
    from atr import parse_date
    parsed = parse_date(value)
    return parsed.strftime("%d.%m.%Y") if parsed else (str(value or "") or "__________")


def _ordinal(number: Any) -> str:
    try:
        value = int(str(number).strip().rstrip(".,"))
    except (TypeError, ValueError):
        return str(number or "____")
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def reference_number(report: dict[str, Any]) -> str:
    """``PU/SOE-CIV/DAC-01/2026-27/Odd/ATR-01`` — the template's own pattern."""
    import re
    school = (re.sub(r"[^A-Za-z0-9]", "", str(report.get("schoolCode") or "School")) or "School").upper()
    department = (re.sub(r"[^A-Za-z0-9]", "", str(report.get("departmentCode") or "Dept")) or "Dept").upper()
    committee = str(report.get("committee") or "DAC").upper()
    number = int(report.get("meetingNo") or 1)
    year = str(report.get("academicYear") or "Academic Year")
    semester = str(report.get("semester") or "Semester")
    return f"PU/{school}-{department}/{committee}-{number:02d}/{year}/{semester}/ATR-{number:02d}"


def _codes(report: dict[str, Any], meeting: dict[str, Any]) -> None:
    """The reference uses the school/department codes the meeting carries."""
    report.setdefault("schoolCode", meeting.get("schoolCode") or "")
    report.setdefault("departmentCode", meeting.get("departmentCode") or "")


def build_atr_pdf(report: dict[str, Any], *, meeting: dict[str, Any] | None = None,
                  owner: dict[str, Any] | None = None, chair: dict[str, Any] | None = None,
                  committee_name: str = "") -> bytes:
    """Render the Action Taken Report as PDF bytes."""
    meeting = meeting or {}
    owner = owner or {}
    chair = chair or {}
    styles = _styles()
    styles["tiny"] = ParagraphStyle("ATRtiny", parent=styles["small"], fontSize=BODY_SIZE - 2.5,
                                    leading=themed_leading(BODY_SIZE - 2.5))
    # The template packs six columns onto one A4 width; the head cells need a tighter
    # face so no word breaks in the middle ("Agenda No." must not become "Agend a No.").
    styles["headtight"] = ParagraphStyle("ATRhead", parent=styles["head"], fontSize=BODY_SIZE - 2,
                                         leading=themed_leading(BODY_SIZE - 2))

    committee = str(report.get("committee") or "DAC").upper()
    meta = committee_registry.meta(committee)
    _codes(report, meeting)
    reference = reference_number(report)
    rows = report.get("rows") or []
    held_on = report.get("meetingDate") or meeting.get("date")
    next_meeting = int(report.get("nextMeetingNo") or (int(report.get("meetingNo") or 1) + 1))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"{meta['name']} — Action Taken Report",
        author=committee_registry.name(committee), subject=reference,
    )
    width = doc.width
    story: list[Any] = []

    story.append(Paragraph("Action Taken Report", styles["title"]))
    story.append(Paragraph(_escape(_official_school(meeting) if meeting.get("school")
                                   else f"SCHOOL OF {report.get('school') or ''}".upper()), styles["subtitle"]))
    department_heading = (_official_department(meeting) if meeting.get("department")
                          else (f"DEPARTMENT OF {report.get('department')}".upper()
                                if report.get("department") else ""))
    if department_heading:
        story.append(Paragraph(_escape(department_heading), styles["subtitle"]))
    story.append(Spacer(1, 5 * mm))

    header = Table(
        [[Paragraph(_escape(f"Ref No. {reference}"), styles["cell"]),
          Paragraph(_escape(f"Date: {_dmy(datetime.now(COLLEGE_TZ).date() if COLLEGE_TZ else None)}"),
                    styles["cell"])]],
        colWidths=[width * 0.66, width * 0.34],
    )
    header.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(header)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("ACTION TAKEN REPORT (ATR)", styles["subtitle"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        _escape(f"For the {_ordinal(next_meeting)} Meeting of the {committee_registry.name(committee)} "
                f"({committee})"), styles["body"]))
    story.append(Paragraph(
        _escape(f"ATR of the Action Items recorded in the Minutes of the {_ordinal(report.get('meetingNo'))} "
                f"Meeting of the {committee_registry.name(committee)} ({committee}) meeting held on "
                f"{_dmy(held_on)}."), styles["body"]))
    story.append(Spacer(1, 3 * mm))

    row_head = [Paragraph("Agenda<br/>No.", styles["headtight"]),
                Paragraph("Action Item(s)<br/>(as per previous MoM)", styles["headtight"]),
                Paragraph("Person(s)<br/>Responsible", styles["headtight"]),
                Paragraph("Target<br/>Date", styles["headtight"]),
                Paragraph("Status<br/>(Completed/<br/>In Progress)", styles["headtight"]),
                Paragraph("Action Taken / Implementation Details / "
                          "Reasons for Pending", styles["headtight"])]
    table_rows: list[list[Any]] = [row_head]
    for row in rows:
        table_rows.append([
            Paragraph(_escape(row.get("agendaNo") or "—"), styles["cell"]),
            Paragraph(_escape(row.get("actionItem") or ""), styles["cell"]),
            Paragraph(_escape(row.get("responsible") or ""), styles["cell"]),
            Paragraph(_escape(_dmy(row.get("targetDate")) if row.get("targetDate") else "—"), styles["cell"]),
            Paragraph(_escape(row.get("status") or "—"), styles["cell"]),
            Paragraph(_escape(row.get("details") or ""), styles["cell"]),
        ])
    if len(table_rows) == 1:
        table_rows.append([Paragraph("—", styles["cell"])] + [Paragraph("No action items recorded.", styles["cell"])]
                          + [Paragraph("", styles["cell"]) for _ in range(4)])
    # A blank ruled row keeps the form usable on paper as well.
    table_rows.append([Paragraph("", styles["cell"]) for _ in range(6)])

    # Wide enough that a date (30.11.2026) never breaks across two lines.
    column_widths = [15 * mm, 34 * mm, 24 * mm, 21 * mm, 24 * mm]
    column_widths.append(width - sum(column_widths))
    table = Table(table_rows, colWidths=column_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("VALIGN", (0, -1), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    story.append(Spacer(1, 4 * mm))

    note_story: list[Any] = [Paragraph("<b>Note:</b>", styles["small"])]
    for index, note in enumerate(NOTES, start=1):
        note_story.append(Paragraph(_escape(f"{index}. {note}"), styles["small"]))
    story.append(KeepTogether(note_story))
    story.append(Spacer(1, 8 * mm))

    half = width / 2
    signatures = Table(
        [[_signature_cell(owner.get("name") or report.get("secretaryName") or "Member Secretary",
                          owner.get("designation") or "Member Secretary",
                          report.get("secretarySignature"), styles, half),
          _signature_cell(chair.get("name") or report.get("chairName") or "Chairperson",
                          chair.get("designation") or "Chairperson",
                          report.get("chairSignature"), styles, half)],
         [Paragraph("<b>Name and Signature of Member Secretary</b>", styles["cell"]),
          Paragraph("<b>Name and Signature of Chairperson</b>", styles["cell"])]],
        colWidths=[half, half])
    signatures.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEABOVE", (0, 1), (-1, 1), 0.6, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(KeepTogether(signatures))
    story.append(Spacer(1, 4 * mm))
    footer_note = [f"Report status: {report.get('status') or 'draft'}"]
    if report.get("submittedAt"):
        footer_note.append(f"Submitted {_readable_stamp(report.get('submittedAt'))}")
    if report.get("decidedAt"):
        footer_note.append(f"Chairperson decision {_readable_stamp(report.get('decidedAt'))}")
    story.append(Paragraph(_escape(" · ".join(footer_note)), styles["tiny"]))

    def _footer(pdf_canvas, _doc):
        pdf_canvas.saveState()
        pdf_canvas.setFont(pdf_font(), 8)
        pdf_canvas.setFillColor(colors.HexColor("#444444"))
        pdf_canvas.drawString(16 * mm, 9 * mm, f"{reference} · Action Taken Report")
        pdf_canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {pdf_canvas.getPageNumber()}")
        pdf_canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)

    # "Page X of Y" — counted on a second pass, exactly as the other documents do.
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas as canvas_module

    first_pass = PdfReader(io.BytesIO(buffer.getvalue()))
    total = len(first_pass.pages)
    output = PdfWriter()
    for page_number, page in enumerate(first_pass.pages, start=1):
        overlay_buffer = io.BytesIO()
        overlay = canvas_module.Canvas(overlay_buffer, pagesize=A4)
        overlay.setFont(pdf_font(), 8)
        overlay.setFillColor(colors.white)
        overlay.rect(A4[0] - 58 * mm, 5 * mm, 43 * mm, 8 * mm, stroke=0, fill=1)
        overlay.setFillColor(colors.HexColor("#444444"))
        overlay.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {page_number} of {total}")
        overlay.save()
        overlay_buffer.seek(0)
        output.add_page(page)
        output.pages[-1].merge_page(PdfReader(overlay_buffer).pages[0])
    output.add_metadata({"/Title": f"{meta['name']} — Action Taken Report {reference}",
                         "/Creator": "DAC Minutes Studio"})
    final = io.BytesIO()
    output.write(final)
    return final.getvalue()
