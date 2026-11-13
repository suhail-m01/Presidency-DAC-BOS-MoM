"""External Member observation report (DAC Meeting - I template).

The External Member of a Departmental Academic Committee is a faculty member of
a **different school** of the university.  Once the meeting has been held and
marked completed, that member fills this report and submits it to the Academic
Office.  The office reviews it (approve or return for revision) and the approved
report is archived as its own document in the central repository, grouped by
school.

The form reproduces the university template:

* **A.** Meeting details (school/department, date, time, venue)
* **B.** Details of the nominated member
* **C.** Agenda-wise observations — *Agenda No · Agenda Item · Response (Yes/No) ·
  Remarks (if any)* — and the agenda rows are **extracted from that DAC meeting
  only**, in the order the agenda was approved.
* **D.** Major observations on non-compliance (including attendance and timely
  commencement) with free-text remarks.
* Signature of the nominated member and of the Dean – Academics.

Nothing here edits the minutes; the report is a separate document.
"""

from __future__ import annotations

import io
import json
import sqlite3
import uuid
from typing import Any

from auth_store import connect, now_iso

RESPONSE_CHOICES = ("yes", "no")
MAX_REMARK = 1200

STATUSES = ("draft", "submitted", "approved", "returned")


def init_reports() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS external_reports (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            member_email TEXT NOT NULL COLLATE NOCASE,
            member_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            payload_json TEXT NOT NULL DEFAULT '{}',
            submitted_at TEXT NOT NULL DEFAULT '',
            decided_at TEXT NOT NULL DEFAULT '',
            reviewer_email TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            document_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reports_workspace ON external_reports(workspace_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reports_member ON external_reports(member_email, status);
        """)
        db.commit()


# ---------------------------------------------------------------------------
# Building / validating the form
# ---------------------------------------------------------------------------

def meeting_agenda_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Agenda rows for this meeting only, taken from its approved MoM sections.

    Falls back to the approved agenda list when the minutes have no sections yet,
    so the member can start reading the agenda as soon as the meeting is over.
    """
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(state.get("momItems") or [], start=1):
        number = int(item.get("agendaNo") or index)
        title = str(item.get("title") or "").strip() or f"Agenda {number}"
        rows.append({"agendaNo": number, "agendaId": item.get("agendaId") or item.get("id") or "",
                     "agendaItem": title, "response": "", "remarks": ""})
    if rows:
        return rows
    meeting = state.get("meeting") or {}
    for index, agenda in enumerate(meeting.get("agendas") or [], start=1):
        rows.append({"agendaNo": index, "agendaId": agenda.get("id") or "",
                     "agendaItem": str(agenda.get("title") or agenda.get("displayTitle") or "").strip()
                     or f"Agenda {index}", "response": "", "remarks": ""})
    return rows


def build_draft(state: dict[str, Any], member: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """A fresh form payload, preserving anything the member already typed."""
    meeting = state.get("meeting") or {}
    # Existing may be DB row with payload key (from get_report) or raw payload — handle both
    if existing and "payload" in existing and isinstance(existing["payload"], dict):
        prev_payload = existing["payload"]
    else:
        prev_payload = existing or {}
    previous = {int(row.get("agendaNo") or 0): row for row in (prev_payload.get("agenda") or [])}
    agenda = []
    for row in meeting_agenda_rows(state):
        prior = previous.get(int(row["agendaNo"]), {})
        agenda.append({**row,
                       "agendaItem": prior.get("agendaItem") or row["agendaItem"],
                       "response": prior.get("response") if prior.get("response") in RESPONSE_CHOICES else "",
                       "remarks": str(prior.get("remarks") or "")[:MAX_REMARK]})
    observations = prev_payload.get("observations") or [
        {"observation": "Members present and attendance as recorded in the minutes.",
         "remarks": ""},
        {"observation": "Timely commencement and conclusion of the meeting.",
         "remarks": ""},
    ]
    return {
        "meeting": {
            "school": meeting.get("school") or "",
            "department": meeting.get("department") or "",
            "date": meeting.get("date") or "",
            "startTime": meeting.get("startTime") or "",
            "venue": meeting.get("venue") or "",
            "meetingNo": meeting.get("meetingNo") or "",
            "academicYear": meeting.get("academicYear") or "",
            "semester": meeting.get("semester") or "",
            "referenceNo": meeting.get("referenceNo") or "",
        },
        "member": {
            "name": member.get("name") or "",
            "designation": member.get("designation") or "",
            "school": member.get("school") or "",
            "department": member.get("department") or "",
            "email": member.get("email") or "",
        },
        "agenda": agenda,
        "observations": observations,
        "declaration": prev_payload.get("declaration") or "",
    }


def validate_payload(payload: dict[str, Any], *, require_complete: bool = False) -> str | None:
    agenda = payload.get("agenda") or []
    if not agenda:
        return "There are no agenda items to report on for this meeting."
    for row in agenda:
        answer = str(row.get("response") or "").strip().lower()
        if answer and answer not in RESPONSE_CHOICES:
            return f"Agenda {row.get('agendaNo')}: choose Yes or No."
        if len(str(row.get("remarks") or "")) > MAX_REMARK:
            return f"Agenda {row.get('agendaNo')}: remarks are too long (limit {MAX_REMARK} characters)."
    if require_complete:
        missing = [str(row.get("agendaNo")) for row in agenda
                   if str(row.get("response") or "").strip().lower() not in RESPONSE_CHOICES]
        if missing:
            return ("Mark Yes or No for every agenda item before submitting — missing agenda: "
                    + ", ".join(missing) + ".")
        said_no = [row for row in agenda if str(row.get("response") or "").lower() == "no"]
        unexplained = [str(row.get("agendaNo")) for row in said_no if not str(row.get("remarks") or "").strip()]
        if unexplained:
            return ("Add a remark explaining every agenda answered 'No' — missing remark for agenda: "
                    + ", ".join(unexplained) + ".")
    return None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {"id": row["id"], "workspaceId": row["workspace_id"], "memberEmail": row["member_email"],
            "memberName": row["member_name"], "status": row["status"], "payload": payload,
            "submittedAt": row["submitted_at"], "decidedAt": row["decided_at"],
            "reviewerEmail": row["reviewer_email"], "comment": row["comment"],
            "documentId": row["document_id"], "createdAt": row["created_at"],
            "updatedAt": row["updated_at"]}


def get_report(workspace_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM external_reports WHERE workspace_id=? AND status != 'superseded' ORDER BY created_at DESC LIMIT 1",
                         (workspace_id,)).fetchone()
    return _row_dict(row) if row else None


def get_report_by_id(report_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM external_reports WHERE id=?", (report_id,)).fetchone()
    return _row_dict(row) if row else None


def save_report(workspace_id: str, member: dict[str, Any], payload: dict[str, Any],
                *, submit: bool = False) -> dict[str, Any]:
    """Create or update the report. ``submit=True`` freezes it for the office."""
    error = validate_payload(payload, require_complete=submit)
    if error:
        raise ValueError(error)
    existing = get_report(workspace_id)
    stamp = now_iso()
    with connect() as db:
        if existing and existing["status"] in {"submitted", "approved"}:
            raise ValueError("This report has already been submitted to the Academic Office.")
        if existing:
            status = "submitted" if submit else "draft"
            db.execute("""UPDATE external_reports SET member_name=?, payload_json=?, status=?,
                          submitted_at=?, updated_at=? WHERE id=?""",
                       (member.get("name") or "", json.dumps(payload, ensure_ascii=False), status,
                        stamp if submit else existing["submittedAt"], stamp, existing["id"]))
            report_id = existing["id"]
        else:
            report_id = uuid.uuid4().hex
            db.execute("""INSERT INTO external_reports(id, workspace_id, member_email, member_name,
                          status, payload_json, submitted_at, created_at, updated_at)
                          VALUES (?,?,?,?,?,?,?,?,?)""",
                       (report_id, workspace_id, str(member.get("email") or "").lower(),
                        member.get("name") or "", "submitted" if submit else "draft",
                        json.dumps(payload, ensure_ascii=False), stamp if submit else "", stamp, stamp))
        db.commit()
    return get_report_by_id(report_id)


def decision_error(report: dict[str, Any] | None, decision: str, comment: str) -> str | None:
    """Why this decision cannot be recorded, or ``None`` when it can.

    Callers validate **before** they render or archive anything: a decision that is
    going to be refused must not leave a file behind in the vault.
    """
    if decision not in {"approved", "returned"}:
        return "Choose approve or return for revision."
    if not report:
        return "Report not found."
    if report["status"] != "submitted":
        return "Only a submitted report can be reviewed."
    if decision == "returned" and not str(comment or "").strip():
        return "Add the reason for returning the report."
    return None


def decide_report(report_id: str, decision: str, comment: str, reviewer: dict[str, Any],
                  *, document_id: str = "") -> dict[str, Any]:
    report = get_report_by_id(report_id)
    error = decision_error(report, decision, comment)
    if error:
        raise ValueError(error)
    with connect() as db:
        db.execute("""UPDATE external_reports SET status=?, decided_at=?, reviewer_email=?, comment=?,
                      document_id=?, updated_at=? WHERE id=?""",
                   (decision, now_iso(), str(reviewer.get("email") or ""), str(comment or "").strip(),
                    document_id, now_iso(), report_id))
        db.commit()
    return get_report_by_id(report_id)


def submitted_report(workspace_id: str) -> dict[str, Any] | None:
    report = get_report(workspace_id)
    return report if report and report["status"] in {"submitted", "approved"} else None


def gate_state(workspace_id: str) -> dict[str, Any]:
    """What the Academic Office needs to know before approving the minutes."""
    report = get_report(workspace_id)
    status = (report or {}).get("status") or "missing"
    return {
        "required": True,
        "status": status,
        "submitted": status in {"submitted", "approved"},
        "approved": status == "approved",
        "reportId": (report or {}).get("id", ""),
        "memberEmail": (report or {}).get("memberEmail", ""),
        "submittedAt": (report or {}).get("submittedAt", ""),
        "comment": (report or {}).get("comment", ""),
        "message": ("External Member report submitted — the minutes can be approved."
                    if status in {"submitted", "approved"}
                    else "The External Member observation report is still awaited; the minutes cannot be approved yet."
                    if status != "returned"
                    else "The observation report was returned to the External Member for revision."),
    }


# ---------------------------------------------------------------------------
# PDF rendering (template layout)
# ---------------------------------------------------------------------------

def render_report_pdf(report: dict[str, Any], issuer: dict[str, Any] | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

    from doc_theme import BODY_SIZE, FOOTNOTE_SIZE, HEADING_SIZE, leading, pdf_font, register_pdf_fonts

    register_pdf_fonts()
    base = getSampleStyleSheet()
    body = BODY_SIZE
    styles = {
        "title": ParagraphStyle("rpt-title", parent=base["Title"], fontName=pdf_font(bold=True),
                                fontSize=13, leading=leading(13), alignment=TA_CENTER, spaceAfter=4),
        "sub": ParagraphStyle("rpt-sub", parent=base["BodyText"], fontName=pdf_font(bold=True),
                              fontSize=HEADING_SIZE, leading=leading(HEADING_SIZE), alignment=TA_CENTER),
        "h": ParagraphStyle("rpt-h", parent=base["BodyText"], fontName=pdf_font(bold=True),
                            fontSize=HEADING_SIZE, leading=leading(HEADING_SIZE), spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("rpt-body", parent=base["BodyText"], fontName=pdf_font(), fontSize=body,
                               leading=leading(body), spaceAfter=3),
        "small": ParagraphStyle("rpt-small", parent=base["BodyText"], fontName=pdf_font(),
                                fontSize=FOOTNOTE_SIZE, leading=leading(FOOTNOTE_SIZE)),
        "cell": ParagraphStyle("rpt-cell", parent=base["BodyText"], fontName=pdf_font(), fontSize=body,
                               leading=leading(body)),
        "cellc": ParagraphStyle("rpt-cellc", parent=base["BodyText"], fontName=pdf_font(), fontSize=body,
                                leading=leading(body), alignment=TA_CENTER),
        "head": ParagraphStyle("rpt-head", parent=base["BodyText"], fontName=pdf_font(bold=True),
                               fontSize=body, leading=leading(body), alignment=TA_CENTER),
        "center": ParagraphStyle("rpt-center", parent=base["BodyText"], fontName=pdf_font(), fontSize=body,
                                 leading=leading(body), alignment=TA_CENTER),
    }
    payload = report.get("payload") or {}
    meeting = payload.get("meeting") or {}
    member = payload.get("member") or {}
    agenda = payload.get("agenda") or []
    observations = payload.get("observations") or []

    def esc(value: Any) -> str:
        return (str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def dmy(value: str) -> str:
        parts = str(value or "").split("-")
        return f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else str(value or "")

    width = A4[0] - 36 * mm
    story = [
        Paragraph("Departmental Academic Committee (DAC)", styles["title"]),
        Paragraph("Observation Report by the Nominated Member from Other School", styles["sub"]),
        Paragraph(f"Academic Year {esc(meeting.get('academicYear'))} ({esc(meeting.get('semester'))} Semester) · "
                  f"DAC Meeting - {esc(meeting.get('meetingNo'))}", styles["center"]),
        Spacer(1, 5 * mm),
        Paragraph("A. Meeting Details", styles["h"]),
    ]
    detail_rows = [
        ["Name of the School / Department", f"{meeting.get('school', '')} — {meeting.get('department', '')}"],
        ["Date of Meeting", dmy(meeting.get("date"))],
        ["Time", meeting.get("startTime", "")],
        ["Venue", meeting.get("venue", "")],
        ["Reference No.", meeting.get("referenceNo", "")],
    ]
    table = Table([[Paragraph(esc(a), styles["cell"]), Paragraph(esc(b), styles["cell"])] for a, b in detail_rows],
                  colWidths=[width * 0.42, width * 0.58], hAlign="LEFT")
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f2f2")),
                               ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.extend([table, Paragraph("B. Details of the Nominated Member", styles["h"])])
    member_rows = [
        ["Name", member.get("name", "")],
        ["Designation", member.get("designation", "")],
        ["School / Department", f"{member.get('school', '')} — {member.get('department', '')}".strip(" —")],
        ["Official Email", member.get("email", "")],
    ]
    member_table = Table([[Paragraph(esc(a), styles["cell"]), Paragraph(esc(b), styles["cell"])] for a, b in member_rows],
                         colWidths=[width * 0.42, width * 0.58], hAlign="LEFT")
    member_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                                      ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                      ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f2f2")),
                                      ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                                      ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.extend([member_table, Paragraph("C. Agenda-Wise Observations", styles["h"])])
    agenda_rows = [[Paragraph("Agenda No.", styles["head"]), Paragraph("Agenda Item", styles["head"]),
                    Paragraph("Response Yes / No", styles["head"]), Paragraph("Remarks (if any)", styles["head"])]]
    for row in agenda:
        answer = str(row.get("response") or "").title() or "—"
        agenda_rows.append([
            Paragraph(esc(row.get("agendaNo")), styles["cellc"]),
            Paragraph(esc(row.get("agendaItem")), styles["cell"]),
            Paragraph(esc(answer), styles["cellc"]),
            Paragraph(esc(row.get("remarks") or "—"), styles["cell"]),
        ])
    agenda_table = Table(agenda_rows, colWidths=[width * 0.11, width * 0.40, width * 0.13, width * 0.36],
                         repeatRows=1, hAlign="LEFT")
    agenda_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                                      ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                      ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                                      ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                      ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.extend([agenda_table, Paragraph("D. Major Observations on Non-compliance (if any)", styles["h"]),
                  Paragraph("Including members' attendance and timely commencement of the meeting.", styles["small"])])
    obs_rows = [[Paragraph("Sl. No.", styles["head"]), Paragraph("Observations", styles["head"]),
                 Paragraph("Remarks (if any)", styles["head"])]]
    for index, row in enumerate(observations, start=1):
        obs_rows.append([Paragraph(str(index), styles["cellc"]),
                         Paragraph(esc(row.get("observation")), styles["cell"]),
                         Paragraph(esc(row.get("remarks") or "—"), styles["cell"])])
    if len(obs_rows) == 1:
        obs_rows.append([Paragraph("—", styles["cellc"]), Paragraph("", styles["cell"]),
                         Paragraph("", styles["cell"])])
    obs_table = Table(obs_rows, colWidths=[width * 0.11, width * 0.47, width * 0.42], repeatRows=1, hAlign="LEFT")
    obs_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                   ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(obs_table)
    if payload.get("declaration"):
        story.append(Paragraph(esc(payload["declaration"]), styles["small"]))
    story.append(Spacer(1, 12 * mm))
    sign = Table([[Paragraph("_____________________________<br/><b>Nominated Member</b>", styles["center"]),
                   Paragraph("_____________________________<br/><b>Dean – Academics</b>", styles["center"])]],
                 colWidths=[width / 2, width / 2])
    sign.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("TOPPADDING", (0, 0), (-1, -1), 8)]))
    story.append(sign)
    if report.get("status") == "approved":
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(
            f"Approved by the Academic Office on {esc((report.get('decidedAt') or '')[:10])} "
            f"({esc((report.get('reviewerEmail') or ''))}). Reference {esc(report.get('id', '')[:12]).upper()}.",
            styles["small"]))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title="DAC External Member Observation Report",
                            author=issuer.get("name") if issuer else "Departmental Academic Committee")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(pdf_font(), FOOTNOTE_SIZE)
        canvas.setFillColor(colors.HexColor("#617084"))
        canvas.drawString(18 * mm, 10 * mm, "Departmental Academic Committee · External Member observation report")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
