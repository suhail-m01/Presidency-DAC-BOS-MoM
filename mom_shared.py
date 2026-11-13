"""Shared, dependency-free helpers for MoM rendering (PDF and DOCX).

These functions are pure: they take the saved workspace payload and return
strings. Both the PDF renderer (`app.py`) and the Word renderer (`mom_docx.py`)
use them so that the two outputs stay word-for-word identical.
"""
from __future__ import annotations

try:
    from committees import name as committee_name
except ImportError:                                     # pragma: no cover - package context
    def committee_name(_value=None):
        return "Departmental Academic Committee"

import re
from datetime import datetime

LEGACY_RESOLUTION_KEYS = ("recommendation",)
RESOLUTION_KEY = "resolution"
NO_RESOLUTION_KEY = "noResolution"
LEGACY_NO_RESOLUTION_KEY = "noRecommendation"
SOURCE_RESOLUTION_KEY = "sourceResolution"
LEGACY_SOURCE_RESOLUTION_KEY = "sourceRecommendation"


def item_resolution(item: dict) -> str:
    """Return the resolution text for an agenda item.

    Reads the current ``resolution`` field first and falls back to the legacy
    ``recommendation`` field so that workspaces saved before the rename keep
    rendering correctly.
    """
    if not isinstance(item, dict):
        return ""
    value = item.get(RESOLUTION_KEY)
    if value in (None, ""):
        for legacy in LEGACY_RESOLUTION_KEYS:
            if item.get(legacy) not in (None, ""):
                return str(item.get(legacy) or "").strip()
    return str(value or "").strip()


def item_has_no_resolution(item: dict) -> bool:
    """Return whether the author marked "no separate resolution recorded"."""
    if not isinstance(item, dict):
        return False
    if NO_RESOLUTION_KEY in item:
        return bool(item.get(NO_RESOLUTION_KEY))
    return bool(item.get(LEGACY_NO_RESOLUTION_KEY))


def migrate_resolution_keys(state: dict) -> dict:
    """Rename legacy ``recommendation`` keys to ``resolution`` in place.

    The rename is idempotent: running it twice changes nothing, and the legacy
    key is dropped once the new key holds the value.
    """
    if not isinstance(state, dict):
        return state

    def convert(rows):
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            for legacy in LEGACY_RESOLUTION_KEYS:
                if legacy in row:
                    row.setdefault(RESOLUTION_KEY, row.pop(legacy))
            if LEGACY_NO_RESOLUTION_KEY in row:
                row.setdefault(NO_RESOLUTION_KEY, row.pop(LEGACY_NO_RESOLUTION_KEY))
            if LEGACY_SOURCE_RESOLUTION_KEY in row:
                row.setdefault(SOURCE_RESOLUTION_KEY, row.pop(LEGACY_SOURCE_RESOLUTION_KEY))

    convert(state.get("momItems"))
    convert(state.get("additionalDiscussions"))
    convert(state.get("actionItems"))
    return state


def ordinal(value) -> str:
    text = str(value or "1").strip()
    match = re.search(r"\d+", text)
    if not match:
        return text
    number = int(match.group(0))
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def numeric_meeting_number(value) -> int:
    match = re.search(r"\d+", str(value or "1"))
    return int(match.group(0)) if match else 1


def format_date_dmy(value) -> str:
    if not value:
        return "Date not recorded"
    try:
        return datetime.fromisoformat(str(value)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(value)


def without_name_prefix(value: object, prefix: str) -> str:
    text = str(value or "").strip()
    return re.sub(rf"^{re.escape(prefix)}\s*", "", text, flags=re.IGNORECASE).strip() or "__________"


def member_role_rank(role: object) -> int:
    """Canonical member order: Chairperson → Member → External Member → Member Secretary."""
    text = str(role or "").lower()
    if "chair" in text:
        return 0
    if "secretary" in text:
        return 3
    if "external" in text:
        return 2
    if "member" in text:
        return 1
    return 1


def sorted_members(members: list[dict] | None) -> list[dict]:
    """Return members in printed order (stable within each role)."""
    indexed = list(enumerate(members or []))
    indexed.sort(key=lambda pair: (member_role_rank((pair[1] or {}).get("role")), pair[0]))
    return [member for _, member in indexed]


def reference_number(meeting: dict, kind: str = "mom") -> str:
    """The file reference printed on the request form and the minutes.

    The committee decides the middle segment: ``.../DAC-01/...`` for a Departmental
    Academic Committee meeting, ``.../BOS-01/...`` for a Board of Studies meeting.
    The trailing segment reads ``Notice`` on the meeting request
    (``kind="request"`` → ``.../Notice-01``) and ``MoM`` in the MoM workspace
    (``kind="mom"`` → ``.../MoM-01``).
    """
    import committees as committee_registry
    number = numeric_meeting_number(meeting.get("meetingNo"))
    school_code = (re.sub(r"[^A-Za-z0-9]", "", str(meeting.get("schoolCode") or "School")) or "School").upper()
    department_code = (re.sub(r"[^A-Za-z0-9]", "", str(meeting.get("departmentCode") or "Dept")) or "Dept").upper()
    academic_year = str(meeting.get("academicYear") or "Academic Year")
    semester = str(meeting.get("semester") or "Semester")
    prefix = committee_registry.reference_prefix(meeting.get("committee"))
    suffix = "Notice" if kind == "request" else "MoM"
    return f"PU/{school_code}-{department_code}/{prefix}-{number:02d}/{academic_year}/{semester}/{suffix}-{number:02d}"


def agenda_document_title(item: dict, meeting: dict) -> str:
    agenda_id = str(item.get("agendaId") or item.get("id") or "")
    title = str(item.get("title") or "").strip()
    current_number = numeric_meeting_number(meeting.get("meetingNo"))
    fallback_previous = str(max(1, current_number - 1)) if current_number > 1 else "previous"
    previous_number = ordinal(meeting.get("previousMeetingNo") or fallback_previous)
    previous_date = format_date_dmy(meeting.get("previousMeetingDate"))
    if agenda_id == "std-mom":
        if title.startswith("To consider the approval of the MoM of the "):
            return title  # Approved wording is frozen in the MoM snapshot.
        return (f"To consider the approval of the MoM of the {previous_number} "
                f"{committee_name(meeting.get('committee'))} meeting held on {previous_date}.")
    if agenda_id == "std-atr":
        if title.startswith("To consider the approval of the Action Taken Report (ATR) of the "):
            return title  # Approved wording is frozen in the MoM snapshot.
        return (f"To consider the approval of the Action Taken Report (ATR) of the {previous_number} "
                f"{committee_name(meeting.get('committee'))} meeting held on {previous_date}.")
    return title or "Agenda"


def meeting_description(meeting: dict) -> str:
    number = ordinal(meeting.get("meetingNo"))
    department = without_name_prefix(meeting.get("department"), "Department of")
    school = without_name_prefix(meeting.get("school"), "School of")
    date_text = format_date_dmy(meeting.get("date"))
    time_text = str(meeting.get("startTime") or "Time not recorded")
    venue = str(meeting.get("venue") or "Venue not recorded")
    mode = str(meeting.get("mode") or "Offline").strip().lower()
    if mode == "offline":
        mode_text = "The meeting was held in offline mode at the University campus in Bengaluru."
    elif mode == "online":
        mode_text = "The meeting was held in online mode."
    else:
        mode_text = "The meeting was held in hybrid mode at the University campus in Bengaluru."
    meeting_link = str(meeting.get("onlineLink") or "").strip()
    link_text = f" The meeting link is provided below: {meeting_link}" if meeting_link else " The meeting link is provided below."
    return (
        f"The {number} Meeting of the {committee_name(meeting.get('committee'))} of the Department of {department}, "
        f"School of {school}, University, was convened on {date_text}, at {time_text} in the {venue}. "
        f"{mode_text}{link_text}"
    )


def annexure_entries(mom_items: list[dict]) -> list[dict]:
    entries = []
    seen = set()
    for agenda_no, item in enumerate(mom_items or [], start=1):
        for file_no, attachment in enumerate(item.get("attachments") or [], start=1):
            file_id = attachment.get("id")
            if not file_id or file_id in seen:
                continue
            seen.add(file_id)
            entries.append({
                "id": file_id,
                "label": f"{agenda_no}.{file_no}",
                "agendaNo": agenda_no,
                "agendaTitle": item.get("title", ""),
                "name": attachment.get("name", "Attachment"),
            })
    return entries


def annexure_refs(item: dict, number: int, labels: dict) -> list[str]:
    """Return the "Annexure x.y — file" reference strings for one agenda item."""
    refs = []
    for attachment in item.get("attachments") or []:
        label = labels.get(attachment.get("id"))
        if label:
            refs.append(f"Annexure {label} — {attachment.get('name', 'Attachment')}")
    # No attachment, no annexure reference: a signed minute must never point at a
    # document that does not exist.
    return refs


def document_label(item: dict) -> str:
    agenda_id = str(item.get("agendaId") or item.get("id") or "")
    return "Document:" if agenda_id == "std-mom" else "Ref. Document:"
