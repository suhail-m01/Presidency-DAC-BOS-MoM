"""The DAC meeting request & agenda approval form.

One document, two signatures: the Member Secretary proposes the meeting, agenda
and invitees and signs; the Chairperson (the Dean or a Head of Department of that
school) approves and signs; the Academic Office then records its decision in the
application. The form is only downloadable by the Member Secretary **after** the
Academic Office approves the request.

The document carries the same house style as the Minutes of Meeting (Cambria
metrics, 11 pt body, 12 pt sub-headings, 1.15 line spacing) and its own
continuous ``Page X of Y`` footer.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as PDFImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import committees as committee_registry
from doc_theme import BODY_SIZE, HEADING_SIZE, TITLE_SIZE, leading as themed_leading, pdf_font
from mom_shared import format_date_dmy, meeting_description, sorted_members, without_name_prefix

#: Common Copy-to list printed on every downloaded meeting document (DAC Circular
#: Template). It is added only at download time — never on the creation screen.
COPY_TO_ITEMS = (
    "Hon’ble Vice Chancellor, PU",
    "Hon’ble Pro Vice Chancellor, PU",
    "Office of the Registrar, PU",
    "Dean-Academics, PU",
)

try:                                   # the college works on IST; documents must too
    from zoneinfo import ZoneInfo
    COLLEGE_TZ = ZoneInfo("Asia/Kolkata")
except Exception:                      # pragma: no cover
    COLLEGE_TZ = None

STATUS_LABELS = {
    "draft": "Draft — not submitted",
    "revision": "Returned for revision",
    "pending_chairperson": "Awaiting the Chairperson's signature",
    "pending": "Awaiting the Academic Office",
    "approved": "Approved by the Academic Office",
    "rejected": "Rejected",
}


def _official_school(meeting: dict) -> str:
    return f"SCHOOL OF {without_name_prefix(meeting.get('school'), 'School of')}".strip().upper()


def _official_department(meeting: dict) -> str:
    """The second heading line: the department, or nothing for a school-level DAC."""
    name = without_name_prefix(meeting.get("department"), "Department of")
    return f"DEPARTMENT OF {name}".strip().upper() if name else ""


def _readable_stamp(value: Any) -> str:
    """Any stored timestamp → '25 Oct 2026, 16:51' in the college's own time zone."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is not None and COLLEGE_TZ is not None:
        parsed = parsed.astimezone(COLLEGE_TZ)
    return parsed.strftime("%d %b %Y, %H:%M")


def _escape(value: Any) -> str:
    return (str(value or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("RFtitle", parent=base["Title"], fontName=pdf_font(bold=True), fontSize=TITLE_SIZE,
                                leading=themed_leading(TITLE_SIZE), alignment=TA_CENTER, textColor=colors.black,
                                spaceAfter=4),
        "subtitle": ParagraphStyle("RFsubtitle", parent=base["Normal"], fontName=pdf_font(bold=True),
                                   fontSize=HEADING_SIZE, leading=themed_leading(HEADING_SIZE), alignment=TA_CENTER,
                                   textColor=colors.black, spaceAfter=2),
        "h1": ParagraphStyle("RFh1", parent=base["Heading1"], fontName=pdf_font(bold=True), fontSize=HEADING_SIZE,
                             leading=themed_leading(HEADING_SIZE), textColor=colors.black, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("RFbody", parent=base["BodyText"], fontName=pdf_font(), fontSize=BODY_SIZE,
                               leading=themed_leading(BODY_SIZE), textColor=colors.black, spaceAfter=4),
        "cell": ParagraphStyle("RFcell", parent=base["BodyText"], fontName=pdf_font(), fontSize=BODY_SIZE,
                               leading=themed_leading(BODY_SIZE), textColor=colors.black),
        "cell_bold": ParagraphStyle("RFcellBold", parent=base["BodyText"], fontName=pdf_font(bold=True),
                                    fontSize=BODY_SIZE, leading=themed_leading(BODY_SIZE), textColor=colors.black),
        "head": ParagraphStyle("RFhead", parent=base["BodyText"], fontName=pdf_font(bold=True), fontSize=BODY_SIZE,
                               leading=themed_leading(BODY_SIZE), textColor=colors.black, alignment=TA_CENTER),
        "small": ParagraphStyle("RFsmall", parent=base["BodyText"], fontName=pdf_font(), fontSize=BODY_SIZE - 1,
                                leading=themed_leading(BODY_SIZE - 1), textColor=colors.HexColor("#333333")),
    }


def _signature_cell(name: str, designation: str, signature: dict[str, Any] | None, styles, width: float):
    """One signature block: the image (if any) above the name and designation."""
    rows: list[list[Any]] = []
    path = (signature or {}).get("path")
    if path and Path(path).is_file():
        image = PDFImage(str(path), width=min(width - 12 * mm, 48 * mm), height=15 * mm, kind="proportional")
        rows.append([image])
    else:
        rows.append([Paragraph("<i>Signature awaited</i>", styles["small"])])
    rows.append([Paragraph(_escape(name), styles["cell_bold"])])
    if designation:
        rows.append([Paragraph(_escape(designation), styles["small"])])
    stamp = (signature or {}).get("signedAt") or ""
    if stamp:
        rows.append([Paragraph(f"Signed {_escape(_readable_stamp(stamp))}", styles["small"])])
    block = Table(rows, colWidths=[width])
    block.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEABOVE", (0, 0), (-1, 0), 0, colors.white),
    ]))
    return block


def build_request_form(state: dict[str, Any], *, reference: str, owner: dict[str, Any],
                       chair: dict[str, Any], secretary_signature: dict[str, Any] | None,
                       chair_signature: dict[str, Any] | None,
                       office: dict[str, Any] | None = None) -> bytes:
    """Render the request & agenda approval form as PDF bytes."""
    styles = _styles()
    meeting = state.get("meeting") or {}
    agendas = meeting.get("agendas") or []
    members = sorted_members(meeting.get("members") or [])
    status = str(state.get("status") or "draft")
    chair_approval = state.get("chairApproval") or {}
    office_decision = state.get("officeDecision") or {}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=17 * mm, bottomMargin=20 * mm,
        title=committee_registry.document_title(meeting.get("committee"), "request"),
        author=committee_registry.name(meeting.get("committee")), subject=reference,
    )
    width = doc.width
    story: list[Any] = []

    story.append(Paragraph(_escape(committee_registry.name(meeting.get("committee"))), styles["title"]))
    story.append(Paragraph(
        _escape(committee_registry.meta(meeting.get("committee"))["requestSubtitle"]), styles["subtitle"]))
    story.append(Paragraph(_escape(_official_school(meeting)), styles["subtitle"]))
    department_heading = _official_department(meeting)
    if department_heading:
        story.append(Paragraph(_escape(department_heading), styles["subtitle"]))
    story.append(Spacer(1, 4 * mm))

    header = Table(
        [[Paragraph(f"<b>Ref No.</b> {_escape(reference)}", styles["cell"]),
          Paragraph(f"<b>Status:</b> {_escape(STATUS_LABELS.get(status, status))}", styles["cell"])],
         [Paragraph(f"<b>Submitted:</b> {_escape(str(state.get('submittedAt') or '—'))}", styles["cell"]),
          Paragraph(f"<b>Academic Year:</b> {_escape(str(meeting.get('academicYear') or ''))} · "
                    f"{_escape(str(meeting.get('semester') or ''))} semester", styles["cell"])]],
        colWidths=[width * 0.5, width * 0.5],
    )
    header.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b9c2cc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(header)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("1. Meeting details", styles["h1"]))
    detail_rows = [
        ("Meeting", f"{meeting.get('meetingNo') or '—'} of {meeting.get('academicYear') or '—'}"),
        ("Date", format_date_dmy(meeting.get("date"))),
        ("Time", f"{meeting.get('startTime') or '—'} to {meeting.get('endTime') or '—'}"),
        ("Venue / mode", f"{meeting.get('venue') or '—'} · {meeting.get('mode') or 'Offline'}"),
        ("Conveyed by", f"{owner.get('name') or ''} ({owner.get('designation') or 'Member Secretary'})"),
        ("Chairperson", f"{chair.get('name') or meeting.get('chairName') or ''} "
                        f"({chair.get('designation') or 'Chairperson'})"),
    ]
    detail_table = Table(
        [[Paragraph(f"<b>{label}</b>", styles["cell"]), Paragraph(_escape(value), styles["cell"])]
         for label, value in detail_rows],
        colWidths=[width * 0.28, width * 0.72],
    )
    detail_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b9c2cc")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f5f8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(detail_table)

    story.append(Paragraph("2. Agenda proposed for approval", styles["h1"]))
    agenda_rows = [[Paragraph("Sl. No.", styles["head"]), Paragraph("Agenda item", styles["head"])]]
    for index, agenda in enumerate(agendas, start=1):
        agenda_rows.append([Paragraph(f"{index:02d}", styles["cell"]),
                            Paragraph(_escape(agenda.get("title") or ""), styles["cell"])])
    if len(agenda_rows) == 1:
        agenda_rows.append([Paragraph("—", styles["cell"]), Paragraph("No agenda selected.", styles["cell"])])
    agenda_table = Table(agenda_rows, colWidths=[20 * mm, width - 20 * mm], repeatRows=1)
    agenda_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(agenda_table)

    # Proposed members + signatures start on the next page (screen and PDF alike).
    story.append(PageBreak())
    story.append(Paragraph("3. Members proposed for the meeting", styles["h1"]))
    member_rows = [[Paragraph("Sl. No.", styles["head"]), Paragraph("Name and designation", styles["head"]),
                    Paragraph("Role", styles["head"]), Paragraph("Email", styles["head"])]]
    for index, member in enumerate(members, start=1):
        member_rows.append([
            Paragraph(f"{index:02d}", styles["cell"]),
            Paragraph(_escape(f"{member.get('name') or ''}, {member.get('designation') or ''}".strip(", ")), styles["cell"]),
            Paragraph(_escape(member.get("role") or "Member"), styles["cell"]),
            Paragraph(_escape(member.get("email") or ""), styles["cell"]),
        ])
    if len(member_rows) == 1:
        member_rows.append([Paragraph("—", styles["cell"]), Paragraph("No members proposed.", styles["cell"]),
                            Paragraph("", styles["cell"]), Paragraph("", styles["cell"])])
    member_table = Table(member_rows, colWidths=[18 * mm, width * 0.42, width * 0.2, width * 0.2], repeatRows=1)
    member_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(member_table)

    story.append(Paragraph("4. Declaration and signatures", styles["h1"]))
    decl = (f"The Member Secretary confirms that the agenda, the members and the meeting arrangements above have "
            f"been prepared for the {committee_registry.name(meeting.get('committee'))}. The Chairperson approves "
            "the agenda and the members for the meeting.")
    story.append(Paragraph(_escape(decl), styles["body"]))
    story.append(Spacer(1, 3 * mm))

    # Academic Office removed for both DAC and BOS per user request 2026-11-10 — request form carries only MS + Chairperson
    half = width / 2
    columns = [
        _signature_cell(owner.get("name") or "Member Secretary", owner.get("designation") or "Member Secretary",
                        secretary_signature, styles, half),
        _signature_cell(chair.get("name") or meeting.get("chairName") or "Chairperson",
                        chair.get("designation") or "Chairperson", chair_signature, styles, half),
    ]
    labels = [Paragraph("<b>Member Secretary</b>", styles["cell"]),
              Paragraph("<b>Chairperson</b>", styles["cell"])]
    widths = [half, half]
    signatures = Table([columns, labels], colWidths=widths)
    signatures.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEABOVE", (0, 1), (-1, 1), 0.6, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(KeepTogether(signatures))
    story.append(Spacer(1, 3 * mm))

    # Copy to — common to every meeting, printed only on the downloaded form
    # (DAC Circular Template). Never shown on the creation screen.
    story.append(Paragraph("Copy to:", styles["h1"]))
    for copy_item in COPY_TO_ITEMS:
        story.append(Paragraph("• " + _escape(copy_item), styles["body"]))
    story.append(Spacer(1, 3 * mm))

    trail: list[str] = []
    if chair_approval.get("decision") == "approved":
        trail.append(f"Chairperson approved on {_readable_stamp(chair_approval.get('decidedAt'))}")
    if office_decision.get("decision") == "approved":
        trail.append(f"Academic Office approved on {_readable_stamp(office_decision.get('decidedAt'))}"
                     + (f" by {office_decision.get('name')}" if office_decision.get("name") else ""))
    if office_decision.get("decision") == "revision":
        trail.append(f"Academic Office returned the request for revision: {office_decision.get('comment') or ''}")
    story.append(Paragraph("5. Approval trail", styles["h1"]))
    if trail:
        for line in trail:
            story.append(Paragraph("• " + _escape(line), styles["body"]))
    else:
        story.append(Paragraph("• No approval recorded yet.", styles["body"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        _escape(f"System note · form generated on {datetime.now(COLLEGE_TZ).strftime('%d %b %Y, %H:%M') if COLLEGE_TZ else datetime.now().strftime('%d %b %Y, %H:%M')} "
                f"from the {committee_registry.name(meeting.get('committee'))} workspace. {meeting_description(meeting)}"),
        styles["small"]))

    def _footer(pdf_canvas, _doc):
        pdf_canvas.saveState()
        pdf_canvas.setFont(pdf_font(), 8)
        pdf_canvas.setFillColor(colors.HexColor("#444444"))
        pdf_canvas.drawString(18 * mm, 10 * mm,
                              f"{reference} · {committee_registry.normalise(meeting.get('committee'))} request form")
        pdf_canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {pdf_canvas.getPageNumber()}")
        pdf_canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)

    # Stamp "Page X of Y": the page count is only known after the build, so the
    # form is rendered twice — once to count, once to write the total.
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
        overlay.rect(A4[0] - 60 * mm, 6 * mm, 45 * mm, 8 * mm, stroke=0, fill=1)
        overlay.setFillColor(colors.HexColor("#444444"))
        overlay.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {page_number} of {total}")
        overlay.save()
        overlay_buffer.seek(0)
        # pypdf 7+ requires page to be attached to writer before merge
        output.add_page(page)
        output.pages[-1].merge_page(PdfReader(overlay_buffer).pages[0])
    result = io.BytesIO()
    output.write(result)
    return result.getvalue()
