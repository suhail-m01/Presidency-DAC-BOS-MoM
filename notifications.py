"""In-app notifications.

Every workflow event that concerns a person creates a notification row, so the
same signal that will later be emailed (Phase: M365 Graph) is already visible in
the application: the invited external member, the Chairperson asked to approve a
request or the minutes, the Academic Office queue, the organiser whose document
was returned for revision.

Kept deliberately small: append-only rows, per-user read state, no fan-out logic
here — the workflow decides who is notified and why.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from auth_store import connect, now_iso

KINDS = {
    "invitation": "Meeting invitation",
    "approval_request": "Approval requested",
    "approval_done": "Approved",
    "revision": "Returned for revision",
    "report_required": "Observation report required",
    "report_submitted": "Observation report submitted",
    "report_returned": "Observation report returned",
    "document_archived": "Document archived",
    "moM_ready": "Minutes ready",
    "system": "System notice",
}


def init_notifications() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            user_email TEXT NOT NULL COLLATE NOCASE,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            workspace_id TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            read_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_email, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_email, read_at);
        """)
        db.commit()


def notify(user_email: str, kind: str, title: str, body: str = "", *, workspace_id: str = "",
           link: str = "", actor: str = "", meta: dict[str, Any] | None = None,
           dedupe_key: str = "") -> dict[str, Any] | None:
    """Create one notification. ``dedupe_key`` makes repeated events idempotent."""
    email = str(user_email or "").strip().lower()
    if not email:
        return None
    with connect() as db:
        if dedupe_key:
            existing = db.execute(
                "SELECT * FROM notifications WHERE user_email=? AND meta_json LIKE ? LIMIT 1",
                (email, f'%"dedupeKey": "{dedupe_key}"%')).fetchone()
            if existing:
                return _notification_dict(existing)
        payload = dict(meta or {})
        if dedupe_key:
            payload["dedupeKey"] = dedupe_key
        notification_id = uuid.uuid4().hex
        db.execute("""INSERT INTO notifications(id, user_email, kind, title, body, workspace_id,
                      link, actor, meta_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                   (notification_id, email, kind, title, body, workspace_id, link, actor,
                    json.dumps(payload, ensure_ascii=False), now_iso()))
        db.commit()
        row = db.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone()
    record = _notification_dict(row)
    _queue_mail(record, actor=actor)
    return record


def _queue_mail(notification: dict[str, Any], *, actor: str = "") -> None:
    """Every in-app notification is also an email, sent by the conveyer of the step."""
    try:
        import mailer
    except Exception:  # pragma: no cover - mailer is optional at import time
        return
    workspace_id = notification.get("workspaceId") or ""
    owner_email, office_email, chair_email = "", "", ""
    if workspace_id:
        try:
            from auth_store import get_user_by_id, get_workspace
            workspace = get_workspace(workspace_id)
            if workspace:
                owner = get_user_by_id(workspace.get("ownerId") or "")
                owner_email = str((owner or {}).get("email") or "")
                chair_email = str(((workspace.get("payload") or {}).get("meeting") or {}).get("chairEmail") or "")
        except Exception:  # pragma: no cover - defensive
            pass
    link = notification.get("link") or ""
    body = notification.get("body") or ""
    mailer.enqueue(
        kind=notification.get("kind") or "system",
        to_email=notification.get("email") or "",
        subject=notification.get("title") or "Departmental Academic Committee",
        body_text="\n".join(part for part in (
            notification.get("title") or "",
            "",
            body,
            "",
            f"Open in the application: {link}" if link else "",
            "",
            "This message was sent by the Departmental Academic Committee system on behalf of the "
            "person named as the sender. Do not reply to this address.",
        ) if part is not None),
        workspace_id=workspace_id,
        actor=actor or notification.get("actor") or "",
        owner=owner_email, office=office_email, cc_email=chair_email,
    )


def _notification_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except json.JSONDecodeError:
        meta = {}
    return {"id": row["id"], "email": row["user_email"], "kind": row["kind"],
            "kindLabel": KINDS.get(row["kind"], row["kind"]),
            "title": row["title"], "body": row["body"], "workspaceId": row["workspace_id"],
            "link": row["link"], "actor": row["actor"], "createdAt": row["created_at"],
            "readAt": row["read_at"], "unread": not row["read_at"], "meta": meta}


def list_for(user_email: str, *, unread_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    sql = "SELECT * FROM notifications WHERE user_email = ? COLLATE NOCASE"
    params: list[Any] = [str(user_email or "").strip().lower()]
    if unread_only:
        sql += " AND read_at = ''"
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit or 100), 500)))
    with connect() as db:
        rows = db.execute(sql, tuple(params)).fetchall()
    return [_notification_dict(row) for row in rows]


def unread_count(user_email: str) -> int:
    with connect() as db:
        row = db.execute("SELECT COUNT(*) AS c FROM notifications WHERE user_email = ? COLLATE NOCASE AND read_at = ''",
                         (str(user_email or "").strip().lower(),)).fetchone()
    return int(row["c"] if row else 0)


def mark_read(notification_id: str, user_email: str) -> bool:
    with connect() as db:
        cursor = db.execute("UPDATE notifications SET read_at = ? WHERE id = ? AND user_email = ? COLLATE NOCASE AND read_at = ''",
                            (now_iso(), notification_id, str(user_email or "").strip().lower()))
        db.commit()
        return cursor.rowcount > 0


def mark_all_read(user_email: str) -> int:
    with connect() as db:
        cursor = db.execute("UPDATE notifications SET read_at = ? WHERE user_email = ? COLLATE NOCASE AND read_at = ''",
                            (now_iso(), str(user_email or "").strip().lower()))
        db.commit()
        return int(cursor.rowcount or 0)
