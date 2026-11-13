"""Outbound mail: one queue, three transports.

Every workflow event that already raises an in-app notification also queues an
email, sent **from the person who conveys that step** ("send-as"), which is the
college's stated requirement:

| Event | Sender (send-as) |
| --- | --- |
| Meeting request submitted / agenda approved | the Member Secretary who scheduled the meeting |
| Request awaiting the Chairperson | the Member Secretary |
| Request approved or returned by the Chairperson | the Chairperson |
| Minutes submitted / returned / approved | the Member Secretary, then the Academic Office |
| Observation report requested / returned | the Academic Office |
| Invitation to members | the Member Secretary |

Transports (``MAIL_TRANSPORT``)
-------------------------------
``file``   (default) writes one ``.eml`` per message under ``data/mail-outbox/``
           and marks it queued. No credentials, no network — this is what runs
           until the Microsoft 365 application registration exists, and it is
           the audit copy of every mail the system would have sent.
``smtp``   sends through any SMTP relay (``SMTP_HOST``, ``SMTP_PORT``,
           ``SMTP_USER``, ``SMTP_PASSWORD``, ``SMTP_STARTTLS``). Useful for a
           college mail relay or an internal Postfix.
``graph``  Microsoft 365 via Graph ``/users/{sender}/sendMail`` using an app
           registration with the ``Mail.Send`` application permission and
           ``SendAs`` granted to the sender mailbox on the no-reply account.

Failure never blocks the workflow: the row stays ``pending`` with ``attempts``
and ``last_error``, so it can be re-sent after the configuration is fixed.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from auth_store import DATA_DIR, connect, now_iso

TRANSPORT = os.environ.get("MAIL_TRANSPORT", "file").strip().lower()
OUTBOX_DIR = Path(os.environ.get("DAC_MAIL_OUTBOX", DATA_DIR / "mail-outbox"))
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

GRAPH_TENANT = os.environ.get("GRAPH_TENANT_ID", "")
GRAPH_CLIENT = os.environ.get("GRAPH_CLIENT_ID", "")
GRAPH_SECRET = os.environ.get("GRAPH_CLIENT_SECRET", "")
GRAPH_DEFAULT_SENDER = os.environ.get("GRAPH_SENDER_UPN", "")
MAIL_DOMAIN = os.environ.get("MAIL_FROM_DOMAIN", "presidencyuniversity.in")

#: Who signs (and therefore sends) each workflow event.
SENDER_RULES = {
    "invitation": "secretary",
    "approval_request": "act",
    "approval_done": "act",
    "revision": "act",
    "report_required": "office",
    "report_submitted": "act",
    "report_returned": "office",
    "document_archived": "office",
    "mom_ready": "secretary",
    "system": "office",
}

STATUSES = {"pending": "Queued", "queued": "Written to the outbox", "sent": "Sent", "failed": "Failed"}


def init_mailer() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS mail_queue (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            to_email TEXT NOT NULL COLLATE NOCASE,
            cc_email TEXT NOT NULL DEFAULT '',
            sender_email TEXT NOT NULL DEFAULT '',
            reply_to TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL,
            body_text TEXT NOT NULL DEFAULT '',
            body_html TEXT NOT NULL DEFAULT '',
            workspace_id TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT '',
            transport TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            sent_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_mail_status ON mail_queue(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_mail_to ON mail_queue(to_email, created_at DESC);
        """)


def transport_status() -> dict[str, Any]:
    configured = {
        "file": True,
        "smtp": bool(os.environ.get("SMTP_HOST")),
        "graph": bool(GRAPH_TENANT and GRAPH_CLIENT and GRAPH_SECRET),
    }
    return {
        "transport": TRANSPORT,
        "configured": configured.get(TRANSPORT, False),
        "senders": {
            "graphSender": GRAPH_DEFAULT_SENDER or f"no-reply@{MAIL_DOMAIN}",
            "sendAsMode": "Pattern A — the conveyer of the step is the sender",
        },
        "options": configured,
    }


def _sender_address(rule: str, *, actor: str, owner: str, office: str) -> str:
    if rule == "secretary":
        return owner or actor or GRAPH_DEFAULT_SENDER
    if rule == "office":
        return office or actor or GRAPH_DEFAULT_SENDER
    return actor or owner or GRAPH_DEFAULT_SENDER


def enqueue(*, kind: str, to_email: str, subject: str, body_text: str, body_html: str = "",
            workspace_id: str = "", actor: str = "", owner: str = "", office: str = "",
            cc_email: str = "", dedupe: bool = True) -> dict[str, Any] | None:
    """Queue one mail. Returns the row, or None when it is a duplicate."""
    to_email = str(to_email or "").strip().lower()
    if not to_email or "@" not in to_email:
        return None
    sender = _sender_address(SENDER_RULES.get(kind, "act"), actor=actor, owner=owner, office=office)
    if not sender:
        sender = GRAPH_DEFAULT_SENDER or f"no-reply@{MAIL_DOMAIN}"
    with connect() as db:
        if dedupe and workspace_id:
            existing = db.execute(
                "SELECT * FROM mail_queue WHERE kind=? AND to_email=? AND workspace_id=? AND status IN ('pending','queued')",
                (kind, to_email, workspace_id)).fetchone()
            if existing:
                return dict(existing)
        mail_id = uuid.uuid4().hex
        db.execute("""INSERT INTO mail_queue(id,kind,to_email,cc_email,sender_email,subject,body_text,body_html,
                      workspace_id,actor,transport,status,created_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (mail_id, kind, to_email, cc_email.lower(), sender.lower(), subject, body_text, body_html,
                    workspace_id, actor, TRANSPORT, "pending", now_iso()))
        db.commit()
        row = db.execute("SELECT * FROM mail_queue WHERE id=?", (mail_id,)).fetchone()
    record = dict(row)
    if TRANSPORT == "file":
        dispatch(record["id"])
        with connect() as db:
            row = db.execute("SELECT * FROM mail_queue WHERE id=?", (mail_id,)).fetchone()
        record = dict(row)
    return record


def _eml_bytes(record: dict[str, Any]) -> bytes:
    message = EmailMessage()
    message["From"] = f"Departmental Academic Committee <{record['sender_email']}>"
    message["To"] = record["to_email"]
    if record.get("cc_email"):
        message["Cc"] = record["cc_email"]
    message["Subject"] = record["subject"]
    message["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    message["X-DAC-Kind"] = record["kind"]
    message["X-DAC-Workspace"] = record.get("workspace_id") or ""
    message.set_content(record["body_text"] or "")
    if record.get("body_html"):
        message.add_alternative(record["body_html"], subtype="html")
    return message.as_bytes()


def _write_file(record: dict[str, Any]) -> str:
    name = f"{record['created_at'][:10]}-{record['kind']}-{record['id'][:8]}.eml"
    path = OUTBOX_DIR / name
    path.write_bytes(_eml_bytes(record))
    return name


def _graph_token() -> str:
    url = f"https://login.microsoftonline.com/{GRAPH_TENANT}/oauth2/v2.0/token"
    body = urllib.parse.urlencode({
        "client_id": GRAPH_CLIENT, "client_secret": GRAPH_SECRET,
        "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
    }).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 - fixed Graph https endpoint
        return json.loads(response.read())["access_token"]


def _send_graph(record: dict[str, Any]) -> None:
    token = _graph_token()
    sender = record["sender_email"] or GRAPH_DEFAULT_SENDER
    payload = {
        "message": {
            "subject": record["subject"],
            "body": {"contentType": "HTML" if record.get("body_html") else "Text",
                     "content": record.get("body_html") or record.get("body_text") or ""},
            "toRecipients": [{"emailAddress": {"address": record["to_email"]}}],
            "from": {"emailAddress": {"address": sender}},
        },
        "saveToSentItems": True,
    }
    if record.get("cc_email"):
        payload["message"]["ccRecipients"] = [{"emailAddress": {"address": record["cc_email"]}}]
    request = urllib.request.Request(
        f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 - fixed Graph https endpoint
        if response.status >= 300:
            raise RuntimeError(f"Graph returned HTTP {response.status}")


def _send_smtp(record: dict[str, Any]) -> None:
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    message = _eml_bytes(record)
    if os.environ.get("SMTP_STARTTLS", "1") == "1":
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=ssl.create_default_context())
    else:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    try:
        if user:
            server.login(user, password)
        server.send_message(message_from_bytes(message))
    finally:
        server.quit()


def dispatch(mail_id: str) -> dict[str, Any] | None:
    """Attempt delivery for one queued mail and record the outcome."""
    with connect() as db:
        row = db.execute("SELECT * FROM mail_queue WHERE id=?", (mail_id,)).fetchone()
    if not row:
        return None
    record = dict(row)
    if record["status"] == "sent":
        return record
    if TRANSPORT == "file":
        try:
            name = _write_file(record)
            with connect() as db:
                db.execute("UPDATE mail_queue SET status='queued', attempts=attempts+1, file_name=?, "
                           "sent_at=? WHERE id=?", (name, now_iso(), mail_id))
                db.commit()
                row = db.execute("SELECT * FROM mail_queue WHERE id=?", (mail_id,)).fetchone()
            return dict(row)
        except Exception as exc:  # pragma: no cover - disk failure
            return _failed(mail_id, f"Could not write the outbox file: {exc}")
    try:
        if TRANSPORT == "graph":
            _send_graph(record)
        elif TRANSPORT == "smtp":
            _send_smtp(record)
        else:
            raise RuntimeError(f"Unknown MAIL_TRANSPORT '{TRANSPORT}'.")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        return _failed(mail_id, f"HTTP {exc.code}: {detail}".strip())
    except Exception as exc:
        return _failed(mail_id, str(exc)[:300])
    with connect() as db:
        db.execute("UPDATE mail_queue SET status='sent', attempts=attempts+1, last_error='', sent_at=? WHERE id=?",
                   (now_iso(), mail_id))
        db.commit()
        row = db.execute("SELECT * FROM mail_queue WHERE id=?", (mail_id,)).fetchone()
    return dict(row)


def _failed(mail_id: str, error: str) -> dict[str, Any] | None:
    with connect() as db:
        db.execute("UPDATE mail_queue SET status='failed', attempts=attempts+1, last_error=? WHERE id=?",
                   (error, mail_id))
        db.commit()
        row = db.execute("SELECT * FROM mail_queue WHERE id=?", (mail_id,)).fetchone()
    return dict(row) if row else None


def flush(limit: int = 50) -> dict[str, Any]:
    """Retry everything that is still pending or failed."""
    with connect() as db:
        rows = db.execute("SELECT id FROM mail_queue WHERE status IN ('pending','failed') ORDER BY created_at LIMIT ?",
                          (limit,)).fetchall()
    results = [dispatch(row["id"]) for row in rows]
    return {"attempted": len(rows), "sent": sum(1 for row in results if row and row["status"] in {"sent", "queued"}),
            "failed": sum(1 for row in results if row and row["status"] == "failed")}


def list_queue(limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM mail_queue"
    params: list[Any] = []
    if status:
        query += " WHERE status=?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with connect() as db:
        rows = db.execute(query, params).fetchall()
    return [{"id": row["id"], "kind": row["kind"], "to": row["to_email"], "from": row["sender_email"],
             "subject": row["subject"], "status": row["status"], "statusLabel": STATUSES.get(row["status"], row["status"]),
             "attempts": int(row["attempts"]), "lastError": row["last_error"], "file": row["file_name"],
             "workspaceId": row["workspace_id"], "createdAt": row["created_at"], "sentAt": row["sent_at"]}
            for row in rows]


def summary() -> dict[str, Any]:
    with connect() as db:
        rows = db.execute("SELECT status, COUNT(*) AS total FROM mail_queue GROUP BY status").fetchall()
    counts = {row["status"]: int(row["total"]) for row in rows}
    return {"counts": counts, "total": sum(counts.values()), **transport_status()}
