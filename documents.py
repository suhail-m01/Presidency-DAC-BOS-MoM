"""Central document repository ("Document Vault") for approved forms and minutes.

Every approved document — the signed meeting request, the approved Minutes of
Meeting and the External Member's observation report — is archived here once,
in one store, indexed by school (then department / academic year / document
type).  The binary lives under ``data/documents/<school>/<academic-year>/`` and
the database row carries the metadata, the SHA-256 checksum and the version.

Design notes
------------
* The table is additive: nothing in the existing workflow tables changes.
* Writes are idempotent per ``(workspace_id, doc_type, version)`` so a retried
  approval cannot create duplicate archive copies.
* Downloads are always served through an authenticated route that re-checks the
  caller's school scope; there is no public directory listing.
* The storage root is configurable (``DAC_DOCUMENT_ROOT``) so a deployment can
  put it on a mounted volume, and the same interface can back onto object
  storage later without touching the workflow.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from auth_store import DATA_DIR, connect, now_iso

DOCUMENT_ROOT = Path(os.environ.get("DAC_DOCUMENT_ROOT", DATA_DIR / "documents"))
DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)

DOC_TYPES: dict[str, str] = {
    "request": "Meeting request & agenda approval form",
    "mom": "Minutes of Meeting",
    "external_report": "External Member observation report",
    "atr": "Action Taken Report",
}

def init_documents() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            school TEXT NOT NULL,
            department TEXT NOT NULL DEFAULT '',
            academic_year TEXT NOT NULL DEFAULT '',
            semester TEXT NOT NULL DEFAULT '',
            workspace_id TEXT NOT NULL DEFAULT '',
            meeting_ref TEXT NOT NULL DEFAULT '',
            doc_type TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'approved',
            version INTEGER NOT NULL DEFAULT 1,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            mime TEXT NOT NULL DEFAULT 'application/pdf',
            size INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            committee TEXT NOT NULL DEFAULT 'DAC',
            UNIQUE(workspace_id, doc_type, version)
        );
        CREATE INDEX IF NOT EXISTS idx_documents_school ON documents(school, doc_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_id, doc_type);
        """)
        # Additive migration: older rows predate the committee column.
        columns = {row["name"] for row in db.execute("PRAGMA table_info(documents)")}
        if "committee" not in columns:
            db.execute("ALTER TABLE documents ADD COLUMN committee TEXT NOT NULL DEFAULT 'DAC'")
        db.commit()
    _backfill_committee()


def _backfill_committee() -> None:
    """Derive the committee for rows archived before the column existed."""
    with connect() as db:
        rows = db.execute("""SELECT d.id AS id, w.payload_json AS payload_json
                             FROM documents d JOIN workspaces w ON w.workspace_id = d.workspace_id
                             WHERE d.committee IS NULL OR d.committee = ''""").fetchall()
        for row in rows:
            try:
                state = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                continue
            committee = str((state.get("meeting") or {}).get("committee")
                            or state.get("committee") or "DAC").strip().upper()
            db.execute("UPDATE documents SET committee=? WHERE id=?",
                       (committee if committee in {"DAC", "BOS"} else "DAC", row["id"]))
        db.commit()


def _slug(value: str, fallback: str = "unspecified") -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip()).strip("-")
    return (text or fallback)[:60]


def _school_dir(school: str, academic_year: str) -> Path:
    target = DOCUMENT_ROOT / _slug(school, "unassigned-school") / _slug(academic_year, "no-academic-year")
    target.mkdir(parents=True, exist_ok=True)
    return target


def store_document(*, school: str, department: str, academic_year: str, semester: str,
                   workspace_id: str, meeting_ref: str, doc_type: str, title: str,
                   pdf_bytes: bytes, created_by: str, version: int = 1,
                   status: str = "approved", meta: dict[str, Any] | None = None,
                   mime: str = "application/pdf", extension: str = ".pdf",
                   committee: str = "DAC") -> dict[str, Any]:
    """Archive one approved document and return its metadata row.

    Re-archiving the same ``(workspace_id, doc_type, version)`` replaces the
    stored bytes and refreshes the checksum instead of adding a duplicate row.
    """
    if doc_type not in DOC_TYPES:
        raise ValueError(f"Unknown document type: {doc_type}")
    committee = str(committee or "DAC").strip().upper()
    if committee not in {"DAC", "BOS"}:
        committee = "DAC"
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    directory = _school_dir(school, academic_year)
    filename = f"{doc_type}-{_slug(meeting_ref or workspace_id, 'document')}-v{version}{extension}"
    path = directory / filename
    path.write_bytes(pdf_bytes)

    document_id = uuid.uuid4().hex
    payload = json.dumps(meta or {}, ensure_ascii=False)
    with connect() as db:
        existing = db.execute(
            "SELECT id FROM documents WHERE workspace_id=? AND doc_type=? AND version=?",
            (workspace_id, doc_type, version)).fetchone()
        if existing:
            document_id = existing["id"]
            db.execute("""UPDATE documents SET school=?, department=?, academic_year=?, semester=?,
                          meeting_ref=?, title=?, status=?, filename=?, stored_path=?, mime=?, size=?,
                          sha256=?, created_at=?, created_by=?, meta_json=?, committee=? WHERE id=?""",
                       (school, department, academic_year, semester, meeting_ref, title, status,
                        filename, str(path), mime, len(pdf_bytes), digest, now_iso(), created_by,
                        payload, committee, document_id))
        else:
            db.execute("""INSERT INTO documents(id, school, department, academic_year, semester,
                          workspace_id, meeting_ref, doc_type, title, status, version, filename,
                          stored_path, mime, size, sha256, created_at, created_by, meta_json, committee)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (document_id, school, department, academic_year, semester, workspace_id,
                        meeting_ref, doc_type, title, status, version, filename, str(path), mime,
                        len(pdf_bytes), digest, now_iso(), created_by, payload, committee))
        db.commit()
        row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    return _document_dict(row)


def _document_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except json.JSONDecodeError:
        meta = {}
    return {
        "id": row["id"], "school": row["school"], "department": row["department"],
        "committee": row["committee"] if "committee" in row.keys() else "DAC",
        "academicYear": row["academic_year"], "semester": row["semester"],
        "workspaceId": row["workspace_id"], "meetingRef": row["meeting_ref"],
        "docType": row["doc_type"], "docTypeLabel": DOC_TYPES.get(row["doc_type"], row["doc_type"]),
        "title": row["title"], "status": row["status"], "version": row["version"],
        "filename": row["filename"], "mime": row["mime"], "size": row["size"],
        "sha256": row["sha256"], "createdAt": row["created_at"], "createdBy": row["created_by"],
        "meta": meta,
    }


def list_documents(school: str | None = None, doc_type: str | None = None,
                   academic_year: str | None = None, department: str | None = None,
                   committee: str | None = None, semester: str | None = None,
                   limit: int = 500) -> list[dict[str, Any]]:
    clauses, params = [], []
    if school:
        clauses.append("school = ? COLLATE NOCASE")
        params.append(school)
    if department:
        clauses.append("department = ? COLLATE NOCASE")
        params.append(department)
    if committee:
        clauses.append("committee = ? COLLATE NOCASE")
        params.append(str(committee).strip().upper())
    if semester:
        clauses.append("semester = ? COLLATE NOCASE")
        params.append(semester)
    if doc_type:
        clauses.append("doc_type = ?")
        params.append(doc_type)
    if academic_year:
        clauses.append("academic_year = ?")
        params.append(academic_year)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(int(limit or 500), 2000)))
    with connect() as db:
        # `where` is assembled from fixed "column = ?" clauses; the values are bound.
        rows = db.execute(f"SELECT * FROM documents{where} ORDER BY created_at DESC, doc_type LIMIT ?",  # nosec B608
                          tuple(params)).fetchall()
    return [_document_dict(row) for row in rows]


def get_document(document_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    return _document_dict(row) if row else None


def document_path(document: dict[str, Any]) -> Path | None:
    with connect() as db:
        row = db.execute("SELECT stored_path FROM documents WHERE id=?", (document["id"],)).fetchone()
    if not row:
        return None
    path = Path(row["stored_path"])
    return path if path.exists() else None


def summary_by_school() -> dict[str, Any]:
    """Grouping used by the vault screen: school → counts per document type."""
    with connect() as db:
        rows = db.execute("""SELECT school, department, academic_year, doc_type, COUNT(*) AS total,
                                    MAX(created_at) AS latest
                             FROM documents GROUP BY school, department, academic_year, doc_type
                             ORDER BY school COLLATE NOCASE, department COLLATE NOCASE,
                                      academic_year DESC, doc_type""").fetchall()
        total = db.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
    schools: dict[str, Any] = {}
    for row in rows:
        entry = schools.setdefault(row["school"], {"school": row["school"], "total": 0,
                                                   "latest": "", "types": {}, "departments": []})
        entry["total"] += row["total"]
        entry["types"][row["doc_type"]] = entry["types"].get(row["doc_type"], 0) + row["total"]
        entry["latest"] = max(entry["latest"], row["latest"] or "")
        entry["departments"].append({"department": row["department"], "academicYear": row["academic_year"],
                                     "docType": row["doc_type"],
                                     "docTypeLabel": DOC_TYPES.get(row["doc_type"], row["doc_type"]),
                                     "count": row["total"]})
    return {"total": total, "schools": sorted(schools.values(), key=lambda item: item["school"].lower()),
            "docTypes": DOC_TYPES}


def archive_approved_mom(state: dict[str, Any], pdf_bytes: bytes, actor_email: str, version: int = 1) -> dict[str, Any]:
    """Archive the approved Minutes of Meeting (called by the Academic Office approval)."""
    meeting = state.get("meeting") or {}
    return store_document(
        school=str(meeting.get("school") or "Unassigned"),
        department=str(meeting.get("department") or ""),
        academic_year=str(meeting.get("academicYear") or ""),
        semester=str(meeting.get("semester") or ""),
        workspace_id=str(state.get("workspaceId") or meeting.get("id") or ""),
        meeting_ref=str(meeting.get("referenceNo") or ""),
        doc_type="mom",
        committee=str(state.get("committee") or meeting.get("committee") or "DAC"),
        title=(f"Minutes of the {meeting.get('meetingNo') or ''} "
               f"{str(state.get('committee') or meeting.get('committee') or 'DAC').upper()} meeting — "
               f"{meeting.get('department') or ''}").strip(" —"),
        pdf_bytes=pdf_bytes, created_by=actor_email, version=version,
        meta={"meetingNo": meeting.get("meetingNo"), "date": meeting.get("date"),
              "chairperson": meeting.get("chairName"), "secretary": meeting.get("secretaryName")},
    )
