"""The Academic Office archive of every committee meeting on record.

One read-only view over all workspaces — DAC and BOS — so the Academic Office can
answer "what has this department held this year?" without opening meetings one by
one.  Each row carries the meeting identity, who convened and chaired it, where the
workflow stands, and links to the archived *request form* and *completion form*
(the approved Minutes of Meeting) when those documents exist.

Nothing here writes to the workflow; it is a filtered projection over the two
existing tables (``workspaces`` and ``documents``), so the archive can never drift
out of step with the records it lists.
"""

from __future__ import annotations

import json
from typing import Any

import committees as committee_registry
from auth_store import connect

STATUS_LABELS = {
    "draft": "Draft — not submitted",
    "pending_chairperson": "Awaiting the Chairperson",
    "pending": "Awaiting the Academic Office",
    "revision": "Returned for revision",
    "rejected": "Rejected",
    "approved": "Approved",
}

MOM_LABELS = {
    "draft": "Minutes not submitted",
    "pending_chairperson": "Minutes with the Chairperson",
    "chair_revision": "Minutes returned by the Chairperson",
    "pending_office": "Minutes with the Academic Office",
    "office_revision": "Minutes returned by the Academic Office",
    "approved": "Minutes approved",
}


def _load_payloads() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("""SELECT w.workspace_id, w.owner_id, w.status, w.payload_json, w.updated_at,
                                    u.full_name AS owner_name, u.email AS owner_email
                             FROM workspaces w LEFT JOIN users u ON u.id = w.owner_id
                             ORDER BY w.updated_at DESC""").fetchall()
        documents: dict[tuple[str, str], dict[str, Any]] = {}
        for row in db.execute("""SELECT id, workspace_id, doc_type, title, version, created_at, created_by
                                 FROM documents ORDER BY version ASC"""):
            documents[(row["workspace_id"], row["doc_type"])] = {
                "id": row["id"], "title": row["title"], "version": row["version"],
                "createdAt": row["created_at"], "createdBy": row["created_by"],
                "downloadUrl": f"/api/documents/{row['id']}/download",
            }
    records = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        meeting = payload.get("meeting") or {}
        review = payload.get("momReview") or {}
        committee = committee_registry.normalise(payload.get("committee") or meeting.get("committee"))
        request_doc = documents.get((row["workspace_id"], "request"))
        mom_doc = documents.get((row["workspace_id"], "mom"))
        submitted = int(payload.get("submittedVersion") or 0)
        records.append({
            "workspaceId": row["workspace_id"],
            "committee": committee,
            "committeeName": committee_registry.name(committee),
            "meetingNo": meeting.get("meetingNo") or "",
            "meetingLabel": committee_registry.meeting_label(committee, meeting.get("meetingNo")),
            "school": meeting.get("school") or "",
            "department": meeting.get("department") or "",
            "academicYear": meeting.get("academicYear") or "",
            "semester": meeting.get("semester") or "",
            "date": meeting.get("date") or "",
            "venue": meeting.get("venue") or "",
            "chairName": meeting.get("chairName") or "",
            "chairEmail": meeting.get("chairEmail") or "",
            "secretaryName": payload.get("secretarySignature", {}).get("name") or row["owner_name"] or "",
            "secretaryEmail": row["owner_email"] or "",
            "reference": payload.get("proposalReference") or meeting.get("referenceNo") or "",
            "status": row["status"],
            "statusLabel": STATUS_LABELS.get(row["status"], row["status"]),
            "submitted": submitted > 0,
            "submittedAt": payload.get("submittedAt") or "",
            "momStatus": review.get("status") or "draft",
            "momStatusLabel": MOM_LABELS.get(review.get("status") or "draft", review.get("status") or ""),
            "requestForm": request_doc,
            "completionForm": mom_doc,
            "documentsAvailable": [kind for kind, doc in (("request", request_doc), ("mom", mom_doc)) if doc],
            "updatedAt": row["updated_at"],
        })
    return records


def list_meetings(*, committee: str | None = None, school: str | None = None,
                  department: str | None = None, academic_year: str | None = None,
                  semester: str | None = None, doc_type: str | None = None,
                  status: str | None = None, search: str | None = None,
                  date_from: str | None = None, date_to: str | None = None,
                  limit: int = 500) -> dict[str, Any]:
    """Filtered archive rows plus the filter options that actually exist."""
    records = [row for row in _load_payloads() if row["submitted"] or row["status"] != "draft"]
    windows = {
        "committee": (committee, lambda row: row["committee"] == committee_registry.normalise(committee) if committee else True),
        "school": (school, lambda row: row["school"].casefold() == str(school).casefold() if school else True),
        "department": (department, lambda row: row["department"].casefold() == str(department).casefold() if department else True),
        "academic_year": (academic_year, lambda row: row["academicYear"] == academic_year if academic_year else True),
        "semester": (semester, lambda row: row["semester"].casefold() == str(semester).casefold() if semester else True),
    }
    for _, (value, predicate) in windows.items():
        if value:
            records = [row for row in records if predicate(row)]
    if doc_type in {"request", "mom"}:
        records = [row for row in records if row["documentsAvailable"] and doc_type in row["documentsAvailable"]]
    if status in STATUS_LABELS:
        records = [row for row in records if row["status"] == status]
    # The Academic Office issues a From–To date range (ISO dates compare lexicographically).
    if date_from:
        records = [row for row in records if (row["date"] or "") >= date_from]
    if date_to:
        records = [row for row in records if (row["date"] or "") <= date_to]
    if search:
        needle = str(search).strip().casefold()
        records = [row for row in records
                   if needle in " ".join(str(row.get(key) or "") for key in
                                         ("school", "department", "chairName", "secretaryName",
                                          "reference", "meetingLabel", "academicYear", "semester")).casefold()]

    # The filter options come from the unfiltered set, so narrowing one filter never
    # hides the values available in another.
    everything = [row for row in _load_payloads() if row["submitted"] or row["status"] != "draft"]
    schools: dict[str, set] = {}
    years: set = set()
    for row in everything:
        if row["school"]:
            schools.setdefault(row["school"], set())
            if row["department"]:
                schools[row["school"]].add(row["department"])
        if row["academicYear"]:
            years.add(row["academicYear"])

    def _count(code: str) -> int:
        return sum(1 for row in everything if row["committee"] == code)

    return {
        "rows": records[: max(1, min(int(limit or 500), 2000))],
        "total": len(records),
        "summary": {
            "all": len(everything),
            "DAC": _count("DAC"),
            "BOS": _count("BOS"),
            "withRequestForm": sum(1 for row in everything if row["requestForm"]),
            "withCompletionForm": sum(1 for row in everything if row["completionForm"]),
        },
        "filters": {
            "committees": [{"code": entry["code"], "name": entry["name"],
                            "scheduleShort": entry["scheduleShort"]}
                           for entry in committee_registry.series_catalogue()],
            "schools": [{"school": school, "departments": sorted(departments)}
                        for school, departments in sorted(schools.items(), key=lambda item: item[0].lower())],
            "academicYears": sorted(years, reverse=True),
            "statuses": [{"code": code, "label": label} for code, label in STATUS_LABELS.items()],
            "momStatuses": [{"code": code, "label": label} for code, label in MOM_LABELS.items()],
        },
    }


__all__ = ["list_meetings", "STATUS_LABELS", "MOM_LABELS"]
