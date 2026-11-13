"""The audit trail.

Every governance event — a request submitted, a signature given, minutes approved, a
report returned, a document archived — is written here. It is the record a reviewer
asks for months later when a decision is questioned, so it has two hard requirements:

* **it must not lose events.** The trail used to live in a JSON file that was read,
  appended to in memory and written back whole. Two requests arriving together raced,
  and the later write won, so an event could disappear without a trace.
* **it must not discard history.** The same file kept only the newest 500 rows, so the
  evidence for everything older vanished silently once the product was in real use.

Both are solved by appending single rows to SQLite (WAL, busy timeout) instead of
rewriting a document. The legacy ``data/audit-log.json`` is imported once, on first
boot, so an installation that upgrades keeps its existing trail.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from auth_store import DATA_DIR, connect, now_iso

logger = logging.getLogger(__name__)

LEGACY_PATH = DATA_DIR / "audit-log.json"

#: Events that must never be dropped from a listing by accident.
DEFAULT_LIMIT = 2000


def init_audit() -> None:
    with connect() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            event TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT '',
            workspace_id TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_events(at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_events(workspace_id);
        """)
        db.commit()
        _import_legacy(db)


def _import_legacy(db) -> None:
    """Bring an existing ``audit-log.json`` across exactly once."""
    if not LEGACY_PATH.is_file():
        return
    already = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    if already:
        return
    try:
        rows = json.loads(LEGACY_PATH.read_text(encoding="utf-8") or "[]")
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        workspace_id = str(details.get("meetingId") or row.get("workspaceId") or row.get("meeting") or "")
        db.execute("""INSERT INTO audit_events(at, event, actor, role, workspace_id, details_json)
                      VALUES (?,?,?,?,?,?)""",
                   (str(row.get("at") or now_iso()), str(row.get("event") or "workflow_event"),
                    str(row.get("actor") or ""), str(row.get("role") or ""), workspace_id,
                    json.dumps(details, ensure_ascii=False)))
    db.commit()


def record(event: str, *, actor: str = "", role: str = "", workspace_id: str = "",
           details: dict[str, Any] | None = None, at: str = "") -> None:
    """Append one event. Never raises into the caller's request."""
    stamp = at or now_iso()
    payload = {key: value for key, value in (details or {}).items() if value not in (None, "")}
    try:
        with connect() as db:
            db.execute("""INSERT INTO audit_events(at, event, actor, role, workspace_id, details_json)
                          VALUES (?,?,?,?,?,?)""",
                       (stamp, str(event or "workflow_event")[:120], str(actor or "")[:200],
                        str(role or "")[:40], str(workspace_id or "")[:120],
                        json.dumps(payload, ensure_ascii=False)[:8000]))
            db.commit()
    except Exception:                                  # an audit failure must not break the workflow
        logger.exception("Could not write audit event %s", event)


def list_events(*, limit: int = DEFAULT_LIMIT, workspace_id: str = "",
                actor: str = "", event: str = "") -> list[dict[str, Any]]:
    """The trail, oldest first (the order the interface has always rendered).

    The window is the **most recent** ``limit`` events, then rendered oldest-first. Reading
    the oldest ``limit`` rows instead would mean that once the trail passed that many
    entries, every new action became permanently invisible on the audit screen — the
    exact opposite of what an audit screen is for.
    """
    clauses, params = [], []
    if workspace_id:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if actor:
        clauses.append("actor = ?")
        params.append(actor.strip().lower())
    if event:
        clauses.append("event = ?")
        params.append(event)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(int(limit or DEFAULT_LIMIT), 20000)))
    with connect() as db:
        rows = db.execute(f"SELECT * FROM audit_events{where} ORDER BY id DESC LIMIT ?",  # nosec B608 - clauses are fixed strings
                          tuple(params)).fetchall()
    return [_event_dict(row) for row in reversed(rows)]   # newest window, oldest first


def count_events() -> int:
    with connect() as db:
        return int(db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])


def _event_dict(row) -> dict[str, Any]:
    try:
        details = json.loads(row["details_json"] or "{}")
    except json.JSONDecodeError:
        details = {}
    return {
        "at": row["at"],
        "event": row["event"],
        "actor": row["actor"],
        "role": row["role"],
        "workspaceId": row["workspace_id"],
        "details": details,
    }


__all__ = ["init_audit", "record", "list_events", "count_events", "LEGACY_PATH"]

