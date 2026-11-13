"""Word (.docx) renderer for the final MoM.

The layout mirrors the PDF (``app.py::_build_main_mom_pdf``) word for word, but
is produced as an editable Word document using the requested house style:

* Cambria throughout (the real font - Word renders it natively);
* sub-headings 12 pt, normal text 11 pt;
* 1.15 line spacing everywhere.

Annexures are referenced exactly as in the PDF; the consolidated annexure pages
remain a PDF-only feature, and the Word file ends with the same enclosure note.
"""
from __future__ import annotations

import io
from typing import Callable

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from doc_theme import (
    BODY_SIZE,
    DOCX_FAMILY_NAME,
    FOOTNOTE_SIZE,
    HEADING_SIZE,
    LINE_SPACING,
    TITLE_SIZE,
    apply_docx_style,
    style_docx_run,
)
from committees import document_title as committee_document_title, label as committee_code, name as committee_name
from mom_shared import (
    agenda_document_title,
    annexure_entries,
    annexure_refs,
    document_label,
    format_date_dmy,
    item_has_no_resolution,
    item_resolution,
    meeting_description,
    ordinal,
    reference_number,
    sorted_members,
    without_name_prefix,
)

NO_RESOLUTION_TEXT = "No separate resolution recorded."

#: Common Copy-to list printed on every downloaded meeting document (DAC Circular
#: Template). It is added only at download time — never on the creation screen.
COPY_TO_ITEMS = (
    "Hon’ble Vice Chancellor, PU",
    "Hon’ble Pro Vice Chancellor, PU",
    "Office of the Registrar, PU",
    "Dean-Academics, PU",
)


def _paragraph(document, text: str = "", *, style: str | None = None, size: float = BODY_SIZE,
               bold: bool = False, italic: bool = False, align=None, space_before: float = 0,
               space_after: float | None = None, keep_with_next: bool = False):
    paragraph = document.add_paragraph(style=style)
    if align is not None:
        paragraph.alignment = align
    paragraph.paragraph_format.line_spacing = LINE_SPACING
    paragraph.paragraph_format.space_before = Pt(space_before)
    paragraph.paragraph_format.space_after = Pt(size * LINE_SPACING * 0.5 if space_after is None else space_after)
    paragraph.paragraph_format.keep_with_next = keep_with_next
    if text:
        run = paragraph.add_run(text)
        style_docx_run(run, size=size, bold=bold, italic=italic)
    return paragraph


def _label_paragraph(document, label: str, value: str, *, size: float = BODY_SIZE):
    """A "Label: value" paragraph where the label is bold and the value is normal."""
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.line_spacing = LINE_SPACING
    paragraph.paragraph_format.space_after = Pt(size * LINE_SPACING * 0.5)
    label_run = paragraph.add_run(label)
    style_docx_run(label_run, size=size, bold=True)
    if value:
        value_run = paragraph.add_run(value)
        style_docx_run(value_run, size=size)
    return paragraph


def _style_table(table, *, header: bool = True, widths: list[float] | None = None) -> None:
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    for row_index, row in enumerate(table.rows):
        for column_index, cell in enumerate(row.cells):
            cell.paragraphs[0].paragraph_format.line_spacing = LINE_SPACING
            cell.paragraphs[0].paragraph_format.space_after = Pt(2)
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    style_docx_run(run, size=BODY_SIZE, bold=header and row_index == 0)
            if widths and column_index < len(widths):
                cell.width = Mm(widths[column_index])
    if header:
        for cell in table.rows[0].cells:
            shading = OxmlElement("w:shd")
            shading.set(qn("w:val"), "clear")
            shading.set(qn("w:fill"), "EEEEEE")
            cell._tc.get_or_add_tcPr().append(shading)


def _cell_text(cell, text: str, *, bold: bool = False, align=None, size: float = BODY_SIZE):
    paragraph = cell.paragraphs[0]
    paragraph.text = ""
    if align is not None:
        paragraph.alignment = align
    paragraph.paragraph_format.line_spacing = LINE_SPACING
    run = paragraph.add_run(text)
    style_docx_run(run, size=size, bold=bold)
    return paragraph


def _add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    style_docx_run(run, size=FOOTNOTE_SIZE)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instruction)
    run._r.append(end)


def _configure_page(section, *, footer: bool = True, committee: str = "DAC") -> None:
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Mm(18)
    section.right_margin = Mm(18)
    section.top_margin = Mm(17)
    section.bottom_margin = Mm(18)
    if footer:
        paragraph = section.footer.paragraphs[0]
        paragraph.text = ""
        paragraph.paragraph_format.line_spacing = LINE_SPACING
        left = paragraph.add_run(f"{committee_name(committee)} · Minutes of Meeting")
        style_docx_run(left, size=FOOTNOTE_SIZE)
        paragraph.add_run("\t")
        page_label = paragraph.add_run("Page ")
        style_docx_run(page_label, size=FOOTNOTE_SIZE)
        _add_page_field(paragraph)


def _build_styles(document) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH as ALIGN

    apply_docx_style(document, "Normal", size=BODY_SIZE)
    apply_docx_style(document, "Title", size=TITLE_SIZE, bold=True, align=ALIGN.CENTER,
                     space_before=0, space_after_pt=TITLE_SIZE * LINE_SPACING * 0.6)
    apply_docx_style(document, "Heading 1", size=HEADING_SIZE, bold=True,
                     space_before=HEADING_SIZE * LINE_SPACING * 0.6, keep_with_next=True)
    apply_docx_style(document, "Heading 2", size=HEADING_SIZE, bold=True,
                     space_before=HEADING_SIZE * LINE_SPACING * 0.5, keep_with_next=True)
    for name in ("Heading 1", "Heading 2", "Title"):
        document.styles[name].font.color.rgb = RGBColor(0, 0, 0)
    document.styles["Normal"].paragraph_format.space_after = Pt(round(BODY_SIZE * LINE_SPACING * 0.5, 2))


def _signatories(data: dict) -> list[dict]:
    """The three signatories of the minutes, with the stored signature image if any.

    Called by the exporter, which resolves the images itself; the renderer only lays
    them out. Signatures are drawn from ``momReview`` stamps written by the workflow.
    """
    meeting = data.get("meeting") or {}
    review = data.get("momReview") or {}
    rows = [
        {"role": "Member Secretary", "name": str(meeting.get("secretaryName") or "Member Secretary"),
         "stamp": review.get("secretarySignature")},
        {"role": "Chairperson", "name": str(meeting.get("chairName") or "Chairperson"),
         "stamp": review.get("chairSignature")},
        {"role": "Academic Office", "name": str((review.get("officeSignature") or {}).get("name") or "Academic Office"),
         "stamp": review.get("officeSignature")},
    ]
    resolved = []
    for row in rows:
        stamp = row.pop("stamp") or None
        if row["role"] == "Academic Office" and not stamp:
            continue
        row["signedAt"] = _readable_stamp((stamp or {}).get("signedAt")) if stamp else ""
        row["image"] = (stamp or {}).get("imageBytes") or None
        resolved.append(row)
    return resolved


def _readable_stamp(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        from datetime import datetime
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y, %H:%M")
    except ValueError:
        return text


def build_mom_docx(data: dict, photo_loader: Callable[[str], bytes | None] | None = None) -> bytes:
    """Render the final MoM as a Word document using the Cambria house style."""
    meeting = data.get("meeting") or {}
    all_members = sorted_members(meeting.get("members") or [])
    present_members = [member for member in all_members if member.get("present", True)]
    mom_items = data.get("momItems") or []
    photos = data.get("photos") or []
    actions = data.get("actionItems") or []
    additional_items = data.get("additionalDiscussions") or []
    annexure_labels = {entry["id"]: entry["label"] for entry in annexure_entries(mom_items)}

    document = Document()
    _build_styles(document)
    section = document.sections[0]
    _configure_page(section, committee=meeting.get("committee"))

    # Page 1 - title, school/department, meeting details, attendance.
    _paragraph(document, f"{committee_code(meeting.get('committee'))} Minutes of Meeting", size=TITLE_SIZE, bold=True,
               align=WD_ALIGN_PARAGRAPH.CENTER, space_after=TITLE_SIZE * LINE_SPACING * 0.4)
    _paragraph(document, f"SCHOOL OF {without_name_prefix(meeting.get('school'), 'School of')}".upper(),
               size=BODY_SIZE, align=WD_ALIGN_PARAGRAPH.CENTER)
    department_heading = without_name_prefix(meeting.get("department"), "Department of")
    _paragraph(document, f"DEPARTMENT OF {department_heading}".upper() if department_heading else "",
               size=BODY_SIZE, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=BODY_SIZE * LINE_SPACING * 0.6)

    _stored_ref = str(meeting.get("referenceNo") or "")
    reference = _stored_ref.replace("/Notice-", "/MoM-") if _stored_ref else reference_number(meeting, "mom")
    reference_table = document.add_table(rows=1, cols=2)
    reference_table.autofit = False
    _cell_text(reference_table.rows[0].cells[0], f"Ref No. {reference}")
    _cell_text(reference_table.rows[0].cells[1], f"Date: {format_date_dmy(meeting.get('date'))}",
               align=WD_ALIGN_PARAGRAPH.RIGHT)
    _style_table(reference_table, header=False, widths=[122, 52])
    _paragraph(document, "", size=BODY_SIZE, space_after=0)

    _paragraph(document, f"Minutes of the {ordinal(meeting.get('meetingNo'))} Meeting of {committee_name(meeting.get('committee'))}",
               size=HEADING_SIZE, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
               space_after=HEADING_SIZE * LINE_SPACING * 0.6)
    _paragraph(document, meeting_description(meeting))
    _label_paragraph(document, "Members Present: ", "")

    member_table = document.add_table(rows=1, cols=4)
    for cell, text in zip(member_table.rows[0].cells, ("Sl. No.", "Name and Designation", "Role", "Signature")):
        _cell_text(cell, text, bold=True)
    for row_no, member in enumerate(present_members, start=1):
        row = member_table.add_row()
        name = str(member.get("name") or "")
        designation = str(member.get("designation") or "")
        _cell_text(row.cells[0], f"{row_no:02d}", align=WD_ALIGN_PARAGRAPH.CENTER)
        _cell_text(row.cells[1], f"{name} {designation}".strip())
        _cell_text(row.cells[2], str(member.get("role") or "Member"))
        _cell_text(row.cells[3], "")
    if not present_members:
        row = member_table.add_row()
        for cell, text in zip(row.cells, ("—", "No attendance marked.", "", "")):
            _cell_text(cell, text)
    _style_table(member_table, widths=[17, 70, 40, 35])

    # Page 2 - opening remarks and one block per approved agenda item.
    document.add_page_break()
    _paragraph(document, "The Chairperson welcomed all the members. The member secretary delivered the opening "
                         "remarks and deliberated on the following agenda points.")
    for index, item in enumerate(mom_items, start=1):
        number = int(item.get("agendaNo") or index)
        title = agenda_document_title(item, meeting)
        _paragraph(document, f"Agenda No: {number:02d}  {title}", bold=True, space_before=BODY_SIZE,
                   keep_with_next=True)
        _label_paragraph(document, "Discussion:", "")
        _paragraph(document, str(item.get("discussion") or "").strip() or "", space_after=BODY_SIZE * LINE_SPACING * 0.5)
        resolution = item_resolution(item)
        if item_has_no_resolution(item) and not resolution:
            resolution = NO_RESOLUTION_TEXT
        _label_paragraph(document, "Resolution:", "")
        _paragraph(document, resolution, space_after=BODY_SIZE * LINE_SPACING * 0.5)
        refs = annexure_refs(item, number, annexure_labels)
        _paragraph(document, f"{document_label(item)} " + "; ".join(refs), size=BODY_SIZE,
                   space_after=BODY_SIZE * LINE_SPACING * 0.7)

    _paragraph(document, "Additional discussion points (if any)", style="Heading 2")
    if not additional_items:
        _paragraph(document, "", space_after=0)
    for index, item in enumerate(additional_items, start=1):
        title = str(item.get("title") or "Additional discussion point")
        _paragraph(document, f"Additional discussion {index:02d}: {title}", bold=True, keep_with_next=True)
        _label_paragraph(document, "Discussion:", "")
        _paragraph(document, str(item.get("discussion") or ""), space_after=BODY_SIZE * LINE_SPACING * 0.5)
        _label_paragraph(document, "Resolution:", "")
        _paragraph(document, str(item_resolution(item)), space_after=BODY_SIZE * LINE_SPACING * 0.5)

    # Page 3 - photos and the action table.
    document.add_page_break()
    _paragraph(document, f"Geo-Tagged Photos and Online Platform Screenshots – {committee_name(meeting.get('committee'))}",
               style="Heading 1", space_before=0)
    image_photos = [photo for photo in photos if (photo.get("file") or {}).get("id")]
    embedded = 0
    for photo_index, photo in enumerate(image_photos, start=1):
        file_data = photo.get("file") or {}
        raw = photo_loader(file_data.get("id", "")) if photo_loader else None
        if raw:
            try:
                paragraph = document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.add_run().add_picture(io.BytesIO(raw), width=Mm(105))
                embedded += 1
            except Exception:
                pass
        caption_parts = [str(photo.get("caption") or file_data.get("name") or f"Image {photo_index}")]
        if photo.get("location"):
            caption_parts.append(f"Location: {photo['location']}")
        if photo.get("capturedAt"):
            caption_parts.append(f"Date/time: {photo['capturedAt']}")
        _paragraph(document, f"Image {photo_index}: " + " · ".join(caption_parts),
                   align=WD_ALIGN_PARAGRAPH.CENTER, space_after=BODY_SIZE * LINE_SPACING * 0.8)
    if image_photos and not embedded:
        _paragraph(document, "Images are attached in the consolidated PDF export.", italic=True)

    _paragraph(document, "Action Items:", style="Heading 2")
    action_table = document.add_table(rows=1, cols=4)
    for cell, text in zip(action_table.rows[0].cells,
                          ("Agenda No", "Action(s) to be Taken", "Person(s) Responsible", "Target Date")):
        _cell_text(cell, text, bold=True)
    for action in actions:
        row = action_table.add_row()
        _cell_text(row.cells[0], str(action.get("agendaNo", "")))
        _cell_text(row.cells[1], str(action.get("text", "")))
        _cell_text(row.cells[2], str(action.get("owner", "")))
        _cell_text(row.cells[3], format_date_dmy(action.get("targetDate")) if action.get("targetDate") else "")
    if not actions:
        row = action_table.add_row()
        for cell, text in zip(row.cells, ("—", "", "", "")):
            _cell_text(cell, text)
    _style_table(action_table, widths=[20, 75, 52, 22])

    # Page 4 - closing, signatures and enclosure note.
    document.add_page_break()
    _paragraph(document, "", space_after=0)
    _paragraph(document, "The Chairperson and the Member Secretary thanked all the members for their contributions "
                         "and requested their continued support.")
    for _ in range(4):
        _paragraph(document, "", space_after=0)
    signatories = _signatories(data)
    signature_table = document.add_table(rows=2, cols=len(signatories))
    for index, entry in enumerate(signatories):
        cell = signature_table.rows[0].cells[index]
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.text = ""
        image = entry.get("image") or b""
        if image:
            try:
                paragraph.add_run().add_picture(io.BytesIO(image), width=Mm(42))
            except Exception:
                paragraph.add_run("_____________________________")
        else:
            paragraph.add_run("_____________________________")
        lines = [entry.get("name") or entry["role"], entry["role"]]
        if entry.get("signedAt"):
            lines.append(f"Signed {entry['signedAt']}")
        _cell_text(signature_table.rows[1].cells[index], "\n".join(lines), align=WD_ALIGN_PARAGRAPH.CENTER)
    _style_table(signature_table, header=False, widths=[174 / max(1, len(signatories))] * len(signatories))
    for _ in range(2):
        _paragraph(document, "", space_after=0)
    # Copy to — common to every meeting, printed only on the downloaded document
    # (DAC Circular Template). Never shown on the creation screen.
    _paragraph(document, "Copy to:", bold=True)
    for copy_item in COPY_TO_ITEMS:
        _paragraph(document, f"• {copy_item}")
    for _ in range(1):
        _paragraph(document, "", space_after=0)
    # Only claim enclosures when the record actually carries annexures.
    has_annexures = any((item.get("attachments") or []) for item in (mom_items or []))
    if has_annexures:
        _paragraph(document, "Encl: Annexures")

    core = document.core_properties
    core.title = committee_document_title(meeting.get("committee"), "mom")
    core.subject = " — ".join(part for part in (meeting.get("school", ""), meeting.get("department", "")) if part)
    core.author = committee_name(meeting.get("committee"))
    core.comments = (f"{DOCX_FAMILY_NAME} {BODY_SIZE} pt body, {HEADING_SIZE} pt sub-headings, "
                     f"{LINE_SPACING} line spacing.")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


__all__ = ["build_mom_docx", "NO_RESOLUTION_TEXT", "WD_BREAK", "WD_SECTION"]
