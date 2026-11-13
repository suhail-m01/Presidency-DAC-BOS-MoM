"""End-to-end checks for DAC workflow, role gates, scoped files and PDF export."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

# Use an isolated database and filesystem so the test cannot alter working data.
_TEST_TMP = tempfile.TemporaryDirectory(prefix="dac-mom-self-test-")
_TEST_ROOT = Path(_TEST_TMP.name)
os.environ["APP_ENV"] = "test"
os.environ["DEV_ECHO_OTP"] = "1"
os.environ["DAC_DATABASE_PATH"] = str(_TEST_ROOT / "dac-test.sqlite3")

import app as server
from auth_store import get_catalog
from docx import Document
from PIL import Image
from pypdf import PdfReader

app = server.app
app.config["TESTING"] = True
server.UPLOAD_DIR = _TEST_ROOT / "uploads"
server.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
server.OUTBOX_PATH = _TEST_ROOT / "test-outbox.json"
server.AUDIT_PATH = _TEST_ROOT / "test-audit.json"


def _signature_png() -> str:
    """A small deterministic signature image (data URL) for the in-process suite."""
    import base64
    import io

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (360, 130), "white")
    draw = ImageDraw.Draw(image)
    draw.line((22, 96, 84, 34, 148, 96, 210, 34, 272, 96, 330, 44), fill="black", width=5)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


_SIGNATURE_PNG = _signature_png()


def sign_in(email: str):
    client = app.test_client()
    requested = client.post("/api/auth/request-code", json={"email": email})
    assert requested.status_code == 200, requested.get_data(as_text=True)
    request_data = requested.get_json()
    if "devCode" not in request_data:
        return client, "", None
    assert len(request_data["devCode"]) == 6
    verified = client.post("/api/auth/verify-code", json={"email": email, "code": request_data["devCode"]})
    assert verified.status_code == 200, verified.get_data(as_text=True)
    data = verified.get_json()
    # First-login signature: no workflow action is allowed until the account signs.
    signature = client.post("/api/signature", json={"image": _SIGNATURE_PNG, "method": "upload"},
                            headers={"X-CSRF-Token": data["csrfToken"]})
    assert signature.status_code == 200, signature.get_data(as_text=True)
    return client, data["csrfToken"], data["user"]


def post(client, csrf: str, path: str, payload: dict):
    return client.post(path, json=payload, headers={"X-CSRF-Token": csrf})


def patch(client, csrf: str, path: str, payload: dict):
    return client.patch(path, json=payload, headers={"X-CSRF-Token": csrf})


# Pure business rules: minutes unlock only for an approved and completed meeting after its scheduled end.
meeting_gate = {"date": "2030-01-02", "endTime": "12:00", "completed": False}
assert not server.meeting_end_passed(meeting_gate, datetime.fromisoformat("2030-01-02T11:59:00"))
assert not server.can_edit_minutes({"status": "approved", "meeting": meeting_gate}, datetime.fromisoformat("2030-01-02T12:00:00"))
assert not server.can_edit_minutes({"status": "approved", "meeting": {**meeting_gate, "completed": True}}, datetime.fromisoformat("2030-01-02T11:59:00"))
assert server.can_edit_minutes({"status": "approved", "meeting": {**meeting_gate, "completed": True}}, datetime.fromisoformat("2030-01-02T12:00:00"))
assert not server.can_edit_minutes({"status": "pending", "meeting": {**meeting_gate, "completed": True}}, datetime.fromisoformat("2030-01-02T12:00:00"))

# ---------------------------------------------------------------------------------
# A restart must not sign everybody out. The session key used to be regenerated with
# secrets.token_urlsafe on every start, so every restart answered 401 to a live browser
# and the access directory rendered empty. It is now read from (or written to) a file.
# ---------------------------------------------------------------------------------
_secret_one = server._session_secret()
_secret_two = server._session_secret()
assert _secret_one == _secret_two and len(_secret_one) >= 32, "the session key must be stable"
_key_file = server.DATA_DIR / ".session_secret"
assert _key_file.exists(), "the session key must be written to disk so a restart keeps it"
assert _key_file.read_text(encoding="utf-8").strip() == _secret_one, "the stored key must be the one used"
assert oct(_key_file.stat().st_mode)[-3:] == "600", oct(_key_file.stat().st_mode)
print("Session key: stable across restarts, stored 0600 at", _key_file.name)

# ---------------------------------------------------------------------------------
# Sign-in from an embedded (sandboxed) page. The preview pane shows the app inside
# `sandbox="allow-scripts"`, which blocks cookies, and a sandboxed document has an opaque
# origin — so `'self'` in the CSP matches nothing and CORS does not apply. Three defects
# came out of that: the bundle was blocked by CSP, the assets and API were refused by
# CORS, and the sign-in button was a native <form> submit, which a sandboxed frame
# blocks outright. Each is pinned here.
# ---------------------------------------------------------------------------------
_csp = app.test_client()
_page = _csp.get("/")
_policy = _page.headers.get("Content-Security-Policy", "")
assert "script-src 'self' http://" in _policy or "script-src http" in _policy, _policy
print("Preview: the CSP names this host, so the bundle loads from an opaque origin")

# Framing has two correct answers and they must not be confused.
#   • a hosted preview pane embeds the app from ANOTHER origin — 'self' blocks the frame
#     and the operator sees a blank pane, so the pane needs frame-ancestors *
#   • a real deployment is framed by itself only, with X-Frame-Options alongside
_saved = {name: os.environ.get(name) for name in ("DAC_PREVIEW", "E2B_SANDBOX", "FRAME_ANCESTORS")}

def _policy_and_headers(**env):
    for name in ("DAC_PREVIEW", "E2B_SANDBOX", "FRAME_ANCESTORS"):
        os.environ.pop(name, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    page = app.test_client().get("/")
    return page.headers.get("Content-Security-Policy", ""), page.headers

try:
    _preview_policy, _preview_headers = _policy_and_headers(E2B_SANDBOX="true")
    assert "frame-ancestors *" in _preview_policy, _preview_policy
    assert "X-Frame-Options" not in _preview_headers, "a permissive policy must not be overridden by XFO"

    _strict_policy, _strict_headers = _policy_and_headers()
    assert "frame-ancestors 'self'" in _strict_policy, _strict_policy
    assert _strict_headers.get("X-Frame-Options") == "SAMEORIGIN", dict(_strict_headers)

    _none_policy, _none_headers = _policy_and_headers(FRAME_ANCESTORS="'none'")
    assert "frame-ancestors 'none'" in _none_policy, _none_policy
    assert _none_headers.get("X-Frame-Options") == "DENY", "a never-framed deployment must say DENY"
finally:
    for name, value in _saved.items():
        os.environ.pop(name, None)
        if value is not None:
            os.environ[name] = value

print("Preview: framing allows the preview pane, restricts a real deployment, honours FRAME_ANCESTORS")

_asset = next((path for path in (server.DIST_DIR / "assets").glob("*.js")), None)
assert _asset is not None, "the built bundle is missing"
_preflight = _csp.options(f"/assets/{_asset.name}", headers={
    "Origin": "null", "Access-Control-Request-Method": "GET"})
assert _preflight.status_code in (200, 204), _preflight.status_code
assert _preflight.headers.get("Access-Control-Allow-Origin") == "null", dict(_preflight.headers)
assert "Access-Control-Allow-Credentials" not in _preflight.headers, "never credential a null origin"
# A foreign website must not be answered.
_foreign = _csp.get(f"/assets/{_asset.name}", headers={"Origin": "https://evil.example"})
assert _foreign.headers.get("Access-Control-Allow-Origin") is None
print("Preview: CORS answers an opaque origin for this app's own assets only")

# The bearer token is the session for a browser that cannot keep cookies.
import auth_store as _auth_store  # noqa: E402  (imported here so the preview checks read the same DB)

_directory_user = next(person for person in _auth_store.list_users() if person["role"] == "system_admin")
_issued = _auth_store.create_api_token(_directory_user)
assert _auth_store.resolve_api_token(_issued["token"])["email"] == _directory_user["email"]
_token_client = app.test_client()
_admin_call = _token_client.get("/api/admin/users", headers={"Authorization": f"Bearer {_issued['token']}"})
assert _admin_call.status_code == 200, _admin_call.status_code
assert len(_admin_call.get_json()["users"]) >= 81
_csrf_blocked = _token_client.post("/api/workspace/save", json={"workspaceId": "x", "state": {}},
                                   headers={"Authorization": f"Bearer {_issued['token']}"})
assert _csrf_blocked.status_code == 403, "the bearer session must still require the CSRF token"
_auth_store.revoke_api_token(_issued["token"])
assert _auth_store.resolve_api_token(_issued["token"]) is None, "a revoked token must stop working"
_stale = app.test_client().get("/api/admin/users", headers={"Authorization": "Bearer not-a-real-token"})
assert _stale.status_code == 401, _stale.status_code
print("Preview: a bearer token authenticates without cookies, needs CSRF, and revokes cleanly")

# The audit window must stay anchored to *now*. Reading the oldest rows means that once
# the trail outgrows the window, new actions never appear on the audit screen.
import audit as _audit  # noqa: E402

_audit.record("self_test.ordering", actor="self-test", role="system", workspace_id="", details={"step": 1})
_audit.record("self_test.ordering", actor="self-test", role="system", workspace_id="", details={"step": 2})
_window = _audit.list_events(limit=2)
assert [row["details"].get("step") for row in _window] == [1, 2], _window
assert _audit.list_events(limit=2, event="self_test.ordering") == _window
print(f"Audit: the window shows the newest events ({_audit.count_events()} recorded so far)")

# ---------------------------------------------------------------------------------
# Roster permanence: every seeded account must exist, be active and keep its profile.
# This is the regression guard for "never remove professor credentials".
# ---------------------------------------------------------------------------------
import auth_store as _auth_store
_seeded = _auth_store.SEEDED_DIRECTORY
_directory = {person["email"].lower(): person for person in _auth_store.list_users()}
_missing = [entry["email"] for entry in _seeded if entry["email"].lower() not in _directory]
assert not _missing, f"Seeded accounts disappeared from the directory: {_missing}"
_inactive = [entry["email"] for entry in _seeded
             if not _directory[entry["email"].lower()].get("active", True)]
assert not _inactive, f"Seeded accounts were deactivated: {_inactive}"
_profile_lost = [entry["email"] for entry in _seeded
                 if _directory[entry["email"].lower()].get("designation") != entry["designation"]]
assert not _profile_lost, f"Seeded professor details were overwritten: {_profile_lost}"
_faculty = [person for person in _directory.values() if person["role"] == "faculty"]
assert len(_faculty) >= 78, f"Faculty roster shrank to {len(_faculty)} accounts (R1 lists 78)"
_chairs = _auth_store.chairperson_candidates()
assert len(_chairs) >= 31, f"Chairperson-eligible roster shrank to {len(_chairs)} (R1 lists 31 Deans and HODs)"
assert any(person["role"] == "faculty" and _auth_store.is_eligible_chairperson(person) for person in _faculty)
# A deleted row must come back on the next start-up (the seed is INSERT OR IGNORE).
_probe_email = "renukadevi.m@presidencyuniversity.in"
with _auth_store.connect() as _db:
    _db.execute("DELETE FROM users WHERE email = ?", (_probe_email,))
    _db.commit()
assert _auth_store.get_user_by_email(_probe_email) is None, "probe account was not deleted"
_auth_store.init_db()
assert _auth_store.get_user_by_email(_probe_email) is not None, \
    "a deleted seeded account was not restored by init_db() — the roster must be permanent"
print(f"Roster permanence: {len(_seeded)} seeded accounts intact, {len(_faculty)} faculty, "
      f"{len(_chairs)} chairperson-eligible, deleted account restored on start-up.")

# The content verification examines typed Discussion/Resolution text only, never annexures.
aligned = server.validate_mom({"momItems": [{
    "title": "Review of curriculum changes",
    "discussion": "The committee reviewed the curriculum changes and discussed course outcomes.",
    "resolution": "The curriculum changes were approved.",
    "attachments": [{"name": "supporting-evidence.pdf", "id": "not-used-by-validator"}],
}]})
assert aligned["summary"]["items"] == 1
assert aligned["items"][0]["status"] == "aligned"
check_names = {check["name"] for check in aligned["items"][0]["checks"]}
assert {"Agenda ↔ Discussion", "Discussion ↔ Resolution"}.issubset(check_names)
assert aligned["mode"] in {"ai-model", "offline-rules"}
assert all(check.get("source") in {"ai-model", "offline-rules"} for check in aligned["items"][0]["checks"])

conflict = server.validate_mom({"momItems": [{
    "title": "Approval of previous minutes",
    "discussion": "The previous minutes were deferred for the next meeting.",
    "resolution": "The previous minutes were approved.",
}]})
assert any(check["name"] == "Outcome consistency" for check in conflict["items"][0]["checks"])

# Backward compatibility: workspaces saved with the legacy "recommendation" key still verify.
legacy = server.validate_mom({"momItems": [{
    "title": "Review of curriculum changes",
    "discussion": "The committee reviewed the curriculum changes and discussed course outcomes.",
    "recommendation": "The curriculum changes were approved.",
}]})
assert legacy["items"][0]["status"] == "aligned", legacy["items"][0]
assert not any("recommendation" in str(check).lower() for check in legacy["items"][0]["checks"])

# Resolution text that nothing in the discussion supports must be flagged for review.
unsupported = server.validate_mom({"momItems": [{
    "title": "Review of syllabus and curriculum matters",
    "discussion": "The committee reviewed the proposed syllabus revisions.",
    "resolution": "The committee resolved to purchase new laboratory furniture for the workshop.",
}]})
resolution_check = next(check for check in unsupported["items"][0]["checks"] if check["name"] == "Discussion ↔ Resolution")
assert resolution_check["status"] in {"review", "needs_revision"}, resolution_check

# The document house style: Cambria, 11 pt body, 12 pt sub-headings, 1.15 spacing.
style = server.document_font_status()
assert style["family"] == "Cambria" and style["docxFont"] == "Cambria", style
assert (style["bodyPt"], style["headingPt"], style["lineSpacing"]) == (11, 12, 1.15), style
assert style["pdfEmbedded"] is True, "The bundled Cambria-metric font should be embedded in the PDF."
assert server._styles()["body"].fontName == "Cambria" and server._styles()["body"].fontSize == 11
assert server._styles()["h2"].fontSize == 12 and round(server._styles()["body"].leading, 2) == 12.65

# Catalog contains R1's schools and their dependent departments.
catalog = get_catalog()
schools = {school["name"]: {department["name"] for department in school["departments"]} for school in catalog["schools"]}
assert {"School of Engineering", "School of Artificial Intelligence and Advanced Computing",
        "School of Commerce", "School of Design"}.issubset(schools), sorted(schools)
assert {"Mechanical Engineering", "Electrical and Electronics Engineering",
        "Civil Engineering"}.issubset(schools["School of Engineering"])
assert {"Artificial Intelligence and Robotics", "Cyber Security and Intelligence System",
        "Data Science and Computing System"}.issubset(
            schools["School of Artificial Intelligence and Advanced Computing"])
# R1 gives School of Commerce no department at all: it is one school-level DAC.
assert schools["School of Commerce"] == set(), schools["School of Commerce"]

# ---------------------------------------------------------------------------------
# R1: the cast used by this suite is taken from the college's own registry, so the
# test signs in with the real Member Secretary, Chairperson and External Member.
# ---------------------------------------------------------------------------------
import r1_registry as _r1

_UNIT = next(dac for dac in _r1.dacs()
             if dac.get("department") and dac.get("memberSecretary") and dac.get("externalMembers"))
UNIT_SCHOOL, UNIT_DEPT, UNIT_CODE = _UNIT["school"], _UNIT["department"], _UNIT["code"]
MS_EMAIL, MS_NAME = _UNIT["memberSecretary"]["email"], _UNIT["memberSecretary"]["name"]
CHAIR_EMAIL, CHAIR_NAME = _UNIT["hod"]["email"], _UNIT["hod"]["name"]
EXT_EMAIL, EXT_NAME = _UNIT["externalMembers"][0]["email"], _UNIT["externalMembers"][0]["name"]
_OTHER = next(dac for dac in _r1.dacs()
              if dac["school"] != UNIT_SCHOOL and dac.get("memberSecretary"))
OTHER_SCHOOL, OTHER_MS_EMAIL = _OTHER["school"], _OTHER["memberSecretary"]["email"]
# A guest account for the "outside observer" path is provisioned explicitly, because
# nothing else may invent a directory entry.
GUEST_EMAIL = "outside.observer@example.org"

# API access starts behind the active email allow-list and a per-session CSRF token.
unauth = app.test_client()
assert unauth.get("/api/admin/users").status_code == 401
assert unauth.post("/api/export", json={}).status_code == 401
assert unauth.post("/api/export-docx", json={}).status_code == 401
unknown, _, _ = sign_in("not-in-directory@example.edu")
unknown_response = unknown.post("/api/auth/verify-code", json={"email": "not-in-directory@example.edu", "code": "123456"})
assert unknown_response.status_code == 401

admin, admin_csrf, admin_user = sign_in("admin@presidencyuniversity.in")
assert admin_user["role"] == "system_admin"
assert admin.get("/api/admin/users").status_code == 200
assert admin.get("/api/workspace").status_code == 403  # administrators manage accounts, not meeting content
assert post(admin, "", "/api/admin/users", {"email": "blocked@example.edu", "name": "Blocked", "role": "faculty", "school": "School of Engineering", "department": "Mechanical Engineering"}).status_code == 403

bad_assignment = post(admin, admin_csrf, "/api/admin/users", {
    "email": "bad-assignment@example.edu", "name": "Bad Assignment", "role": "faculty",
    "school": "School of Engineering", "department": "Artificial Intelligence and Robotics",
})
assert bad_assignment.status_code == 400
created = post(admin, admin_csrf, "/api/admin/users", {
    "email": "new.faculty@example.edu", "name": "New Faculty", "role": "faculty",
    "school": "School of Engineering", "department": "Mechanical Engineering",
})
assert created.status_code == 201, created.get_data(as_text=True)
new_user_id = created.get_json()["user"]["id"]
assert post(admin, admin_csrf, "/api/admin/users", {
    "email": "new.faculty@example.edu", "name": "Duplicate", "role": "faculty",
    "school": "School of Engineering", "department": "Mechanical Engineering",
}).status_code == 409
updated = patch(admin, admin_csrf, f"/api/admin/users/{new_user_id}", {
    "name": "New Faculty", "role": "faculty", "school": "School of Engineering",
    "department": "Petroleum Engineering", "active": False,
})
assert updated.status_code == 200
inactive, _, inactive_user = sign_in("new.faculty@example.edu")
assert inactive_user is None  # inactive database entries receive no local code
assert inactive.post("/api/auth/verify-code", json={"email": "new.faculty@example.edu", "code": "123456"}).status_code == 401

faculty, faculty_csrf, faculty_user = sign_in(MS_EMAIL)
assert faculty_user["role"] == "faculty"
faculty_catalog = faculty.get("/api/catalog").get_json()
assert [school["name"] for school in faculty_catalog["schools"]] == [UNIT_SCHOOL]
assert faculty.get("/api/admin/users").status_code == 403
assert faculty.get("/api/workspaces/inbox").status_code == 403
assert post(faculty, "", "/api/audit", {"event": "missing-csrf"}).status_code == 403

# The outside observer is provisioned by the administrator (a member list may never
# invent a directory entry), so the guest path is exercised on a real account.
_guest_created = post(admin, admin_csrf, "/api/admin/users",
                      {"email": GUEST_EMAIL, "name": EXT_NAME + " (Outside Observer)",
                       "role": "external_member", "designation": "External Academic"})
assert _guest_created.status_code in (201, 409), _guest_created.get_data(as_text=True)

workspace_id = f"test-{uuid4().hex}"
proposal = {
    "status": "draft", "workspaceId": workspace_id, "approvalVersion": 0, "submittedVersion": 0,
    "meeting": {
        "id": workspace_id, "meetingNo": "2", "academicYear": "2026-27", "semester": "Odd",
        "school": UNIT_SCHOOL, "department": f"Department of {UNIT_DEPT}",
        "schoolCode": UNIT_CODE, "departmentCode": UNIT_CODE, "previousMeetingNo": "1",
        "previousMeetingDate": "2026-06-30",
        "date": "2030-01-02", "startTime": "10:30", "endTime": "12:00", "venue": "Room 1",
        "mode": "Offline", "onlineLink": "", "chairName": CHAIR_NAME,
        "chairEmail": CHAIR_EMAIL,
        "completed": False, "attendanceConfirmed": False,
        "agendas": [
            {"id": "std-mom", "kind": "standard", "title": "Approval of the previous MoM", "rationale": ""},
            {"id": "std-atr", "kind": "standard", "title": "Action Taken Report of the previous DAC meeting", "rationale": ""},
            {"id": "std-curriculum", "kind": "standard", "title": "Review curriculum matters", "rationale": ""},
        ],
        "members": [
            {"id": "chair", "name": CHAIR_NAME, "designation": _UNIT["hod"]["designation"],
             "role": "Chairperson", "email": CHAIR_EMAIL, "external": False, "present": False},
            {"id": "secretary", "name": MS_NAME, "designation": _UNIT["memberSecretary"]["designation"],
             "role": "Member Secretary", "email": MS_EMAIL, "external": False, "present": False},
            {"id": "guest", "name": "Dr. Alex Morgan", "designation": "External Academic",
             "role": "External Member", "email": GUEST_EMAIL, "external": True, "present": False},
        ],
    },
    "momItems": [], "additionalDiscussions": [], "photos": [], "actionItems": [], "agendaBank": [],
}
wrong_scope = json.loads(json.dumps(proposal))
wrong_scope["meeting"]["school"] = OTHER_SCHOOL
assert post(faculty, faculty_csrf, "/api/workspace/save", {"workspaceId": f"bad-{uuid4().hex}", "state": wrong_scope}).status_code == 403
saved = post(faculty, faculty_csrf, "/api/workspace/save", {"workspaceId": workspace_id, "state": proposal})
assert saved.status_code == 200, saved.get_data(as_text=True)
assert any(row["workspaceId"] == workspace_id for row in faculty.get("/api/workspaces/mine").get_json()["workspaces"])

# Uploads are authenticated and private to the owner and Academic Office; not to guests or other faculty.
uploaded = faculty.post("/api/upload", data={"file": (BytesIO(b"private test attachment\n"), "meeting-note.txt")}, headers={"X-CSRF-Token": faculty_csrf}, content_type="multipart/form-data")
assert uploaded.status_code == 200, uploaded.get_data(as_text=True)
file_id = uploaded.get_json()["id"]
assert faculty.get(f"/api/file/{file_id}").status_code == 200

other_faculty, other_csrf, other_user = sign_in(OTHER_MS_EMAIL)
assert other_user["school"] == OTHER_SCHOOL, other_user["school"]
assert other_faculty.get(f"/api/workspaces/{workspace_id}").status_code == 403
assert other_faculty.get(f"/api/file/{file_id}").status_code == 403
assert post(other_faculty, other_csrf, "/api/workspace/save", {"workspaceId": workspace_id, "state": proposal}).status_code == 403
assert post(other_faculty, other_csrf, "/api/export", {"meeting": {"id": workspace_id}}).status_code == 403
assert post(other_faculty, other_csrf, "/api/export-docx", {"meeting": {"id": workspace_id}}).status_code == 403

submitted = post(faculty, faculty_csrf, "/api/workspace/submit", {"workspaceId": workspace_id, "state": proposal})
assert submitted.status_code == 200, submitted.get_data(as_text=True)
assert submitted.get_json()["state"]["status"] == "pending_chairperson", "the request must reach the Chairperson first"

office, office_csrf, office_user = sign_in("academic.office@presidencyuniversity.in")
assert office_user["role"] == "academic_office"
assert office.get("/api/workspaces/mine").status_code == 403
queue = office.get("/api/workspaces/inbox").get_json()["workspaces"]
# A request that is still with the Chairperson is not in the Academic Office queue.
assert all(row["workspaceId"] != workspace_id for row in queue)
# A submitted request is readable by the Academic Office — it is the approving authority and
# opens it from the archive — but it may not act on it until the Chairperson has signed.
assert office.get(f"/api/workspaces/{workspace_id}").status_code == 200
assert office.get(f"/api/file/{file_id}").status_code == 200
assert office.get("/api/admin/users").status_code == 403

# The Academic Office cannot decide until the Chairperson has signed the request.
assert post(office, office_csrf, "/api/workspace/decision",
            {"workspaceId": workspace_id, "decision": "approved", "comment": ""}).status_code == 409
assert all(row["workspaceId"] != workspace_id for row in office.get("/api/workspaces/inbox").get_json()["workspaces"])
chair_client, chair_csrf, chair_user = sign_in(CHAIR_EMAIL)
assert chair_user["email"] == CHAIR_EMAIL, chair_user
assert chair_client.get(f"/api/workspaces/{workspace_id}").status_code == 200
chair_inbox = chair_client.get("/api/workspaces/chair-inbox").get_json()["workspaces"]
assert any(row["workspaceId"] == workspace_id for row in chair_inbox), chair_inbox
# Only the nominated Chairperson may decide; another Head of Department cannot.
impostor, impostor_csrf, _ = sign_in(MS_EMAIL)
assert post(impostor, impostor_csrf, "/api/workspace/chair-decision",
            {"workspaceId": workspace_id, "decision": "approved", "comment": ""}).status_code == 403
signed = post(chair_client, chair_csrf, "/api/workspace/chair-decision",
              {"workspaceId": workspace_id, "decision": "approved", "comment": ""})
assert signed.status_code == 200, signed.get_data(as_text=True)
signed_state = signed.get_json()
assert signed_state["status"] == "pending", signed_state["status"]
assert signed_state["chairApproval"]["signatureSha256"], "the Chairperson's signature must be recorded"
assert any(row["workspaceId"] == workspace_id for row in office.get("/api/workspaces/inbox").get_json()["workspaces"])

# The Member Secretary cannot download the signed form before the office approves.
assert faculty.get(f"/api/workspace/{workspace_id}/request-form").status_code == 409

# Deactivating a proposed member blocks approval until the directory entry is reactivated.
external_id = next(user["id"] for user in admin.get("/api/admin/users").get_json()["users"] if user["email"] == GUEST_EMAIL)
assert patch(admin, admin_csrf, f"/api/admin/users/{external_id}", {"active": False}).status_code == 200
blocked_approval = post(office, office_csrf, "/api/workspace/decision", {"workspaceId": workspace_id, "decision": "approved", "comment": ""})
assert blocked_approval.status_code == 409
assert patch(admin, admin_csrf, f"/api/admin/users/{external_id}", {"active": True}).status_code == 200

approved_response = post(office, office_csrf, "/api/workspace/decision", {"workspaceId": workspace_id, "decision": "approved", "comment": ""})
assert approved_response.status_code == 200, approved_response.get_data(as_text=True)
approved_state = approved_response.get_json()["state"]
assert approved_state["status"] == "approved"
assert len(approved_state["momItems"]) == 3
assert "1st Departmental Academic Committee meeting held on 30.06.2026" in approved_state["momItems"][0]["title"]
# The signed request & agenda approval form: archived on approval, downloadable by the Member Secretary.
form = faculty.get(f"/api/workspace/{workspace_id}/request-form")
assert form.status_code == 200 and form.data[:4] == b"%PDF", form.status_code
assert approved_state.get("requestDocumentId"), approved_state.get("requestDocumentId")
archived = office.get(f"/api/documents/{approved_state['requestDocumentId']}/download")
assert archived.status_code == 200 and archived.data[:4] == b"%PDF"
assert other_faculty.get(f"/api/workspace/{workspace_id}/request-form").status_code == 403

# The Academic Office reviews the minutes of an approved meeting, so it may open it
# (read-only); other faculty still cannot, and the office queue stays pending-only.
assert office.get(f"/api/workspaces/{workspace_id}").status_code == 200
assert all(row["workspaceId"] != workspace_id for row in office.get("/api/workspaces/inbox").get_json()["workspaces"])

# The simulated invitation uses canonical, stored meeting data and the per-meeting organizer.
invite = post(office, office_csrf, "/api/outbox", {
    "meeting": {"id": workspace_id}, "from": MS_EMAIL, "subject": "Test invitation",
})
assert invite.status_code == 201, invite.get_data(as_text=True)
invite_data = invite.get_json()
assert invite_data["from"] == MS_EMAIL
assert invite_data["meeting"]["agendas"][0]["title"].startswith("To consider the approval of the MoM")
assert office.get("/api/outbox").status_code == 200
assert admin.get("/api/outbox").status_code == 403
assert len(faculty.get("/api/outbox").get_json()) == 1
assert other_faculty.get("/api/outbox").get_json() == []
assert other_faculty.get(f"/api/file/{file_id}").status_code == 403

# Guest receives only the explicitly invited approved meeting's safe schedule/agenda projection.
guest, guest_csrf, guest_user = sign_in(GUEST_EMAIL)
assert guest_user["role"] == "external_member"
guest_workspace = guest.get("/api/workspace").get_json()
assert guest_workspace["workspaceId"] == workspace_id
safe_state = guest_workspace["state"]
assert set(safe_state) == {"status", "meeting", "approvedMeeting", "momItems"}
assert "members" not in safe_state["meeting"] and "chairEmail" not in safe_state["meeting"]
assert safe_state["momItems"] == []
assert MS_EMAIL not in json.dumps(guest_workspace)
assert guest.get(f"/api/workspaces/{workspace_id}").status_code == 200
assert guest.get(f"/api/file/{file_id}").status_code == 403
assert guest.get("/api/catalog").status_code == 403
assert guest.get("/api/workspaces/inbox").status_code == 403
assert post(guest, guest_csrf, "/api/validate", {"momItems": []}).status_code == 403

# Meeting completion alone does not unlock before the scheduled end; the clock hook is owner-only.
assert faculty.get("/api/workspace").get_json()["state"]["status"] == "approved"
complete = post(faculty, faculty_csrf, "/api/workspace/complete", {"workspaceId": workspace_id})
assert complete.status_code == 200
locked_export = post(faculty, faculty_csrf, "/api/export", {"meeting": {"id": workspace_id}})
assert locked_export.status_code == 409
assert post(faculty, faculty_csrf, "/api/export-docx", {"meeting": {"id": workspace_id}}).status_code == 409
fast_forward = post(faculty, faculty_csrf, "/api/testing/advance-clock", {"workspaceId": workspace_id})
assert fast_forward.status_code == 200, fast_forward.get_data(as_text=True)

# Minutes review chain: the download is gated until the Chairperson approves, the External
# Member files the observation report and the Academic Office approves the filled minutes.
minutes_state = faculty.get("/api/workspace").get_json()["state"]
for index, item in enumerate(minutes_state["momItems"], start=1):
    # The discussion and the resolution repeat the approved agenda wording, exactly as
    # the content check expects: same subject terms in agenda, discussion and resolution.
    title = item.get("title") or f"agenda item {index}"
    item["discussion"] = (f"{title} The committee reviewed {title} in detail, discussed it "
                          f"point by point and recorded the deliberation on {title}.")
    item["resolution"] = f"The committee approved {title} as recorded in the discussion."
saved_minutes = post(faculty, faculty_csrf, "/api/workspace/save", {"workspaceId": workspace_id, "state": minutes_state})
assert saved_minutes.status_code == 200, saved_minutes.get_data(as_text=True)
blocked_export = post(faculty, faculty_csrf, "/api/export", {"meeting": {"id": workspace_id}})
assert blocked_export.status_code == 409, "the minutes must not download before approval"
assert "Awaiting" in blocked_export.get_json()["error"] or "review" in blocked_export.get_json()["error"].lower()

self_chair = post(faculty, faculty_csrf, "/api/workspace/mom/chair-decision", {"workspaceId": workspace_id, "decision": "approved"})
assert self_chair.status_code == 403, "the Member Secretary cannot approve as the Chairperson"
mom_submit = post(faculty, faculty_csrf, "/api/workspace/mom/submit", {"workspaceId": workspace_id})
assert mom_submit.status_code == 200, mom_submit.get_data(as_text=True)
assert mom_submit.get_json()["momReview"]["status"] == "pending_chairperson"
chair_client, chair_csrf, _chair_user = sign_in(CHAIR_EMAIL)
chair_ok = post(chair_client, chair_csrf, "/api/workspace/mom/chair-decision", {"workspaceId": workspace_id, "decision": "approved"})
assert chair_ok.status_code == 200, chair_ok.get_data(as_text=True)
assert chair_ok.get_json()["momReview"]["status"] == "pending_office"
gate_blocked = post(office, office_csrf, "/api/workspace/mom/office-decision", {"workspaceId": workspace_id, "decision": "approved"})
assert gate_blocked.status_code == 409, "the office cannot approve before the External Member reports"

report_guest, report_csrf, _ = sign_in(GUEST_EMAIL)
report_form = report_guest.get(f"/api/external-report/{workspace_id}").get_json()
for row in report_form["draft"]["agenda"]:
    row["response"], row["remarks"] = "yes", "Verified during the meeting."
report_saved = post(report_guest, report_csrf, f"/api/external-report/{workspace_id}",
                    {"payload": report_form["draft"], "submit": True})
assert report_saved.status_code == 200, report_saved.get_data(as_text=True)
assert report_saved.get_json()["report"]["status"] == "submitted"
office_ok = post(office, office_csrf, "/api/workspace/mom/office-decision", {"workspaceId": workspace_id, "decision": "approved"})
assert office_ok.status_code == 200, office_ok.get_data(as_text=True)
assert office_ok.get_json()["document"]["docType"] == "mom", "the approved minutes are archived in the vault"

exported = post(faculty, faculty_csrf, "/api/export", {"meeting": {"id": workspace_id}})
assert exported.status_code == 200, exported.get_data(as_text=True)
assert exported.mimetype == "application/pdf"
assert len(PdfReader(BytesIO(exported.data)).pages) >= 3

word = post(faculty, faculty_csrf, "/api/export-docx", {"meeting": {"id": workspace_id}})
assert word.status_code == 200, word.get_data(as_text=True)
assert word.mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
docx_document = Document(BytesIO(word.data))
docx_paragraphs = [paragraph for paragraph in docx_document.paragraphs if paragraph.text.strip()]
assert any(paragraph.text.strip() == "Resolution:" for paragraph in docx_paragraphs), "Word export must label resolutions."
assert any(paragraph.text.strip() == "Discussion:" for paragraph in docx_paragraphs)
assert all(round(paragraph.paragraph_format.line_spacing or 1.15, 2) == 1.15 for paragraph in docx_paragraphs), "Word export must keep 1.15 line spacing."
assert docx_document.styles["Normal"].font.name == "Cambria", docx_document.styles["Normal"].font.name
assert docx_document.styles["Normal"].font.size.pt == 11
assert docx_document.styles["Heading 2"].font.size.pt == 12

# PDF renderer: reference sections, actual attendance, pagination beyond four pages and annexure assembly.
sample_meeting = {
    "meetingNo": "2", "academicYear": "2026-27", "semester": "Odd",
    "school": UNIT_SCHOOL, "department": f"Department of {UNIT_DEPT}",
    "schoolCode": UNIT_CODE, "departmentCode": UNIT_CODE,
    "previousMeetingNo": "1", "previousMeetingDate": "2026-06-30",
    "date": "2030-01-02", "startTime": "10:00", "endTime": "12:00",
    "venue": "Room 1", "mode": "Offline", "chairName": CHAIR_NAME, "chairEmail": CHAIR_EMAIL,
    "members": [
        {"name": CHAIR_NAME, "designation": "Chairperson", "role": "Chairperson", "present": True},
        {"name": EXT_NAME, "designation": "External Member", "role": "External Member", "present": False},
    ],
}
pdf = server.build_final_pdf({
    "status": "approved", "meeting": sample_meeting,
    "momItems": [
        {"id": "mom-1", "agendaId": "std-mom", "agendaNo": 1, "title": "Approval of previous MoM", "discussion": "The previous MoM was reviewed.", "resolution": "The previous MoM was approved.", "attachments": []},
        {"id": "mom-2", "agendaId": "std-curriculum", "agendaNo": 2, "title": "Review curriculum", "discussion": "The committee reviewed the curriculum.", "resolution": "The proposed changes were approved.", "attachments": []},
    ],
    "photos": [{"id": "photo-1", "caption": "Committee photo"}],
    "actionItems": [{"agendaNo": "2", "text": "Update the syllabus", "owner": "Member Secretary", "targetDate": "2030-02-01"}],
    "additionalDiscussions": [{"title": "Library access", "discussion": "Access hours were discussed.", "resolution": "The matter was noted."}],
})
reader = PdfReader(BytesIO(pdf))
assert len(reader.pages) >= 3
# Uniform page numbers across the whole document: "Page X of Y" on every page, Y == page count.
_pages = [page.extract_text() or "" for page in reader.pages]
assert all(f"Page {index} of {len(_pages)}" in " ".join(text.split()) for index, text in enumerate(_pages, start=1)), _pages
pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
for required_text in (
    "DAC · Minutes of Meeting",
    f"Ref No. PU/{UNIT_CODE}-{UNIT_CODE}/DAC-02/2026-27/Odd/MoM-02",
    "Members Present:", "Agenda DAC-2.1", "Discussion:", "Recommendations:",
    "Geo-Tagged Photos and Online Platform Screenshots", "Action Items:",
    "Person(s) Responsible", "Library access", "Member Secretary", "Chairperson",
):
    assert required_text in pdf_text, f"Missing document content: {required_text}"
assert "Alex Morgan" not in pdf_text, "Final attendance must not include an absent invitee."
# No annexure ATTACHED means no Annexure Index and no uploaded-file annexure pages —
# a signed minute must never point at a document that does not exist.
assert "Annexure Index" not in pdf_text, "Minutes must not index annexures that were never attached."

long_items = [{
    "id": f"long-{index}", "agendaId": f"custom-{index}", "agendaNo": index,
    "title": f"Expanded agenda item {index}", "discussion": ("Recorded committee discussion. " * 55),
    "resolution": ("The committee considered the recorded matter and recommended the next academic action. " * 20),
    "attachments": [],
} for index in range(1, 9)]
long_pdf = server.build_final_pdf({"status": "approved", "meeting": sample_meeting, "momItems": long_items,
                                  "photos": [], "actionItems": [], "additionalDiscussions": []})
assert len(PdfReader(BytesIO(long_pdf)).pages) > 4

frozen_title = "To consider the approval of the MoM of the 1st Departmental Academic Committee meeting held on 30.06.2026."
frozen_pdf = server.build_final_pdf({
    "status": "approved", "meeting": {**sample_meeting, "previousMeetingDate": "2026-07-30"},
    "momItems": [{"id": "mom-frozen", "agendaId": "std-mom", "agendaNo": 1, "title": frozen_title,
                  "discussion": "", "resolution": "", "attachments": []}],
    "photos": [], "actionItems": [], "additionalDiscussions": [],
})
frozen_text = " ".join(" ".join((page.extract_text() or "").split()) for page in PdfReader(BytesIO(frozen_pdf)).pages)
assert " ".join(frozen_title.split()) in frozen_text
assert "held on 30.07.2026" not in frozen_text

attachment_id = uuid4().hex
attachment_path = server.UPLOAD_DIR / f"{attachment_id}.png"
Image.new("RGB", (20, 12), color=(230, 230, 230)).save(attachment_path, format="PNG")
try:
    annexure_pdf = server.build_final_pdf({
        "status": "approved", "meeting": sample_meeting,
        "momItems": [{"id": "mom-annexure", "agendaId": "std-curriculum", "agendaNo": 1,
                      "title": "Review curriculum", "discussion": "", "resolution": "",
                      "attachments": [{"id": attachment_id, "name": "curriculum-reference.png", "size": 80, "type": "image/png"}]}],
        "photos": [], "actionItems": [], "additionalDiscussions": [],
    })
    annexure_reader = PdfReader(BytesIO(annexure_pdf))
    annexure_text = "\n".join(page.extract_text() or "" for page in annexure_reader.pages)
    assert len(annexure_reader.pages) >= 5
    _annexure_pages = [page.extract_text() or "" for page in annexure_reader.pages]
    _total = len(_annexure_pages)
    assert all(f"Page {i} of {_total}" in " ".join(text.split())
               for i, text in enumerate(_annexure_pages, start=1)), _annexure_pages
    assert "Annexure Index" in annexure_text
    assert "Encl: Annexures" in annexure_text, "A record with annexures must list them."
    assert "1.1" in annexure_text and "curriculum-reference.png" in annexure_text
finally:
    attachment_path.unlink(missing_ok=True)

# Word builder: same agenda content, Cambria house style, resolution wording.
docx_bytes = server.build_mom_docx({
    "status": "approved", "meeting": sample_meeting,
    "momItems": [
        {"id": "mom-1", "agendaId": "std-mom", "agendaNo": 1, "title": "Approval of previous MoM",
         "discussion": "The previous MoM was reviewed.", "resolution": "The previous MoM was approved.", "attachments": []},
    ],
    "photos": [], "actionItems": [], "additionalDiscussions": [],
})
docx_check = Document(BytesIO(docx_bytes))
texts = [paragraph.text.strip() for paragraph in docx_check.paragraphs]
assert "DAC Minutes of Meeting" in texts
assert "Resolution:" in texts and "Discussion:" in texts
assert any(text.startswith("Agenda No: 01") for text in texts)
assert "No separate resolution recorded." not in texts
no_resolution_docx = Document(BytesIO(server.build_mom_docx({
    "meeting": sample_meeting,
    "momItems": [{"id": "mom-x", "agendaId": "std-other", "agendaNo": 1, "title": "Any other matter",
                  "discussion": "Nothing further was discussed.", "noResolution": True, "resolution": "", "attachments": []}],
})))
no_resolution_texts = [paragraph.text.strip() for paragraph in no_resolution_docx.paragraphs]
assert "No separate resolution recorded." in no_resolution_texts

print("Self-test passed: allow-list/OTP, admin provisioning, role and owner scopes, CSRF, office approval, guest/file redaction, AND unlock gate, AI/offline content verification, resolution rename with legacy migration, Cambria 11/12 pt 1.15 style and consolidated PDF + Word export.")
