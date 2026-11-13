"""Action Taken Report (ATR) for a completed DAC / BOS meeting.

Every action item recorded in the Minutes of Meeting carries a target date. Once the
minutes are approved by the Academic Office, those action items become the agenda of an
**Action Taken Report** that the Member Secretary must fill before the next meeting of the
same committee.

Three rules govern *when* the report may be filled, and they come from the university's
practice rather than from this application:

1. **It opens only after the latest target date has passed.** If the action items are due
   on 12-11-2026, 20-11-2026 and 30-11-2026, the report opens on 01-12-2026 — reporting on
   actions before their deadline would be meaningless.
2. **It is due one week before the next meeting** of that committee. The report is tabled
   at that meeting (DAC agenda #2 is the review of the Action Taken Report).
3. **Reminders start three weeks before the next meeting**, and keep appearing until the
   report is submitted.

The meeting dates are not invented here: they are **issued by the Academic Office before
the academic year begins** and stored in ``meeting_calendar``. Until a date is issued the
report still opens on rule 1, but it has no deadline and the interface says so, so nobody
is asked to meet a date that has not been published.

The report belongs to the meeting whose actions it reports on (its workspace), so it stays
in the Member Secretary's own record and can be carried into later meetings.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from auth_store import connect, now_iso

try:                                   # the college works on IST; so do the deadlines
    from zoneinfo import ZoneInfo
    COLLEGE_TZ = ZoneInfo("Asia/Kolkata")
except Exception:                      # pragma: no cover
    COLLEGE_TZ = None

#: How the Member Secretary describes an action when the report is filled.
STATUS_CHOICES = ("Completed", "In Progress", "Pending")

#: Stored workflow states. ``draft`` covers "not started" and "being filled".
REPORT_STATUSES = ("draft", "submitted", "approved", "returned")

#: Derived, never stored: what the interface shows.
AVAILABILITY = {
    "not_required": "No action items — no report required",
    "waiting": "Not open yet — opens after the latest target date",
    "open": "Open — fill before the next meeting",
    "overdue": "Overdue — the next meeting is less than a week away",
    "returned": "Returned by the Chairperson — correct and resubmit",
    "submitted": "With the Chairperson for signature",
    "approved": "Approved and signed",
}

#: Days before the next meeting by which the report must be filled.
DUE_DAYS_BEFORE_MEETING = 7
#: Days before the next meeting at which the reminders start.
REMINDER_DAYS_BEFORE_MEETING = 21

MAX_DETAILS = 2000
MAX_ACTION_TEXT = 600


def init_atr() -> None:
    """Create the two tables this feature owns. Safe to call on every boot."""
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS meeting_calendar (
            id TEXT PRIMARY KEY,
            academic_year TEXT NOT NULL,
            semester TEXT NOT NULL DEFAULT '',
            committee TEXT NOT NULL DEFAULT 'DAC',
            meeting_no INTEGER NOT NULL,
            date TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            issued_by TEXT NOT NULL DEFAULT '',
            issued_at TEXT NOT NULL DEFAULT '',
            UNIQUE (academic_year, semester, committee, meeting_no)
        );
        CREATE INDEX IF NOT EXISTS idx_calendar_year ON meeting_calendar(academic_year, committee, meeting_no);

        CREATE TABLE IF NOT EXISTS action_taken_reports (
            workspace_id TEXT PRIMARY KEY,
            committee TEXT NOT NULL DEFAULT 'DAC',
            school TEXT NOT NULL DEFAULT '',
            department TEXT NOT NULL DEFAULT '',
            academic_year TEXT NOT NULL DEFAULT '',
            semester TEXT NOT NULL DEFAULT '',
            meeting_no INTEGER NOT NULL DEFAULT 1,
            meeting_date TEXT NOT NULL DEFAULT '',
            owner_email TEXT NOT NULL DEFAULT '' COLLATE NOCASE,
            chair_email TEXT NOT NULL DEFAULT '' COLLATE NOCASE,
            chair_name TEXT NOT NULL DEFAULT '',
            activation_date TEXT NOT NULL DEFAULT '',
            next_meeting_no INTEGER NOT NULL DEFAULT 0,
            next_meeting_date TEXT NOT NULL DEFAULT '',
            due_by TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            rows_json TEXT NOT NULL DEFAULT '[]',
            secretary_signature_json TEXT NOT NULL DEFAULT '{}',
            chair_signature_json TEXT NOT NULL DEFAULT '{}',
            submitted_at TEXT NOT NULL DEFAULT '',
            decided_at TEXT NOT NULL DEFAULT '',
            chair_comment TEXT NOT NULL DEFAULT '',
            document_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_atr_owner ON action_taken_reports(owner_email, status);
        CREATE INDEX IF NOT EXISTS idx_atr_chair ON action_taken_reports(chair_email, status);
        """)
        # The office issues a From–To date range per meeting, not a single date.
        for column in ("from_date", "to_date"):
            try:
                db.execute(f"ALTER TABLE meeting_calendar ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # column already present
        db.commit()


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def today() -> date:
    """Today in the college's own time zone."""
    return datetime.now(COLLEGE_TZ).date() if COLLEGE_TZ else date.today()


def parse_date(value: Any) -> date | None:
    """Read any date this application stores or a person types.

    Accepts ISO (2026-11-30), day-first with dashes (30-11-2026) and day-first with
    dots (30.11.2026) — the three forms that appear in the registry, the interface and
    the university's own templates.
    """
    text = str(value or "").strip()
    if not text:
        return None
    text = text[:10]
    for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value).strip()).date()
    except ValueError:
        return None


def _iso(value: date | None) -> str:
    return value.isoformat() if value else ""


def meeting_number(value: Any, fallback: int = 1) -> int:
    """``"2"``, ``"2nd"`` and ``2`` all read as 2."""
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return int(digits) if digits else fallback


def latest_target_date(action_items: Iterable[dict[str, Any]]) -> date | None:
    """The **latest** target date among the action items — the day the report opens after.

    Action items without a target date cannot drive the window; they are still reported,
    they simply do not hold the report back.
    """
    dates = [parse_date((item or {}).get("targetDate")) for item in action_items or []]
    found = [value for value in dates if value]
    return max(found) if found else None


# ---------------------------------------------------------------------------
# The issued meeting calendar (Academic Office)
# ---------------------------------------------------------------------------

def _calendar_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "academicYear": row["academic_year"], "semester": row["semester"],
        "committee": row["committee"], "meetingNo": int(row["meeting_no"]),
        "date": row["date"], "note": row["note"],
        "fromDate": row["from_date"] if "from_date" in row.keys() else row["date"],
        "toDate": row["to_date"] if "to_date" in row.keys() else "",
        "issuedBy": row["issued_by"], "issuedAt": row["issued_at"],
    }


def list_calendar(*, academic_year: str = "", committee: str = "") -> list[dict[str, Any]]:
    clauses, params = [], []
    if academic_year:
        clauses.append("academic_year = ?")
        params.append(academic_year)
    if committee:
        clauses.append("committee = ?")
        params.append(committee.upper())
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect() as db:
        rows = db.execute(
            f"SELECT * FROM meeting_calendar{where} ORDER BY academic_year DESC, committee, meeting_no",  # nosec B608
            tuple(params)).fetchall()
    return [_calendar_dict(row) for row in rows]


def issue_calendar(entries: Iterable[dict[str, Any]], *, issued_by: str) -> dict[str, Any]:
    """Record the dates the Academic Office has issued for an academic year.

    One row per (academic year, semester, committee, meeting number). A blank date clears
    that row — the office may withdraw a date it has not finally decided.
    """
    stamp = now_iso()
    written, cleared = 0, 0
    with connect() as db:
        for entry in entries or []:
            year = str(entry.get("academicYear") or "").strip()
            committee = str(entry.get("committee") or "").strip().upper()
            semester = str(entry.get("semester") or "").strip()
            try:
                meeting_no = int(str(entry.get("meetingNo") or 0))
            except ValueError:
                meeting_no = 0
            if not year or committee not in {"DAC", "BOS"} or meeting_no <= 0:
                continue
            raw_from = str(entry.get("fromDate") or entry.get("date") or "").strip()
            raw_to = str(entry.get("toDate") or "").strip()
            if not raw_from:
                db.execute("""DELETE FROM meeting_calendar
                              WHERE academic_year=? AND semester=? AND committee=? AND meeting_no=?""",
                           (year, semester, committee, meeting_no))
                cleared += 1
                continue
            parsed = parse_date(raw_from)
            if not parsed:
                continue
            parsed_to = parse_date(raw_to) if raw_to else None
            db.execute("""INSERT INTO meeting_calendar(id, academic_year, semester, committee,
                          meeting_no, date, note, issued_by, issued_at, from_date, to_date)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(academic_year, semester, committee, meeting_no)
                          DO UPDATE SET date=excluded.date, note=excluded.note,
                                        issued_by=excluded.issued_by, issued_at=excluded.issued_at,
                                        from_date=excluded.from_date, to_date=excluded.to_date""",
                       (uuid.uuid4().hex, year, semester, committee, meeting_no, parsed.isoformat(),
                        str(entry.get("note") or "").strip(), issued_by, stamp,
                        parsed.isoformat(), parsed_to.isoformat() if parsed_to else ""))
            written += 1
        db.commit()
    return {"written": written, "cleared": cleared}


def next_meeting(committee: str, after: date | None, *, academic_year: str = "") -> dict[str, Any] | None:
    """The next issued meeting of this committee strictly after ``after``."""
    if not after:
        return None
    clauses = ["committee = ?", "date != ''", "date > ?"]
    params: list[Any] = [str(committee or "DAC").upper(), after.isoformat()]
    if academic_year:
        clauses.append("academic_year = ?")
        params.append(academic_year)
    with connect() as db:
        row = db.execute(
            f"SELECT * FROM meeting_calendar WHERE {' AND '.join(clauses)} ORDER BY date ASC LIMIT 1",  # nosec B608
            tuple(params)).fetchone()
    return _calendar_dict(row) if row else None


# ---------------------------------------------------------------------------
# The report itself
# ---------------------------------------------------------------------------

def _action_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per action item recorded in the minutes, in the order they were written."""
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(state.get("actionItems") or [], start=1):
        target = parse_date(item.get("targetDate"))
        rows.append({
            "sl": index,
            "agendaNo": str(item.get("agendaNo") or "").strip(),
            "actionItem": str(item.get("text") or "").strip(),
            "responsible": str(item.get("owner") or "").strip(),
            "targetDate": _iso(target) or str(item.get("targetDate") or "").strip(),
            "status": "",
            "details": "",
        })
    return rows


def build_rows(state: dict[str, Any], previous: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Rows for a new report, matching any earlier text the same meeting already had."""
    rows = _action_rows(state)
    saved = {str(row.get("sl")): row for row in (previous or {}).get("rows") or []}
    for row in rows:
        earlier = saved.get(str(row["sl"]))
        if earlier:
            row["status"] = str(earlier.get("status") or "")
            row["details"] = str(earlier.get("details") or "")
    return rows


def _report_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        rows = json.loads(row["rows_json"] or "[]")
    except json.JSONDecodeError:
        rows = []
    try:
        secretary = json.loads(row["secretary_signature_json"] or "{}")
    except json.JSONDecodeError:
        secretary = {}
    try:
        chair = json.loads(row["chair_signature_json"] or "{}")
    except json.JSONDecodeError:
        chair = {}
    return {
        "workspaceId": row["workspace_id"],
        "committee": row["committee"],
        "school": row["school"], "department": row["department"],
        "academicYear": row["academic_year"], "semester": row["semester"],
        "meetingNo": int(row["meeting_no"]), "meetingDate": row["meeting_date"],
        "ownerEmail": row["owner_email"], "chairEmail": row["chair_email"], "chairName": row["chair_name"],
        "activationDate": row["activation_date"],
        "nextMeetingNo": int(row["next_meeting_no"] or 0),
        "nextMeetingDate": row["next_meeting_date"],
        "dueBy": row["due_by"],
        "status": row["status"], "rows": rows,
        "secretarySignature": secretary, "chairSignature": chair,
        "submittedAt": row["submitted_at"], "decidedAt": row["decided_at"],
        "chairComment": row["chair_comment"], "documentId": row["document_id"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def get_report(workspace_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM action_taken_reports WHERE workspace_id=?",
                         (workspace_id,)).fetchone()
    return _report_dict(row) if row else None


def _minutes_approved(state: dict[str, Any]) -> bool:
    return str((state.get("momReview") or {}).get("status") or "") == "approved"


def ensure_report(workspace: dict[str, Any]) -> dict[str, Any] | None:
    """Create (or refresh the window of) the report for one approved meeting.

    Nothing is created while the minutes are still in review: a report on actions that
    have not been approved yet would be reporting on a document that can still change.
    """
    state = workspace.get("payload") or {}
    if not _minutes_approved(state):
        return None
    workspace_id = str(workspace.get("workspaceId") or state.get("workspaceId") or "")
    if not workspace_id:
        return None
    meeting = state.get("meeting") or {}
    committee = str(state.get("committee") or meeting.get("committee") or "DAC").upper()
    meeting_date = parse_date(meeting.get("date"))
    action_items = state.get("actionItems") or []
    latest = latest_target_date(action_items)
    approval = (state.get("momReview") or {}).get("officeDecisionAt") or ""
    approved_on = parse_date(approval) or meeting_date

    # Rule 1: opens the day after the latest target date. With no target date anywhere,
    # there is nothing to wait for, so it opens as soon as the minutes are approved.
    activation = (latest + timedelta(days=1)) if latest else (approved_on or today())

    # Rule 2 & 3 read the dates the Academic Office issued for the year.
    upcoming = next_meeting(committee, meeting_date or approved_on,
                            academic_year=str(meeting.get("academicYear") or ""))
    next_date = parse_date((upcoming or {}).get("date"))
    due_by = (next_date - timedelta(days=DUE_DAYS_BEFORE_MEETING)) if next_date else None
    if due_by and due_by < activation:
        # The published date leaves less than a week after the report can open; the report
        # cannot be due before it exists, so it is due from the day it opens.
        due_by = activation

    existing = get_report(workspace_id)
    stamp = now_iso()
    if existing:
        # The window is recomputed on every read: the Academic Office may issue or move a
        # meeting date after the report was created.
        changed = (existing["activationDate"] != _iso(activation)
                   or existing["nextMeetingDate"] != _iso(next_date)
                   or existing["dueBy"] != _iso(due_by)
                   or existing["nextMeetingNo"] != int((upcoming or {}).get("meetingNo") or 0))
        if changed:
            with connect() as db:
                db.execute("""UPDATE action_taken_reports
                              SET activation_date=?, next_meeting_no=?, next_meeting_date=?,
                                  due_by=?, updated_at=? WHERE workspace_id=?""",
                           (_iso(activation), int((upcoming or {}).get("meetingNo") or 0),
                            _iso(next_date), _iso(due_by), stamp, workspace_id))
                db.commit()
            existing = get_report(workspace_id)
        return existing

    rows = build_rows(state)
    record = {
        "workspace_id": workspace_id, "committee": committee,
        "school": str(meeting.get("school") or ""), "department": str(meeting.get("department") or ""),
        "academic_year": str(meeting.get("academicYear") or ""), "semester": str(meeting.get("semester") or ""),
        "meeting_no": meeting_number(meeting.get("meetingNo")),
        "meeting_date": _iso(meeting_date),
        "owner_email": str((workspace.get("ownerEmail") or "")).strip().lower(),
        "chair_email": str(meeting.get("chairEmail") or "").strip().lower(),
        "chair_name": str(meeting.get("chairName") or "").strip(),
        "activation_date": _iso(activation),
        "next_meeting_no": int((upcoming or {}).get("meetingNo") or 0),
        "next_meeting_date": _iso(next_date),
        "due_by": _iso(due_by),
        "status": "draft",
        "rows_json": json.dumps(rows, ensure_ascii=False),
        "created_at": stamp, "updated_at": stamp,
    }
    if not record["owner_email"]:
        from auth_store import get_user_by_id
        owner = get_user_by_id(str(workspace.get("ownerId") or ""))
        record["owner_email"] = str((owner or {}).get("email") or "").strip().lower()
    with connect() as db:
        db.execute("""INSERT OR IGNORE INTO action_taken_reports(
                      workspace_id, committee, school, department, academic_year, semester,
                      meeting_no, meeting_date, owner_email, chair_email, chair_name,
                      activation_date, next_meeting_no, next_meeting_date, due_by, status,
                      rows_json, created_at, updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (record["workspace_id"], record["committee"], record["school"], record["department"],
                    record["academic_year"], record["semester"], record["meeting_no"],
                    record["meeting_date"], record["owner_email"], record["chair_email"],
                    record["chair_name"], record["activation_date"], record["next_meeting_no"],
                    record["next_meeting_date"], record["due_by"], record["status"],
                    record["rows_json"], record["created_at"], record["updated_at"]))
        db.commit()
    return get_report(workspace_id)


def availability(report: dict[str, Any], *, on: date | None = None) -> str:
    """What the report is, right now — the single source of truth for the interface."""
    if not report:
        return "not_required"
    if not report.get("rows"):
        return "not_required"
    status = str(report.get("status") or "draft")
    if status == "approved":
        return "approved"
    if status == "submitted":
        return "submitted"
    if status == "returned":
        return "returned"
    current = on or today()
    activation = parse_date(report.get("activationDate"))
    due_by = parse_date(report.get("dueBy"))
    if activation and current < activation:
        return "waiting"
    if due_by and current > due_by:
        return "overdue"
    return "open"


def can_fill(report: dict[str, Any], *, on: date | None = None) -> bool:
    return availability(report, on=on) in {"open", "overdue", "returned"}


def window(report: dict[str, Any], *, on: date | None = None) -> dict[str, Any]:
    """Everything the screen needs to explain the timing, in one place."""
    current = on or today()
    activation = parse_date(report.get("activationDate"))
    next_date = parse_date(report.get("nextMeetingDate"))
    due_by = parse_date(report.get("dueBy"))
    latest = latest_target_date([{"targetDate": row.get("targetDate")} for row in report.get("rows") or []])
    state = availability(report, on=current)
    return {
        "availability": state,
        "label": AVAILABILITY.get(state, state),
        "latestTargetDate": _iso(latest),
        "activationDate": _iso(activation),
        "nextMeetingNo": int(report.get("nextMeetingNo") or 0),
        "nextMeetingDate": _iso(next_date),
        "dueBy": _iso(due_by),
        "daysUntilOpen": (activation - current).days if activation and current < activation else 0,
        "daysUntilDue": (due_by - current).days if due_by else None,
        "daysUntilNextMeeting": (next_date - current).days if next_date else None,
        "canFill": can_fill(report, on=current),
        "calendarIssued": bool(next_date),
        "scheduleConflict": bool(activation and next_date and (next_date - timedelta(days=DUE_DAYS_BEFORE_MEETING)) < activation),
        "dueDaysBeforeMeeting": DUE_DAYS_BEFORE_MEETING,
        "reminderDaysBeforeMeeting": REMINDER_DAYS_BEFORE_MEETING,
    }


# ---------------------------------------------------------------------------
# Filling, signing and deciding
# ---------------------------------------------------------------------------

def validate_rows(rows: Iterable[dict[str, Any]], *, require_complete: bool = False) -> str | None:
    """The reason the given rows cannot be saved, or ``None`` when they are fine."""
    rows = list(rows or [])
    if not rows:
        return "This meeting recorded no action items, so there is nothing to report."
    for index, row in enumerate(rows, start=1):
        status = str(row.get("status") or "").strip()
        if status and status not in STATUS_CHOICES:
            return f"Row {index}: choose Completed, In Progress or Pending."
        details = str(row.get("details") or "")
        if len(details) > MAX_DETAILS:
            return f"Row {index}: the action taken is longer than {MAX_DETAILS} characters."
        if require_complete:
            if not status:
                return f"Row {index}: record whether the action is completed, in progress or pending."
            if not str(details).strip():
                return f"Row {index}: write the action taken, or the reason it is pending."
    return None


def save_rows(workspace_id: str, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Store what has been typed so far. No signature, no status change."""
    report = get_report(workspace_id)
    if not report:
        raise LookupError("This meeting has no Action Taken Report yet.")
    cleaned = []
    for index, row in enumerate(rows or [], start=1):
        cleaned.append({
            "sl": index,
            "agendaNo": str(row.get("agendaNo") or "")[:40],
            "actionItem": str(row.get("actionItem") or "")[:MAX_ACTION_TEXT],
            "responsible": str(row.get("responsible") or "")[:120],
            "targetDate": str(row.get("targetDate") or "")[:10],
            "status": str(row.get("status") or "").strip(),
            "details": str(row.get("details") or "")[:MAX_DETAILS],
        })
    with connect() as db:
        db.execute("UPDATE action_taken_reports SET rows_json=?, updated_at=? WHERE workspace_id=?",
                   (json.dumps(cleaned, ensure_ascii=False), now_iso(), workspace_id))
        db.commit()
    return get_report(workspace_id) or report


def submit_report(workspace_id: str, signature: dict[str, Any]) -> dict[str, Any]:
    """The Member Secretary signs and sends the report to the Chairperson."""
    stamp = now_iso()
    with connect() as db:
        db.execute("""UPDATE action_taken_reports
                      SET status='submitted', secretary_signature_json=?, submitted_at=?,
                          chair_comment='', updated_at=? WHERE workspace_id=?""",
                   (json.dumps(signature, ensure_ascii=False), stamp, stamp, workspace_id))
        db.commit()
    return get_report(workspace_id) or {}


def decide_report(workspace_id: str, decision: str, *, comment: str = "",
                  signature: dict[str, Any] | None = None) -> dict[str, Any]:
    """The Chairperson signs the report, or returns it for correction."""
    stamp = now_iso()
    if decision == "approved":
        with connect() as db:
            db.execute("""UPDATE action_taken_reports
                          SET status='approved', chair_signature_json=?, decided_at=?,
                              chair_comment=?, updated_at=? WHERE workspace_id=?""",
                       (json.dumps(signature or {}, ensure_ascii=False), stamp, comment, stamp, workspace_id))
            db.commit()
    else:
        with connect() as db:
            db.execute("""UPDATE action_taken_reports
                          SET status='returned', decided_at=?, chair_comment=?, updated_at=?
                          WHERE workspace_id=?""", (stamp, comment, stamp, workspace_id))
            db.commit()
    return get_report(workspace_id) or {}


def attach_document(workspace_id: str, document_id: str) -> None:
    with connect() as db:
        db.execute("UPDATE action_taken_reports SET document_id=?, updated_at=? WHERE workspace_id=?",
                   (document_id, now_iso(), workspace_id))
        db.commit()


# ---------------------------------------------------------------------------
# Reading the reports
# ---------------------------------------------------------------------------

def _reports_for(email: str, *, role: str) -> list[dict[str, Any]]:
    email = str(email or "").strip().lower()
    with connect() as db:
        if role in {"academic_office", "system_admin"}:
            rows = db.execute("SELECT * FROM action_taken_reports ORDER BY updated_at DESC").fetchall()
        else:
            rows = db.execute("""SELECT * FROM action_taken_reports
                                 WHERE owner_email=? OR chair_email=?
                                 ORDER BY updated_at DESC""", (email, email)).fetchall()
    return [_report_dict(row) for row in rows]


def _approved_workspaces(owner_id: str | None = None) -> list[dict[str, Any]]:
    """Every meeting whose minutes are approved — the meetings that need a report."""
    from auth_store import get_workspace
    with connect() as db:
        if owner_id:
            rows = db.execute("SELECT workspace_id FROM workspaces WHERE status='approved' AND owner_id=?",
                              (owner_id,)).fetchall()
        else:
            rows = db.execute("SELECT workspace_id FROM workspaces WHERE status='approved'").fetchall()
    workspaces = []
    for row in rows:
        workspace = get_workspace(row["workspace_id"])
        if workspace:
            workspaces.append(workspace)
    return workspaces


def ensure_for_user(user: dict[str, Any]) -> None:
    """Create any report this account's approved meetings are owed, and refresh windows."""
    role = user.get("role")
    owner_id = user.get("id") if role == "faculty" else None
    for workspace in _approved_workspaces(owner_id):
        ensure_report(workspace)


def list_reports(user: dict[str, Any]) -> list[dict[str, Any]]:
    ensure_for_user(user)
    reports = _reports_for(user.get("email"), role=str(user.get("role") or ""))
    output = []
    for report in reports:
        # A faculty account only sees its own reports or the ones it chairs.
        if user.get("role") not in {"academic_office", "system_admin"}:
            email = str(user.get("email") or "").strip().lower()
            if email not in {report["ownerEmail"], report["chairEmail"]}:
                continue
        output.append({
            "workspaceId": report["workspaceId"],
            "committee": report["committee"],
            "school": report["school"], "department": report["department"],
            "academicYear": report["academicYear"], "semester": report["semester"],
            "meetingNo": report["meetingNo"], "meetingDate": report["meetingDate"],
            "ownerEmail": report["ownerEmail"], "chairEmail": report["chairEmail"],
            "chairName": report["chairName"],
            "status": report["status"],
            "window": window(report),
            "isOwner": report["ownerEmail"] == str(user.get("email") or "").strip().lower(),
            "isChair": report["chairEmail"] == str(user.get("email") or "").strip().lower(),
            "completedRows": sum(1 for row in report["rows"] if str(row.get("status") or "").strip()),
            "totalRows": len(report["rows"]),
        })
    return output


def history_for(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Earlier reports of the same committee and school — what the next meeting inherits."""
    with connect() as db:
        rows = db.execute("""SELECT * FROM action_taken_reports
                             WHERE committee=? AND school=? AND department=? AND workspace_id!=?
                             ORDER BY meeting_date DESC LIMIT 5""",
                          (report["committee"], report["school"], report["department"],
                           report["workspaceId"])).fetchall()
    history = []
    for row in rows:
        record = _report_dict(row)
        history.append({"workspaceId": record["workspaceId"], "meetingNo": record["meetingNo"],
                        "meetingDate": record["meetingDate"], "status": record["status"],
                        "availability": availability(record),
                        "pending": [row_item for row_item in record["rows"]
                                    if str(row_item.get("status") or "") in {"In Progress", "Pending"}]})
    return history


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

def sweep_for(user: dict[str, Any]) -> int:
    """Create the reminders this account is owed right now. Idempotent.

    Called when the account reads its notifications, so the reminders appear without a
    scheduler on the server and cannot be missed by one that failed to run.
    """
    import notifications as notification_store
    email = str(user.get("email") or "").strip().lower()
    if not email or user.get("role") != "faculty":
        return 0
    ensure_for_user(user)
    created = 0
    current = today()
    for report in _reports_for(email, role="faculty"):
        if report["ownerEmail"] != email:
            continue
        if not report["rows"] or report["status"] in {"submitted", "approved"}:
            continue
        win = window(report, on=current)
        activation = parse_date(report["activationDate"])
        due_by = parse_date(report["dueBy"])
        next_date = parse_date(report["nextMeetingDate"])
        label = (f"{report['committee']} {report['meetingNo']} · "
                 f"{report['department'] or report['school']}")

        # Three weeks before the next meeting: the report is coming due.
        if next_date:
            reminder_from = next_date - timedelta(days=REMINDER_DAYS_BEFORE_MEETING)
            if current >= reminder_from:
                due_text = (f" It must be filled by {due_by.strftime('%d %b %Y')} — one week before "
                            f"the next meeting on {next_date.strftime('%d %b %Y')}."
                            if due_by else "")
                opened = win["canFill"]
                body = ("The Action Taken Report is ready to fill." if opened else
                        f"The report opens on {activation.strftime('%d %b %Y')}, once the latest "
                        "action-item target date has passed.")
                notification_store.notify(
                    email, "approval_request",
                    f"Action Taken Report for {label}",
                    body + due_text,
                    workspace_id=report["workspaceId"], link="atr",
                    meta={"stage": "atr", "nextMeetingDate": report["nextMeetingDate"]},
                    dedupe_key=f"atr:reminder:{report['workspaceId']}:{report['nextMeetingDate']}")
                created += 1

        # The report has opened: say so once.
        if activation and current > activation:
            notification_store.notify(
                email, "approval_request",
                f"Action Taken Report now open for {label}",
                ("The latest action-item target date has passed, so the report can be filled."
                 + (f" It is due by {due_by.strftime('%d %b %Y')}." if due_by else "")),
                workspace_id=report["workspaceId"], link="atr",
                meta={"stage": "atr"},
                dedupe_key=f"atr:open:{report['workspaceId']}:{report['activationDate']}")
            created += 1

        # Past the deadline and still not sent.
        if due_by and current > due_by:
            notification_store.notify(
                email, "revision",
                f"Action Taken Report overdue for {label}",
                (f"The report was due on {due_by.strftime('%d %b %Y')} and has not been submitted."
                 + (f" The next meeting is on {next_date.strftime('%d %b %Y')}." if next_date else "")),
                workspace_id=report["workspaceId"], link="atr",
                meta={"stage": "atr"},
                dedupe_key=f"atr:overdue:{report['workspaceId']}:{report['dueBy']}")
            created += 1
    return created
