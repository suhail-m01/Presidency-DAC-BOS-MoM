from __future__ import annotations

import csv
import hashlib
import hmac
import html
import io
import json
import mimetypes
import os
import re
import requests
import secrets
import threading
import time as time_module
import uuid
from datetime import datetime, time as time_value, timedelta
from functools import wraps
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

from flask import Flask, jsonify, request, redirect, session, send_file
import dac_registry
import r1_registry
from auth_store import (
    ROLES, add_user as db_add_user, chairperson_candidates, connect,
    count_active_admins, is_eligible_chairperson,
    create_upload_record, get_catalog, get_upload_record,
    get_user_by_email, get_user_by_id, get_workspace, init_db, latest_pending_workspace,
    list_pending_workspaces, list_users, list_workspaces_for_owner, owner_for_workspace,
    save_workspace, update_user as db_update_user, verify_login_code, workspace_access_for_email,
    workspace_for_owner, store_login_code,
    create_api_token, resolve_api_token, revoke_api_token,
)

# Directory profile fields the admin UI may set alongside name/role/scope
# ("employeeCode" is the API spelling of the users.employee_code column).
PROFILE_FIELDS = ("employeeCode", "qualification", "specialization", "phone", "office")

# ------------------------------------------------------------------- OAuth SSO
# Google / Microsoft Entra ID federation. Reads client credentials from the
# environment (.env). Without them the corresponding sign-in button reports a
# clear configuration message instead of failing silently.
GOOGLE_CLIENT_ID = str(os.environ.get("GOOGLE_CLIENT_ID", "")).strip()
GOOGLE_CLIENT_SECRET = str(os.environ.get("GOOGLE_CLIENT_SECRET", "")).strip()
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_SCOPE = "openid email profile"

MICROSOFT_CLIENT_ID = str(os.environ.get("MICROSOFT_CLIENT_ID", "")).strip()
MICROSOFT_CLIENT_SECRET = str(os.environ.get("MICROSOFT_CLIENT_SECRET", "")).strip()
MICROSOFT_TENANT_ID = str(os.environ.get("MICROSOFT_TENANT_ID", "common")).strip()
MICROSOFT_AUTH_URL = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/oauth2/v2.0/token"
MICROSOFT_USERINFO_URL = "https://graph.microsoft.com/v1.0/me"
MICROSOFT_SCOPE = "openid email profile"


def _oauth_redirect_uri(provider: str) -> str:
    base = request.url_root.rstrip("/")
    return f"{base}/api/auth/{provider}/callback"


def _exchange_code_for_token(provider: str, code: str) -> dict:
    if provider == "google":
        data = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _oauth_redirect_uri("google"),
        }
        resp = requests.post(GOOGLE_TOKEN_URL, data=data, timeout=20)
    else:
        data = {
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _oauth_redirect_uri("microsoft"),
            "scope": MICROSOFT_SCOPE,
        }
        resp = requests.post(MICROSOFT_TOKEN_URL, data=data, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def _get_userinfo(provider: str, access_token: str) -> dict:
    if provider == "google":
        resp = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    else:
        resp = requests.get(
            MICROSOFT_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    if not resp.ok:
        raise RuntimeError(f"User info request failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def _finalize_oauth_user(user: dict, provider: str) -> tuple:
    """Set the Flask session + bearer token for an OAuth-authenticated user."""
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    issued = create_api_token(user, csrf=session["csrf_token"])
    signature = signature_store.get_signature(str(user["id"]))
    audit.record("oauth_signin", actor=user["email"],
                 details={"provider": provider, "email": user["email"]})
    return (user, session["csrf_token"], issued["token"], issued["expiresAt"], signature)


def _oauth_callback(provider: str):
    state = request.args.get("state", "")
    expected_state = session.pop("oauth_state", None)
    if not state or state != expected_state:
        return redirect(f"/?oauth=error&message=Invalid+OAuth+state+parameter.")
    error = request.args.get("error")
    if error:
        return redirect(f"/?oauth=error&message={urlencode({'message': error})}")
    code = request.args.get("code")
    if not code:
        return redirect("/?oauth=error&message=No+authorization+code+received.")
    try:
        token_data = _exchange_code_for_token(provider, code)
        user_info = _get_userinfo(provider, token_data["access_token"])
    except Exception as exc:
        app.logger.exception("OAuth callback failed for %s", provider)
        return redirect(f"/?oauth=error&message={urlencode({'message': str(exc)[:120]})}")

    if provider == "google":
        email = str(user_info.get("email", "")).strip().lower()
        name = user_info.get("name", "") or ""
    else:
        email = str(user_info.get("mail") or user_info.get("userPrincipalName", "")).strip().lower()
        name = user_info.get("displayName", "") or ""

    if not email or "@" not in email:
        return redirect("/?oauth=error&message=Could+not+retrieve+email+from+provider.")

    user = get_user_by_email(email, active_only=True)
    if not user:
        return redirect(f"/?oauth=error&message={urlencode({'message': f'No active account found for {email}. Contact the System Administrator.'})}")

    _user, csrf_token, token, expires_at, signature = _finalize_oauth_user(user, provider)
    return redirect(f"/?oauth=ok&provider={provider}&email={urlencode(email)}")
from PIL import Image as PILImage
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_module
from reportlab.platypus import (
    Image as PDFImage,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from werkzeug.utils import secure_filename

from ai_verify import probe as ai_probe, provider_status as ai_provider_status, verify as ai_verify_mom
from resolution_triage import ACTIONABLE_CATEGORIES, CATEGORY_LABELS, triage_resolutions
import agenda_library
import archive as committee_archive
import atr as atr_store
import atr_pdf
import audit
import committees as committee_registry
import documents as document_vault
import external_report
import mailer as mail_queue
import notifications as notification_store
import request_form as request_document
import signatures as signature_store
from doc_theme import (
    BODY_SIZE,
    FOOTNOTE_SIZE,
    HEADING_SIZE,
    TITLE_SIZE,
    font_status as document_font_status,
    leading as themed_leading,
    pdf_font,
)
from mom_docx import build_mom_docx
from mom_shared import (
    agenda_document_title as _agenda_document_title,
    annexure_entries,
    annexure_refs as _annexure_refs,
    document_label as _document_label,
    format_date_dmy as _format_date_dmy,
    item_has_no_resolution as _item_has_no_resolution,
    item_resolution as _item_resolution,
    meeting_description as _meeting_description,
    migrate_resolution_keys as _migrate_resolution_keys,
    numeric_meeting_number as _numeric_meeting_number,
    ordinal as _ordinal,
    reference_number as _reference_number,
    sorted_members as _sorted_members,
    without_name_prefix as _without_name_prefix,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTBOX_PATH = DATA_DIR / "outbox.json"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 250
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".xlsx", ".pptx", ".txt", ".csv"
}
FILE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
COLLEGE_TZ = ZoneInfo("Asia/Kolkata")
NAVY = colors.HexColor("#172b45")
MUTED = colors.HexColor("#617084")
RULE = colors.HexColor("#d7dee5")

app = Flask(__name__, static_folder=None)
APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
if IS_PRODUCTION and not os.environ.get("FLASK_SECRET_KEY"):
    raise RuntimeError("FLASK_SECRET_KEY must be configured for production.")


def _session_secret() -> str:
    """The key that signs session cookies — kept across restarts.

    This used to be regenerated with ``secrets.token_urlsafe`` on every start, so each
    restart (or upgrade, or container bounce) quietly invalidated every signed-in
    browser: the shell still rendered, every API call answered 401 and pages such as
    the access directory came up empty. The key is now written once to a private file
    and reused, so a restart keeps people signed in.
    """
    from_env = os.environ.get("FLASK_SECRET_KEY")
    if from_env:
        return from_env
    key_path = DATA_DIR / ".session_secret"
    try:
        if key_path.exists():
            existing = key_path.read_text(encoding="utf-8").strip()
            if existing:
                try:
                    key_path.chmod(0o600)   # a file created by an older build may be 0644
                except OSError:
                    pass
                return existing
        generated = secrets.token_urlsafe(48)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(generated, encoding="utf-8")
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        return generated
    except OSError:
        # A read-only data directory must not stop the application from booting.
        return secrets.token_urlsafe(48)

#: Sign-in is a one-time code delivered by email. When no mail transport is
#: configured the code is written to the server console (and the mail outbox), so a
#: fresh install can still be operated. Outside production the code may also be
#: echoed to the browser for automated tests; production never echoes it.
DEV_ECHO_OTP = (not IS_PRODUCTION) and os.environ.get("DEV_ECHO_OTP", "1").strip().lower() in {"1", "true", "yes"}
#: Clock hooks used by the automated suites (advance a meeting past its scheduled
#: end). They are inert in production, where the real clock governs the workflow.
TEST_HOOKS = (not IS_PRODUCTION) and os.environ.get(
    "DAC_TEST_HOOKS", "1").strip().lower() in {"1", "true", "yes"}

#: The demonstration fast-forward. A meeting's minutes stay locked until its scheduled end
#: has passed AND the meeting is marked completed — which is the right rule, and useless in
#: a twenty-minute demonstration. This switch adds a clearly-labelled button that moves one
#: meeting's clock into the past so the workflow can be shown end to end.
#:
#: It is off in production, always: no demo control can exist in the live product. Set
#: DAC_FAST_TRACK=0 to switch it off in a demonstration build as well.
FAST_TRACK = (not IS_PRODUCTION) and os.environ.get(
    "DAC_FAST_TRACK", "1").strip().lower() in {"1", "true", "yes"}

#: The compiled single-page app. Served by this process so one command runs the
#: whole product on one origin; `npm run dev` (Vite, port 3000) is only for frontend work.
DIST_DIR = Path(__file__).resolve().parent / "frontend" / "dist"
app.config.update(
    SECRET_KEY=_session_secret(),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES + 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=APP_ENV == "production" or os.environ.get("SESSION_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes"},
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)
init_db()
audit.init_audit()
document_vault.init_documents()
notification_store.init_notifications()
external_report.init_reports()
atr_store.init_atr()
signature_store.init_signatures()
mail_queue.init_mailer()

ROLE_CHOICES = sorted(ROLES)


def get_current_user():
    user_id = session.get("user_id")
    return get_user_by_id(user_id) if user_id else None


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            session.clear()
            return jsonify({"error": "Sign in with an active, allow-listed account."}), 401
        return fn(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if not user or user["role"] not in roles:
                return jsonify({"error": "Your account does not have permission for this action."}), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def _csrf_exempt_path(path: str) -> bool:
    return path in {"/api/auth/request-code", "/api/auth/verify-code"}


@app.route("/<path:_any>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
def cors_preflight(_any: str = ""):
    """Answer the browser's preflight for an embedded (opaque-origin) client."""
    return ("", 204)


def _bearer_token() -> str:
    """The `Authorization: Bearer …` token, when the client sent one."""
    header = str(request.headers.get("Authorization") or "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


@app.before_request
def authenticate_bearer_token():
    """Let a token stand in for the session cookie.

    A browser that shows the app inside a sandboxed iframe cannot read or store cookies
    (the document has an opaque origin), so the cookie session never survives sign-in.
    The token is opaque, stored hashed server-side, and re-checked on every request, so a
    cookie-less client gets exactly the same authorisation the cookie would have given.
    """
    token = _bearer_token()
    if not token:
        return None
    record = resolve_api_token(token)
    if not record:
        return None  # An unknown/expired token is simply "not signed in".
    session["user_id"] = record["userId"]
    session["csrf_token"] = record["csrf"]
    session.permanent = True
    return None


@app.before_request
def enforce_session_csrf():
    if not request.path.startswith("/api/") or request.method in {"GET", "HEAD", "OPTIONS"} or _csrf_exempt_path(request.path):
        return None
    if not session.get("user_id"):
        return None  # The route-level decorator returns the authentication error.
    expected = str(session.get("csrf_token") or "")
    supplied = str(request.headers.get("X-CSRF-Token") or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        return jsonify({"error": "CSRF verification failed. Refresh the application and retry."}), 403
    return None


#: Sent on every response. The interface is one origin with no third-party scripts, so
#: the policy can be tight: nothing may be framed, nothing may load from another host,
#: and a signature or an uploaded annexure can only come back from this origin or as a
#: data: URL.
def _preview_hosted() -> bool:
    """True when the app is being served inside a hosted preview pane.

    The preview pane puts the interface in an iframe whose parent is the operator's
    workspace — a *different origin* — so a policy restricted to `'self'` blocks the frame
    outright and the pane shows a blank error page. A hosted preview is detected from the
    sandbox environment it runs in; a normal deployment on a real server never sets this,
    so it keeps the strict default.
    """
    if os.environ.get("DAC_PREVIEW", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return os.environ.get("E2B_SANDBOX", "").strip().lower() in {"1", "true", "yes"}


def frame_ancestors() -> str:
    """Who may embed this application.

    FRAME_ANCESTORS wins when set (a deployment that never frames it should set
    `'none'`). Otherwise: a hosted preview pane may embed it — its parent origin is not
    this application, so `'self'` would leave the operator with a blank pane — and every
    other deployment is framed by itself only.
    """
    configured = os.environ.get("FRAME_ANCESTORS", "").strip()
    if configured:
        return configured
    return "*" if _preview_hosted() else "'self'"


def content_security_policy() -> str:
    """The policy for one response, naming the origin this page is actually served from.

    `'self'` alone is not enough. When the interface is displayed inside a sandboxed
    iframe — the operator's preview pane does exactly that — the document has an opaque
    origin, and `'self'` then matches nothing: the browser refuses to load the bundle and
    the page never boots. The request's own host is therefore written into the policy
    alongside `'self'`, which allows this application and nothing else.
    In E2B the external preview host is https://*.e2b.app (Host header is forwarded
    as X-Forwarded-Host, not as Host), so that origin must be allowed too.
    """
    origin = request.host_url.rstrip("/")
    # E2B proxy forwards the public host in X-Forwarded-Host / X-Forwarded-Proto
    xf_host = (request.headers.get("X-Forwarded-Host") or "").strip()
    xf_proto = (request.headers.get("X-Forwarded-Proto") or request.scheme).strip()
    extra = ""
    if xf_host:
        # allow the public preview origin, e.g. https://8000-xxxx.e2b.app
        extra = f" {xf_proto}://{xf_host}"
    # Also allow any e2b.app preview host when running inside E2B
    e2b_extra = " https://*.e2b.app" if _preview_hosted() else ""
    sources = f"'self' {origin}{extra}{e2b_extra}"
    return "; ".join((
        f"default-src {sources}",
        f"script-src {sources}",
        f"style-src {sources} 'unsafe-inline'",
        f"img-src {sources} data: blob:",
        f"font-src {sources}",
        f"connect-src {sources}",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        f"frame-ancestors {frame_ancestors()}",
    ))


def _embedded_origin() -> str:
    """The `Origin` of an embedding preview pane, when the client sent one.

    A page shown inside a sandboxed iframe runs in an opaque origin, so it reports
    `Origin: null` and — despite the same URL — every subresource and API call is a
    cross-origin request. Without a CORS answer the browser refuses to load the bundle
    and the app never starts, which is exactly what happened in the operator's preview.
    Only `null` and this application's own origin are answered, and the answer is never
    credentialed (`Access-Control-Allow-Credentials` is not sent), so a third-party page
    gains nothing: it still needs this account's bearer token to read anything.
    """
    origin = str(request.headers.get("Origin") or "").strip()
    if not origin:
        return ""
    if origin == "null" or origin == request.host_url.rstrip("/"):
        return origin
    return ""


@app.after_request
def security_headers(response):
    origin = _embedded_origin()
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-CSRF-Token"
        response.headers["Access-Control-Max-Age"] = "600"
        response.headers["Vary"] = "Origin"
    response.headers.setdefault("Content-Security-Policy", content_security_policy())
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # X-Frame-Options cannot express "any ancestor", and a browser that sees it alongside a
    # permissive frame-ancestors still refuses the frame. It is therefore only sent when the
    # policy actually restricts framing to this origin.
    _ancestors = frame_ancestors()
    if _ancestors == "'self'":
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    elif _ancestors == "'none'":
        response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if IS_PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


#: Serialises read-modify-write on the small JSON logs. Without it two requests that
#: arrive together can each read the same file and the later write erases the earlier
#: record — the invitation log lost entries under load.
_LOG_LOCK = threading.Lock()


def _append_json(path: Path, value: dict, keep: int = 500) -> None:
    with _LOG_LOCK:
        rows = _read_json(path, [])
        rows.append(value)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(rows[-keep:], ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)          # atomic: a reader never sees a half-written log


def get_upload_path(file_id: str) -> Path | None:
    if not FILE_ID_RE.fullmatch(file_id or ""):
        return None
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    return matches[0] if len(matches) == 1 else None


def read_uploaded_bytes(file_id: str) -> bytes | None:
    path = get_upload_path(file_id)
    if not path or not path.is_file():
        return None
    return path.read_bytes()


def validate_mom(payload: dict) -> dict:
    """Verify Discussion/Resolution content for every agenda item.

    Delegates to :mod:`ai_verify`, which uses a hosted model when an AI key is
    configured and always falls back to the transparent offline rules in
    :mod:`content_check`. The returned shape is stable for the UI:

    ``mode`` / ``engine`` / ``summary`` / ``items[{agendaNo, agendaTitle,
    status, checks[{name, status, score, message, evidence, suggestion}]}]``.
    """
    items = payload.get("momItems") or []
    for item in items:
        _migrate_resolution_keys({"momItems": [item]})
    return ai_verify_mom(items, payload.get("meeting") or None)


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=True).replace("\n", "<br/>")


def _styles():
    """House style: Cambria (Caladea metrics), 12 pt sub-headings, 11 pt body, 1.15 spacing."""
    base = getSampleStyleSheet()
    body, heading, title = BODY_SIZE, HEADING_SIZE, TITLE_SIZE
    return {
        "title": ParagraphStyle("DACtitle", parent=base["Title"], fontName=pdf_font(bold=True), fontSize=title,
                                leading=themed_leading(title), textColor=colors.black, alignment=TA_CENTER,
                                spaceAfter=round(themed_leading(title) * 0.4, 2)),
        "subtitle": ParagraphStyle("DACsubtitle", parent=base["Normal"], fontName=pdf_font(bold=True), fontSize=heading,
                                   leading=themed_leading(heading), textColor=colors.black, alignment=TA_CENTER,
                                   spaceAfter=round(themed_leading(heading) * 0.3, 2)),
        "h1": ParagraphStyle("DACh1", parent=base["Heading1"], fontName=pdf_font(bold=True), fontSize=heading,
                             leading=themed_leading(heading), textColor=colors.black,
                             spaceBefore=round(themed_leading(heading) * 0.5, 2),
                             spaceAfter=round(themed_leading(heading) * 0.4, 2)),
        "h2": ParagraphStyle("DACh2", parent=base["Heading2"], fontName=pdf_font(bold=True), fontSize=heading,
                             leading=themed_leading(heading), textColor=colors.black,
                             spaceBefore=round(themed_leading(heading) * 0.5, 2),
                             spaceAfter=round(themed_leading(heading) * 0.3, 2)),
        "body": ParagraphStyle("DACbody", parent=base["BodyText"], fontName=pdf_font(), fontSize=body,
                               leading=themed_leading(body), textColor=colors.black,
                               spaceAfter=round(themed_leading(body) * 0.5, 2)),
        "small": ParagraphStyle("DACsmall", parent=base["BodyText"], fontName=pdf_font(), fontSize=body,
                                leading=themed_leading(body), textColor=colors.black,
                                spaceAfter=round(themed_leading(body) * 0.4, 2)),
        "table": ParagraphStyle("DACtable", parent=base["BodyText"], fontName=pdf_font(), fontSize=body,
                                leading=themed_leading(body), textColor=colors.black),
        "table_head": ParagraphStyle("DACtablehead", parent=base["BodyText"], fontName=pdf_font(bold=True),
                                     fontSize=body, leading=themed_leading(body), textColor=colors.white),
        "table_head_plain": ParagraphStyle("DACtableheadplain", parent=base["BodyText"], fontName=pdf_font(bold=True),
                                           fontSize=body, leading=themed_leading(body), textColor=colors.black),
        "center": ParagraphStyle("DACcenter", parent=base["BodyText"], fontName=pdf_font(), fontSize=body,
                                 leading=themed_leading(body), textColor=colors.black, alignment=TA_CENTER),
    }


#: Height of the band that is masked at the foot of every merged page.  An
#: annexure keeps whatever footer it was printed with; the band hides it so the
#: finished document carries exactly one, continuous page number.
FOOTER_MASK_MM = float(os.environ.get("PDF_FOOTER_MASK_MM", "14"))


def _on_page(canvas, doc):
    """Per-document hook. Page numbers are stamped once, after merging.

    Drawing them here would repeat the number inside every annexure that is
    appended later, so this hook deliberately stays empty: the single
    :func:`_stamp_page_numbers` pass owns the footer for the whole document.
    """


def _footer_overlay(width: float, height: float, number: int, total: int,
                    committee: str = "DAC") -> "PdfReader":
    """One transparent page containing the uniform footer for a merged page."""
    buffer = io.BytesIO()
    canvas = canvas_module.Canvas(buffer, pagesize=(width, height))
    canvas.saveState()
    # Mask the band so an annexure's own printed page number disappears.
    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, width, FOOTER_MASK_MM * mm, stroke=0, fill=1)
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, (FOOTER_MASK_MM + 1.5) * mm, width - 18 * mm, (FOOTER_MASK_MM + 1.5) * mm)
    canvas.setFont(pdf_font(), FOOTNOTE_SIZE)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, (FOOTER_MASK_MM - 4.5) * mm, f"{committee} · Minutes of Meeting")
    canvas.drawRightString(width - 18 * mm, (FOOTER_MASK_MM - 4.5) * mm, f"Page {number} of {total}")
    canvas.restoreState()
    canvas.save()
    buffer.seek(0)
    return PdfReader(buffer)


def _stamp_page_numbers(writer: "PdfWriter", committee: str = "DAC") -> "PdfWriter":
    """Stamp ``Page X of Y`` continuously across minutes, index and annexures."""
    total = len(writer.pages)
    for index, page in enumerate(writer.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        page.merge_page(_footer_overlay(width, height, index, total, committee).pages[0])
    return writer


def _as_pdf_image(file_id: str, max_width: float, max_height: float):
    raw = read_uploaded_bytes(file_id)
    if not raw:
        return None
    image = PILImage.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((int(max_width * 2), int(max_height * 2)))
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=88)
    stream.seek(0)
    flowable = PDFImage(stream, width=max_width, height=max_height, kind="proportional")
    flowable.hAlign = "CENTER"
    return flowable


def _image_to_pdf(raw: bytes, title: str) -> bytes:
    image = PILImage.open(io.BytesIO(raw)).convert("RGB")
    width_px, height_px = image.size
    page = A4 if height_px >= width_px else (A4[1], A4[0])
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=page, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=22 * mm, bottomMargin=20 * mm)
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=90)
    stream.seek(0)
    styles = _styles()
    story = [Paragraph(_escape(title), styles["h1"]), Spacer(1, 6 * mm), PDFImage(stream, width=doc.width, height=doc.height - 15 * mm, kind="proportional")]
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()


def _office_attachment_pdf(file_path: Path, display_name: str, agenda_title: str, label: str) -> bytes:
    """Render supported Office files as readable text and table pages."""
    ext = file_path.suffix.lower()
    styles = _styles()
    story = [
        Paragraph(_escape(f"Annexure {label} · {display_name}"), styles["h1"]),
        Paragraph(_escape(f"Related agenda: {agenda_title}"), styles["small"]),
        Spacer(1, 4 * mm),
    ]

    if ext == ".docx":
        from docx import Document

        docx = Document(str(file_path))
        for paragraph in docx.paragraphs:
            if paragraph.text.strip():
                story.append(Paragraph(_escape(paragraph.text), styles["body"]))
        for table_index, table in enumerate(docx.tables, start=1):
            story.append(Paragraph(f"Table {table_index}", styles["h2"]))
            for row_index, row in enumerate(table.rows, start=1):
                row_text = "  |  ".join(cell.text.strip() for cell in row.cells)
                story.append(Paragraph(_escape(f"Row {row_index}: {row_text}"), styles["small"]))

    elif ext == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(file_path, read_only=True, data_only=True)
        for sheet in workbook.worksheets:
            story.append(Paragraph(_escape(f"Worksheet: {sheet.title}"), styles["h2"]))
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = ["" if value is None else str(value) for value in row]
                while values and not values[-1]:
                    values.pop()
                if values:
                    story.append(Paragraph(_escape(f"Row {row_index}: " + " | ".join(values)), styles["small"]))
        workbook.close()

    elif ext == ".pptx":
        from pptx import Presentation

        presentation = Presentation(str(file_path))
        for slide_index, slide in enumerate(presentation.slides, start=1):
            story.append(Paragraph(_escape(f"Slide {slide_index}"), styles["h2"]))
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False) and shape.text.strip():
                    story.append(Paragraph(_escape(shape.text), styles["body"]))
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        story.append(Paragraph(_escape(" | ".join(cell.text for cell in row.cells)), styles["small"]))

    elif ext in {".txt", ".csv"}:
        text = file_path.read_text(encoding="utf-8-sig", errors="replace")
        lines = []
        if ext == ".csv":
            lines = [" | ".join(row) for row in csv.reader(io.StringIO(text))]
        else:
            lines = text.splitlines()
        for line in lines:
            story.append(Paragraph(_escape(line) if line.strip() else "&nbsp;", styles["small"]))

    else:
        story.append(Paragraph("This file type cannot be rendered inline; the original file is attached.", styles["body"]))

    if len(story) == 3:
        story.append(Paragraph("No extractable text was found in this file.", styles["body"]))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=20 * mm, title=display_name)
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()


def _annexure_index_pdf(entries: list[dict]) -> bytes:
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=22 * mm)
    story = [Paragraph("Annexure Index", styles["title"]), Paragraph("Supporting documents included after the MoM pages", styles["subtitle"]), Spacer(1, 6 * mm)]
    rows = [[Paragraph("Annexure", styles["table_head"]), Paragraph("Agenda item", styles["table_head"]), Paragraph("File", styles["table_head"])]]
    for entry in entries:
        rows.append([
            Paragraph(_escape(f"{entry['label']}"), styles["table"]),
            Paragraph(_escape(f"Agenda {entry['agendaNo']}: {entry['agendaTitle']}"), styles["table"]),
            Paragraph(_escape(entry["name"]), styles["table"]),
        ])
    table = LongTable(rows, colWidths=[25 * mm, 75 * mm, doc.width - 100 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("GRID", (0, 0), (-1, -1), 0.45, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(table)
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()


def _annexure_divider_pdf(entry: dict) -> bytes:
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=65 * mm, bottomMargin=25 * mm)
    story = [
        Paragraph(_escape(f"Annexure {entry['label']}"), styles["title"]),
        Spacer(1, 5 * mm),
        Paragraph(_escape(entry["name"]), styles["h1"]),
        Paragraph(_escape(f"Related agenda: {entry['agendaTitle']}"), styles["subtitle"]),
    ]
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()


def _attach_signature_images(state: dict) -> dict:
    """Copy the drawn signature images into the minute stamps for the Word export."""
    review = dict(state.get("momReview") or {})
    if not review:
        return state
    for key in ("secretarySignature", "chairSignature", "officeSignature"):
        stamp = review.get(key)
        if not isinstance(stamp, dict) or not stamp:
            continue
        path = signature_store.signature_path(signature_store.signature_for_email(stamp.get("email") or ""))
        if path is not None:
            try:
                review[key] = {**stamp, "imageBytes": path.read_bytes()}
            except OSError:
                review[key] = stamp
    return {**state, "momReview": review}


def _readable_stamp(value: object) -> str:
    """Any stored timestamp as ``27 Oct 2026, 09:14`` in the college's time zone."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(COLLEGE_TZ)
    return parsed.strftime("%d %b %Y, %H:%M")


def _mom_signatories(data: dict) -> list[dict]:
    """Who signed the minutes, with the image that was used, in signing order."""
    meeting = data.get("meeting") or {}
    review = data.get("momReview") or {}

    def _entry(role: str, name: str, designation: str, email: str, stamp: dict | None) -> dict:
        record = signature_store.signature_for_email(email) if stamp else None
        path = ""
        if record:
            resolved = signature_store.signature_path(record)
            path = str(resolved) if resolved else ""
        return {"role": role, "name": name or role, "designation": designation,
                "email": email, "signed": bool(stamp),
                "signedAt": str((stamp or {}).get("signedAt") or ""), "path": path}

    entries = [
        _entry("Member Secretary", str(meeting.get("secretaryName") or ""),
               "Member Secretary", str(meeting.get("secretaryEmail") or ""),
               review.get("secretarySignature")),
        _entry("Chairperson", str(meeting.get("chairName") or ""),
               "Chairperson", str(meeting.get("chairEmail") or ""), review.get("chairSignature")),
    ]
    # Academic Office signature removed for both DAC and BOS per user request 2026-11-10 — minutes carry only MS + Chairperson
    return entries


def _mom_signature_table(data: dict, styles, width: float):
    """The closing signature block of the minutes — drawn images, names and dates."""
    signatories = [row for row in _mom_signatories(data) if row["signed"] or row["role"] != "Academic Office"]
    columns = len(signatories)
    cell_width = width / max(1, columns)
    images: list[Any] = []
    labels: list[Any] = []
    for row in signatories:
        lines: list[str] = []
        path = row.get("path")
        if path and Path(path).is_file():
            images.append(PDFImage(str(path), width=min(cell_width - 10 * mm, 46 * mm), height=14 * mm,
                                   kind="proportional"))
        else:
            images.append(Paragraph("_____________________________", styles["center"]))
        lines.append(f"<b>{_escape(row['name'])}</b>")
        if row["designation"]:
            lines.append(_escape(row["designation"]))
        if row["signedAt"]:
            lines.append(_escape(f"Signed {_readable_stamp(row['signedAt'])}"))
        lines.append(f"<b>{_escape(row['role'])}</b>")
        labels.append(Paragraph("<br/>".join(lines), styles["center"]))
    table = Table([images, labels], colWidths=[cell_width] * columns)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
    ]))
    return table


def _request_signature_table(data: dict, styles, width: float, sec: dict, chair: dict):
    """The Notice signature block with drawn images — Member Secretary + Chairperson.

    The final downloaded PDF must carry both signatures (2026-11-13, item 11), not
    just printed names. Falls back to a ruled line when no image is on file.
    """
    meeting = data.get("meeting") or {}
    chair_approval = data.get("chairApproval") or {}
    rows = [
        ("Member Secretary", sec.get("name") or "Member Secretary",
         str(sec.get("email") or meeting.get("secretaryEmail") or ""),
         str(data.get("submittedAt") or "")),
        ("Chairperson", chair.get("name") or "Chairperson",
         str(chair.get("email") or meeting.get("chairEmail") or ""),
         str(chair_approval.get("signedAt") or chair_approval.get("decidedAt") or "")),
    ]
    cell_width = width / 2
    images: list[Any] = []
    labels: list[Any] = []
    for role, name, email, signed_at in rows:
        record = signature_store.signature_for_email(email) if email else None
        path = signature_store.signature_path(record) if record else None
        if path is not None and Path(path).is_file():
            images.append(PDFImage(str(path), width=min(cell_width - 10 * mm, 46 * mm),
                                   height=14 * mm, kind="proportional"))
        else:
            images.append(Paragraph("____________________________", styles["center"]))
        lines = [f"<b>{_escape(name)}</b>", _escape(role)]
        if signed_at:
            lines.append(_escape(f"Signed {_readable_stamp(signed_at)}"))
        labels.append(Paragraph("<br/>".join(lines), styles["center"]))
    table = Table([images, labels], colWidths=[cell_width] * 2)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
    ]))
    return table


def _format_date_long(value):
    """BOS style long date: 15th December 2025."""
    if not value:
        return ""
    try:
        from datetime import datetime
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y", "%d.%m.%Y"):
                try:
                    dt = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
            else:
                return str(value)
        else:
            dt = value
        day = dt.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{day}{suffix} {dt.strftime('%B %Y')}"
    except Exception:
        return str(value)

def _format_date_dmy(value):
    if not value:
        return ""
    try:
        from datetime import datetime
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y", "%d.%m.%Y"):
                try:
                    dt = datetime.strptime(value, fmt)
                    return dt.strftime("%d.%m.%Y")
                except ValueError:
                    continue
            return str(value)
        return value.strftime("%d.%m.%Y")
    except Exception:
        return str(value)

def _build_main_mom_pdf(data: dict) -> bytes:
    """BOS-exact DAC MoM — strictly replicates the 50-page 22nd BOSDOC structure, only BOS->DAC and content by input.

    Order (as in BOS):
    1. Cover (MODERN DESIGN / U N I V E R S I T Y + SCHOOL/DEPT + Committee + subtitle + www) — page 1, no photo
    2. Inner cover (SCHOOL/DEPT + Committee Documents for Approval) — page 2
    3. Table of Contents (S. No., Description, Page No.) — page 3
    4. MOM Request / NOTICE: Ref No/ Date, XXth MEETING NOTICE, paragraph, AGENDA list, TO Members & Invitees table, Copy to — pages 4-6
    5. Completed MOM: Ref No, Minutes of the Xth Meeting, paragraph, Members Present, Agendas with Discussion/Recommendations/Ref, Geo-Tagged Photos, Action Items, Signatures — pages 7-13
    6. Annexures as in BOS — pages 14-50, if annexures provided else placeholder
    Keeps one-page sections whole, continues only after part content.
    """
    styles = _styles()
    meeting = data.get("meeting") or {}
    all_members = _sorted_members(meeting.get("members") or [])
    present_members = [m for m in all_members if m.get("present", True)]
    mom_items = data.get("momItems") or data.get("items") or []
    photos = data.get("photos") or []
    actions = data.get("actionItems") or []
    additional = data.get("additionalDiscussions") or []

    buffer = io.BytesIO()
    width = A4[0] - 36*mm
    # Header/footer for BOS pages 4-50: SCHOOL/DEPT at top center blue, page number at bottom center
    school_hdr = _without_name_prefix(meeting.get('school'), 'School of').strip() or "__________"
    raw_dept = meeting.get('department') or ""
    dept_hdr = _without_name_prefix(raw_dept, 'Department of').strip() if str(raw_dept).strip() else ""
    if dept_hdr == "__________":
        dept_hdr = ""
    header_text = f"SCHOOL OF {school_hdr.upper()}" + (f" / DEPARTMENT OF {dept_hdr.upper()}" if dept_hdr else "")
    committee_name = committee_registry.name(meeting.get('committee'))
    committee_short = meeting.get('committee') or "DAC"
    meeting_no = meeting.get('meetingNo') or "02"
    meeting_ord = _ordinal(meeting_no)
    # Notice section carries Notice; Minutes section carries MoM.
    _stored_ref = str(meeting.get("referenceNo") or "")
    notice_reference = _stored_ref.replace("/MoM-", "/Notice-") if _stored_ref else _reference_number(meeting, "request")
    mom_reference = _stored_ref.replace("/Notice-", "/MoM-") if _stored_ref else _reference_number(meeting, "mom")
    reference = notice_reference
    # Date formatting: BOS uses "15th December 2025" for notice, "27.12.2025" for minutes — use dmy with ordinal for notice
    notice_date = _format_date_long(meeting.get('date'))  # e.g. 26th December 2025
    mom_date = _format_date_dmy(meeting.get('date'))  # 27.12.2025

    def header_footer(canvas, doc):
        canvas.saveState()
        # BOS-exact header/footer with logo and DAC on every page as in BOS (p4 has 1 image, p7 has 4 images)
        logo_path = Path(__file__).parent / "assets" / "presidency_logo.png"
        has_logo = logo_path.exists()
        # Logo on every page (BOS p4 has 1 image, p5 4 images, p7 4 images) at top-left
        if has_logo:
            try:
                canvas.drawImage(str(logo_path), 14*mm, A4[1] - 13*mm, width=22*mm, height=7*mm, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
        if doc.page >= 4:  # Header text only from page 4 onwards (BOS p4) — centered 7pt #0f2a44
            # BOS shows SCHOOL OF ENGINEERING / DEPARTMENT OF MECHANICAL ENGINEERING (7pt blue) — for DAC add DAC
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.HexColor("#0f2a44"))
            if dept_hdr:
                hdr = f"SCHOOL OF {school_hdr.upper()} / DEPARTMENT OF {dept_hdr.upper()} / {committee_name.upper()}"
            else:
                hdr = f"SCHOOL OF {school_hdr.upper()} / {committee_name.upper()}"
            canvas.drawCentredString(A4[0]/2, A4[1] - 14*mm, hdr)
        # Footer page number centered 8pt black (BOS p4,6,7,13 etc.)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#000000"))
        canvas.drawCentredString(A4[0]/2, 12*mm, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14*mm, rightMargin=14*mm,
        topMargin=12*mm, bottomMargin=18*mm,
        title=committee_registry.document_title(committee_short, "mom"),
        author=committee_name,
    )

    # ── Styles BOS-exact (from pdfminer): Cover 25pt Tahoma-Bold white, Body 10pt Cambria, TOC 12pt/14pt ──
    s_cover_modern = ParagraphStyle("CoverModern", parent=styles["small"], alignment=TA_CENTER, fontSize=9, leading=11, spaceAfter=0, textColor=colors.HexColor("#4a6582"))
    s_cover_univ = ParagraphStyle("CoverUniv", parent=styles["small"], alignment=TA_CENTER, fontSize=10, leading=12, spaceAfter=3, textColor=colors.HexColor("#162a5c"), fontName="Helvetica-Bold")
    s_banner_school = ParagraphStyle("BannerSchool", parent=styles["subtitle"], alignment=TA_CENTER, fontSize=12, leading=14, spaceAfter=1, textColor=colors.white, fontName="Helvetica-Bold")
    s_banner_dept = ParagraphStyle("BannerDept", parent=styles["subtitle"], alignment=TA_CENTER, fontSize=10, leading=12, spaceAfter=1, textColor=colors.white, fontName="Helvetica-Bold")
    s_banner_committee = ParagraphStyle("BannerCommittee", parent=styles["title"], alignment=TA_CENTER, fontSize=12, leading=14, spaceBefore=1, spaceAfter=1, textColor=colors.white, fontName="Helvetica-Bold")
    s_banner_sub = ParagraphStyle("BannerSub", parent=styles["subtitle"], alignment=TA_CENTER, fontSize=9, leading=11, spaceAfter=1, textColor=colors.white, fontName="Helvetica")
    s_inner_school = ParagraphStyle("InnerSchool", parent=styles["subtitle"], alignment=TA_CENTER, fontSize=11, leading=13, spaceAfter=1, textColor=colors.HexColor("#0f2a44"), fontName="Helvetica-Bold")
    s_inner_committee = ParagraphStyle("InnerCommittee", parent=styles["subtitle"], alignment=TA_CENTER, fontSize=11, leading=13, spaceAfter=1, textColor=colors.HexColor("#0f2a44"), fontName="Helvetica-Bold")
    s_toc_title = ParagraphStyle("TOCTitle", parent=styles["title"], alignment=TA_CENTER, fontSize=13, leading=15, spaceAfter=6, textColor=colors.HexColor("#0f2a44"), fontName="Helvetica-Bold")
    s_toc_head = ParagraphStyle("TOCHead", parent=styles["body"], alignment=TA_CENTER, fontSize=9, leading=10, textColor=colors.HexColor("#000000"), fontName="Helvetica-Bold")
    s_toc_item = ParagraphStyle("TOCItem", parent=styles["body"], alignment=TA_LEFT, fontSize=8, leading=10, textColor=colors.HexColor("#000000"))
    s_toc_page = ParagraphStyle("TOCPage", parent=styles["body"], alignment=TA_RIGHT, fontSize=8, leading=10, textColor=colors.HexColor("#000000"))
    s_notice_ref = ParagraphStyle("NoticeRef", parent=styles["small"], alignment=TA_LEFT, fontSize=8, leading=10, textColor=colors.HexColor("#000000"))
    s_notice_title = ParagraphStyle("NoticeTitle", parent=styles["title"], alignment=TA_CENTER, fontSize=10, leading=12, spaceAfter=4, textColor=colors.HexColor("#0f2a44"), fontName="Helvetica-Bold")
    s_body = ParagraphStyle("BodyExact", parent=styles["body"], alignment=TA_JUSTIFY, fontSize=10, leading=12, spaceAfter=2, textColor=colors.HexColor("#000000"), fontName="Helvetica")
    s_small = ParagraphStyle("SmallExact", parent=styles["small"], alignment=TA_LEFT, fontSize=8, leading=10, textColor=colors.HexColor("#000000"))
    s_agenda_title = ParagraphStyle("AgendaTitle", parent=s_body, alignment=TA_LEFT, fontSize=10, leading=12, spaceBefore=4, spaceAfter=2, textColor=colors.HexColor("#0f2a44"), fontName="Helvetica-Bold")
    s_label = ParagraphStyle("Label", parent=styles["body"], alignment=TA_LEFT, fontSize=8, leading=10, spaceBefore=2, spaceAfter=1, textColor=colors.HexColor("#000000"), fontName="Helvetica-Bold")
    s_sig = ParagraphStyle("Sig", parent=styles["body"], alignment=TA_LEFT, fontSize=8, leading=10, spaceBefore=4, textColor=colors.HexColor("#000000"))

    story = []

    # ── 1. COVER PAGE 1 — MODERN DESIGN / U N I V E R S I T Y + blue banner (no photo, as BOS) ──
    story.append(Paragraph("MODERN DESIGN", s_cover_modern))
    story.append(Paragraph("U&nbsp;&nbsp;N&nbsp;&nbsp;I&nbsp;&nbsp;V&nbsp;&nbsp;E&nbsp;&nbsp;R&nbsp;&nbsp;S&nbsp;&nbsp;I&nbsp;&nbsp;T&nbsp;&nbsp;Y", s_cover_univ))
    story.append(Spacer(1, 12*mm))
    # School / Department — if dept exists show both, else only school (as per user)
    banner_rows = []
    banner_rows.append([Paragraph(f"<b>SCHOOL OF {school_hdr.upper()}</b>", s_banner_school)])
    if dept_hdr:
        banner_rows.append([Paragraph(f"<b>DEPARTMENT OF {dept_hdr.upper()}</b>", s_banner_dept)])
    banner_rows.append([Paragraph(f"<b>{committee_name.upper()}</b>", s_banner_committee)])
    # Subtitle: BOS = Documents for Approval at the 29th Meeting of Academic Council; DAC = Minutes of the 2nd Meeting
    if committee_short == "BOS":
        banner_sub_txt = f"Documents for Approval at the {meeting_ord} Meeting of Academic Council"
    else:
        banner_sub_txt = f"Documents for Approval at the {meeting_ord} Meeting"
        # For DAC completed MOM we show Minutes; but cover for DAC request should mirror BOS Documents for Approval
        # Use Minutes for DAC to distinguish request vs MOM — keep as Minutes per earlier
        banner_sub_txt = f"Minutes of the {meeting_ord} Meeting"
    banner_rows.append([Paragraph(banner_sub_txt, s_banner_sub)])
    # Perfect banner: use BOS banner image (1653x1007) as background with white text overlay — exact as BOS p1
    banner_img_path = Path(__file__).parent / "assets" / "bos_banner.png"
    if banner_img_path.exists():
        try:
            # Use image as banner background: draw image then overlay text via table with transparent background
            banner_bg = Image(str(banner_img_path), width=width, height=42*mm)
            banner_bg.hAlign = 'CENTER'
            story.append(banner_bg)
            # Add white text as separate centered paragraphs below image to avoid table background mismatch
            # Re-add rows as white centered text (simulating overlay)
            for row in banner_rows:
                # row is [Paragraph] — set textColor white already, re-append centered
                for para in row:
                    para.style.alignment = TA_CENTER
                    story.append(para)
            story.append(Spacer(1, 1*mm))
        except Exception:
            banner_tbl = Table(banner_rows, colWidths=[width])
            banner_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#0f2a44")),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("ALIGN", (0,0), (-1,-1), "CENTER"),
                ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
                ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ]))
            story.append(banner_tbl)
    else:
        banner_tbl = Table(banner_rows, colWidths=[width])
        banner_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#0f2a44")),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ]))
        story.append(banner_tbl)
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph("www.presidencyuniversity.in", ParagraphStyle("CoverWeb", parent=s_small, alignment=TA_CENTER, fontSize=8, leading=10, textColor=colors.HexColor("#4a6582"))))
    story.append(PageBreak())

    # ── 2. INNER COVER PAGE 2 — SCHOOL / DEPARTMENT / Committee Documents for Approval (BOS p2) ──
    story.append(Spacer(1, 30*mm))
    story.append(Paragraph(f"SCHOOL OF {school_hdr.upper()}", s_inner_school))
    if dept_hdr:
        story.append(Paragraph(f"DEPARTMENT OF {dept_hdr.upper()}", s_inner_school))
    story.append(Spacer(1, 4*mm))
    if committee_short == "BOS":
        inner_txt = f"{committee_name} Documents for Approval at the {meeting_ord} Meeting of Academic Council"
    else:
        inner_txt = f"{committee_name} Minutes of the {meeting_ord} Meeting"
    story.append(Paragraph(inner_txt, s_inner_committee))
    story.append(PageBreak())

    # ── 3. TABLE OF CONTENTS — PAGE 3 (BOS p3) ──
    story.append(Paragraph("Table of Contents", s_toc_title))
    story.append(Spacer(1, 3*mm))
    # Build TOC entries: 1. Notice (1-3), 2. Minutes (4-10), 3. Annexures (11-36) with sub-entries as in BOS
    toc_data = [[Paragraph("<b>S. No.</b>", s_toc_head), Paragraph("<b>Description</b>", s_toc_head), Paragraph("<b>Page No</b>", s_toc_head)]]
    # TOC lines exactly as BOS, only committee swapped and content by input
    mom_no = meeting_no or "2"
    if committee_short == "BOS":
        toc_data.append([Paragraph("1", s_toc_page), Paragraph(f"{meeting_ord} Board of Studies Meeting Notice.", s_toc_item), Paragraph("1-3", s_toc_page)])
        toc_data.append([Paragraph("2", s_toc_page), Paragraph(f"Minutes of the {meeting_ord} Board of Studies Meeting.", s_toc_item), Paragraph("4-10", s_toc_page)])
    else:
        toc_data.append([Paragraph("1", s_toc_page), Paragraph(f"{meeting_ord} Departmental Academic Committee Meeting Notice.", s_toc_item), Paragraph("1-3", s_toc_page)])
        toc_data.append([Paragraph("2", s_toc_page), Paragraph(f"Minutes of the {meeting_ord} Departmental Academic Committee Meeting.", s_toc_item), Paragraph("4-10", s_toc_page)])
    toc_data.append([Paragraph("3", s_toc_head), Paragraph("<b>Annexures</b>", s_toc_item), Paragraph("", s_toc_page)])
    # Annexures sub-entries — use actual annexure entries if present, else generic BOS list
    annex_labels = {e["id"]: e["label"] for e in annexure_entries(mom_items)}
    if annex_labels:
        for idx, (aid, label) in enumerate(annex_labels.items(), 1):
            toc_data.append([Paragraph(f"3.{idx}", s_toc_page), Paragraph(_escape(label), s_toc_item), Paragraph(f"{11+idx}-", s_toc_page)])
    else:
        # Default BOS annexure list when no custom
        for entry in [f"Annexure-{committee_short}-{mom_no}.1 Minutes of previous {meeting_ord} {committee_name}.", f"Annexure-{committee_short}-{mom_no}.2 Action Taken Report of previous {committee_name}.", f"Annexure-{committee_short}-{mom_no}.3 Course Catalogs of the new courses.", f"Annexure-{committee_short}-{mom_no}.4 List of seminar, webinar, guest lecture and industrial visit.", f"Annexure-{committee_short}-{mom_no}.5 Name of the Value-Added Course/Workshops."]:
            toc_data.append([Paragraph("", s_toc_page), Paragraph(_escape(entry), s_toc_item), Paragraph("", s_toc_page)])
    toc_table = Table(toc_data, colWidths=[width*0.10, width*0.72, width*0.18])
    toc_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (0,0), (0,-1), "CENTER"), ("ALIGN", (2,0), (2,-1), "CENTER"),
        ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LINEBELOW", (0,0), (-1,0), 0.5, colors.HexColor("#000000")),
    ]))
    story.append(toc_table)
    story.append(PageBreak())

    # ── 4. MOM REQUEST / NOTICE — Pages 4-6 (BOS p4-6): Ref, Notice, Agenda, Members, Copy to ──
    # Ref No / Date row (BOS p4)
    ref_para = Paragraph(f"Ref No. {reference}", s_notice_ref)
    date_para = Paragraph(f"Date: {notice_date}", s_notice_ref)
    ref_tbl = Table([[ref_para, date_para]], colWidths=[width*0.70, width*0.30])
    ref_tbl.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("ALIGN", (1,0), (1,0), "RIGHT"), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0)]))
    story.append(ref_tbl)
    story.append(Spacer(1, 3*mm))
    # Notice title: XXth BOS/DAC MEETING NOTICE (BOS p4)
    story.append(Paragraph(f"{meeting_ord} {committee_name.upper()} MEETING NOTICE", s_notice_title))
    story.append(Spacer(1, 2*mm))
    # Notice paragraph — exactly as BOS p4, only content by input
    venue = meeting.get('venue') or "ES02, E Block, 2nd Floor"
    mode = meeting.get('mode') or "Hybrid"
    if dept_hdr:
        notice_para_text = f"The {meeting_ord} Meeting of the {committee_name} of the Department of {dept_hdr}, Presidency University - School of {school_hdr}, is convened on {_format_date_long(meeting.get('date'))} at {meeting.get('startTime') or '2:00 PM'} (Venue: {venue}) hosted in {mode} mode from Presidency University Campus, Itgalpur, Rajankunte, Yelahanka, Bengaluru. Kindly make it convenient to attend the meeting."
    else:
        notice_para_text = f"The {meeting_ord} Meeting of the {committee_name}, School of {school_hdr}, Presidency University, is convened on {_format_date_long(meeting.get('date'))} at {meeting.get('startTime') or '2:00 PM'} (Venue: {venue}) hosted in {mode} mode from Presidency University Campus, Itgalpur, Rajankunte, Yelahanka, Bengaluru. Kindly make it convenient to attend the meeting."
    notice_para_text += (f" The meeting link is provided below: {meeting.get('meetingLink')}" if meeting.get('meetingLink') else "")
    notice_para = Paragraph(notice_para_text, s_body)
    story.append(notice_para)
    if meeting.get('meetingLink'):
        story.append(Paragraph(_escape(meeting.get('meetingLink') or ""), s_small))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("AGENDA", ParagraphStyle("AgendaHead", parent=s_notice_title, alignment=TA_CENTER, fontSize=10, leading=12, spaceBefore=2, spaceAfter=3)))
    # Agenda list — as BOS p4: Agenda SOE-MEC 22.1 Approval of MOM...
    for idx, item in enumerate(mom_items, 1):
        ag_code = f"Agenda {committee_short}-{mom_no}.{idx}" if committee_short else f"Agenda {idx}"
        # Use code like Agenda SOE-MEC 22.1 if provided
        agenda_title = item.get('title') or item.get('agendaTitle') or f"Agenda {idx}"
        story.append(Paragraph(f"<b>{ag_code}</b> { _escape(agenda_title)}", ParagraphStyle(f"Agenda{idx}", parent=s_body, alignment=TA_LEFT, fontSize=8, leading=10, spaceBefore=1, spaceAfter=2, leftIndent=10)))
    # Proposed members + signatures start on the next page (Notice page 1 = Ref + Agenda).
    story.append(PageBreak())
    # Members & Invitees — page 5 in BOS
    story.append(Paragraph("To", s_label))
    story.append(Paragraph("Members & Invitees", s_label))
    story.append(Spacer(1, 1*mm))
    # Members table header as BOS p5
    mem_head = [Paragraph("<b>Sl. No.</b>", s_toc_head), Paragraph("<b>Name Designation with Affiliation</b>", s_toc_head), Paragraph("<b>Position</b>", s_toc_head)]
    mem_rows = [mem_head]
    for idx, m in enumerate(all_members, 1):
        name = m.get('name') or ""
        desig = m.get('designation') or m.get('affiliation') or ""
        pos = m.get('role') or m.get('position') or "Member"
        mem_rows.append([Paragraph(str(idx)+".", s_body), Paragraph(f"{_escape(name)}<br/><font size=7>{_escape(desig)}</font>", s_body), Paragraph(_escape(pos), s_body)])
    mem_table = Table(mem_rows, colWidths=[width*0.08, width*0.62, width*0.30], repeatRows=1)
    mem_table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#000000")),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#d9e2f3")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (0,0), (0,-1), "CENTER"),
        ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    story.append(mem_table)
    story.append(Spacer(1, 6*mm))
    # Signatures for Request — both DAC and BOS: MS+Chair only (Academic Office removed per user request 2026-11-10)
    sig_data = []
    chair = next((m for m in all_members if 'chair' in (m.get('role') or '').lower()), all_members[0] if all_members else {"name":"Chairperson","role":"Chairperson"})
    sec = next((m for m in all_members if 'secretary' in (m.get('role') or '').lower()), all_members[1] if len(all_members)>1 else chair)
    try:
        story.append(_request_signature_table(data, styles, width, sec, chair))
    except Exception:
        sig_data = [[Paragraph(f"{_escape(sec.get('name') or '')}<br/><b>{_escape(sec.get('role') or 'Member Secretary')}</b><br/>Member Secretary", s_sig),
                      Paragraph(f"{_escape(chair.get('name') or '')}<br/><b>{_escape(chair.get('role') or 'Chairperson')}</b><br/>Chairperson", s_sig)]]
        sig_tbl = Table(sig_data, colWidths=[width*0.5, width*0.5])
        sig_tbl.setStyle(TableStyle([("ALIGN", (0,0), (-1,-1), "LEFT"), ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 0)]))
        story.append(sig_tbl)
    story.append(Spacer(1, 4*mm))
    # Copy to — common to every meeting, printed only on the downloaded document
    # (DAC Circular Template). Never shown on the creation screen.
    story.append(Paragraph("Copy to:", s_label))
    copy_items = ["Hon’ble Vice Chancellor, PU", "Hon’ble Pro Vice Chancellor, PU", "Office of the Registrar, PU", "Dean-Academics, PU"]
    for item in copy_items:
        story.append(Paragraph(f"• {item}", s_body))
    story.append(PageBreak())

    # ── 5. COMPLETED MOM — Pages 7-13 (BOS p7-13): Ref, Notice, Members Present, Agendas, Photos, Action Items, Signatures ──
    # Ref No for Minutes — BOS p7: Ref No. PU/SoE-MEC/BoS-22/2025-26/EVEN/MoM-22 Date: 27.12.2025
    mom_ref_para = Paragraph(f"Ref No. {mom_reference}", s_notice_ref)
    mom_date_para = Paragraph(f"Date: {notice_date}", s_notice_ref)
    mom_ref_tbl = Table([[mom_ref_para, mom_date_para]], colWidths=[width*0.70, width*0.30])
    mom_ref_tbl.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("ALIGN", (1,0), (1,0), "RIGHT"), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0)]))
    story.append(mom_ref_tbl)
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(f"Minutes of the {meeting_ord} Meeting of {committee_name}", s_notice_title))
    story.append(Spacer(1, 2*mm))
    if dept_hdr:
        mom_para_text = f"The {meeting_ord} Meeting of the {committee_name} of the Department of {dept_hdr}, School of {school_hdr}, Presidency University, was convened on {mom_date} at {meeting.get('startTime') or '2:00 PM'} in {venue}. The meeting was held in {mode.lower()} mode from the Presidency University campus in Bengaluru."
    else:
        mom_para_text = f"The {meeting_ord} Meeting of the {committee_name}, School of {school_hdr}, Presidency University, was convened on {mom_date} at {meeting.get('startTime') or '2:00 PM'} in {venue}. The meeting was held in {mode.lower()} mode from the Presidency University campus in Bengaluru."
    mom_para_text += (f" The meeting link is as follows: {meeting.get('meetingLink')}" if meeting.get('meetingLink') else "")
    mom_para = Paragraph(mom_para_text, s_body)
    story.append(mom_para)
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("Members Present:", s_label))
    story.append(Spacer(1, 1*mm))
    # Members Present table — BOS p7-8
    pres_head = [Paragraph("<b>Sl. No</b>", s_toc_head), Paragraph("<b>Name and Affiliation</b>", s_toc_head), Paragraph("<b>Role</b>", s_toc_head), Paragraph("<b>Signature</b>", s_toc_head)]
    pres_rows = [pres_head]
    for idx, m in enumerate(present_members, 1):
        nm = m.get('name') or ""
        aff = m.get('designation') or ""
        role = m.get('role') or ""
        sig = m.get('signatureText') or ("Attended Online" if m.get('present') else "")
        pres_rows.append([Paragraph(f"{idx:02d}", s_body), Paragraph(f"{_escape(nm)}, {_escape(aff)}", s_body), Paragraph(_escape(role), s_body), Paragraph(_escape(sig), s_body)])
    pres_table = Table(pres_rows, colWidths=[width*0.08, width*0.52, width*0.20, width*0.20], repeatRows=1)
    pres_table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#000000")),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#d9e2f3")),
        ("VALIGN", (0,0), (-1,-1), "TOP"), ("ALIGN", (0,0), (0,-1), "CENTER"),
        ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    story.append(pres_table)
    story.append(Spacer(1, 3*mm))
    chair_welcome = Paragraph("The Chairperson welcomed all the members. The member secretary delivered the opening remarks and deliberated on the following agenda points.", s_body)
    story.append(chair_welcome)
    story.append(Spacer(1, 2*mm))
    # Agendas with Discussion/Recommendations/Ref — BOS p8-11
    for idx, item in enumerate(mom_items, 1):
        ag_code = f"Agenda {committee_short}-{mom_no}.{idx}"
        title = item.get('title') or item.get('agendaTitle') or f"Agenda {idx}"
        story.append(Paragraph(f"<b>{ag_code} { _escape(title)}</b>", s_agenda_title))
        disc = item.get('discussion') or item.get('discussionText') or "Discussion as per input."
        rec = item.get('resolution') or item.get('recommendation') or item.get('recommendations') or "Recommendations as per discussion."
        # Annexure label for this agenda
        annex = annex_labels.get(item.get('id') or item.get('agendaId') or "", "") or f"Annexure {committee_short}-{mom_no}.{idx}"
        story.append(Paragraph("<b>Discussion:</b>", s_label))
        story.append(Paragraph(_escape(disc), s_body))
        story.append(Paragraph("<b>Recommendations:</b>", s_label))
        story.append(Paragraph(_escape(rec), s_body))
        story.append(Paragraph(f"<b>Ref. Document:</b> { _escape(annex)}", s_small))
        story.append(Spacer(1, 2*mm))
    # Any other matter if provided
    for add in additional:
        story.append(Paragraph(f"<b>{ _escape(add.get('title') or 'Any other matter with permission of the Chair')}</b>", s_agenda_title))
        story.append(Paragraph("<b>Discussion:</b>", s_label))
        story.append(Paragraph(_escape(add.get('discussion') or ""), s_body))
        story.append(Paragraph("<b>Recommendations:</b>", s_label))
        story.append(Paragraph(_escape(add.get('resolution') or ""), s_body))
        story.append(Spacer(1, 2*mm))
    # DAC specific text — as user said "then some text configure this DAC also" — add standard thanking text before photos
    # Geo-Tagged Photos — BOS p12
    if photos:
        story.append(Paragraph("Geo-Tagged Photos and Online Platform Screenshots – " + committee_name + (" (BoS)" if committee_short=="BOS" else " (DAC)"), s_label))
        story.append(Spacer(1, 2*mm))
        for idx, ph in enumerate(photos, 1):
            cap = ph.get('caption') or f"Image {idx}"
            story.append(Paragraph(f"Image {idx}: { _escape(cap)}", s_body))
            img_data = None
            # Image if dataUrl present
            data_url = ph.get('dataUrl') or ph.get('url') or ""
            if data_url.startswith("data:image"):
                try:
                    import base64
                    b64 = data_url.split(",",1)[1]
                    img_data = base64.b64decode(b64)
                except Exception:
                    img_data = None
            # Image if a file object references an uploaded file (photo uploads store file.id / file.previewUrl)
            if img_data is None:
                photo_file = ph.get('file') or {}
                file_id = photo_file.get('id') or photo_file.get('fileId') or ""
                if file_id:
                    try:
                        img_data = read_uploaded_bytes(file_id)
                    except Exception:
                        img_data = None
            if img_data:
                try:
                    from reportlab.lib.utils import ImageReader
                    import io as _io
                    img = Image(_io.BytesIO(img_data), width=width*0.9, height=38*mm)
                    img.hAlign = "CENTER"
                    story.append(img)
                except Exception:
                    pass
            story.append(Spacer(1, 3*mm))
    # Action Items — BOS p13
    story.append(Paragraph("Action Items:", s_label))
    story.append(Spacer(1, 1*mm))
    if actions:
        act_head = [Paragraph("<b>Agenda No</b>", s_toc_head), Paragraph("<b>Action(s) to be Taken</b>", s_toc_head), Paragraph("<b>Person(s) Responsible</b>", s_toc_head), Paragraph("<b>Target Date</b>", s_toc_head)]
        act_rows = [act_head]
        for act in actions:
            agno = act.get('agendaNo') or act.get('agenda') or ""
            txt = act.get('text') or act.get('action') or ""
            resp = act.get('owner') or act.get('responsible') or ""
            tgt = _format_date_dmy(act.get('targetDate') or act.get('target') or "")
            act_rows.append([Paragraph(_escape(str(agno)), s_body), Paragraph(_escape(txt), s_body), Paragraph(_escape(resp), s_body), Paragraph(_escape(tgt), s_body)])
        act_table = Table(act_rows, colWidths=[width*0.15, width*0.40, width*0.25, width*0.20], repeatRows=1)
        act_table.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#000000")),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#d9e2f3")),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (0,0), (-1,-1), 3),
            ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ]))
        story.append(act_table)
    else:
        story.append(Paragraph("No action items assigned.", s_body))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("The Chairperson and the Member Secretary thanked all the members for their contributions and requested their continued support.", s_body))
    story.append(Spacer(1, 4*mm))
    # Signatures for MoM — both DAC and BOS: MS+Chair only (Academic Office removed per user request 2026-11-10).
    # The downloaded form carries the drawn signatures, not just names (item 11, 2026-11-13).
    if not meeting.get("secretaryEmail") and sec.get("email"):
        data = {**data, "meeting": {**meeting, "secretaryEmail": sec["email"]}}
    try:
        story.append(_mom_signature_table(data, styles, width))
    except Exception:
        story.append(Table([[Paragraph(f"{_escape(sec.get('name') or '')}<br/><b>{_escape(sec.get('role') or 'Member Secretary')}</b><br/>Member Secretary", s_sig),
                            Paragraph(f"{_escape(chair.get('name') or '')}<br/><b>{_escape(chair.get('role') or 'Chairperson')}</b><br/>Chairperson", s_sig)]], colWidths=[width*0.5, width*0.5]))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph("Encl: Annexures", s_small))
    story.append(PageBreak())

    # ── 6. ANNEXURES — Pages 14-50 in BOS, exactly as in above pdf ──
    # Each annexure as separate section with SCHOOL/DEPT header, Ref No, Title, content tables
    if annex_labels or mom_items:
        # If we have specific annexure content from data, render it; otherwise generic placeholder that matches BOS structure
        annex_data = data.get("annexures") or data.get("annexureDetails") or []
        if not annex_data:
            # Create placeholder annexures that mimic BOS annexures (11-36) with course lists etc.
            for idx, item in enumerate(mom_items, 1):
                story.append(Paragraph(f"SCHOOL OF {school_hdr.upper()}", s_inner_school))
                if dept_hdr:
                    story.append(Paragraph(f"DEPARTMENT OF {dept_hdr.upper()}", s_inner_school))
                story.append(Paragraph(f"Annexure {committee_short}-{mom_no}.{idx}", s_notice_title))
                story.append(Paragraph(_escape(item.get('title') or f"Annexure {idx}"), s_agenda_title))
                story.append(Paragraph(_escape(item.get('discussion') or "Content as per annexure document.")[:800], s_body))
                if idx < len(mom_items):
                    story.append(PageBreak())
        else:
            for ann in annex_data:
                story.append(Paragraph(f"SCHOOL OF {school_hdr.upper()}", s_inner_school))
                if dept_hdr:
                    story.append(Paragraph(f"DEPARTMENT OF {dept_hdr.upper()}", s_inner_school))
                story.append(Paragraph(_escape(ann.get('title') or "Annexure"), s_notice_title))
                for line in (ann.get("content") or "").split(chr(10)):
                    story.append(Paragraph(_escape(line), s_body))
                story.append(PageBreak())
        # Remove last PageBreak if added
        if story and isinstance(story[-1], PageBreak):
            story.pop()
    else:
        # No annexures — add blank annexure section as BOS p14-15 separator
        story.append(Paragraph(f"SCHOOL OF {school_hdr.upper()}", s_inner_school))
        if dept_hdr:
            story.append(Paragraph(f"DEPARTMENT OF {dept_hdr.upper()}", s_inner_school))
        story.append(Paragraph(f"Annexures for {meeting_ord} Meeting of {committee_name}", s_notice_title))
        story.append(Paragraph("As per the meeting agenda, annexures are attached in the order listed in the Table of Contents.", s_body))

    # Remove trailing PageBreak
    if story and isinstance(story[-1], PageBreak):
        story.pop()

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return buffer.getvalue()
def build_final_pdf(data: dict) -> bytes:
    main_pdf = _build_main_mom_pdf(data)
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(main_pdf)))

    meeting = data.get("meeting") or {}
    mom_items = data.get("momItems") or []
    entries = annexure_entries(mom_items)
    if entries:
        writer.append(PdfReader(io.BytesIO(_annexure_index_pdf(entries))))
    for entry in entries:
        path = get_upload_path(entry["id"])
        if not path:
            continue
        extension = path.suffix.lower()
        if extension == ".pdf":
            writer.append(PdfReader(io.BytesIO(_annexure_divider_pdf(entry))))
            writer.append(str(path))
        elif extension in {".jpg", ".jpeg", ".png", ".webp"}:
            annexure_pdf = _image_to_pdf(path.read_bytes(), f"Annexure {entry['label']}: {entry['name']}")
            writer.append(PdfReader(io.BytesIO(annexure_pdf)))
        elif extension in {".docx", ".xlsx", ".pptx", ".txt", ".csv"}:
            annexure_pdf = _office_attachment_pdf(path, entry["name"], entry["agendaTitle"], entry["label"])
            writer.append(PdfReader(io.BytesIO(annexure_pdf)))

    _stamp_page_numbers(writer, _committee_of(data))
    writer.add_metadata({
        "/Title": committee_registry.document_title(meeting.get("committee"), "mom"),
        "/Subject": f"{meeting.get('school', '')} — {meeting.get('department', '')}",
        "/Creator": "DAC Minutes Studio",
    })
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def meeting_end_passed(meeting: dict, now: datetime | None = None) -> bool:
    """Return whether the scheduled local meeting end has passed, independent of completion."""
    date_text = meeting.get("date")
    end_text = meeting.get("endTime")
    if not date_text or not end_text:
        return False
    try:
        end_at = datetime.combine(
            datetime.fromisoformat(date_text).date(),
            time_value.fromisoformat(end_text),
            tzinfo=COLLEGE_TZ,
        )
    except ValueError:
        return False
    current = now or datetime.now(COLLEGE_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=COLLEGE_TZ)
    return current >= end_at


def meeting_start_passed(meeting: dict, now: datetime | None = None) -> bool:
    date_text, start_text = meeting.get("date"), meeting.get("startTime")
    if not date_text or not start_text:
        return False
    try:
        start_at = datetime.combine(datetime.fromisoformat(date_text).date(), time_value.fromisoformat(start_text), tzinfo=COLLEGE_TZ)
    except ValueError:
        return False
    current = now or datetime.now(COLLEGE_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=COLLEGE_TZ)
    return current >= start_at


def _minutes_unlocked(data: dict, now: datetime | None = None) -> bool:
    """Meeting finished and marked complete — the minutes may be drafted."""
    meeting = data.get("meeting") or {}
    return data.get("status") == "approved" and meeting.get("completed") is True and meeting_end_passed(meeting, now)


def _fast_forward_meeting(state: dict, days: int = 1) -> dict:
    """Move this meeting's date into the past and mark it completed.

    One shared transformation, used by the automated suites' clock hook and by the
    demonstration fast-forward, so the two can never drift apart: after this call
    ``_minutes_unlocked`` is true and nothing else in the record has been altered.
    """
    date_text = (datetime.now(COLLEGE_TZ) - timedelta(days=max(1, int(days)))).date().isoformat()
    meeting = {**(state.get("meeting") or {}), "date": date_text, "completed": True}
    approved = state.get("approvedMeeting")
    if approved:
        approved = {**approved, "date": date_text}
    return {**state, "meeting": meeting, "approvedMeeting": approved,
            "meetingCompletedAt": datetime.now(COLLEGE_TZ).strftime("%d %b %Y, %H:%M")}


def _move_action_targets(state: dict, days: int = 1) -> tuple[dict, str]:
    """Pull every action-item target date into the past so the ATR window opens."""
    target = (datetime.now(COLLEGE_TZ).date() - timedelta(days=max(1, int(days)))).isoformat()
    items = [{**item, "targetDate": target} for item in (state.get("actionItems") or [])]
    return {**state, "actionItems": items}, target



#: Minutes review states in which the organiser may still edit.
EDITABLE_REVIEW_STATES = {"draft", "chair_revision", "office_revision"}

MOM_REVIEW_LABELS = {
    "draft": "Draft — not submitted",
    "pending_chairperson": "Awaiting Chairperson approval",
    "chair_revision": "Returned by the Chairperson",
    "pending_office": "Awaiting Academic Office approval",
    "office_revision": "Returned by the Academic Office",
    "approved": "Approved by the Academic Office",
}


def _mom_review_payload(state: dict) -> dict:
    review = dict(state.get("momReview") or {})
    status = str(review.get("status") or "draft")
    if status not in MOM_REVIEW_LABELS:
        status = "draft"
    meeting = state.get("meeting") or {}
    return {
        "status": status,
        "label": MOM_REVIEW_LABELS[status],
        "requiresChair": bool(review.get("requiresChair", True)),
        "submittedAt": str(review.get("submittedAt") or ""),
        "chairName": str(meeting.get("chairName") or ""),
        "chairEmail": str(meeting.get("chairEmail") or ""),
        "chairDecisionAt": str(review.get("chairDecisionAt") or ""),
        "chairComment": str(review.get("chairComment") or ""),
        "officeDecisionAt": str(review.get("officeDecisionAt") or ""),
        "officeComment": str(review.get("officeComment") or ""),
        "version": int(review.get("version") or 0),
        "history": list(review.get("history") or []),
        "chairReviewReused": bool(review.get("chairReviewReused")),
        "signatures": {
            "secretary": review.get("secretarySignature") or None,
            "chair": review.get("chairSignature") or None,
            "office": review.get("officeSignature") or None,
        },
    }


def _external_report_required(state: dict) -> bool:
    return any(member.get("role") == "External Member"
               for member in ((state.get("meeting") or {}).get("members") or []))


def _download_gate(state: dict, workspace_id: str) -> dict:
    """Everything that stands between the organiser and the final documents."""
    review = _mom_review_payload(state)
    report = (external_report.gate_state(workspace_id) if _external_report_required(state)
              else {"required": False, "status": "not_required", "submitted": True, "approved": True,
                    "message": "No External Member is nominated for this meeting."})
    unlocked = _minutes_unlocked(state)
    allowed = bool(unlocked and review["status"] == "approved")
    if not unlocked:
        reason = ("The final documents unlock after the scheduled end time has passed and the meeting is "
                  "marked completed.")
    elif review["status"] == "approved":
        reason = "Approved by the Academic Office — download is available."
    elif review["status"] == "pending_office":
        reason = ("Awaiting Academic Office approval."
                  + ("" if report["submitted"] else " The External Member's observation report is still awaited."))
    elif review["status"] == "pending_chairperson":
        reason = "Awaiting Chairperson approval."
    elif review["status"] in {"chair_revision", "office_revision"}:
        reason = "Returned for revision — update the minutes and submit again."
    else:
        reason = "Submit the minutes for review (Chairperson, then Academic Office) to unlock the download."
    return {"allowed": allowed, "reason": reason, "momReview": review, "externalReport": report}


def can_edit_minutes(data: dict, now: datetime | None = None) -> bool:
    return _minutes_unlocked(data, now) and _mom_review_payload(data)["status"] in EDITABLE_REVIEW_STATES

def _validate_upload(file_storage) -> tuple[str, bytes]:
    original_name = file_storage.filename or ""
    safe_name = secure_filename(original_name)
    extension = Path(safe_name).suffix.lower()
    if not safe_name or extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Choose a supported PDF, image, Office document, TXT, or CSV file.")
    raw = file_storage.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Each file must be 15 MB or smaller.")
    if not raw:
        raise ValueError("The selected file is empty.")

    try:
        if extension == ".pdf":
            pdf = PdfReader(io.BytesIO(raw))
            if pdf.is_encrypted:
                raise ValueError("Password-protected PDFs are not supported.")
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise ValueError(f"PDFs are limited to {MAX_PDF_PAGES} pages.")
        elif extension in {".jpg", ".jpeg", ".png", ".webp"}:
            image = PILImage.open(io.BytesIO(raw))
            image.verify()
        elif extension in {".docx", ".xlsx", ".pptx"}:
            if not raw.startswith(b"PK\x03\x04"):
                raise ValueError("This does not look like a valid Office Open XML document.")
        elif b"\x00" in raw:
            raise ValueError("Binary content is not accepted as TXT/CSV.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The file could not be validated. Try exporting it as PDF or a standard image.") from exc
    return safe_name, raw


#: Endpoints an account may still call before it has signed, so a first-time user
#: can reach the sign-in flow and register a signature.
SIGNATURE_EXEMPT_PATHS = (
    "/api/auth/request-code", "/api/auth/verify-code", "/api/auth/logout",
    "/api/auth/me", "/api/signature", "/api/ai/status", "/api/catalog",
    "/api/health", "/api/document-style",
)
SIGNATURE_EXEMPT_PREFIXES = ("/api/signature", "/api/auth/")


def _signature_exempt(path: str) -> bool:
    return path in SIGNATURE_EXEMPT_PATHS or any(path.startswith(prefix) for prefix in SIGNATURE_EXEMPT_PREFIXES)


@app.before_request
def _require_signature_before_workflow():
    """Refuse workflow actions until the account has registered its signature."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    path = request.path or ""
    if not path.startswith("/api/") or _signature_exempt(path):
        return None
    user = get_current_user()
    if not user:
        return None
    if signature_store.has_signature(user):
        return None
    return jsonify({
        "error": "Record your digital signature before continuing. It is stamped on every form you sign.",
        "signatureRequired": True,
    }), 428


def _public_user(user: dict) -> dict:
    return {key: user.get(key) for key in ("id", "email", "name", "designation", "employeeCode",
                                           "qualification", "specialization", "phone", "office", "role",
                                           "active", "schoolId", "school", "departmentId", "department")}


def _email_is_valid(email: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email or ""))


def _code_digest(email: str, code: str) -> str:
    secret = str(app.secret_key).encode("utf-8")
    return hmac.new(secret, f"{email.lower()}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _build_request_form_pdf(workspace: dict) -> bytes:
    """Render the signed request & agenda approval form for one workspace."""
    state = workspace.get("payload") or {}
    meeting = state.get("meeting") or {}
    owner = get_user_by_id(workspace.get("ownerId") or "") or {}
    chair_email = str(meeting.get("chairEmail") or "")
    chair = get_user_by_email(chair_email, active_only=False) or {"name": meeting.get("chairName") or "Chairperson"}
    secretary_signature = signature_store.signature_for_email(owner.get("email") or "")
    chair_signature = signature_store.signature_for_email(chair_email)
    for signature in (secretary_signature, chair_signature):
        if signature:
            signature["path"] = str(signature_store.signature_path(signature) or "")
    chair_approval = state.get("chairApproval") or {}
    if chair_signature and chair_approval.get("signedAt"):
        chair_signature = {**chair_signature, "signedAt": chair_approval["signedAt"]}
    if secretary_signature and state.get("submittedAt"):
        secretary_signature = {**secretary_signature, "signedAt": str(state.get("submittedAt"))}
    office_decision = state.get("officeDecision") or {}
    office = None
    if office_decision:
        office_signature = signature_store.signature_for_email(office_decision.get("email") or "")
        if office_signature:
            office_signature = {**office_signature,
                               "path": str(signature_store.signature_path(office_signature) or ""),
                               "signedAt": office_decision.get("decidedAt") or office_decision.get("signedAt") or ""}
        elif office_decision.get("decision"):
            # The signatory's image has since been replaced or removed: fall back to the
            # stored record so the block still names them and the date.
            office_signature = {"path": "", "name": office_decision.get("name") or "",
                                "designation": office_decision.get("designation") or "",
                                "signedAt": office_decision.get("decidedAt") or ""}
        office = {"name": office_decision.get("name") or "",
                  "designation": office_decision.get("designation") or "Academic Office",
                  "signature": office_signature if office_decision.get("decision") else None}
    return request_document.build_request_form(
        state, reference=str(state.get("proposalReference") or _reference_number(meeting, "request")),
        owner=owner, chair=chair, secretary_signature=secretary_signature,
        chair_signature=chair_signature, office=office)


def _workspace_payload(workspace: dict | None) -> dict:
    if not workspace:
        return {"workspace": None}
    state = _migrate_resolution_keys(workspace["payload"])  # legacy "recommendation" -> "resolution"
    return {"workspaceId": workspace["workspaceId"], "status": workspace["status"],
            "state": state, "updatedAt": workspace["updatedAt"],
            "committee": _committee_payload(_committee_of(state)),
            "momReview": _mom_review_payload(state),
            "externalReport": external_report.gate_state(workspace["workspaceId"]),
            "downloadGate": _download_gate(state, workspace["workspaceId"])}


def _external_workspace_payload(workspace: dict | None) -> dict:
    if not workspace:
        return {"workspace": None}
    source = _migrate_resolution_keys(workspace["payload"])
    meeting = source.get("meeting") or {}
    approved = source.get("approvedMeeting") or {}
    safe_meeting = {key: meeting.get(key) for key in ("id", "meetingNo", "academicYear", "semester", "school", "department", "date", "startTime", "endTime", "venue", "mode")}
    safe_agendas = [{key: item.get(key) for key in ("id", "kind", "title")} for item in (approved.get("agendas") or [])]
    safe_state = {"status": "approved", "meeting": safe_meeting, "approvedMeeting": {"agendas": safe_agendas}, "momItems": []}
    return {"workspaceId": workspace["workspaceId"], "status": "approved", "state": safe_state, "updatedAt": workspace["updatedAt"]}


def _clean_school(value: str) -> str:
    """Both sides go through the same normaliser ("School of X" ≡ "X").

    The registry stores R1's own wording while a document carries "School of …", so
    cleaning only one side made an exact match fail.
    """
    return dac_registry.norm(value)


def _clean_department(value: str) -> str:
    return dac_registry.norm(value)


def _meeting_profile_matches(meeting: dict, user: dict) -> bool:
    """The signed-in Member Secretary must own the meeting's school/department.

    The Chairperson is a *different* person chosen by the Member Secretary, so
    the chair fields are validated separately in ``_validate_workspace_proposal``.
    A school-level DAC (no department in R1) has no department to compare.
    """
    same_school = _clean_school(meeting.get("school", "")) == _clean_school(user.get("school"))
    same_department = (_clean_department(meeting.get("department", "")) == _clean_department(user.get("department"))
                       or not _clean_department(meeting.get("department", "")))
    return same_school and same_department


def _committee_of(state: dict) -> str:
    """The committee a workspace belongs to (DAC when unrecorded)."""
    meeting = state.get("meeting") or {}
    return committee_registry.normalise(state.get("committee") or meeting.get("committee"))


def _stamp_committee(state: dict) -> dict:
    """Write the committee onto both the state and the meeting record."""
    code = _committee_of(state)
    meeting = {**(state.get("meeting") or {}), "committee": code}
    return {**state, "committee": code, "meeting": meeting}


def _committee_payload(code: object) -> dict:
    entry = committee_registry.meta(code)
    return {"code": entry["code"], "name": entry["name"],
            "meetingsPerSemester": entry["meetingsPerSemester"],
            "meetingsPerYear": entry["meetingsPerYear"],
            "schedule": entry["schedule"], "scheduleShort": entry["scheduleShort"],
            "agendaSeries": entry["agendaSeries"],
            "requestTitle": entry["requestTitle"], "momTitle": entry["momTitle"],
            "requestSubtitle": entry.get("requestSubtitle", ""),
            "startNote": entry.get("startNote", ""),
            "referencePrefix": entry["referencePrefix"]}


@app.get("/api/committees")
@login_required
def committees_index():
    """The committee registry, published so the interface is not the source of truth.

    Adding a third committee (or changing a cadence, title or reference prefix) is an
    edit in :mod:`committees`; this route hands the change to the UI on the next load.
    """
    return jsonify({"committees": [_committee_payload(code) for code in committee_registry.codes()],
                    "default": committee_registry.DEFAULT_COMMITTEE,
                    "agendaSeries": {code: committee_registry.meta(code)["agendaSeries"]
                                     for code in committee_registry.codes()}})


def _validate_workspace_proposal(payload: dict, user: dict) -> str | None:
    meeting = payload.get("meeting") or {}
    # A school that R1 gives no department is a school-level DAC, so the department
    # field does not exist for it and must not be demanded.
    catalog = get_catalog()
    school_entry = next((school for school in catalog["schools"]
                         if _clean_school(school["name"]) == _clean_school(meeting.get("school"))), None)
    if not school_entry:
        return "Choose a school from the academic catalog."
    if school_entry["departments"]:
        if not str(meeting.get("department") or "").strip():
            return "Choose the department of the meeting."
        if not any(_clean_department(department["name"]) == _clean_department(meeting.get("department"))
                   for department in school_entry["departments"]):
            return "That department is not part of the selected school."
    else:
        meeting["department"] = ""
        payload["meeting"] = meeting
    required = ("meetingNo", "academicYear", "semester", "school", "date", "startTime", "endTime", "venue", "chairName", "chairEmail")
    missing = [field for field in required if not str(meeting.get(field) or "").strip()]
    if missing:
        return "Complete required meeting details: " + ", ".join(missing) + "."
    if not _meeting_profile_matches(meeting, user):
        return "The meeting school, department and organizer must match your provisioned faculty profile. Ask the System Administrator to update your assignment if needed."
    raw_committee = str(meeting.get("committee") or "").strip()
    if raw_committee and raw_committee.upper() not in committee_registry.codes():
        return ("Choose the committee this meeting belongs to: DAC (Departmental Academic Committee) "
                "or BOS (Board of Studies).")
    committee = committee_registry.normalise(raw_committee)
    limit = committee_registry.meeting_number_limit(committee)
    number = _numeric_meeting_number(meeting.get("meetingNo"))
    if number < 1 or number > limit:
        return (f"{committee} holds {limit} meeting{'s' if limit > 1 else ''} in a semester "
                f"({committee_registry.meta(committee)['schedule']}); the meeting number must be "
                f"between 1 and {limit}.")
    if not (meeting.get("agendas") or []):
        return "Select or add at least one agenda item."
    if meeting.get("startTime", "") >= meeting.get("endTime", ""):
        return "Expected end time must be after start time."
    if any(item.get("id") in {"std-mom", "std-atr"} for item in meeting.get("agendas", [])) and not (meeting.get("previousMeetingNo") and meeting.get("previousMeetingDate")):
        return "Add the previous meeting number and date for the selected MoM / ATR agenda."
    members = meeting.get("members") or []
    chairs = [member for member in members if member.get("role") == "Chairperson"]
    if len(chairs) != 1:
        return "The meeting roster must contain exactly one Chairperson."
    chair = chairs[0]
    if (str(chair.get("email") or "").strip().lower() != str(meeting.get("chairEmail") or "").strip().lower()
            or str(chair.get("name") or "").strip().casefold() != str(meeting.get("chairName") or "").strip().casefold()):
        return "The Chairperson roster row must match the Chairperson named in the meeting details."
    with connect() as db:
        scheduler_ok = dac_registry.is_secretary(db, user["email"], meeting.get("school"), meeting.get("department"))
        unit = dac_registry.unit_for(db, meeting.get("school"), meeting.get("department"))
    if not scheduler_ok:
        return ("Only a Member Secretary of this DAC can schedule its meeting. R1 names the "
                "Member Secretary of every DAC; ask the System Administrator to add you if the "
                "registry is incomplete.")
    chair_email = str(meeting.get("chairEmail") or "").strip().lower()
    if unit and unit["chairs"] and chair_email not in [email.lower() for email in unit["chairs"]]:
        names = ", ".join(person["name"] for person in _people_payload(unit["chairs"]))
        return "The Chairperson of this DAC must be its Dean or Head of Department: " + names + "."
    if chair_email == str(user.get("email") or "").strip().lower():
        return ("The Chairperson must be a different person from the Member Secretary who schedules the meeting. "
                "Choose the Dean or the Head of a department of this school.")
    chair_account = get_user_by_email(chair_email, active_only=True)
    if not chair_account:
        return "The Chairperson must be an active account in the access directory. Ask the System Administrator to provision them first."
    if chair_account.get("role") not in {"faculty", "external_member"}:
        return "The Chairperson must be a faculty account (the Dean or a Head of Department)."
    chair_school = str(chair_account.get("school") or "").strip()
    if chair_school and _clean_school(chair_school) != _clean_school(meeting.get("school", "")):
        return "The Chairperson must belong to the same school as the meeting."
    if not is_eligible_chairperson(chair_account):
        return ("The Chairperson must be the Dean or a Head of Department of this school. "
                "Choose from the eligible Chairpersons list.")
    externals = [member for member in members if member.get("role") == "External Member"]
    if len(externals) > 1:
        return "Nominate exactly one External Member for the meeting (faculty of a different school)."
    seen = set()
    for member in members:
        email = str(member.get("email") or "").strip().lower()
        if not str(member.get("name") or "").strip() or not _email_is_valid(email):
            return "Every proposed member needs a name and valid email address."
        if email in seen:
            return "The proposed member list contains a duplicate email address."
        seen.add(email)
        allowed = get_user_by_email(email, active_only=True)
        if not allowed:
            return f"{email} is not in the active access directory. Ask the System Administrator to provision this invitee first."
        is_nominated_external = member.get("role") == "External Member"
        if is_nominated_external:
            if str(email) == str(meeting.get("chairEmail") or "").strip().lower():
                return "The External Member must be a different person from the Chairperson."
            # R1 names the External Member of every DAC; that nomination is authoritative
            # even when the person's own school is the same as the DAC's.
            if unit and email in [row["email"].lower() for row in unit["externals"]]:
                continue
            if allowed.get("role") == "external_member":
                continue  # legacy outside guest accounts remain valid
            if allowed.get("role") != "faculty":
                return f"{email} cannot be nominated as the External Member; choose faculty from a different school."
            member_school = str(allowed.get("school") or "").strip()
            if member_school and _clean_school(member_school) == _clean_school(meeting.get("school", "")):
                return (f"{email} belongs to the same school. The External Member must be faculty of a "
                        "different school of the university.")
        elif allowed.get("role") == "external_member":
            return (f"{email} is provisioned as an External Member. Give that row the External Member role, "
                    "or invite an internal faculty member.")
    return None


def _attachment_ids(items: list[dict]) -> set[str]:
    result: set[str] = set()
    for item in items or []:
        for attachment in item.get("attachments") or []:
            if attachment.get("id"):
                result.add(str(attachment["id"]))
    return result


def _validate_minutes_content(state: dict) -> str | None:
    """The minutes must actually be written before they go for approval."""
    items = state.get("momItems") or []
    if not items:
        return "There are no agenda sections in the minutes yet."
    missing = []
    for index, item in enumerate(items, start=1):
        number = item.get("agendaNo") or index
        if not str(item.get("discussion") or "").strip():
            missing.append(f"agenda {number}: discussion")
        if not str(_item_resolution(item) or "").strip() and not _item_has_no_resolution(item):
            missing.append(f"agenda {number}: resolution")
    if missing:
        return "Complete the minutes before submitting them: " + "; ".join(missing[:6]) + "."
    return None


def _validate_ai_alignment(state: dict) -> str | None:
    """Agenda → Discussion → Resolution must be relevant before the minutes leave the desk.

    The Member Secretary must run **AI content verification** and every agenda item must
    read as ``aligned``: its discussion addresses the agenda, and its resolution is
    grounded in the discussion. The check is fresh at submit time (not trusted from
    the client) and uses the same engine the UI shows — a hosted model when a key is
    configured, otherwise the transparent offline word-overlap rules. Until every item
    is aligned, the minutes cannot be submitted for approval.
    """
    mom_items = list(state.get("momItems") or [])
    additional = list(state.get("additionalDiscussions") or [])
    combined = []
    for item in mom_items:
        combined.append(item)
    for idx, ad in enumerate(additional, start=1):
        if not str(ad.get("title") or "").strip() and not str(ad.get("discussion") or "").strip() and not str(ad.get("resolution") or "").strip():
            continue
        combined.append({
            "title": str(ad.get("title") or f"Additional {idx}"),
            "discussion": str(ad.get("discussion") or ""),
            "resolution": str(ad.get("resolution") or ""),
            "noResolution": bool(ad.get("noResolution")),
            "agendaNo": len(mom_items) + idx,
        })
    if not combined:
        return None
    # The submission gate uses the deterministic offline rules, not the hosted model.
    # The model is valuable for review, but its strictness varies by provider and
    # would make the gate flaky in a live demo (a vague but relevant resolution
    # should pass the gate; the reviewer can still read the model\'s findings).
    try:
        import content_check
        report = content_check.check_items(combined)
        # Re-shape to the same summary shape the UI expects (aligned/review/needsRevision)
        report["provider"] = {"provider": "offline", "label": "Offline review rules (deterministic)"}
    except Exception as exc:
        return f"AI verification could not be completed: {exc}. Try again."
    if not report or not report.get("items"):
        return "Run AI content verification before submitting the minutes."
    summary = report.get("summary") or {}
    if summary.get("needsRevision", 0) > 0 or summary.get("review", 0) > 0:
        bad = [f"Agenda {item.get('agendaNo')} — {item.get('status')}" for item in report.get("items", []) if item.get("status") != "aligned"]
        # Surface the human-readable messages from the first failing item as guidance.
        first_bad = next((i for i in report.get("items", []) if i.get("status") != "aligned"), None)
        hint = ""
        if first_bad and first_bad.get("checks"):
            hint = " " + " ".join(c.get("message","") for c in first_bad["checks"] if c.get("status") != "aligned")[:220]
        detail = "; ".join(bad[:4])
        return (
            f"AI verification must show every agenda as aligned before submission. Issues: {detail}." + hint +
            " Run AI content verification, revise the Discussion and Resolution to match the agenda, and re-run until all are aligned."
        )
    return None


def _validate_owned_uploads(user_id: str, state: dict) -> bool:
    ids = _attachment_ids(state.get("momItems") or [])
    ids.update(str((photo.get("file") or {}).get("id")) for photo in state.get("photos") or [] if (photo.get("file") or {}).get("id"))
    return all((record := get_upload_record(file_id)) is not None and record["owner_id"] == user_id for file_id in ids)


def _approved_mom_snapshot(state: dict) -> dict:
    import copy
    meeting = copy.deepcopy(state.get("meeting") or {})
    meeting["completed"] = False
    meeting["attendanceConfirmed"] = False
    meeting["members"] = [{**member, "present": False} for member in (meeting.get("members") or [])]
    previous = {item.get("agendaId"): item for item in (state.get("momItems") or [])}
    mom_items = []
    for index, agenda in enumerate(meeting.get("agendas") or [], start=1):
        existing = previous.get(agenda.get("id"))
        title = _agenda_document_title(agenda, meeting)
        if existing:
            mom_items.append({**existing, "agendaNo": index, "agendaId": agenda.get("id"), "title": title, "kind": agenda.get("kind", "standard")})
        else:
            mom_items.append({"id": uuid.uuid4().hex, "agendaId": agenda.get("id"), "agendaNo": index, "title": title,
                              "kind": agenda.get("kind", "standard"), "discussion": "", "resolution": "",
                              "noResolution": False, "attachments": []})
    state = {**state, "status": "approved", "meeting": meeting,
             "approvedMeeting": {**meeting, "agendas": [{**agenda, "title": _agenda_document_title(agenda, meeting)} for agenda in (meeting.get("agendas") or [])]},
             "momItems": mom_items, "approvalVersion": int(state.get("approvalVersion") or 0) + 1,
             "officeComment": "", "changeRequest": False, "meetingCompletedAt": "", "pdfGenerated": False}
    return state


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "mode": APP_ENV,
        "authentication": "access-directory allow-list + emailed one-time code",
        "message": ("Sign-in codes are emailed through the configured transport; "
                    "Microsoft 365 SSO can replace this flow."),
        "contentVerification": ai_provider_status(),
        "documentStyle": document_font_status(),
        "agendaLibrary": {"items": len(agenda_library.AGENDA_LIBRARY),
                          "source": agenda_library.SOURCE},
        "documentVault": {"root": str(document_vault.DOCUMENT_ROOT)},
        "notifications": {"store": "sqlite", "channels": ["in-app"]},
        # True only in a demonstration build: the interface shows a fast-track control
        # that moves one meeting's clock so the workflow can be shown end to end.
        "fastTrack": {"enabled": bool(FAST_TRACK), "scope": "one meeting, owned account"},
    })


@app.post("/api/ai/triage")
@roles_required("faculty", "academic_office")
def ai_triage_endpoint():
    """Categorise every agenda resolution and propose the Action Items rows.

    Three categories are possible per resolution - Approved, In process and
    Not approved - and only In process / Not approved resolutions are proposed
    for the Action Items table, using a deliberately very short next-step line.
    The engine is the configured model when a key is available and the
    deterministic cue rules otherwise (see :mod:`resolution_triage`). Nothing is
    written into the minutes: the report is a proposal for the organiser.
    """
    payload = request.get_json(silent=True) or {}
    items = payload.get("momItems") or []
    for item in items:
        _migrate_resolution_keys({"momItems": [item]})
    return jsonify(triage_resolutions(items, payload.get("meeting") or None))


@app.post("/api/ai/check")
@roles_required("faculty", "academic_office")
def ai_check_endpoint():
    """Probe the configured AI provider so a bad key/model is caught before a review."""
    return jsonify(ai_probe())


@app.get("/api/ai/status")
@login_required
def ai_status_endpoint():
    """Report which verification engine and document style are active."""
    return jsonify({
        "ai": ai_provider_status(),
        "document": document_font_status(),
        "checks": ["Agenda ↔ Discussion", "Discussion ↔ Resolution", "Agenda ↔ Resolution",
                   "Numeric / factual consistency", "Outcome consistency"],
        "resolutionTriage": {
            "endpoint": "/api/ai/triage",
            "categories": dict(CATEGORY_LABELS),
            "actionableCategories": list(ACTIONABLE_CATEGORIES),
            "rule": "Only In process and Not approved resolutions are proposed for the Action Items table.",
        },
    })


@app.get("/api/directory/roster")
def directory_roster():
    """The college's teaching roster, published for the sign-in screen.

    Every account in the access directory, with the profile details a person needs
    to recognise themselves (designation, school, department, staff ID) and whether
    a signature is on file. No secret is exposed: sign-in still requires a one-time
    code delivered to the address itself.
    """
    # R1's External Members are real professors of other schools, so their directory role is
    # "faculty". What makes them an External Member is the DAC that nominated them, so that
    # nomination is read from the registry and published alongside the account.
    with connect() as db:
        nominated: dict[str, list[str]] = {}
        for row in db.execute("""SELECT e.email, u.school, u.department FROM dac_external e
                                 JOIN dac_units u ON u.unit_id = e.unit_id"""):
            label = f"{row['school']} / {row['department']}" if row["department"] else row["school"]
            nominated.setdefault(str(row["email"] or "").lower(), []).append(label)

    people = []
    for person in list_users():
        external_for = sorted(set(nominated.get(str(person["email"] or "").lower(), [])))
        people.append({
            "email": person["email"], "name": person["name"], "role": person["role"],
            "designation": person.get("designation") or "",
            "school": person.get("school") or "", "department": person.get("department") or "",
            "employeeCode": person.get("employeeCode") or "",
            "qualification": person.get("qualification") or "",
            "specialization": person.get("specialization") or "",
            "phone": person.get("phone") or "", "office": person.get("office") or "",
            "active": bool(person.get("active", True)),
            "chairpersonEligible": bool(person.get("role") == "faculty"
                                        and is_eligible_chairperson(person)),
            "externalMember": bool(external_for or person.get("role") == "external_member"),
            "externalFor": external_for,
            "hasSignature": bool(signature_store.has_signature(person)),
        })
    order = {"system_admin": 0, "academic_office": 1, "faculty": 2, "external_member": 3}
    people = [row for row in people if row["active"]]
    people.sort(key=lambda row: (order.get(row["role"], 9), row["school"], row["email"]))
    return jsonify({
        "accounts": people,
        "counts": {
            "total": len(people),
            "faculty": sum(1 for row in people if row["role"] == "faculty"),
            "chairpersonEligible": sum(1 for row in people if row["chairpersonEligible"]),
            "academicOffice": sum(1 for row in people if row["role"] == "academic_office"),
            "externalMember": sum(1 for row in people if row["externalMember"]),
        },
    })


@app.post("/api/auth/request-code")
def auth_request_code():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email") or "").strip().lower()
    if not _email_is_valid(email):
        return jsonify({"error": "Enter a valid email address."}), 400
    user = get_user_by_email(email, active_only=True)
    if not user:
        return jsonify({"message": "If the address is active in the access directory, a sign-in code is available."})
    code = f"{secrets.randbelow(1_000_000):06d}"
    now_ts = time_module.time()
    try:
        store_login_code(email, _code_digest(email, code), now_ts + 300, now_ts, request.remote_addr or "")
    except TimeoutError as exc:
        return jsonify({"error": str(exc)}), 429
    delivery = _signin_delivery(_deliver_login_code(user, code))
    if delivery == "email":
        message = f"A sign-in code has been sent to {email}. It is valid for 5 minutes."
    else:
        message = ("No mail server is configured yet, so the sign-in code was printed in the server "
                   "console (the terminal running app.py) and saved to the mail outbox. It is valid for 5 minutes.")
    response = {"message": message, "delivery": delivery, "email": email}
    if DEV_ECHO_OTP or delivery == "console":
        response["devCode"] = code
        response["devCodeReason"] = ("No mail transport is configured, so the code is shown here and in the "
                                     "server console. Configure Microsoft 365 or SMTP and it is emailed only.")
    return jsonify(response)


def _signin_delivery(transport: str) -> str:
    """How the code reaches the account holder: by email, or through the console."""
    return "email" if transport in {"smtp", "graph"} else "console"


def _deliver_login_code(user: dict, code: str) -> str:
    """Send the sign-in code to the account holder and return the delivery channel.

    Delivery uses the configured mail transport (Microsoft 365 Graph or SMTP). With
    no transport configured the message is still written to the mail outbox and the
    code is printed to the server console, so a fresh installation stays operable.
    A sign-in code is never displayed in the browser interface.
    """
    body = (f"Your DAC Minutes Studio sign-in code is {code}.\n\n"
            "It expires in 5 minutes and can be used once.\n"
            "If you did not request it, no action is needed - the code will expire on its own.\n\n"
            f"{user.get('name') or ''} - {user.get('email') or ''}")
    try:
        mail_queue.enqueue(kind="signin_code", to_email=str(user.get("email") or ""),
                           subject="Your DAC Minutes Studio sign-in code", body_text=body,
                           actor=str(user.get("email") or ""))
        mail_queue.flush(limit=5)
    except Exception:                                    # delivery must never block sign-in
        app.logger.exception("Could not queue the sign-in code email")
    transport = str((mail_queue.transport_status() or {}).get("transport") or "console")
    delivery = _signin_delivery(transport)
    if delivery == "email":
        app.logger.info("Sign-in code emailed to %s via %s", user.get("email"), transport)
        return delivery
    banner = "=" * 70
    line = (f"\n{banner}\n SIGN-IN CODE for {user.get('email')} : {code}\n "
            f"No mail transport is configured, so the code is shown here instead of being emailed.\n "
            f"It is also written to {mail_queue.OUTBOX_DIR}\n{banner}\n")
    print(line, flush=True)
    app.logger.warning(line)
    return delivery


@app.post("/api/auth/verify-code")
def auth_verify_code():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email") or "").strip().lower()
    code = str(payload.get("code") or "").strip()
    user = get_user_by_email(email, active_only=True) if _email_is_valid(email) else None
    if not user or not re.fullmatch(r"\d{6}", code) or not verify_login_code(email, _code_digest(email, code), time_module.time()):
        return jsonify({"error": "The code is invalid or expired, or this account is not active in the access directory."}), 401
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    # The same sign-in also issues a bearer token: it keeps the session alive in a browser
    # that blocks the cookie (see authenticate_bearer_token).
    issued = create_api_token(user, csrf=session["csrf_token"])
    signature = signature_store.get_signature(str(user["id"]))
    return jsonify({"user": _public_user(user), "csrfToken": session["csrf_token"],
                    "sessionToken": issued["token"], "sessionExpiresAt": issued["expiresAt"],
                    "signature": signature, "signatureRequired": signature is None})


@app.get("/api/auth/me")
@login_required
def auth_me():
    user = get_current_user()
    signature = signature_store.get_signature(str(user["id"]))
    return jsonify({"user": _public_user(user), "csrfToken": session.get("csrf_token", ""),
                    "sessionToken": _bearer_token(), "signature": signature,
                    "signatureRequired": signature is None})


@app.post("/api/auth/logout")
@login_required
def auth_logout():
    revoke_api_token(_bearer_token())
    session.clear()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- OAuth SSO routes
@app.get("/api/auth/google/login")
def oauth_google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return jsonify({"error": "Google sign-in is not configured by the System Administrator."}), 503
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    session["oauth_provider"] = "google"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("google"),
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return redirect(GOOGLE_AUTH_URL + "?" + urlencode(params))


@app.get("/api/auth/google/callback")
def oauth_google_callback():
    return _oauth_callback("google")


@app.get("/api/auth/microsoft/login")
def oauth_microsoft_login():
    if not MICROSOFT_CLIENT_ID or not MICROSOFT_CLIENT_SECRET:
        return jsonify({"error": "Microsoft sign-in is not configured by the System Administrator."}), 503
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    session["oauth_provider"] = "microsoft"
    params = {
        "client_id": MICROSOFT_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("microsoft"),
        "response_type": "code",
        "scope": MICROSOFT_SCOPE,
        "state": state,
    }
    return redirect(MICROSOFT_AUTH_URL + "?" + urlencode(params))


@app.get("/api/auth/microsoft/callback")
def oauth_microsoft_callback():
    return _oauth_callback("microsoft")


@app.get("/api/catalog")
@roles_required("system_admin", "academic_office", "faculty")
def academic_catalog():
    catalog = get_catalog()
    # The published agenda series follows the committee the caller is working on
    # (DAC #1/#2, or a single BOS meeting), so no screen can show a DAC label
    # above a BOS meeting.
    catalog["agendaLibrary"] = agenda_library.group_payload(
        request.args.get("meetingNo") or "1", request.args.get("committee") or "DAC")
    user = get_current_user()
    if user["role"] == "faculty":
        catalog["schools"] = [school for school in catalog["schools"] if school["name"] == user.get("school")]
    return jsonify(catalog)


@app.get("/api/admin/users")
@roles_required("system_admin")
def admin_list_users():
    """The whole access directory, with each person's R1 DAC office.

    The administrator needs the complete roster here — not only on the sign-in screen —
    because this is the screen used to set a meeting up: who chairs which DAC, who may
    schedule it and who observes it. The offices come from the same registry tables the
    workflow validates against, so the directory can never disagree with the meeting form.
    """
    with connect() as db:
        offices: dict[str, list[dict[str, str]]] = {}
        for row in db.execute("""SELECT o.email, o.role, u.school, u.department FROM dac_office o
                                 JOIN dac_units u ON u.unit_id = o.unit_id"""):
            label = f"{row['school']} / {row['department']}" if row["department"] else row["school"]
            offices.setdefault(str(row["email"] or "").lower(), []).append(
                {"role": "Chairperson" if row["role"] == "chair" else "Member Secretary", "unit": label})
        for row in db.execute("""SELECT e.email, u.school, u.department FROM dac_external e
                                 JOIN dac_units u ON u.unit_id = e.unit_id"""):
            label = f"{row['school']} / {row['department']}" if row["department"] else row["school"]
            offices.setdefault(str(row["email"] or "").lower(), []).append(
                {"role": "External Member", "unit": label})
    people = []
    for person in list_users():
        held = offices.get(str(person["email"] or "").lower(), [])
        order = {"Chairperson": 0, "Member Secretary": 1, "External Member": 2}
        people.append({**person, "dacOffices": sorted(held, key=lambda item: order.get(item["role"], 9)),
                       "hasSignature": bool(signature_store.has_signature(person))})
    return jsonify({"users": people, "roles": ROLE_CHOICES, "catalog": get_catalog()})


@app.post("/api/admin/users")
@roles_required("system_admin")
def admin_add_user():
    payload = request.get_json(silent=True) or {}
    email, name, role = str(payload.get("email") or "").strip().lower(), str(payload.get("name") or "").strip(), str(payload.get("role") or "faculty")
    if not _email_is_valid(email) or not name:
        return jsonify({"error": "Enter a valid email and full name."}), 400
    if role not in ROLES:
        return jsonify({"error": "Choose a valid role."}), 400
    try:
        user = db_add_user(email, name, role, payload.get("school") or None, payload.get("department") or None,
                           payload.get("designation") or None,
                           {key: payload.get(key) for key in PROFILE_FIELDS})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            return jsonify({"error": "That email already exists in the access directory."}), 409
        raise
    audit.record("allowlisted_user_added", actor=get_current_user()["email"], details={"target": user["email"]})
    return jsonify({"user": user}), 201


@app.patch("/api/admin/users/<user_id>")
@roles_required("system_admin")
def admin_update_user(user_id: str):
    payload = request.get_json(silent=True) or {}
    current, admin = get_user_by_id(user_id, active_only=False), get_current_user()
    if not current:
        return jsonify({"error": "Account not found."}), 404
    requested_role = payload.get("role", current["role"])
    requested_active = bool(payload.get("active", current["active"]))
    if current["id"] == admin["id"] and (not requested_active or requested_role != "system_admin"):
        return jsonify({"error": "You cannot deactivate or demote your own System Administrator account."}), 400
    if current["role"] == "system_admin" and (not requested_active or requested_role != "system_admin") and count_active_admins() <= 1:
        return jsonify({"error": "At least one active System Administrator must remain."}), 400
    try:
        updated = db_update_user(user_id, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    audit.record("allowlisted_user_updated", actor=admin["email"], details={"target": updated["email"]})
    return jsonify({"user": updated})


def _people_payload(emails: list[str]) -> list[dict]:
    """Resolve a list of office-holder emails to directory records the UI can show."""
    rows = []
    for email in emails:
        person = get_user_by_email(email, active_only=False)
        if not person:
            continue
        rows.append({"name": person.get("name"), "email": person.get("email"),
                     "designation": person.get("designation"),
                     "school": person.get("school"), "department": person.get("department"),
                     "active": bool(person.get("active", True)),
                     "hasSignature": signature_store.has_signature(person)})
    return rows


def _unit_payload_with_people(unit: dict) -> dict:
    people = {person["email"]: person for person in list_users()}
    chairs = [{"name": (people.get(email) or {}).get("name") or email, "email": email,
               "designation": (people.get(email) or {}).get("designation") or "",
               "school": (people.get(email) or {}).get("school") or "",
               "department": (people.get(email) or {}).get("department") or "",
               "hasSignature": signature_store.has_signature(people.get(email) or {"email": email})}
              for email in unit["chairs"]]
    secretaries = [{"name": (people.get(email) or {}).get("name") or email, "email": email,
                    "designation": (people.get(email) or {}).get("designation") or ""}
                   for email in unit["secretaries"]]
    return {**unit, "chairPeople": chairs, "secretaryPeople": secretaries}


@app.get("/api/dac/units")
@login_required
def dac_units():
    """Every DAC unit: school, department (or none), programmes, offices."""
    user = get_current_user()
    with connect() as db:
        units = dac_registry.all_units(db)
        mine = {"secretary": [unit["unitId"] for unit in dac_registry.units_for_secretary(db, user["email"])],
                "chair": [unit["unitId"] for unit in dac_registry.units_for_chair(db, user["email"])],
                "external": [unit["unitId"] for unit in dac_registry.units_for_external(db, user["email"])]}
    school = str(request.args.get("school") or "").strip()
    if school:
        units = [unit for unit in units if unit["school"] == school]
    return jsonify({"units": [_unit_payload_with_people(unit) for unit in units], "mine": mine,
                    "catalog": get_catalog()})


@app.get("/api/dac/office")
@login_required
def dac_office():
    """The offices of one DAC: who may chair, who may schedule, who observes."""
    school = str(request.args.get("school") or "").strip()
    department = str(request.args.get("department") or "").strip() or None
    if not school:
        return jsonify({"error": "Choose the school of the meeting first."}), 400
    with connect() as db:
        unit = dac_registry.unit_for(db, school, department)
    if not unit:
        return jsonify({"error": "That school/department has no DAC in the registry."}), 404
    return jsonify({"unit": _unit_payload_with_people(unit)})


@app.get("/api/capabilities")
@login_required
def capabilities():
    """What this account may do in the workflow, and why.

    A DAC may only be scheduled by one of its Member Secretaries, and only one live
    request may exist per DAC at a time — the other Member Secretaries of the same DAC
    keep read access but the scheduling action is closed to them.
    """
    user = get_current_user()
    with connect() as db:
        secretariats = dac_registry.units_for_secretary(db, user["email"])
        chairs = dac_registry.units_for_chair(db, user["email"])
        externals = dac_registry.units_for_external(db, user["email"])
    live = [workspace for workspace in list_pending_workspaces(include_chairperson=True)]
    live_by_unit = {}
    for summary in live:
        workspace = get_workspace(summary["workspaceId"])
        if not workspace:
            continue
        meeting = (workspace["payload"] or {}).get("meeting") or {}
        key = dac_registry.unit_id(meeting.get("school"), meeting.get("department"))
        live_by_unit.setdefault(key, []).append({
            "workspaceId": summary["workspaceId"], "status": summary.get("status"),
            "owner": summary.get("ownerName"), "ownerEmail": summary.get("ownerEmail"),
            "date": meeting.get("date"), "meetingNo": meeting.get("meetingNo")})
    scheduling = []
    for unit in secretariats:
        existing = live_by_unit.get(unit["unitId"], [])
        scheduling.append({"unitId": unit["unitId"], "school": unit["school"],
                           "department": unit["department"], "unit": _unit_payload_with_people(unit),
                           "open": not existing, "existing": existing})
    reason = ""
    if user["role"] != "faculty":
        reason = "Only faculty accounts sign meeting requests."
    elif not secretariats:
        reason = ("Your account is not a Member Secretary of a DAC, so it cannot start a "
                  "meeting request. You can still sign in, review and sign what is addressed to you.")
    elif all(item["existing"] for item in scheduling):
        reason = "A meeting request for your DAC is already open; finish it before starting another."
    return jsonify({"role": user["role"], "scheduling": scheduling,
                    "canSchedule": bool(scheduling) and any(item["open"] for item in scheduling),
                    "reason": reason, "chairs": chairs,
                    "isChair": bool(chairs), "externalUnits": externals,
                    "isExternal": bool(externals),
                    # The demonstration fast-forward, offered to the organizer of a meeting
                    # only. Absent from every production build.
                    "fastTrack": {"enabled": bool(FAST_TRACK) and user["role"] == "faculty"}})


@app.post("/api/dac/external")
@login_required
def add_dac_external():
    """Add an External Member to a DAC (R1 names the member; this adds new ones)."""
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    school = str(payload.get("school") or "").strip()
    department = str(payload.get("department") or "").strip() or None
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    designation = str(payload.get("designation") or "").strip()
    if not school or not name or not _email_is_valid(email):
        return jsonify({"error": "Give the external member's name, a valid email and the school."}), 400
    with connect() as db:
        secretary = dac_registry.is_secretary(db, user["email"], school, department)
        if user["role"] != "system_admin" and not secretary:
            return jsonify({"error": "Only the Member Secretary of this DAC or the System "
                                     "Administrator can add an external member."}), 403
        try:
            record = dac_registry.add_external(db, school, department, name, designation, email,
                                               dac_registry_now())
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404
    if not get_user_by_email(email, active_only=False):
        db_add_user(email, name, "external_member", None, None, designation or "External Member")
        audit.record("external_member_provisioned", actor=user["email"], details={"target": email})
    audit.record("dac_external_added", actor=user["email"],
                 details={"school": school, "department": department or "", "member": email})
    return jsonify({"external": record}), 201


def dac_registry_now() -> str:
    from auth_store import now_iso
    return now_iso()


@app.get("/api/workspace")
@login_required
def get_current_workspace():
    user = get_current_user()
    workspace = None
    if user["role"] == "faculty":
        workspace = workspace_for_owner(user["id"])
    elif user["role"] == "academic_office":
        workspace = latest_pending_workspace()
    elif user["role"] == "external_member":
        from auth_store import connect as _connect
        with _connect() as db:
            rows = db.execute("SELECT workspace_id FROM workspaces WHERE status='approved' ORDER BY updated_at DESC").fetchall()
        for row in rows:
            if workspace_access_for_email(row["workspace_id"], user["email"]):
                workspace = get_workspace(row["workspace_id"])
                break
    else:
        return jsonify({"error": "System Administrators manage the access directory, not meeting content."}), 403
    return jsonify(_external_workspace_payload(workspace) if user["role"] == "external_member" else _workspace_payload(workspace))


@app.get("/api/directory/faculty")
@roles_required("faculty", "academic_office")
def directory_faculty():
    """Faculty picker source for the Chairperson and External Member fields.

    Only the fields needed to choose a person are returned; the directory itself
    is unchanged and remains administrator-managed.
    """
    people = []
    for person in list_users():
        if not person.get("active") or person.get("role") not in {"faculty", "external_member"}:
            continue
        people.append({"id": person["id"], "email": person["email"], "name": person["name"],
                       "designation": person.get("designation") or "", "school": person.get("school") or "",
                       "department": person.get("department") or "", "role": person["role"]})
    meeting_school = str(request.args.get("school") or "").strip()
    return jsonify({"people": people, "school": meeting_school,
                    "note": "The Chairperson must be faculty of the same school and must not be the Member Secretary. "
                            "The External Member must be faculty of a different school."})


@app.get("/api/workspaces/inbox")
@roles_required("academic_office")
def workspace_inbox():
    return jsonify({"workspaces": list_pending_workspaces()})


@app.get("/api/workspaces/previous-meeting")
@login_required
def previous_meeting():
    """The last approved meeting of the same DAC/BOS.

    The meeting-request form auto-fills its previous-meeting reference (number and
    date) from here, so the Member Secretary never types it by hand.
    """
    school = (request.args.get("school") or "").strip()
    department = (request.args.get("department") or "").strip()
    committee = (request.args.get("committee") or "DAC").strip().upper() or "DAC"
    exclude = (request.args.get("exclude") or "").strip()
    best: tuple[str, str, str] | None = None
    with connect() as db:
        rows = db.execute(
            "SELECT workspace_id, payload_json FROM workspaces WHERE status='approved' ORDER BY updated_at DESC"
        ).fetchall()
    for row in rows:
        if row["workspace_id"] == exclude:
            continue
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        meeting = payload.get("meeting") or {}
        if (meeting.get("school") or "") != school or (meeting.get("department") or "") != department:
            continue
        if _committee_of(payload) != committee:
            continue
        date = str(meeting.get("date") or "")
        if best is None or date > best[0]:
            best = (date, str(meeting.get("meetingNo") or ""), row["workspace_id"])
    if not best:
        return jsonify({"meetingNo": "", "date": ""})
    return jsonify({"meetingNo": best[1], "date": best[0], "workspaceId": best[2]})


@app.get("/api/workspaces/mine")
@roles_required("faculty")
def my_workspaces():
    user = get_current_user()
    return jsonify({"workspaces": list_workspaces_for_owner(user["id"])})


@app.get("/api/workspace/<workspace_id>/signatures")
@login_required
def workspace_signatures(workspace_id: str):
    """The signatures on one meeting: the request form and the minutes.

    The PDFs already print both signature blocks; the interface must show the same
    evidence, otherwise the Academic Office reviews a document that looks unsigned.
    Two sets are returned — ``signatures`` for the meeting request (Member Secretary,
    Chairperson, Academic Office) and ``momSignatures`` for the filled minutes — each
    with the drawn image, name, designation, role and the moment it was given.

    Only this workspace's signatories are returned, and only to accounts that may
    read the workspace.
    """
    workspace = get_workspace(workspace_id)
    if not workspace:
        # New draft not yet saved to server (e.g. DAC-xxx-mwc... from localStorage) — return empty instead of 404 to keep console clean and allow preview
        return jsonify({"workspaceId": workspace_id, "status": "draft", "committee": {"code": "DAC"}, "signatures": [], "complete": False, "momSignatures": [], "momStatus": "draft", "momComplete": False, "momSubmitted": False})
    user = get_current_user()
    state = _migrate_resolution_keys(workspace["payload"])
    meeting = state.get("meeting") or {}
    is_owner = workspace["ownerId"] == user["id"]
    is_chair = str(meeting.get("chairEmail") or "").lower() == str(user["email"] or "").lower()
    is_office = user["role"] in {"academic_office", "system_admin"}
    if not (is_owner or is_chair or is_office):
        return jsonify({"error": "These signatures are outside your access scope."}), 403

    def _image(record: dict | None) -> str:
        path = signature_store.signature_path(record) if record else None
        if path is None:
            return ""
        try:
            import base64
            return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            return ""

    def _entry(role: str, name: str, designation: str, email: str, signed_at: str = "",
               record: dict | None = None, decision: str = "", note: str = "") -> dict:
        # One readable stamp for every row: the raw ISO value leaked through for the
        # Chairperson and the Academic Office while the Member Secretary showed the
        # formatted form, so the same block read "26 Oct 2026, 22:06" next to
        # "2026-10-26 16:36". The PDFs already print the readable form.
        return {"role": role, "name": name, "designation": designation, "email": email,
                "signedAt": _readable_stamp(signed_at), "signedAtRaw": str(signed_at or ""),
                "signed": bool(record), "decision": decision,
                "note": note, "version": (record or {}).get("version", 0), "image": _image(record)}

    owner = get_user_by_id(workspace["ownerId"]) or {}
    chair_email = str(meeting.get("chairEmail") or "")
    chair = get_user_by_email(chair_email, active_only=False) or {}
    chair_approval = state.get("chairApproval") or {}
    office_stamp = (state.get("officeDecision") or {})
    office_account = get_user_by_email(office_stamp.get("email") or "", active_only=False) or {}
    committee = _committee_of(state)
    owner_record = signature_store.signature_for_email(owner.get("email") or "")

    request_rows = [
        _entry("Member Secretary", owner.get("name") or meeting.get("secretaryName") or "",
               owner.get("designation") or "", owner.get("email") or "",
               str(state.get("submittedAt") or ""), owner_record,
               note="Signs on submission"),
        _entry("Chairperson", chair.get("name") or meeting.get("chairName") or "",
               chair.get("designation") or "", chair_email,
               str(chair_approval.get("signedAt") or chair_approval.get("decidedAt") or ""),
               signature_store.signature_for_email(chair_email)
               if chair_approval.get("decision") == "approved" else None,
               decision=str(chair_approval.get("decision") or ""),
               note="Signs before the Academic Office review"),
    ]
    # Academic Office row removed for both DAC and BOS — request carries only MS + Chairperson (user request 2026-11-10)

    # ---- the minutes have their own signatures — DAC: MS + Chairperson only
    review = state.get("momReview") or {}
    mom_secretary = review.get("secretarySignature") or None
    mom_chair = review.get("chairSignature") or None
    mom_office = review.get("officeSignature") or None
    mom_status = str(review.get("status") or "draft")
    mom_rows = [
        _entry("Member Secretary", owner.get("name") or meeting.get("secretaryName") or "",
               owner.get("designation") or "", owner.get("email") or "",
               str((mom_secretary or {}).get("signedAt") or review.get("submittedAt") or ""),
               mom_secretary, note="Signs the filled minutes"),
        _entry("Chairperson", chair.get("name") or meeting.get("chairName") or "",
               chair.get("designation") or "", chair_email,
               str((mom_chair or {}).get("signedAt") or (review.get("chairDecisionAt") or "")),
               mom_chair, decision="approved" if mom_chair else str(review.get("status") or ""),
               note="Signs when approving the minutes"),
    ]
    # Academic Office row removed for both DAC and BOS (user request 2026-11-10) — no append
    if False:  # keep block for reference, never executed
        mom_rows.append(
            _entry("Academic Office", (mom_office or {}).get("name") or office_account.get("name") or "",
                   (mom_office or {}).get("designation") or office_account.get("designation") or "",
                   (mom_office or {}).get("email") or office_stamp.get("email") or "",
                   str((mom_office or {}).get("signedAt") or review.get("officeDecisionAt") or ""),
                   mom_office, decision="approved" if mom_office else "",
                   note="Signs on final approval")
        )
    return jsonify({
        "workspaceId": workspace_id,
        "status": workspace["status"],
        "committee": _committee_payload(committee),
        "signatures": request_rows,
        "complete": all(row["signed"] for row in request_rows[:2]),
        "momSignatures": mom_rows,
        "momStatus": mom_status,
        "momComplete": all(row["signed"] for row in mom_rows),
        "momSubmitted": bool(mom_secretary),
    })


@app.get("/api/workspaces/<workspace_id>")
@login_required
def get_workspace_detail(workspace_id: str):
    workspace = get_workspace(workspace_id)
    if not workspace:
        return jsonify({"error": "Workspace not found."}), 404
    user = get_current_user()
    nominated_external = workspace_access_for_email(workspace_id, user["email"])
    meeting_payload = workspace["payload"].get("meeting") or {}
    is_chairperson = (user["role"] == "faculty"
                      and str(meeting_payload.get("chairEmail") or "").lower() == str(user["email"]).lower())
    submitted_once = int((workspace["payload"] or {}).get("submittedVersion") or 0) > 0
    allowed = ((user["role"] == "faculty" and workspace["ownerId"] == user["id"])
               or (user["role"] == "academic_office" and (workspace["status"] in {"pending", "approved"} or submitted_once))
               or (user["role"] == "system_admin" and submitted_once)
               # The Chairperson must be able to read what they are asked to sign.
               or (is_chairperson and workspace["status"] in {"pending_chairperson", "revision", "approved"})
               or nominated_external)
    if not allowed:
        return jsonify({"error": "This meeting is outside your access scope."}), 403
    # The nominated Chairperson signs the request, so they see it in full; only a
    # nominated External Member gets the redacted guest view.
    guest_view = (nominated_external and not is_chairperson
                  and workspace["ownerId"] != user["id"] and user["role"] != "academic_office")
    return jsonify(_external_workspace_payload(workspace) if guest_view else _workspace_payload(workspace))


@app.post("/api/workspace/save")
@roles_required("faculty")
def save_current_workspace():
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    state = _stamp_committee(_migrate_resolution_keys(payload.get("state") or {}))
    meeting = state.get("meeting") or {}
    workspace_id = str(payload.get("workspaceId") or meeting.get("id") or "").strip()
    if not workspace_id or len(workspace_id) > 120:
        return jsonify({"error": "Missing or invalid workspace identifier."}), 400
    existing = get_workspace(workspace_id)
    if existing and existing["ownerId"] != user["id"]:
        return jsonify({"error": "This workspace belongs to another account."}), 403
    error = _validate_workspace_proposal(state, user)
    if error and state.get("status") in {"pending", "approved"}:
        return jsonify({"error": error}), 400
    status = existing["status"] if existing else "draft"
    if existing and status == "approved":
        if state.get("status") == "revision" and not meeting_start_passed(existing["payload"].get("meeting") or {}):
            change_request = {**existing["payload"], "status": "revision", "officeComment": "Faculty proposed a change; resubmission requires Academic Office review.", "changeRequest": True}
            save_workspace(workspace_id, user["id"], change_request, "revision")
            return jsonify({"ok": True, "state": change_request, "status": "revision"})
        # The unlock gate is read from the STORED record, never from the request body:
        # otherwise a client could send a stale copy (status "approved", review "draft")
        # and keep editing the minutes after the Academic Office had approved them.
        if state.get("status") != "approved" or not can_edit_minutes(existing["payload"]):
            return jsonify({"error": "Approved meeting content is locked until the scheduled end time has passed AND "
                                     "the meeting is marked completed; once the minutes are submitted or approved "
                                     "the record is frozen."}), 409
        if not _validate_owned_uploads(user["id"], state):
            return jsonify({"error": "An attachment is not owned by this account."}), 403
        old, new_meeting = existing["payload"], state.get("meeting") or {}
        old_meeting = old.get("meeting") or {}
        immutable_fields = ("meetingNo", "academicYear", "semester", "school", "department", "schoolCode", "departmentCode", "previousMeetingNo", "previousMeetingDate", "date", "startTime", "endTime", "venue", "mode", "onlineLink", "chairName", "chairEmail")
        differing = [field for field in immutable_fields if new_meeting.get(field) != old_meeting.get(field)]
        if differing:
            # Name the field(s) so the organiser (and any support conversation) knows
            # exactly which approved detail is being changed rather than guessing.
            return jsonify({
                "error": "Approved meeting details and agenda wording are read-only; submit a change for reapproval.",
                "readOnlyFields": differing,
            }), 403
        if [item.get("id") for item in new_meeting.get("agendas", [])] != [item.get("id") for item in old_meeting.get("agendas", [])]:
            return jsonify({"error": "Approved agenda wording and sequence are immutable."}), 403
        old_members, new_members = old_meeting.get("members", []), new_meeting.get("members", [])
        if [{key: member.get(key) for key in ("id", "name", "designation", "role", "email")} for member in new_members] != [{key: member.get(key) for key in ("id", "name", "designation", "role", "email")} for member in old_members]:
            return jsonify({"error": "The approved invitee roster is immutable in the MoM."}), 403
        old_items = {item.get("id"): item for item in old.get("momItems", [])}
        new_items = {item.get("id"): item for item in state.get("momItems", [])}
        if set(old_items) != set(new_items):
            return jsonify({"error": "Approved MoM sections cannot be added or removed."}), 403
        merged = dict(old)
        merged_meeting = dict(old_meeting)
        merged_meeting["completed"] = bool(new_meeting.get("completed"))
        merged_meeting["attendanceConfirmed"] = bool(new_meeting.get("attendanceConfirmed"))
        merged_meeting["members"] = [{**member, "present": bool(new_members[index].get("present"))} for index, member in enumerate(old_members)]
        merged["meeting"] = merged_meeting
        merged["meetingCompletedAt"] = state.get("meetingCompletedAt", old.get("meetingCompletedAt", ""))
        merged["momItems"] = [{**old_items[item_id], **{key: new_items[item_id].get(key) for key in ("discussion", "resolution", "noResolution", "attachments")}} for item_id in old_items]
        merged["additionalDiscussions"] = state.get("additionalDiscussions") or []
        merged["photos"] = state.get("photos") or []
        merged["actionItems"] = state.get("actionItems") or []
        merged["aiReport"] = state.get("aiReport")
        merged["pdfGenerated"] = False
        save_workspace(workspace_id, user["id"], merged, "approved")
        return jsonify({"ok": True, "state": merged, "status": "approved"})
    if existing and status == "pending":
        return jsonify({"ok": True, "status": "pending", "state": existing["payload"]})
    if state.get("status") not in ({"draft", "revision", "rejected"} if existing else {"draft"}):
        return jsonify({"error": "Only an editable draft can be autosaved."}), 409
    if not _meeting_profile_matches(meeting, user):
        return jsonify({"error": "Meeting organizer, school and department must match the signed-in faculty profile."}), 403
    state["status"] = status if existing else "draft"
    save_workspace(workspace_id, user["id"], state, state["status"])
    return jsonify({"ok": True, "status": state["status"]})


@app.post("/api/workspace/submit")
@roles_required("faculty")
def submit_workspace():
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    state = _migrate_resolution_keys(payload.get("state") or {})
    meeting = state.get("meeting") or {}
    workspace_id = str(payload.get("workspaceId") or meeting.get("id") or "").strip()
    if not workspace_id:
        return jsonify({"error": "Missing meeting workspace identifier."}), 400
    error = _validate_workspace_proposal(state, user)
    if error:
        return jsonify({"error": error}), 400
    existing = get_workspace(workspace_id)
    if existing and existing["ownerId"] != user["id"]:
        return jsonify({"error": "This workspace belongs to another account."}), 403
    if existing and existing["status"] not in {"draft", "revision", "rejected"}:
        is_premeeting_change = existing["status"] == "approved" and state.get("status") == "revision" and not meeting_start_passed(existing["payload"].get("meeting") or {})
        if not is_premeeting_change:
            return jsonify({"error": "This request is not editable or is already pending review."}), 409
        state["changeRequest"] = True
    if not signature_store.has_signature(user):
        return jsonify({"error": "Record your digital signature before submitting — it is stamped on the request form.",
                        "signatureRequired": True}), 428
    state = _stamp_committee(state)
    meeting = state.get("meeting") or {}
    committee = state["committee"]
    previous_state = (existing or {}).get("payload") or {}
    previous_chair = previous_state.get("chairApproval") or {}
    # The Chairperson stays in the loop on EVERY version. A first submission, a revision
    # returned by the Chairperson and a revision returned by the Academic Office all
    # route to the Chairperson first: nothing reaches the Academic Office unsigned.
    counted_as_office_revision = bool(
        existing and (existing["status"] == "revision" or previous_state.get("officeDecision") == "revision"))
    revised_in_place = bool(previous_chair.get("decision") or previous_state.get("submittedVersion"))
    chair_history = list(previous_state.get("chairApprovalHistory") or [])
    if previous_chair:
        # The earlier decision is kept as a record, but it no longer signs this version.
        chair_history.append({**previous_chair, "forVersion": previous_state.get("submittedVersion")})
    state["status"] = "pending_chairperson"
    state["submittedAt"] = datetime.now(COLLEGE_TZ).strftime("%d %b %Y, %H:%M")
    state["submittedVersion"] = int(state.get("submittedVersion") or 0) + 1
    state["officeComment"] = ""
    state["chairComment"] = ""
    state["secretarySignature"] = signature_store.stamp(user)
    state["proposalReference"] = state.get("proposalReference") or _reference_number(meeting, "request")
    state["chairReviewCompleted"] = False
    state["routedTo"] = "Chairperson"
    state["chairApproval"] = {}
    state["chairApprovalHistory"] = chair_history
    state["chairReviewNote"] = (
        "The Chairperson reviews this version and signs it again before the Academic Office sees it."
        if revised_in_place else "")
    history = list(state.get("submittedHistory") or [])
    history.append({"at": state["submittedAt"], "version": state["submittedVersion"],
                    "routedTo": "Chairperson", "chairReviewReused": False,
                    "resubmission": bool(revised_in_place),
                    "afterOfficeRevision": counted_as_office_revision})
    state["submittedHistory"] = history
    save_workspace(workspace_id, user["id"], state, state["status"])
    chair_email = str(meeting.get("chairEmail") or "")
    label = f"{meeting.get('meetingNo') or ''} {committee}".strip()
    notification_store.notify(
        chair_email, "approval_request",
        (f"Revised {committee} request awaiting your signature" if revised_in_place
         else f"{committee} request awaiting your signature"),
        (f"{user['name']} (Member Secretary) resubmitted the corrected {label} meeting request for "
         f"{meeting.get('department') or ''} on {_format_date_dmy(meeting.get('date'))}. "
         if revised_in_place else
         f"{user['name']} (Member Secretary) submitted the {label} meeting request for "
         f"{meeting.get('department') or ''} on {_format_date_dmy(meeting.get('date'))}. ")
        + "Your review and signature are needed again.",
        workspace_id=workspace_id, link=f"/?workspace={workspace_id}", actor=user["email"],
        dedupe_key=f"request-chair-{workspace_id}-{state['submittedVersion']}")
    if counted_as_office_revision:
        _notify_office(workspace_id, meeting, f"{committee} request returned for correction",
                       f"{user['name']} resubmitted the corrected {label} request; it is back with the "
                       "Chairperson for review and signature before it reaches you.")
    audit.record("request_submitted", actor=user["email"], role=user["role"],
                 workspace_id=workspace_id,
                 details={"committee": committee, "routedTo": state["routedTo"],
                          "chairReviewReused": False})
    return jsonify({"ok": True, "workspaceId": workspace_id, "state": state, "status": state["status"],
                    "committee": _committee_payload(committee),
                    "routedTo": state["routedTo"], "chairReviewReused": False})


@app.get("/api/signature/me")
@login_required
def signature_me():
    user = get_current_user()
    return jsonify({"signature": signature_store.get_signature(str(user["id"])),
                    "history": signature_store.history(str(user["id"])),
                    "required": not signature_store.has_signature(user)})


@app.post("/api/signature")
@login_required
def signature_register():
    """Register or replace the signed-in account's signature (drawn or uploaded)."""
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    method = str(payload.get("method") or "upload").strip().lower()
    try:
        record = signature_store.save_signature(user, str(payload.get("image") or ""), method)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    audit.record("signature_registered", actor=user["email"], role=user["role"],
                 details={"version": record.get("version")})
    return jsonify({"ok": True, "signature": record})


@app.get("/api/signature/<user_id>.png")
@login_required
def signature_image(user_id):
    """Serve a signature image to its owner, the Academic Office and the System Administrator."""
    user = get_current_user()
    owner = get_user_by_id(user_id)
    if not owner:
        return jsonify({"error": "Unknown account."}), 404
    allowed = (owner["id"] == user["id"] or user["role"] in {"academic_office", "system_admin"}
               or is_eligible_chairperson(owner))
    if not allowed:
        return jsonify({"error": "This signature is not available to your account."}), 403
    record = signature_store.get_signature(user_id)
    path = signature_store.signature_path(record)
    if not path:
        return jsonify({"error": "No signature registered for this account."}), 404
    return send_file(path, mimetype="image/png", max_age=0)


@app.get("/api/directory/chairpersons")
@login_required
def chairperson_directory():
    """The Deans and Heads of Department who may chair a DAC meeting."""
    user = get_current_user()
    school = request.args.get("school") or (user.get("school") if user["role"] == "faculty" else "")
    people = [person for person in chairperson_candidates(school or None)]
    return jsonify({
        "chairpersons": [{"name": person.get("name"), "email": person.get("email"),
                          "designation": person.get("designation"), "school": person.get("school"),
                          "department": person.get("department"),
                          "hasSignature": signature_store.has_signature(person)}
                         for person in people if str(person.get("email") or "").lower() != str(user.get("email") or "").lower()],
        "school": school,
        "rule": "The Chairperson must be the Dean or a Head of Department of the meeting's own school, and cannot be the Member Secretary.",
    })


@app.get("/api/workspaces/chair-inbox")
@roles_required("faculty")
def chairperson_inbox():
    """Requests waiting for this Chairperson's signature."""
    user = get_current_user()
    rows = []
    for summary in list_pending_workspaces(include_chairperson=True):
        if summary.get("status") != "pending_chairperson":
            continue
        workspace = get_workspace(summary["workspaceId"])
        if not workspace:
            continue
        meeting = (workspace["payload"].get("meeting") or {})
        if str(meeting.get("chairEmail") or "").lower() != str(user["email"]).lower():
            continue
        rows.append({**summary, "proposedBy": summary.get("ownerName"),
                     "agendaCount": len(meeting.get("agendas") or []),
                     "memberCount": len(meeting.get("members") or []),
                     "submittedAt": workspace["payload"].get("submittedAt", ""),
                     "chairApproved": (workspace["payload"].get("chairApproval") or {}).get("decision") == "approved"})
    return jsonify({"workspaces": rows})


@app.post("/api/workspace/chair-decision")
@roles_required("faculty")
def chairperson_request_decision():
    """The Chairperson approves or returns the request before it reaches the Academic Office."""
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    workspace_id = str(payload.get("workspaceId") or "")
    decision = str(payload.get("decision") or "").strip().lower()
    comment = str(payload.get("comment") or "").strip()
    workspace = get_workspace(workspace_id)
    if not workspace or workspace["status"] != "pending_chairperson":
        return jsonify({"error": "This request is not awaiting a Chairperson decision."}), 409
    state = workspace["payload"]
    meeting = state.get("meeting") or {}
    if str(meeting.get("chairEmail") or "").lower() != str(user["email"]).lower():
        return jsonify({"error": "Only the nominated Chairperson can decide this request."}), 403
    if decision not in {"approved", "revision"}:
        return jsonify({"error": "Choose approve or return for revision."}), 400
    if decision == "revision" and not comment:
        return jsonify({"error": "Add a reason so the Member Secretary knows what to change."}), 400
    if decision == "approved" and not signature_store.has_signature(user):
        return jsonify({"error": "Register your signature before approving — it is stamped on the request form.",
                        "signatureRequired": True}), 428
    stamp = signature_store.stamp(user)
    chair_approval = {**stamp, "decision": "approved" if decision == "approved" else "revision",
                      "comment": comment, "decidedAt": stamp["signedAt"]}
    if decision == "approved":
        state = {**state, "status": "pending", "chairApproval": chair_approval, "chairComment": "",
                 "chairReviewCompleted": True,
                 "chairDecidedAt": chair_approval["signedAt"]}
        new_status = "pending"
    else:
        state = {**state, "status": "revision", "chairApproval": chair_approval, "chairComment": comment,
                 "chairDecidedAt": chair_approval["signedAt"]}
        new_status = "revision"
    save_workspace(workspace_id, workspace["ownerId"], state, new_status)
    owner = get_user_by_id(workspace["ownerId"])
    audit.record("chairperson_request_approved" if decision == "approved" else "chairperson_request_revision",
                 actor=user["email"], role=user["role"], workspace_id=workspace_id,
                 details={"comment": comment})
    if decision == "approved":
        for office_user in [person for person in list_users() if person["role"] == "academic_office" and person["active"]]:
            notification_store.notify(
                office_user["email"], "approval_request",
                "DAC request signed by the Chairperson",
                f"{meeting.get('department') or ''} · {meeting.get('meetingNo')} DAC meeting is ready for Academic Office review.",
                workspace_id=workspace_id, link=f"/?workspace={workspace_id}", actor=user["email"])
        if owner:
            notification_store.notify(owner["email"], "approval_done", "Chairperson approved your request",
                                      "The request now carries the Chairperson's signature and is with the Academic Office.",
                                      workspace_id=workspace_id, actor=user["email"])
    elif owner:
        notification_store.notify(owner["email"], "revision", "Chairperson returned your request",
                                  comment, workspace_id=workspace_id, actor=user["email"])
    return jsonify({"ok": True, "status": new_status, "state": state, "chairApproval": chair_approval})


@app.get("/api/workspace/<workspace_id>/request-form")
@login_required
def download_request_form(workspace_id):
    """The signed request & agenda approval form.

    The Member Secretary may download it only after the Academic Office approves;
    the Chairperson may preview what they signed, and the Academic Office may read
    it in order to decide.
    """
    user = get_current_user()
    workspace = get_workspace(workspace_id)
    if not workspace:
        return jsonify({"error": "Unknown workspace."}), 404
    state = workspace["payload"]
    meeting = state.get("meeting") or {}
    is_owner = workspace["ownerId"] == user["id"]
    is_chair = str(meeting.get("chairEmail") or "").lower() == str(user["email"]).lower()
    is_office = user["role"] in {"academic_office", "system_admin"}
    if not (is_owner or is_chair or is_office):
        return jsonify({"error": "This request form is not available to your account."}), 403
    if is_owner and not is_office and workspace["status"] != "approved":
        return jsonify({"error": "The signed request form is downloadable once the Academic Office approves the request.",
                        "status": workspace["status"]}), 409
    pdf_bytes = _build_request_form_pdf(workspace)
    name = f"DAC-request-{(meeting.get('department') or 'DAC').replace(' ', '-')}-{meeting.get('date') or ''}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
                     download_name=name, max_age=0)


@app.get("/api/mail/summary")
@roles_required("system_admin", "academic_office")
def mail_summary():
    return jsonify(mail_queue.summary())


@app.get("/api/mail/queue")
@roles_required("system_admin", "academic_office")
def mail_queue_list():
    return jsonify({"mails": mail_queue.list_queue(limit=int(request.args.get("limit") or 100),
                                                   status=request.args.get("status") or None)})


@app.post("/api/mail/flush")
@roles_required("system_admin")
def mail_flush():
    return jsonify({"ok": True, **mail_queue.flush()})


@app.post("/api/workspace/decision")
@roles_required("academic_office")
def decide_workspace():
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    workspace_id = str(payload.get("workspaceId") or "")
    decision, comment = str(payload.get("decision") or ""), str(payload.get("comment") or "").strip()
    workspace = get_workspace(workspace_id)
    if not workspace or workspace["status"] != "pending":
        return jsonify({"error": "This request is no longer pending review."}), 409
    if decision not in {"approved", "revision", "rejected"}:
        return jsonify({"error": "Choose approve, return for revision, or reject."}), 400
    if decision in {"revision", "rejected"} and not comment:
        return jsonify({"error": "Add a specific review comment or rejection reason."}), 400
    state = workspace["payload"]
    if decision in {"revision", "rejected"} and not (state.get("chairApproval") or {}).get("signatureSha256"):
        return jsonify({"error": "This request has not been signed by the Chairperson yet."}), 409
    office_stamp = signature_store.stamp(user)
    office_decision = {**office_stamp, "decision": decision, "comment": comment, "decidedAt": office_stamp["signedAt"]}
    document = None
    if decision == "approved":
        owner = get_user_by_id(workspace["ownerId"], active_only=True)
        proposal_error = _validate_workspace_proposal(state, owner) if owner else "The meeting owner account is no longer active."
        if proposal_error:
            return jsonify({"error": f"The request can no longer be approved: {proposal_error}"}), 409
        state = _approved_mom_snapshot(state)
        state["officeDecision"] = office_decision
        # The signed request form is the approved paperwork: archive it in the vault.
        try:
            pdf_bytes = _build_request_form_pdf({**workspace, "payload": state, "status": "approved"})
            meeting_now = state.get("meeting") or {}
            document = document_vault.store_document(
                school=str(meeting_now.get("school") or "Unspecified"),
                department=str(meeting_now.get("department") or ""),
                academic_year=str(meeting_now.get("academicYear") or ""),
                semester=str(meeting_now.get("semester") or ""),
                workspace_id=workspace_id,
                meeting_ref=str(state.get("proposalReference") or meeting_now.get("referenceNo") or ""),
                doc_type="request",
                committee=str(state.get("committee") or meeting_now.get("committee") or "DAC"),
                title=(f"{str(state.get('committee') or meeting_now.get('committee') or 'DAC').upper()} "
                       f"request and agenda approval form — {meeting_now.get('department') or ''}").strip(" —"),
                pdf_bytes=pdf_bytes, created_by=user["email"],
                version=int(state.get("submittedVersion") or 1),
                meta={"chairperson": meeting_now.get("chairName", ""),
                      "reference": state.get("proposalReference", "")})
            state["requestDocumentId"] = document["id"]
        except Exception as exc:  # pragma: no cover - archive must not break approval
            state["requestDocumentError"] = str(exc)[:200]
        save_workspace(workspace_id, workspace["ownerId"], state, "approved")
    else:
        state = {**state, "status": decision, "officeComment": comment, "officeDecision": office_decision}
        save_workspace(workspace_id, workspace["ownerId"], state, decision)
    event = "agenda_and_members_approved" if decision == "approved" else "request_returned_for_revision" if decision == "revision" else "request_rejected"
    audit.record(event, actor=user["email"], role=user["role"], workspace_id=workspace_id,
                 details={"comment": comment, "documentId": (document or {}).get("id", "")})
    owner = get_user_by_id(workspace["ownerId"])
    chair_email = str((state.get("meeting") or {}).get("chairEmail") or "")
    if owner:
        if decision == "approved":
            notification_store.notify(
                owner["email"], "approval_done", "Request approved — signed form available",
                "The Academic Office approved the DAC request. You can now download the signed request form.",
                workspace_id=workspace_id, actor=user["email"])
        else:
            notification_store.notify(owner["email"], "revision",
                                      "Academic Office returned your request" if decision == "revision" else "Request rejected",
                                      comment, workspace_id=workspace_id, actor=user["email"])
    if chair_email and decision != "approved":
        notification_store.notify(chair_email, "revision", "Academic Office returned the request you approved",
                                  comment, workspace_id=workspace_id, actor=user["email"])
    return jsonify({"ok": True, "workspaceId": workspace_id, "state": state, "status": decision,
                    "document": document,
                    "downloadGate": {"allowed": decision == "approved",
                                     "reason": "The signed request form is available for download." if decision == "approved"
                                     else "The signed form becomes downloadable once the Academic Office approves."}})


@app.post("/api/workspace/complete")
@roles_required("faculty")
def mark_workspace_completed():
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    workspace_id = str(payload.get("workspaceId") or "")
    workspace = get_workspace(workspace_id)
    if not workspace or workspace["ownerId"] != user["id"] or workspace["status"] != "approved":
        return jsonify({"error": "An approved meeting owned by this account is required."}), 403
    state = workspace["payload"]
    meeting = {**(state.get("meeting") or {}), "completed": True}
    state = {**state, "meeting": meeting, "meetingCompletedAt": datetime.now(COLLEGE_TZ).strftime("%d %b %Y, %H:%M")}
    save_workspace(workspace_id, user["id"], state, "approved")
    audit.record("meeting_marked_completed", actor=user["email"], role=user["role"],
                 workspace_id=workspace_id)
    # The nominated External Member is told the observation report is now due.
    for member in (meeting.get("members") or []):
        if member.get("role") == "External Member" and member.get("email"):
            notification_store.notify(member["email"], "report_required",
                                      "Observation report due",
                                      f"The {meeting.get('meetingNo')} DAC meeting of {meeting.get('department') or ''} "
                                      "is complete. Please fill the External Member observation report.",
                                      workspace_id=workspace_id, link="member", actor=user["email"],
                                      meta={"stage": "external_report"})
    return jsonify({"ok": True, "state": state})


@app.post("/api/testing/advance-clock")
@roles_required("faculty")
def testing_advance_clock():
    """Test hook: move an approved meeting's date into the past so the completion
    gate can be exercised without waiting for the real clock. Inert in production."""
    if not TEST_HOOKS:
        return jsonify({"error": "Not available."}), 404
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    workspace_id = str(payload.get("workspaceId") or "")
    workspace = get_workspace(workspace_id)
    if not workspace or workspace["ownerId"] != user["id"] or workspace["status"] != "approved":
        return jsonify({"error": "An approved meeting owned by this account is required."}), 403
    state = _fast_forward_meeting(workspace["payload"], int(payload.get("daysAgo") or 1))
    save_workspace(workspace_id, user["id"], state, "approved")
    audit.record("meeting_clock_advanced_for_test", actor=user["email"], role=user["role"],
                 workspace_id=workspace_id)
    return jsonify({"ok": True, "state": state})


@app.post("/api/upload")
@roles_required("faculty")
def upload():
    file_storage = request.files.get("file")
    if not file_storage:
        return jsonify({"error": "Choose a file to upload."}), 400
    try:
        safe_name, raw = _validate_upload(file_storage)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    file_id = uuid.uuid4().hex
    extension = Path(safe_name).suffix.lower()
    target = UPLOAD_DIR / f"{file_id}{extension}"
    target.write_bytes(raw)
    create_upload_record(file_id, get_current_user()["id"], safe_name, extension, len(raw))
    mimetype = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    return jsonify({
        "id": file_id,
        "name": safe_name,
        "size": len(raw),
        "type": mimetype,
        "extension": extension,
        "previewUrl": f"/api/file/{file_id}",
    })


@app.get("/api/file/<file_id>")
@login_required
def get_file(file_id: str):
    path = get_upload_path(file_id)
    record = get_upload_record(file_id)
    if not path or not record:
        return jsonify({"error": "File not found."}), 404
    user = get_current_user()
    if record["owner_id"] != user["id"] and user["role"] not in {"academic_office", "system_admin"}:
        # Chairperson (and nominated members) must see photos/annexures in the
        # Minutes-to-sign view even though the Member Secretary uploaded them.
        # Allow if the user chairs or is listed on a workspace containing this file.
        allowed = False
        try:
            with connect() as db:
                rows = db.execute(
                    "SELECT workspace_id, owner_id, payload_json FROM workspaces WHERE payload_json LIKE ?",
                    (f"%{file_id}%",),
                ).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except (json.JSONDecodeError, TypeError):
                    continue
                meeting = (payload.get("meeting") or {})
                if str(meeting.get("chairEmail") or "").strip().lower() == str(user.get("email") or "").strip().lower():
                    allowed = True
                    break
                if row["owner_id"] == user["id"]:
                    allowed = True
                    break
                members = meeting.get("members") or []
                if any(str(m.get("email") or "").strip().lower() == str(user.get("email") or "").strip().lower() for m in members):
                    allowed = True
                    break
                # The Chairperson who signed the minutes (stamp email) may view them too.
                chair_stamp = ((payload.get("momReview") or {}).get("chairSignature") or {})
                if str(chair_stamp.get("email") or "").strip().lower() == str(user.get("email") or "").strip().lower():
                    allowed = True
                    break
                # Chairperson by office (R1): the Dean/HoD of this school/department,
                # even if this meeting's chairEmail field was never filled.
                try:
                    with connect() as _chair_db:
                        chair_units = dac_registry.units_for_chair(_chair_db, user.get("email") or "")
                    unit_id = dac_registry.unit_id(meeting.get("school"), meeting.get("department"))
                    if any(unit.get("unitId") == unit_id for unit in chair_units):
                        allowed = True
                        break
                except Exception:
                    pass
        except Exception:
            allowed = False
        if not allowed:
            return jsonify({"error": "This file is outside your access scope. Guest annexure sharing is not enabled."}), 403
    response = send_file(path, mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream", as_attachment=False, download_name=path.name)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.post("/api/validate")
@roles_required("faculty", "academic_office")
def validate_endpoint():
    payload = request.get_json(silent=True) or {}
    return jsonify(validate_mom(payload))


@app.post("/api/outbox")
@roles_required("academic_office")
def outbox_endpoint():
    payload = request.get_json(silent=True) or {}
    meeting_id = str((payload.get("meeting") or {}).get("id") or "")
    workspace = get_workspace(meeting_id)
    if not workspace or workspace["status"] != "approved":
        return jsonify({"error": "An approved meeting workspace is required to send the invitation."}), 403
    workspace_id = meeting_id
    meeting = dict(workspace["payload"].get("meeting") or {})
    meeting["agendas"] = [{**agenda, "title": _agenda_document_title(agenda, meeting)} for agenda in (meeting.get("agendas") or [])]
    members = meeting.get("members", [])
    recipients = [str(member.get("email", "")) for member in members if member.get("email")]
    if not recipients:
        return jsonify({"error": "No approved invitees are listed."}), 400
    for member in members:
        invited = get_user_by_email(str(member.get("email") or ""), active_only=True)
        if not invited:
            return jsonify({"error": f"The approved invitee {member.get('email', '')} is no longer active."}), 409
        nominated_external = member.get("role") == "External Member"
        if nominated_external and invited.get("role") not in {"external_member", "faculty"}:
            return jsonify({"error": f"The External Member {member.get('email', '')} is no longer an eligible account."}), 409
        if not nominated_external and invited.get("role") == "external_member":
            return jsonify({"error": f"{member.get('email', '')} is provisioned as an External Member but has a different roster role."}), 409
    # The Member Secretary (the meeting organizer, i.e. the workspace owner) conveys the
    # invitation — the Chairperson is a separate person who approves, not the sender.
    owner = get_user_by_id(workspace["ownerId"]) if workspace.get("ownerId") else None
    organizer_email = str((owner or {}).get("email") or meeting.get("chairEmail") or "")
    if str(payload.get("from") or "").lower() != organizer_email.lower():
        return jsonify({"error": "Invitation sender does not match the Member Secretary who scheduled the meeting."}), 403
    subject = str(payload.get("subject") or "DAC meeting invitation")
    record = {
        "id": uuid.uuid4().hex,
        "createdAt": datetime.now(COLLEGE_TZ).isoformat(),
        "from": organizer_email,
        "recipients": recipients,
        "subject": subject,
        "meeting": meeting,
    }
    # The invitation is a real mail, sent by the Member Secretary who scheduled the
    # meeting (Pattern A: the conveyer of the step is the sender). It used to be written
    # to a log file marked "not sent to email" while the mail transport sat unused, so
    # invitees were never actually told about the meeting.
    body = _invitation_body(meeting, subject)
    queued = 0
    for address in recipients:
        result = mail_queue.enqueue(kind="invitation", to_email=address, subject=subject,
                                    body_text=body, workspace_id=workspace_id,
                                    actor=organizer_email, dedupe=False)
        if result:
            queued += 1
    sent = mail_queue.flush(limit=max(5, queued)) if queued else {}
    transport = str((mail_queue.transport_status() or {}).get("transport") or "console")
    record["status"] = ("sent by email" if transport in {"smtp", "graph"}
                        else "queued in the mail outbox (no mail transport configured)")
    record["transport"] = transport
    record["queued"] = queued
    _append_json(OUTBOX_PATH, record)
    audit.record("invitation_queued", actor=organizer_email, workspace_id=workspace_id,
                 role=get_current_user()["role"], at=record["createdAt"],
                 details={"recipients": len(recipients), "queued": queued, "transport": transport,
                          "flushed": (sent or {}).get("sent", 0)})
    return jsonify(record), 201


def _invitation_body(meeting: dict, subject: str) -> str:
    """The plain-text invitation an invitee receives."""
    agendas = "\n".join(f"  {index}. {_agenda_document_title(item, meeting)}"
                        for index, item in enumerate(meeting.get("agendas") or [], start=1))
    return (f"{subject}\n\n"
            f"{meeting.get('school') or ''} · {meeting.get('department') or ''}\n"
            f"{_meeting_description(meeting)}\n\n"
            f"Date: {_format_date_dmy(meeting.get('date'))}\n"
            f"Time: {meeting.get('startTime')} to {meeting.get('endTime')}\n"
            f"Venue: {meeting.get('venue')}\n\n"
            f"Agenda:\n{agendas}\n\n"
            "This is an automated message from the DAC Minutes Studio.")


@app.get("/api/outbox")
@roles_required("academic_office", "faculty")
def get_outbox():
    rows = _read_json(OUTBOX_PATH, [])
    user = get_current_user()
    if user["role"] == "faculty":
        rows = [row for row in rows if owner_for_workspace(str((row.get("meeting") or {}).get("id") or "")) == user["id"]]
    return jsonify(rows)


@app.post("/api/audit")
@roles_required("system_admin", "academic_office", "faculty")
def audit_endpoint():
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    audit.record(str(payload.get("event") or "workflow_event")[:100], actor=user["email"], role=user["role"],
                 workspace_id=str((payload.get("details") or {}).get("meetingId") or "")[:120],
                 details={"note": str((payload.get("details") or {}).get("note") or "")[:300]})
    return jsonify({"ok": True})


@app.get("/api/audit")
@roles_required("system_admin", "academic_office")
def get_audit():
    """The governance trail, oldest first.

    Served from SQLite rather than a JSON file: the trail is evidence, so it is no
    longer rewritten whole on every event (which could lose events under concurrent
    requests) and no longer capped at the newest 500 rows (which discarded history).
    """
    return jsonify(audit.list_events(limit=int(request.args.get("limit") or audit.DEFAULT_LIMIT),
                                     workspace_id=request.args.get("workspaceId") or ""))


@app.get("/README")
def readme():
    readme_path = BASE_DIR / "README.md"
    return send_file(readme_path, mimetype="text/markdown")


# ---------------------------------------------------------------------------
# Minutes of Meeting review chain
#   Member Secretary submits  ->  Chairperson approves  ->  Academic Office
# The Academic Office cannot approve while the External Member's observation
# report is still awaited, and the final documents unlock only after approval.
# ---------------------------------------------------------------------------

@app.post("/api/workspace/mom/submit")
@roles_required("faculty")
def submit_minutes_for_review():
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    workspace_id = str(payload.get("workspaceId") or "")
    workspace = get_workspace(workspace_id)
    if not workspace or workspace["ownerId"] != user["id"]:
        return jsonify({"error": "Only the Member Secretary who scheduled this meeting can submit the minutes."}), 403
    state = _stamp_committee(_migrate_resolution_keys(workspace["payload"]))
    if not _minutes_unlocked(state):
        return jsonify({"error": "The minutes can be submitted after the scheduled end time has passed and the "
                                 "meeting is marked completed."}), 409
    review = _mom_review_payload(state)
    if review["status"] in {"pending_chairperson", "pending_office"}:
        return jsonify({"error": "These minutes are already with "
                                 + ("the Chairperson." if review["status"] == "pending_chairperson"
                                    else "the Academic Office.")}), 409
    if review["status"] == "approved":
        return jsonify({"error": "These minutes are already approved. Use a revision request to change them."}), 409
    error = _validate_minutes_content(state)
    if error:
        return jsonify({"error": error}), 400
    # The three-way relevance gate: Agenda → Discussion → Resolution must be aligned.
    # This recomputes the verification fresh on the server (not trusting the client's
    # stored aiReport) and blocks submission until every agenda reads as aligned.
    ai_error = _validate_ai_alignment(state)
    if ai_error:
        return jsonify({"error": ai_error}), 400
    meeting = state.get("meeting") or {}
    chair_email = str(meeting.get("chairEmail") or "").strip().lower()
    requires_chair = bool(chair_email) and chair_email != str(user.get("email") or "").strip().lower()
    # The Chairperson stays in the loop on every version of the minutes as well: a first
    # submission and a resubmission after an Academic Office correction both reach the
    # Chairperson for review and signature before the Academic Office sees them again.
    previous_review = state.get("momReview") or {}
    resubmission = review["status"] == "office_revision"
    requires_chair = requires_chair or (resubmission and bool(chair_email)
                                        and chair_email != str(user.get("email") or "").strip().lower())
    next_status = "pending_chairperson" if requires_chair else "pending_office"
    stamp = datetime.now(COLLEGE_TZ).strftime("%d %b %Y, %H:%M")
    history = review["history"] + [{"at": stamp, "actor": user["email"], "role": "Member Secretary",
                                    "action": "minutes_resubmitted" if resubmission else "minutes_submitted",
                                    "comment": ("Corrected after the Academic Office revision; sent back to the "
                                                "Chairperson for review and signature." if resubmission else "")}]
    chair_history = list(previous_review.get("chairSignatureHistory") or [])
    if previous_review.get("chairSignature"):
        chair_history.append({"signature": previous_review["chairSignature"],
                              "decidedAt": previous_review.get("chairDecisionAt", ""),
                              "comment": previous_review.get("chairComment", ""),
                              "forVersion": previous_review.get("version")})
    secretary_signature = signature_store.stamp(user)
    state = {**state, "momReview": {"status": next_status, "requiresChair": requires_chair,
                                    "submittedAt": stamp, "version": review["version"] + 1,
                                    "chairDecisionAt": "",
                                    "chairComment": "",
                                    "chairSignature": None,
                                    "chairSignatureHistory": chair_history,
                                    "officeDecisionAt": "", "officeComment": "",
                                    "secretarySignature": secretary_signature,
                                    "chairReviewReused": False,
                                    "history": history}}
    save_workspace(workspace_id, user["id"], state, workspace["status"])
    audit.record("minutes_submitted", actor=user["email"], role=user["role"],
                 workspace_id=workspace_id, details={"next": next_status})
    if requires_chair:
        notification_store.notify(chair_email, "approval_request",
                                  f"Minutes awaiting your approval — DAC {meeting.get('meetingNo')} {meeting.get('department') or ''}".strip(),
                                  f"{user.get('name') or user['email']} submitted the filled minutes of the "
                                  f"{meeting.get('meetingNo')} DAC meeting held on {meeting.get('date')}.",
                                  workspace_id=workspace_id, link="mom-review", actor=user["email"],
                                  meta={"meetingNo": meeting.get("meetingNo"), "stage": "minutes"})
    else:
        _notify_office(workspace_id, meeting, "Minutes awaiting your approval",
                       f"{user.get('name') or user['email']} submitted the filled minutes.")
    return jsonify({"ok": True, "workspaceId": workspace_id, "state": state,
                    "momReview": _mom_review_payload(state),
                    "downloadGate": _download_gate(state, workspace_id)})


@app.get("/api/workspaces/minutes-inbox")
@roles_required("faculty", "academic_office")
def minutes_inbox():
    """The completed forms waiting for a signature.

    A Chairperson sees the minutes of the meetings they chair that await their
    approval; the Academic Office sees the minutes the Chairperson has approved. The
    office only reaches this list after the Chairperson has signed, which is the rule
    the workflow already enforces on the decision itself.
    """
    user = get_current_user()
    rows = []
    with connect() as db:
        candidates = db.execute("""SELECT workspace_id, status, payload_json, updated_at
                                   FROM workspaces ORDER BY updated_at DESC""").fetchall()
    for row in candidates:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        review = payload.get("momReview") or {}
        stage = str(review.get("status") or "draft")
        meeting = payload.get("meeting") or {}
        if stage not in {"pending_chairperson", "pending_office"}:
            continue
        if user["role"] == "faculty":
            if stage != "pending_chairperson":
                continue
            if str(meeting.get("chairEmail") or "").strip().lower() != str(user["email"]).strip().lower():
                continue
        else:
            if stage != "pending_office":
                continue
        rows.append({
            "workspaceId": row["workspace_id"],
            "status": row["status"],
            "committee": _committee_of(payload),
            "meetingNo": meeting.get("meetingNo"),
            "meetingLabel": committee_registry.meeting_label(_committee_of(payload), meeting.get("meetingNo")),
            "school": meeting.get("school"), "department": meeting.get("department"),
            "date": meeting.get("date"), "chairName": meeting.get("chairName"),
            "chairEmail": meeting.get("chairEmail"),
            "secretaryName": (payload.get("secretarySignature") or {}).get("name") or "",
            "momStatus": stage,
            "momStatusLabel": MOM_REVIEW_LABELS.get(stage, stage),
            "submittedAt": review.get("submittedAt") or "",
            "stage": "minutes",
        })
    # De-duplicate: the same workspace can appear through both queries.
    unique = {row["workspaceId"]: row for row in rows if row.get("stage") == "minutes"}
    return jsonify({"workspaces": sorted(unique.values(), key=lambda item: item.get("updatedAt") or "",
                                         reverse=True)})


@app.post("/api/workspace/mom/chair-decision")
@roles_required("faculty")
def chair_decide_minutes():
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    workspace_id = str(payload.get("workspaceId") or "")
    decision = str(payload.get("decision") or "").strip()
    comment = str(payload.get("comment") or "").strip()
    workspace = get_workspace(workspace_id)
    if not workspace:
        return jsonify({"error": "Meeting not found."}), 404
    state = _migrate_resolution_keys(workspace["payload"])
    meeting = state.get("meeting") or {}
    if str(meeting.get("chairEmail") or "").strip().lower() != str(user.get("email") or "").strip().lower():
        return jsonify({"error": "Only the Chairperson of this meeting can act on it."}), 403
    if workspace["ownerId"] == user["id"]:
        return jsonify({"error": "The Chairperson must be a different person from the Member Secretary."}), 403
    review = _mom_review_payload(state)
    if review["status"] != "pending_chairperson":
        return jsonify({"error": "These minutes are not awaiting the Chairperson."}), 409
    if decision not in {"approved", "revision"}:
        return jsonify({"error": "Choose approve or return for revision."}), 400
    if decision == "revision" and not comment:
        return jsonify({"error": "Add a note so the Member Secretary knows what to correct."}), 400
    if not signature_store.has_signature(user):
        return jsonify({"error": "Record your digital signature before approving the minutes — it is "
                                 "printed on the approved minutes.", "signatureRequired": True}), 428
    stamp = datetime.now(COLLEGE_TZ).strftime("%d %b %Y, %H:%M")
    history = review["history"] + [{"at": stamp, "actor": user["email"], "role": "Chairperson",
                                    "action": "chair_" + decision, "comment": comment}]
    next_status = "pending_office" if decision == "approved" else "chair_revision"
    chair_signature = signature_store.stamp(user)
    state = {**state, "momReview": {**state.get("momReview", {}), "status": next_status,
                                    "chairDecisionAt": stamp, "chairComment": comment, "history": history,
                                    "chairSignature": chair_signature if decision == "approved" else None}}
    save_workspace(workspace_id, workspace["ownerId"], state, workspace["status"])
    audit.record("chair_minutes_" + decision, actor=user["email"], role=user["role"],
                 workspace_id=workspace_id, details={"comment": comment})
    owner = get_user_by_id(workspace["ownerId"])
    if owner:
        notification_store.notify(owner["email"], "approval_done" if decision == "approved" else "revision",
                                  ("Chairperson approved the minutes" if decision == "approved"
                                   else "Chairperson returned the minutes"),
                                  comment or f"DAC {meeting.get('meetingNo')} minutes.",
                                  workspace_id=workspace_id, link="mom", actor=user["email"],
                                  meta={"stage": "minutes", "decision": decision})
    if decision == "approved":
        _notify_office(workspace_id, meeting, "Minutes awaiting your approval",
                       f"Chairperson {user.get('name') or user['email']} approved the minutes of DAC "
                       f"{meeting.get('meetingNo')}.")
    return jsonify({"ok": True, "state": state, "momReview": _mom_review_payload(state),
                    "downloadGate": _download_gate(state, workspace_id)})


@app.post("/api/workspace/mom/office-decision")
@roles_required("academic_office")
def office_decide_minutes():
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    workspace_id = str(payload.get("workspaceId") or "")
    decision = str(payload.get("decision") or "").strip()
    comment = str(payload.get("comment") or "").strip()
    workspace = get_workspace(workspace_id)
    if not workspace:
        return jsonify({"error": "Meeting not found."}), 404
    state = _migrate_resolution_keys(workspace["payload"])
    meeting = state.get("meeting") or {}
    review = _mom_review_payload(state)
    if review["status"] not in {"pending_office", "office_revision", "approved"}:
        return jsonify({"error": "The minutes have not reached the Academic Office yet."}), 409
    if decision not in {"approved", "revision"}:
        return jsonify({"error": "Choose approve or return for revision."}), 400
    if decision == "revision" and not comment:
        return jsonify({"error": "Add the clarification or revision required."}), 400
    if decision == "approved":
        if review["status"] != "pending_office":
            return jsonify({"error": "These minutes are not awaiting approval."}), 409
        if _external_report_required(state) and not external_report.submitted_report(workspace_id):
            gate = external_report.gate_state(workspace_id)
            return jsonify({"error": "The minutes cannot be approved until the External Member has filled and "
                                     "submitted the observation report.", "externalReport": gate}), 409
        if not (state.get("momReview") or {}).get("chairSignature"):
            return jsonify({"error": "The Chairperson has not signed these minutes yet, so they cannot be "
                                     "approved.", "signatureRequired": False}), 409
        if not signature_store.has_signature(user):
            return jsonify({"error": "Record your digital signature before approving the minutes — it is "
                                     "printed on the approved minutes.", "signatureRequired": True}), 428
        stamp = datetime.now(COLLEGE_TZ).strftime("%d %b %Y, %H:%M")
        history = review["history"] + [{"at": stamp, "actor": user["email"], "role": "Academic Office",
                                        "action": "office_approved", "comment": comment}]
        approved_state = {**state, "momReview": {**state.get("momReview", {}), "status": "approved",
                                                 "officeDecisionAt": stamp, "officeComment": comment,
                                                 "officeSignature": signature_store.stamp(user),
                                                 "history": history}}
        archived = None
        try:
            pdf_bytes = build_final_pdf(approved_state)
            archived = document_vault.archive_approved_mom(approved_state, pdf_bytes, user["email"],
                                                           version=max(1, review["version"]))
        except Exception:
            app.logger.exception("Could not archive the approved minutes")
        save_workspace(workspace_id, workspace["ownerId"], approved_state, workspace["status"])
        audit.record("minutes_approved", actor=user["email"], role=user["role"],
                     workspace_id=workspace_id, details={"document": (archived or {}).get("id", "")})
        owner = get_user_by_id(workspace["ownerId"])
        if owner:
            notification_store.notify(owner["email"], "approval_done", "Minutes approved — download available",
                                      f"The Academic Office approved the minutes of DAC {meeting.get('meetingNo')}.",
                                      workspace_id=workspace_id, link="mom", actor=user["email"],
                                      meta={"stage": "minutes", "documentId": (archived or {}).get("id", "")})
        chair_email = str(meeting.get("chairEmail") or "").strip().lower()
        if chair_email:
            notification_store.notify(chair_email, "approval_done", "Minutes approved by the Academic Office",
                                      f"DAC {meeting.get('meetingNo')} minutes are approved.",
                                      workspace_id=workspace_id, link="mom-review", actor=user["email"],
                                      meta={"stage": "minutes"})
        return jsonify({"ok": True, "state": approved_state,
                        "momReview": _mom_review_payload(approved_state),
                        "document": archived,
                        "downloadGate": _download_gate(approved_state, workspace_id)})
    stamp = datetime.now(COLLEGE_TZ).strftime("%d %b %Y, %H:%M")
    history = review["history"] + [{"at": stamp, "actor": user["email"], "role": "Academic Office",
                                    "action": "office_revision", "comment": comment}]
    state = {**state, "momReview": {**state.get("momReview", {}), "status": "office_revision",
                                    "officeComment": comment, "history": history}}
    save_workspace(workspace_id, workspace["ownerId"], state, workspace["status"])
    audit.record("minutes_returned", actor=user["email"], role=user["role"],
                 workspace_id=workspace_id, details={"comment": comment})
    owner = get_user_by_id(workspace["ownerId"])
    if owner:
        notification_store.notify(owner["email"], "revision", "Minutes returned for revision", comment,
                                  workspace_id=workspace_id, link="mom", actor=user["email"],
                                  meta={"stage": "minutes"})
    return jsonify({"ok": True, "state": state, "momReview": _mom_review_payload(state),
                    "downloadGate": _download_gate(state, workspace_id)})


# ---------------------------------------------------------------------------
# External Member observation report
# ---------------------------------------------------------------------------

def _notify_office(workspace_id: str, meeting: dict, title: str, body: str) -> None:
    for office in list_users():
        if office.get("active") and office.get("role") == "academic_office":
            notification_store.notify(office["email"], "approval_request", title, body,
                                      workspace_id=workspace_id, link="review",
                                      meta={"meetingNo": meeting.get("meetingNo")})


def _nominated_member(state: dict, user: dict) -> dict | None:
    for member in (state.get("meeting") or {}).get("members") or []:
        if member.get("role") == "External Member" and str(member.get("email") or "").strip().lower() == str(user.get("email") or "").strip().lower():
            account = get_user_by_email(member["email"], active_only=True) or {}
            return {**member, "school": account.get("school") or "", "department": account.get("department") or ""}
    return None


@app.get("/api/external-report/inbox")
@login_required
def external_report_inbox():
    """Meetings where the signed-in person is the nominated External Member."""
    user = get_current_user()
    is_office = user["role"] in {"academic_office", "system_admin"}
    rows = []
    # Office preview: show all workspaces with External Member, not just approved — so template is visible even in draft
    source = _all_workspaces_with_external() if is_office else _approved_workspaces()
    for workspace in source:
        state = workspace["payload"]
        member = _nominated_member(state, user)
        if not member and not is_office:
            continue
        if is_office and not any(row.get("role") == "External Member"
                                 for row in (state.get("meeting") or {}).get("members") or []):
            continue
        meeting = state.get("meeting") or {}
        report = external_report.get_report(workspace["workspaceId"])
        rows.append({"workspaceId": workspace["workspaceId"], "meetingNo": meeting.get("meetingNo"),
                     "school": meeting.get("school"), "department": meeting.get("department"),
                     "date": meeting.get("date"), "startTime": meeting.get("startTime"),
                     "venue": meeting.get("venue"), "completed": bool(meeting.get("completed")),
                     "status": workspace["status"],
                     "reportStatus": (report or {}).get("status") or "not_started",
                     "reportId": (report or {}).get("id", ""),
                     "comment": (report or {}).get("comment", "")})
    return jsonify({"meetings": rows, "member": {"name": user.get("name"), "email": user.get("email"),
                                                 "designation": user.get("designation"),
                                                 "school": user.get("school"), "department": user.get("department")}})


def _approved_workspaces() -> list[dict]:
    from auth_store import connect as _connect
    with _connect() as db:
        rows = db.execute("SELECT workspace_id FROM workspaces WHERE status='approved' ORDER BY updated_at DESC").fetchall()
    return [workspace for row in rows if (workspace := get_workspace(row["workspace_id"]))]

def _all_workspaces_with_external() -> list[dict]:
    """All workspaces (any status) that have an External Member — for Office preview"""
    from auth_store import connect as _connect
    with _connect() as db:
        rows = db.execute("SELECT workspace_id FROM workspaces ORDER BY updated_at DESC").fetchall()
    result = []
    for row in rows:
        ws = get_workspace(row["workspace_id"])
        if not ws: continue
        members = (ws["payload"].get("meeting") or {}).get("members") or []
        if any(m.get("role") == "External Member" for m in members):
            result.append(ws)
    return result


@app.get("/api/external-report/<workspace_id>")
@login_required
def get_external_report(workspace_id: str):
    user = get_current_user()
    workspace = get_workspace(workspace_id)
    if not workspace:
        return jsonify({"error": "This meeting is not available."}), 404
    # Allow Academic Office to preview template even before approval — otherwise form is never visible
    if workspace["status"] != "approved" and user["role"] not in {"academic_office", "system_admin"}:
        # External Member can only see approved meetings; for others check nomination
        temp_state = _migrate_resolution_keys(workspace["payload"])
        if not _nominated_member(temp_state, user):
            return jsonify({"error": "This meeting is not available."}), 404
    state = _migrate_resolution_keys(workspace["payload"])
    member = _nominated_member(state, user)
    is_office = user["role"] in {"academic_office", "system_admin"}
    if not member and not is_office:
        return jsonify({"error": "Only the nominated External Member or the Academic Office can open this report."}), 403
    existing = external_report.get_report(workspace_id)
    payload = external_report.build_draft(state, member or (existing or {}).get("payload", {}).get("member", {}), existing)
    meeting = state.get("meeting") or {}
    can_fill = bool(member) and bool(meeting.get("completed")) and (existing is None or existing["status"] in {"draft", "returned"})
    return jsonify({"workspaceId": workspace_id, "report": existing, "draft": payload,
                    "gate": external_report.gate_state(workspace_id),
                    "canFill": can_fill,
                    "canReview": user["role"] == "academic_office" and (existing or {}).get("status") == "submitted",
                    "meetingCompleted": bool(meeting.get("completed")),
                    "responseChoices": list(external_report.RESPONSE_CHOICES)})


@app.post("/api/external-report/<workspace_id>")
@login_required
def save_external_report(workspace_id: str):
    user = get_current_user()
    workspace = get_workspace(workspace_id)
    if not workspace or workspace["status"] != "approved":
        return jsonify({"error": "This meeting is not available."}), 404
    state = _migrate_resolution_keys(workspace["payload"])
    member = _nominated_member(state, user)
    if not member:
        return jsonify({"error": "Only the nominated External Member can fill this report."}), 403
    meeting = state.get("meeting") or {}
    if not meeting.get("completed"):
        return jsonify({"error": "The report opens once the meeting has been conducted and marked completed."}), 409
    body = request.get_json(silent=True) or {}
    payload = body.get("payload") or {}
    submit = bool(body.get("submit"))
    # The agenda rows always come from this meeting; a client cannot inject others.
    fresh = external_report.build_draft(state, member, payload)
    try:
        report = external_report.save_report(workspace_id, member, fresh, submit=submit)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if submit:
        audit.record("external_report_submitted", actor=user["email"], role=user["role"],
                     workspace_id=workspace_id)
        _notify_office(workspace_id, meeting, "External Member report submitted",
                       f"{user.get('name') or user['email']} submitted the observation report for DAC "
                       f"{meeting.get('meetingNo')}. The minutes can now be approved.")
        owner = get_user_by_id(workspace["ownerId"])
        if owner:
            notification_store.notify(owner["email"], "report_submitted", "External Member report submitted",
                                      "The Academic Office can now approve the minutes.",
                                      workspace_id=workspace_id, link="mom", actor=user["email"],
                                      meta={"stage": "external_report"})
    return jsonify({"ok": True, "report": report, "gate": external_report.gate_state(workspace_id)})


@app.get("/api/external-report/<report_id>/pdf")
@login_required
def external_report_pdf(report_id: str):
    user = get_current_user()
    report = external_report.get_report_by_id(report_id)
    if not report:
        return jsonify({"error": "Report not found."}), 404
    workspace = get_workspace(report["workspaceId"])
    state = (workspace or {}).get("payload") or {}
    member = _nominated_member(_migrate_resolution_keys(state), user)
    if not member and user["role"] not in {"academic_office", "system_admin"}:
        return jsonify({"error": "This report is outside your access scope."}), 403
    pdf_bytes = external_report.render_report_pdf(report, user)
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
                     download_name=f"DAC-external-observation-{report_id[:8]}.pdf")


@app.post("/api/external-report/<report_id>/decision")
@roles_required("academic_office")
def decide_external_report(report_id: str):
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    decision = str(body.get("decision") or "").strip()
    comment = str(body.get("comment") or "").strip()
    report = external_report.get_report_by_id(report_id)
    # Validate the transition BEFORE anything is rendered or written to the vault: a
    # refused decision must leave no document behind.
    transition_error = external_report.decision_error(report, decision, comment)
    if transition_error:
        return jsonify({"error": transition_error}), (404 if not report else 400)
    document = None
    if decision == "approved":
        try:
            pdf_bytes = external_report.render_report_pdf(report, user)
        except Exception as exc:
            return jsonify({"error": f"Could not render the report: {exc}"}), 500
        workspace = get_workspace(report["workspaceId"])
        meeting = ((workspace or {}).get("payload") or {}).get("meeting") or {}
        document = document_vault.store_document(
            school=str(meeting.get("school") or "Unassigned"),
            department=str(meeting.get("department") or ""),
            academic_year=str(meeting.get("academicYear") or ""),
            semester=str(meeting.get("semester") or ""),
            workspace_id=report["workspaceId"],
            meeting_ref=str(meeting.get("referenceNo") or ""),
            doc_type="external_report",
            committee=str(((workspace or {}).get("payload") or {}).get("committee")
                          or meeting.get("committee") or "DAC"),
            title=(f"External Member observation report — "
                   f"{str(((workspace or {}).get('payload') or {}).get('committee') or meeting.get('committee') or 'DAC').upper()} "
                   f"{meeting.get('meetingNo') or ''} {meeting.get('department') or ''}").strip(),
            pdf_bytes=pdf_bytes, created_by=user["email"], version=1,
            meta={"member": report["memberEmail"]})
    try:
        updated = external_report.decide_report(report_id, decision, comment, user,
                                                document_id=(document or {}).get("id", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    audit.record("external_report_" + decision, actor=user["email"], role=user["role"],
                 workspace_id=report["workspaceId"], details={"comment": comment})
    notification_store.notify(report["memberEmail"],
                              "approval_done" if decision == "approved" else "report_returned",
                              "Observation report approved" if decision == "approved" else "Observation report returned",
                              comment or "Reviewed by the Academic Office.",
                              workspace_id=report["workspaceId"], link="member", actor=user["email"],
                              meta={"stage": "external_report"})
    return jsonify({"ok": True, "report": updated, "document": document})


# ---------------------------------------------------------------------------
# Central document repository (grouped by school)
# ---------------------------------------------------------------------------

@app.get("/api/documents")
@roles_required("academic_office", "system_admin")
def documents_index():
    school = str(request.args.get("school") or "").strip() or None
    department = str(request.args.get("department") or "").strip() or None
    committee = str(request.args.get("committee") or "").strip() or None
    semester = str(request.args.get("semester") or "").strip() or None
    doc_type = str(request.args.get("docType") or "").strip() or None
    academic_year = str(request.args.get("academicYear") or "").strip() or None
    documents = document_vault.list_documents(school=school, department=department,
                                              committee=committee, semester=semester,
                                              doc_type=doc_type, academic_year=academic_year)
    return jsonify({"summary": document_vault.summary_by_school(), "documents": documents,
                    "total": len(documents),
                    "filters": {"school": school or "", "department": department or "",
                                "committee": committee or "", "semester": semester or "",
                                "docType": doc_type or "", "academicYear": academic_year or ""},
                    "committees": [{"code": code, "label": committee_registry.name(code)}
                                   for code in committee_registry.codes()]})


@app.get("/api/documents/<document_id>/download")
@login_required
def download_document(document_id: str):
    user = get_current_user()
    document = document_vault.get_document(document_id)
    if not document:
        return jsonify({"error": "Document not found."}), 404
    if user["role"] not in {"academic_office", "system_admin"}:
        if user["role"] != "faculty" or _clean_school(user.get("school") or "") != _clean_school(document["school"]):
            return jsonify({"error": "This document is outside your access scope."}), 403
    path = document_vault.document_path(document)
    if not path:
        return jsonify({"error": "The stored file is missing from the repository."}), 410
    return send_file(path, mimetype=document["mime"], as_attachment=True,
                     download_name=document["filename"])


# ---------------------------------------------------------------------------
# In-app notifications
# ---------------------------------------------------------------------------

@app.get("/api/archive/committees")
@roles_required("academic_office", "system_admin")
def committee_archive_list():
    """Every DAC and BOS meeting on record, filterable by committee, school and department."""
    user = get_current_user()
    school = request.args.get("school") or ""
    # The Academic Office may look across the college; the System Administrator does not
    # act for a school, so neither is silently narrowed. Faculty never reach this route.
    filters = {
        "committee": request.args.get("committee") or "",
        "school": school,
        "department": request.args.get("department") or "",
        "academic_year": request.args.get("academicYear") or "",
        "semester": request.args.get("semester") or "",
        "doc_type": request.args.get("docType") or "",
        "status": request.args.get("status") or "",
        "search": request.args.get("q") or "",
        "date_from": request.args.get("dateFrom") or "",
        "date_to": request.args.get("dateTo") or "",
    }
    result = committee_archive.list_meetings(**filters)
    audit.record("committee_archive_viewed", actor=user["email"], role=user["role"],
                 details={"filters": ", ".join(f"{k}={v}" for k, v in filters.items() if v),
                          "returned": result["total"]})
    return jsonify(result)


@app.get("/api/notifications")
@login_required
def list_notifications():
    user = get_current_user()
    unread_only = str(request.args.get("unread") or "").lower() in {"1", "true", "yes"}
    # Reminders for the Action Taken Report are created when the account looks, so they
    # appear without a scheduler running on the server.
    try:
        atr_store.sweep_for(user)
    except Exception:                                  # a reminder must never break the list
        app.logger.exception("Could not sweep Action Taken Report reminders")
    return jsonify({"items": notification_store.list_for(user["email"], unread_only=unread_only),
                    "unread": notification_store.unread_count(user["email"])})


@app.post("/api/notifications/read")
@login_required
def read_notifications():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    if body.get("all"):
        return jsonify({"ok": True, "updated": notification_store.mark_all_read(user["email"])})
    notification_id = str(body.get("id") or "")
    if not notification_id:
        return jsonify({"error": "Missing notification id."}), 400
    return jsonify({"ok": True, "updated": 1 if notification_store.mark_read(notification_id, user["email"]) else 0})


@app.post("/api/export")
@roles_required("faculty")
def export_pdf():
    user = get_current_user()
    request_payload = request.get_json(silent=True) or {}
    meeting_id = str((request_payload.get("meeting") or {}).get("id") or "")
    owner_id = owner_for_workspace(meeting_id)
    if not owner_id or owner_id != user["id"]:
        return jsonify({"error": "This meeting is outside your access scope."}), 403
    workspace = get_workspace(meeting_id)
    payload = workspace["payload"] if workspace else {}
    gate = _download_gate(payload, meeting_id)
    if not gate["allowed"]:
        return jsonify({"error": gate["reason"], "downloadGate": gate}), 409
    try:
        pdf = build_final_pdf(payload)
    except Exception as exc:
        app.logger.exception("Could not generate the final MoM PDF")
        return jsonify({"error": f"PDF generation failed: {exc}"}), 500
    meeting = payload.get("meeting") or {}
    code = _committee_of(payload)
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-",
                  f"{code}-{meeting.get('meetingNo', 'Meeting')}-{meeting.get('department', 'MoM')}").strip("-") or f"{code}-MoM"
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True, download_name=f"{slug}.pdf")


@app.post("/api/export-docx")
@roles_required("faculty")
def export_docx():
    """Export the same final MoM as an editable Word document (Cambria house style)."""
    user = get_current_user()
    request_payload = request.get_json(silent=True) or {}
    meeting_id = str((request_payload.get("meeting") or {}).get("id") or "")
    owner_id = owner_for_workspace(meeting_id)
    if not owner_id or owner_id != user["id"]:
        return jsonify({"error": "This meeting is outside your access scope."}), 403
    workspace = get_workspace(meeting_id)
    payload = _migrate_resolution_keys(workspace["payload"] if workspace else {})
    gate = _download_gate(payload, meeting_id)
    if not gate["allowed"]:
        return jsonify({"error": gate["reason"], "downloadGate": gate}), 409
    payload = _attach_signature_images(payload)
    try:
        document = build_mom_docx(payload, photo_loader=read_uploaded_bytes)
    except Exception as exc:
        app.logger.exception("Could not generate the final MoM Word document")
        return jsonify({"error": f"Word export failed: {exc}"}), 500
    meeting = payload.get("meeting") or {}
    code = _committee_of(payload)
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-",
                  f"{code}-{meeting.get('meetingNo', 'Meeting')}-{meeting.get('department', 'MoM')}").strip("-") or f"{code}-MoM"
    return send_file(
        io.BytesIO(document),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"{slug}.docx",
    )


# ------------------------------------------------------------------ interface
# The compiled single-page app is served by this process, so the whole product
# runs on one origin with one command. `npm run dev` (Vite, port 3000) remains
# available for frontend work and proxies /api here.
def _dist_file(relative: str) -> Path | None:
    if not DIST_DIR.is_dir():
        return None
    try:
        candidate = (DIST_DIR / relative).resolve()
    except (OSError, ValueError):
        return None
    if candidate != DIST_DIR.resolve() and DIST_DIR.resolve() not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def _index_or_error():
    index = _dist_file("index.html")
    if index is None:
        return jsonify({"error": "The interface has not been built yet. Run: cd frontend && npm run build",
                        "health": "/api/health"}), 503
    return send_file(index, mimetype="text/html", max_age=0)


@app.get("/")
def interface_index():
    return _index_or_error()


@app.get("/<path:asset>")
def interface_asset(asset: str):
    if asset.startswith("api/"):
        return jsonify({"error": "Unknown API endpoint."}), 404
    found = _dist_file(asset)
    if found is not None:
        cache = 3600 if asset.startswith("assets/") else 0
        return send_file(found, max_age=cache)
    if asset.startswith("assets/"):
        return jsonify({"error": "Unknown file."}), 404
    return _index_or_error()


@app.route("/api/<path:_unmatched>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def unknown_api(_unmatched: str):
    """Anything under /api/ that no route claimed answers JSON, never the HTML shell."""
    return jsonify({"error": "Unknown API endpoint."}), 404


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "The upload is too large."}), 413


def _serve() -> None:
    """Start the development/preview server.

    Bind address and port are configuration so the same code runs on a laptop, behind
    the sandbox preview proxy and on a departmental server. For a production
    deployment put this application behind a real WSGI server (for example
    ``waitress-serve --call app:create_app``) and let that server terminate TLS; the
    Flask server below is not designed to face the internet directly.
    """
    host = os.environ.get("HOST", "0.0.0.0")            # nosec B104 - bind address is deployment config
    port = int(os.environ.get("PORT", "8000"))
    app.run(host=host, port=port, debug=False, threaded=True)


# ---------------------------------------------------------------------------
# Action Taken Report (ATR)
#
# The meeting dates that drive the ATR window are issued by the Academic Office
# before the academic year begins, so the office owns the calendar and the Member
# Secretary owns the report. The rules live in ``atr.py``; these routes only carry
# the requests and the permissions.
# ---------------------------------------------------------------------------

def _atr_workspace(workspace_id: str) -> tuple[dict | None, dict | None, tuple | None]:
    """(workspace, report, error_response) for one ATR request."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        return None, None, (jsonify({"error": "Unknown meeting."}), 404)
    report = atr_store.ensure_report(workspace)
    if not report:
        return workspace, None, (jsonify({
            "error": "The Action Taken Report belongs to minutes the Academic Office has approved. "
                     "This meeting's minutes are not approved yet."}), 409)
    return workspace, report, None


def _atr_owner_or_chair(report: dict, user: dict) -> bool:
    email = str(user.get("email") or "").strip().lower()
    return email in {str(report.get("ownerEmail") or "").lower(), str(report.get("chairEmail") or "").lower()}


@app.get("/api/atr")
@login_required
def list_action_taken_reports():
    """Every report this account may see, with the window that governs it."""
    user = get_current_user()
    if user["role"] not in {"faculty", "academic_office", "system_admin"}:
        return jsonify({"error": "The Action Taken Report is filled by the Member Secretary and signed "
                                 "by the Chairperson."}), 403
    reports = atr_store.list_reports(user)
    return jsonify({"reports": reports,
                    "rules": {"dueDaysBeforeMeeting": atr_store.DUE_DAYS_BEFORE_MEETING,
                              "reminderDaysBeforeMeeting": atr_store.REMINDER_DAYS_BEFORE_MEETING},
                    "statusChoices": list(atr_store.STATUS_CHOICES)})


@app.get("/api/atr/<workspace_id>")
@login_required
def get_action_taken_report(workspace_id: str):
    user = get_current_user()
    if user["role"] not in {"faculty", "academic_office", "system_admin"}:
        return jsonify({"error": "Not available to this account."}), 403
    workspace, report, error = _atr_workspace(workspace_id)
    if error:
        return error
    if user["role"] not in {"academic_office", "system_admin"} and not _atr_owner_or_chair(report, user):
        return jsonify({"error": "This Action Taken Report is not addressed to your account."}), 403
    state = workspace["payload"]
    return jsonify({"report": report, "window": atr_store.window(report),
                    "meeting": state.get("meeting") or {},
                    "history": atr_store.history_for(report),
                    "statusChoices": list(atr_store.STATUS_CHOICES),
                    "documentId": report.get("documentId") or ""})


@app.post("/api/atr/<workspace_id>/save")
@roles_required("faculty")
def save_action_taken_report(workspace_id: str):
    """Store what the Member Secretary has typed. No signature, no state change."""
    user = get_current_user()
    workspace, report, error = _atr_workspace(workspace_id)
    if error:
        return error
    if str(report.get("ownerEmail") or "") != str(user["email"] or "").lower():
        return jsonify({"error": "Only the Member Secretary of this meeting fills its Action Taken Report."}), 403
    if report["status"] in {"submitted", "approved"}:
        return jsonify({"error": "The report is already with the Chairperson and can no longer be edited.",
                        "status": report["status"]}), 409
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or []
    problem = atr_store.validate_rows(rows)
    if problem:
        return jsonify({"error": problem}), 400
    updated = atr_store.save_rows(workspace_id, rows)
    audit.record("atr_saved", actor=user["email"], role=user["role"], workspace_id=workspace_id,
                 details={"rows": len(updated.get("rows") or [])})
    return jsonify({"ok": True, "report": updated, "window": atr_store.window(updated)})


@app.post("/api/atr/<workspace_id>/submit")
@roles_required("faculty")
def submit_action_taken_report(workspace_id: str):
    """The Member Secretary signs the report; it then goes to the Chairperson."""
    user = get_current_user()
    workspace, report, error = _atr_workspace(workspace_id)
    if error:
        return error
    if str(report.get("ownerEmail") or "") != str(user["email"] or "").lower():
        return jsonify({"error": "Only the Member Secretary of this meeting submits its Action Taken Report."}), 403
    if report["status"] == "approved":
        return jsonify({"error": "This report is already approved and signed."}), 409
    if report["status"] == "submitted":
        return jsonify({"error": "The report is already with the Chairperson for signature."}), 409
    # The form is activated only after the latest target date has passed.
    if not atr_store.can_fill(report):
        state = atr_store.availability(report)
        win = atr_store.window(report)
        if state == "waiting":
            return jsonify({"error": f"This report opens on {win['activationDate']}, once the latest "
                                     "action-item target date has passed.",
                            "window": win}), 409
        return jsonify({"error": "This report is not open for filling.", "window": win}), 409
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or (report.get("rows") or [])
    problem = atr_store.validate_rows(rows, require_complete=True)
    if problem:
        return jsonify({"error": problem}), 400
    if not signature_store.has_signature(user):
        return jsonify({"error": "Record your digital signature before submitting the report — it is printed "
                                 "on the form.", "signatureRequired": True}), 428
    saved = atr_store.save_rows(workspace_id, rows)
    submitted = atr_store.submit_report(workspace_id, signature_store.stamp(user))
    audit.record("atr_submitted", actor=user["email"], role=user["role"], workspace_id=workspace_id,
                 details={"rows": len(saved.get("rows") or [])})
    chair_email = str(submitted.get("chairEmail") or "").strip().lower()
    if chair_email:
        meeting = (workspace["payload"].get("meeting") or {})
        notification_store.notify(
            chair_email, "approval_request",
            "Action Taken Report awaiting your signature",
            f"{user.get('name') or 'The Member Secretary'} submitted the Action Taken Report for "
            f"{submitted['committee']} {submitted['meetingNo']} ({submitted.get('department') or submitted.get('school')}).",
            workspace_id=workspace_id, link="atr", actor=user["email"],
            meta={"stage": "atr", "meetingNo": meeting.get("meetingNo")})
    return jsonify({"ok": True, "report": submitted, "window": atr_store.window(submitted)})


@app.post("/api/atr/<workspace_id>/chair-decision")
@roles_required("faculty")
def chair_decide_action_taken_report(workspace_id: str):
    """The Chairperson signs the report, or returns it for correction."""
    user = get_current_user()
    workspace, report, error = _atr_workspace(workspace_id)
    if error:
        return error
    if str(report.get("chairEmail") or "") != str(user["email"] or "").lower():
        return jsonify({"error": "Only the Chairperson of this meeting signs its Action Taken Report."}), 403
    if report["status"] != "submitted":
        return jsonify({"error": "The report has not been submitted for signature yet.",
                        "status": report["status"]}), 409
    payload = request.get_json(silent=True) or {}
    decision = str(payload.get("decision") or "").strip()
    comment = str(payload.get("comment") or "").strip()
    if decision not in {"approved", "revision"}:
        return jsonify({"error": "Choose approve or return for revision."}), 400
    if decision == "revision" and not comment:
        return jsonify({"error": "Add a note explaining what should be corrected."}), 400
    if not signature_store.has_signature(user):
        return jsonify({"error": "Record your digital signature before signing the report.",
                        "signatureRequired": True}), 428

    decided = atr_store.decide_report(workspace_id, decision, comment=comment,
                                      signature=signature_store.stamp(user) if decision == "approved" else None)
    document = None
    if decision == "approved":
        try:
            meeting = workspace["payload"].get("meeting") or {}
            owner = get_user_by_email(decided.get("ownerEmail") or "") or {}
            chair = get_user_by_email(decided.get("chairEmail") or "") or {}
            merged = {**decided, "schoolCode": meeting.get("schoolCode") or "",
                      "departmentCode": meeting.get("departmentCode") or ""}
            pdf_bytes = atr_pdf.build_atr_pdf(merged, meeting=meeting, owner=owner, chair=chair)
            document = document_vault.store_document(
                school=str(decided.get("school") or "Unassigned"),
                department=str(decided.get("department") or ""),
                academic_year=str(decided.get("academicYear") or ""),
                semester=str(decided.get("semester") or ""),
                workspace_id=workspace_id,
                meeting_ref=atr_pdf.reference_number(merged),
                doc_type="atr", committee=str(decided.get("committee") or "DAC"),
                title=(f"Action Taken Report — {decided.get('committee')} {decided.get('meetingNo')} "
                       f"({decided.get('department') or decided.get('school')})"),
                pdf_bytes=pdf_bytes, created_by=user["email"],
                meta={"meetingNo": decided.get("meetingNo"), "nextMeeting": decided.get("nextMeetingNo"),
                      "date": decided.get("meetingDate")})
            atr_store.attach_document(workspace_id, document["id"])
        except Exception:
            app.logger.exception("Could not archive the Action Taken Report")
    audit.record("atr_approved" if decision == "approved" else "atr_returned",
                 actor=user["email"], role=user["role"], workspace_id=workspace_id,
                 details={"comment": comment})
    owner_email = str(decided.get("ownerEmail") or "").strip().lower()
    if owner_email:
        notification_store.notify(
            owner_email,
            "approval_done" if decision == "approved" else "revision",
            ("Action Taken Report signed by the Chairperson" if decision == "approved"
             else "Action Taken Report returned for correction"),
            (f"The Chairperson signed the Action Taken Report for {decided['committee']} "
             f"{decided['meetingNo']}. It is filed with the meeting record."
             if decision == "approved" else comment),
            workspace_id=workspace_id, link="atr", actor=user["email"], meta={"stage": "atr"})
    return jsonify({"ok": True, "report": atr_store.get_report(workspace_id),
                    "document": document})


@app.get("/api/atr/<workspace_id>/document")
@login_required
def download_action_taken_report(workspace_id: str):
    """The signed report once the Chairperson has approved it."""
    user = get_current_user()
    workspace, report, error = _atr_workspace(workspace_id)
    if error:
        return error
    if user["role"] not in {"academic_office", "system_admin"} and not _atr_owner_or_chair(report, user):
        return jsonify({"error": "This Action Taken Report is not available to your account."}), 403
    if report["status"] != "approved":
        return jsonify({"error": "The report is downloadable once the Chairperson signs it.",
                        "status": report["status"]}), 409
    meeting = workspace["payload"].get("meeting") or {}
    owner = get_user_by_email(report.get("ownerEmail") or "") or {}
    chair = get_user_by_email(report.get("chairEmail") or "") or {}
    merged = {**report, "schoolCode": meeting.get("schoolCode") or "",
              "departmentCode": meeting.get("departmentCode") or ""}
    pdf_bytes = atr_pdf.build_atr_pdf(merged, meeting=meeting, owner=owner, chair=chair)
    name = f"Action-Taken-Report-{report['committee']}-{report['meetingNo']}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
                     download_name=name)


# --------------------------- the issued meeting calendar ---------------------------

@app.get("/api/atr/calendar")
@login_required
def read_meeting_calendar():
    """The meeting dates the Academic Office has issued for the academic year."""
    user = get_current_user()
    if user["role"] not in {"faculty", "academic_office", "system_admin"}:
        return jsonify({"error": "Not available to this account."}), 403
    academic_year = str(request.args.get("academicYear") or "").strip()
    return jsonify({"entries": atr_store.list_calendar(academic_year=academic_year),
                    "rules": {"dueDaysBeforeMeeting": atr_store.DUE_DAYS_BEFORE_MEETING,
                              "reminderDaysBeforeMeeting": atr_store.REMINDER_DAYS_BEFORE_MEETING},
                    "canEdit": user["role"] == "academic_office"})


@app.post("/api/atr/calendar")
@roles_required("academic_office")
def write_meeting_calendar():
    """Record the dates the Academic Office issues before the academic year begins."""
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        return jsonify({"error": "Send the calendar as a list of meetings."}), 400
    result = atr_store.issue_calendar(entries, issued_by=user["email"])
    years = sorted({str(entry.get("academicYear") or "") for entry in entries if entry.get("academicYear")})
    for year in years:
        audit.record("meeting_calendar_issued", actor=user["email"], role=user["role"],
                     details={"academicYear": year, "written": result["written"]})
    # Every open report recomputes its deadline from the dates just issued.
    for workspace in atr_store._approved_workspaces():
        atr_store.ensure_report(workspace)
    return jsonify({"ok": True, "written": result["written"], "cleared": result["cleared"],
                    "entries": atr_store.list_calendar()})


@app.post("/api/testing/atr-clock")
@roles_required("faculty")
def testing_atr_clock():
    """Test hook: move this meeting's action-item target dates into the past.

    Lets the automated suites exercise activation, reminders and the deadline without
    waiting weeks. Inert in production.
    """
    if not TEST_HOOKS:
        return jsonify({"error": "Not available."}), 404
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    workspace_id = str(payload.get("workspaceId") or "")
    workspace = get_workspace(workspace_id)
    if not workspace or workspace["ownerId"] != user["id"]:
        return jsonify({"error": "A meeting owned by this account is required."}), 403
    days = int(payload.get("daysAgo") or 1)
    state, target = _move_action_targets(workspace["payload"], days)
    save_workspace(workspace_id, user["id"], state, workspace["status"])
    atr_store.ensure_report(get_workspace(workspace_id))
    return jsonify({"ok": True, "targetDate": target})


@app.post("/api/demo/fast-track")
@roles_required("faculty")
def demo_fast_track():
    """Demonstration fast-forward: show the whole workflow without waiting for the date.

    The minutes are locked until the scheduled end has passed and the meeting is marked
    completed — correct, and impossible to demonstrate in twenty minutes. This control
    moves *this one meeting's* clock instead:

    ``stage="meeting"`` (default)
        The meeting date moves into the past and the meeting is marked completed, so the
        MoM unlocks exactly as it would on the day. Nothing else in the record changes.
    ``stage="atr"``
        The action-item target dates move into the past, so the Action Taken Report opens.

    It only ever touches a meeting owned by the signed-in Member Secretary, it records its
    own audit event, and it does not exist at all in production (``FAST_TRACK`` is false
    there, so the route answers 404 and the interface never shows the button).
    """
    if not FAST_TRACK:
        return jsonify({"error": "Fast-track is not available."}), 404
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    workspace_id = str(payload.get("workspaceId") or "")
    stage = str(payload.get("stage") or "meeting").strip().lower()
    workspace = get_workspace(workspace_id)
    if not workspace or workspace["ownerId"] != user["id"]:
        return jsonify({"error": "A meeting owned by this account is required."}), 403

    if stage == "atr":
        state, target = _move_action_targets(workspace["payload"], int(payload.get("daysAgo") or 1))
        save_workspace(workspace_id, user["id"], state, workspace["status"])
        atr_store.ensure_report(get_workspace(workspace_id))
        audit.record("demo_fast_track", actor=user["email"], role=user["role"],
                     workspace_id=workspace_id, details={"stage": "atr", "targetDate": target})
        return jsonify({"ok": True, "stage": "atr", "targetDate": target, "state": state})

    if stage != "meeting":
        return jsonify({"error": "Choose the meeting or the Action Taken Report."}), 400
    if workspace["status"] != "approved":
        return jsonify({"error": "The Academic Office must approve the meeting before its "
                                 "minutes can be completed."}), 409
    state = _fast_forward_meeting(workspace["payload"], int(payload.get("daysAgo") or 1))
    save_workspace(workspace_id, user["id"], state, "approved")
    audit.record("demo_fast_track", actor=user["email"], role=user["role"],
                 workspace_id=workspace_id,
                 details={"stage": "meeting", "meetingDate": state["meeting"].get("date")})
    return jsonify({"ok": True, "stage": "meeting", "state": state,
                    "unlocked": _minutes_unlocked(state)})


if __name__ == "__main__":
    _serve()
