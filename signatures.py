"""Digital signature register.

Every account signs once — uploaded image or signature drawn on screen — and that
signature is the one stamped on the documents the person signs: the meeting
request / agenda approval form (Member Secretary and Chairperson) and, later, the
approved Minutes of Meeting.

Design notes
------------
* One signature per account, replaceable at any time; the *previous* signature is
  kept as a version row so a signed document can always be traced to the exact
  image that was used (``document`` + ``version`` columns on the workflow states).
* Storage is a file under ``data/signatures/<user-id>-v<n>.png`` plus a row in
  ``user_signatures``; the DB row carries the SHA-256 of the stored bytes so a
  signature on a downloaded PDF can be verified against the register.
* Sign-in does not depend on a signature (the OTP still works), but every
  state-changing API call is refused until the account has one — that is what
  makes the "ask on first login" rule server-enforced rather than cosmetic.
* Only PNG/JPEG input, re-encoded to PNG with a white background and a hard size
  cap. An SVG or a PDF is rejected because it cannot be embedded safely.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
from pathlib import Path
from typing import Any

from PIL import Image

from auth_store import DATA_DIR, connect, now_iso

SIGNATURE_ROOT = Path(os.environ.get("DAC_SIGNATURE_ROOT", DATA_DIR / "signatures"))
SIGNATURE_ROOT.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024          # 2 MB on the wire
MAX_FINAL_WIDTH = 1200                      # px, after re-encoding
MAX_FINAL_HEIGHT = 600
MIN_WIDTH = 120                             # below this a signature is not legible in print
MIN_HEIGHT = 40
DATA_URL_RE = re.compile(r"^data:image/(png|jpe?g);base64,(?P<payload>[A-Za-z0-9+/=\s]+)$", re.I)

METHODS = {"draw": "Drawn on screen", "upload": "Uploaded image"}


def init_signatures() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS user_signatures (
            user_id TEXT PRIMARY KEY,
            email TEXT NOT NULL COLLATE NOCASE,
            file_name TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT 'upload',
            version INTEGER NOT NULL DEFAULT 1,
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            bytes INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_signature_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE,
            file_name TEXT NOT NULL,
            version INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            retired_at TEXT NOT NULL
        );
        """)


def _decode_payload(payload: str, filename: str = "") -> bytes:
    """Accept a data URL, raw base64, or raw image bytes."""
    text = (payload or "").strip()
    if not text:
        raise ValueError("Provide a signature image.")
    match = DATA_URL_RE.match(text)
    if match:
        text = match.group("payload")
    elif text[:5].lower() == "data:":
        raise ValueError("Only PNG or JPEG signature images are accepted.")
    try:
        blob = base64.b64decode(re.sub(r"\s+", "", text), validate=True)
    except Exception:
        blob = b""
    if not blob and os.path.isfile(text):
        blob = Path(text).read_bytes()
    if not blob:
        raise ValueError("The signature image could not be read. Upload a PNG or JPEG file.")
    if len(blob) > MAX_UPLOAD_BYTES:
        raise ValueError("The signature image is larger than 2 MB. Use a smaller image.")
    return blob


def _normalise(blob: bytes) -> tuple[bytes, int, int]:
    """Re-encode to a trimmed PNG on a white background so print output is clean."""
    try:
        image = Image.open(io.BytesIO(blob))
        image.load()
    except Exception as exc:  # pragma: no cover - depends on input file
        raise ValueError("That file is not a readable image. Use a PNG or JPEG signature.") from exc
    if image.mode in {"RGBA", "LA", "P"}:
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        background.alpha_composite(image)
        image = background.convert("RGB")
    else:
        image = image.convert("RGB")
    # Trim the white margin so the signature sits tight in the PDF cell.
    grayscale = image.convert("L").point(lambda value: 255 if value < 245 else 0)
    bbox = grayscale.getbbox()
    if bbox:
        image = image.crop(bbox)
    if image.width < MIN_WIDTH or image.height < MIN_HEIGHT:
        raise ValueError("The signature is too small to print. Use an image at least "
                         f"{MIN_WIDTH}×{MIN_HEIGHT} px.")
    if image.width > MAX_FINAL_WIDTH or image.height > MAX_FINAL_HEIGHT:
        image.thumbnail((MAX_FINAL_WIDTH, MAX_FINAL_HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), image.width, image.height


def save_signature(user: dict, payload: str, method: str = "upload") -> dict[str, Any]:
    """Store (or replace) one account's signature and return its record."""
    if method not in METHODS:
        method = "upload"
    blob, width, height = _normalise(_decode_payload(payload))
    checksum = hashlib.sha256(blob).hexdigest()
    user_id = str(user["id"])
    email = str(user["email"]).lower()
    stamp = now_iso()
    with connect() as db:
        current = db.execute("SELECT * FROM user_signatures WHERE user_id=?", (user_id,)).fetchone()
        if current and str(current["sha256"]) == checksum and (SIGNATURE_ROOT / current["file_name"]).exists():
            # Same image as last time: keep the version, do not churn the history.
            return get_signature(user_id) or {}
        version = int(current["version"]) + 1 if current else 1
        if current:
            db.execute("""INSERT INTO user_signature_history(user_id,email,file_name,version,sha256,retired_at)
                          VALUES(?,?,?,?,?,?)""",
                       (user_id, email, current["file_name"], current["version"], current["sha256"], stamp))
        file_name = f"{user_id}-v{version}.png"
        (SIGNATURE_ROOT / file_name).write_bytes(blob)
        previous = current["file_name"] if current else ""
        db.execute("""INSERT INTO user_signatures(user_id,email,file_name,method,version,width,height,bytes,sha256,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(user_id) DO UPDATE SET file_name=excluded.file_name, email=excluded.email,
                          method=excluded.method, version=excluded.version, width=excluded.width,
                          height=excluded.height, bytes=excluded.bytes, sha256=excluded.sha256,
                          updated_at=excluded.updated_at""",
                   (user_id, email, file_name, method, version, width, height, len(blob), checksum,
                    current["created_at"] if current else stamp, stamp))
        db.commit()
    if previous and previous != file_name:
        try:
            (SIGNATURE_ROOT / previous).unlink(missing_ok=True)
        except OSError:
            pass
    return get_signature(user_id) or {}


def _row_dict(row: Any) -> dict[str, Any]:
    return {
        "userId": row["user_id"], "email": row["email"], "fileName": row["file_name"],
        "method": row["method"], "methodLabel": METHODS.get(row["method"], row["method"]),
        "version": int(row["version"]), "width": int(row["width"]), "height": int(row["height"]),
        "bytes": int(row["bytes"]), "sha256": row["sha256"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        "url": f"/api/signature/{row['user_id']}.png",
    }


def get_signature(user_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM user_signatures WHERE user_id=?", (user_id,)).fetchone()
    return _row_dict(row) if row else None


def signature_for_email(email: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM user_signatures WHERE email=?", (str(email or "").lower(),)).fetchone()
    return _row_dict(row) if row else None


def signature_path(record: dict[str, Any] | None) -> Path | None:
    """The stored image for a signature record *or* a workflow stamp.

    ``get_signature()`` returns ``fileName``; a stamp written into a workspace
    carries ``signatureFile``. Both point at the same file, so both are accepted —
    otherwise a document would print "Signature awaited" for someone who signed.
    """
    if not record:
        return None
    name = str(record.get("fileName") or record.get("signatureFile") or "")
    path = SIGNATURE_ROOT / name if name else None
    return path if path and path.is_file() else None


def has_signature(user: dict | None) -> bool:
    if not user:
        return False
    return bool(get_signature(str(user["id"])))


def history(user_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM user_signature_history WHERE user_id=? ORDER BY id DESC",
                          (user_id,)).fetchall()
    return [{"fileName": row["file_name"], "version": int(row["version"]), "sha256": row["sha256"],
             "retiredAt": row["retired_at"]} for row in rows]


def stamp(user: dict | None) -> dict[str, Any]:
    """The evidence block written into a workflow state when someone signs."""
    record = get_signature(str(user["id"])) if user else None
    return {
        "name": (user or {}).get("name") or "",
        "email": (user or {}).get("email") or "",
        "designation": (user or {}).get("designation") or "",
        "signedAt": now_iso(),
        "signatureVersion": record["version"] if record else 0,
        "signatureSha256": record["sha256"] if record else "",
        "signatureFile": record["fileName"] if record else "",
    }
