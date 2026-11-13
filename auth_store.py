"""SQLite-backed identity directory, academic catalog and shared meeting workspace."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import r1_registry

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("DAC_DATABASE_PATH", DATA_DIR / "dac-minutes.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

ROLES = {"system_admin", "academic_office", "faculty", "external_member"}
#: The academic catalog is R1's own structure, one entry per school, listing that
#: school's departments — empty when R1 gives the school no department (in which case the
#: DAC is school-level and the interface hides the department field).
SCHOOLS: dict[str, list[str]] = {school["name"]: [department["department"]
                                                   for department in school["departments"]]
                                 for school in r1_registry.R1_SCHOOLS}

#: Programmes per school (school-level DACs) or per department, straight from R1.
SCHOOL_CODES: dict[str, str] = {school["name"]: school["code"] for school in r1_registry.R1_SCHOOLS}
PROGRAMMES: dict[str, dict[str, list[str]]] = {
    school["name"]: (
        {department["department"]: department["programmes"] for department in school["departments"]}
        if school["departments"] else {"": school["schoolLevel"]["programmes"]}
    ) for school in r1_registry.R1_SCHOOLS
}

DEPARTMENT_CODES: dict[str, str] = {
    department["department"]: department["code"]
    for school in r1_registry.R1_SCHOOLS for department in school["departments"]
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def init_db() -> None:
    with connect() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL REFERENCES schools(id),
            name TEXT NOT NULL COLLATE NOCASE,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(school_id, name)
        );
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            full_name TEXT NOT NULL,
            designation TEXT NOT NULL DEFAULT '',
            employee_code TEXT NOT NULL DEFAULT '',
            qualification TEXT NOT NULL DEFAULT '',
            specialization TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            office TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL CHECK(role IN ('system_admin','academic_office','faculty','external_member')),
            school_id INTEGER REFERENCES schools(id),
            department_id INTEGER REFERENCES departments(id),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS api_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE,
            csrf TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at REAL NOT NULL,
            last_used TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);
        CREATE TABLE IF NOT EXISTS login_codes (
            email TEXT PRIMARY KEY COLLATE NOCASE,
            code_hash TEXT NOT NULL,
            expires_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            requested_at REAL NOT NULL,
            source_ip TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES users(id),
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_workspaces_owner ON workspaces(owner_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_workspaces_status ON workspaces(status, updated_at DESC);
        CREATE TABLE IF NOT EXISTS uploads (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES users(id),
            filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            size INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        for school_name, departments in SCHOOLS.items():
            db.execute("INSERT OR IGNORE INTO schools(name) VALUES (?)", (school_name,))
            school_id = db.execute("SELECT id FROM schools WHERE name = ?", (school_name,)).fetchone()["id"]
            for department in departments:
                db.execute("INSERT OR IGNORE INTO departments(school_id, name) VALUES (?, ?)", (school_id, department))
        _migrate_users_profile(db)
        db.commit()
        # Seed the college roster only for a non-production database; never provision
        # fixture identities into a production database.
        if os.environ.get("APP_ENV", "development").strip().lower() != "production":
            _seed_users(db)
        # The DAC registry (who chairs, who may schedule, who observes) is seeded on
        # every start and is append-only: R1 entries are never replaced or deleted.
        import dac_registry
        dac_registry.seed(db, now_iso())


PROFILE_COLUMNS = ("designation", "employee_code", "qualification", "specialization", "phone", "office")


def _migrate_users_profile(db: sqlite3.Connection) -> None:
    """Add the directory/profile columns to a database created before they existed.

    Existing databases keep working: each column is added empty and the seed
    pass below backfills the campus directory details.
    """
    columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    for column in PROFILE_COLUMNS:
        if column not in columns:
            db.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")


def _school_department_ids(db: sqlite3.Connection, school: str | None, department: str | None) -> tuple[int | None, int | None]:
    if not school:
        return None, None
    row = db.execute("SELECT id FROM schools WHERE name = ? AND active = 1", (school,)).fetchone()
    if not row:
        raise ValueError("Choose a valid school from the academic catalog.")
    school_id = int(row["id"])
    if not department:
        return school_id, None
    dept = db.execute("SELECT id FROM departments WHERE school_id = ? AND name = ? AND active = 1", (school_id, department)).fetchone()
    if not dept:
        raise ValueError("Choose a department that belongs to the selected school.")
    return school_id, int(dept["id"])


def _seed_users(db: sqlite3.Connection) -> None:
    for entry in SEEDED_DIRECTORY:
        email = str(entry["email"]).lower()
        school_id, department_id = _school_department_ids(db, entry.get("school"), entry.get("department"))
        stamp = now_iso()
        db.execute(
            """INSERT OR IGNORE INTO users(id,email,full_name,designation,employee_code,qualification,
                   specialization,phone,office,role,school_id,department_id,active,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (uuid.uuid4().hex, email, entry["name"], entry["designation"], entry["employeeCode"],
             entry["qualification"], entry["specialization"], entry["phone"], entry["office"],
             entry["role"], school_id, department_id, stamp, stamp),
        )
        # External members are faculty of the school they represent, so the "different
        # school" rule and the school-grouped document vault both have real data.
        if entry["role"] == "external_member" and entry.get("school"):
            db.execute("""UPDATE users SET school_id=?, department_id=?
                          WHERE email=? AND (school_id IS NULL OR department_id IS NULL)""",
                       (school_id, department_id, email))
        # Backfill profile details on directories seeded before these fields existed.
        db.execute("""UPDATE users SET full_name=?, designation=?, employee_code=?, qualification=?,
                         specialization=?, phone=?, office=?
                      WHERE email=? AND (designation='' OR employee_code='' OR qualification='')""",
                   (entry["name"], entry["designation"], entry["employeeCode"], entry["qualification"],
                    entry["specialization"], entry["phone"], entry["office"], email))
    db.commit()


#: R1's own people are the access directory. The list is generated from
#: ``r1_registry`` at import time, so it is a constant of the program: the seeder only
#: ever runs ``INSERT OR IGNORE`` and no code path deletes an account. Every future
#: upgrade re-creates these people instead of replacing them.
_OFFICE_ACCOUNTS: list[dict[str, str | None]] = [
    {"email": "admin@presidencyuniversity.in", "name": "System Administrator",
     "role": "system_admin", "school": None, "department": None,
     "designation": "System Administrator (IT Services)", "employeeCode": "PU-ADM-1001",
     "qualification": "M.Sc. (Computer Science)", "specialization": "ERP, access control",
     "phone": "", "office": "Administration Block"},
    {"email": "academic.office@presidencyuniversity.in", "name": "Academic Office Reviewer",
     "role": "academic_office", "school": None, "department": None,
     "designation": "Deputy Registrar, Academic Office", "employeeCode": "PU-ADM-2001",
     "qualification": "M.A. (Public Administration)", "specialization": "Academic governance",
     "phone": "", "office": "Academic Office"},
    {"email": "academic.office2@presidencyuniversity.in",
     "name": "Academic Office Reviewer (Backup)", "role": "academic_office",
     "school": None, "department": None, "designation": "Assistant Registrar, Academic Office",
     "employeeCode": "PU-ADM-2002", "qualification": "MBA (Higher Education)",
     "specialization": "Examination records", "phone": "", "office": "Academic Office"},
]

#: Abbreviations R1 uses in the "Faculty Member from other department" column.
_SCHOOL_BY_ABBREVIATION = {
    "soe": "School of Engineering",
    "psaiac": "School of Artificial Intelligence and Advanced Computing",
    "pscse": "School of Computer Science and Engineering",
    "psocse": "School of Computer Science and Engineering",
    "socse": "School of Computer Science and Engineering",
    "csese": "School of Computer Science and Engineering",
    "sois": "School of Information Science",
    "sod": "School of Design",
    "som": "School of Management",
    "soc": "School of Commerce",
    "psoc": "School of Commerce",
    "psoe": "School of Engineering",
}
_DEPARTMENT_BY_ABBREVIATION = {
    "ece": "Electronics and Communication Engineering",
    "civil": "Civil Engineering",
    "mechanical": "Mechanical Engineering",
    "eee": "Electrical and Electronics Engineering",
    "petroleum": "Petroleum Engineering",
    "mathematics": "Mathematics",
}


def _known_departments() -> list[str]:
    """Every department R1 gives, longest first so "Civil Engineering" wins over "Civil"."""
    names = {department
             for school in r1_registry.school_names()
             for department in r1_registry.departments_of(school)}
    return sorted(names, key=len, reverse=True)


def _department_from_designation(text: str) -> str:
    """The department named inside R1's designation text, e.g. "Professor, Mathematics, SoE"."""
    lowered = str(text or "").casefold()
    for name in _known_departments():
        if name.casefold() in lowered:
            return name
    match = re.search(r"Dept\.? of ([A-Za-z]+)", text)
    if match:
        return _DEPARTMENT_BY_ABBREVIATION.get(match.group(1).lower(), "")
    return ""


def _school_from_designation(designation: str) -> tuple[str, str]:
    """The external member's own school/department, read from R1's designation text."""
    text = str(designation or "")
    school = ""
    for token in re.findall(r"[A-Za-z]+", text):
        resolved = _SCHOOL_BY_ABBREVIATION.get(token.lower())
        if resolved:
            school = resolved
    return school, _department_from_designation(text)


def _seeded_directory() -> list[dict[str, str | None]]:
    accounts = [dict(account) for account in _OFFICE_ACCOUNTS]
    for email, record in sorted(r1_registry.all_people().items(), key=lambda item: item[1]["name"]):
        school = record.get("school") or ""
        department = record.get("department") or ""
        holds_office = any(role.startswith(("Dean", "HOD", "MemberSecretary"))
                           for role in record["roles"])
        if not holds_office:
            # An external member serves a *different* school from the DAC that invites
            # them, so their own school comes from R1's designation text, never from the
            # DAC they sit on.
            derived_school, derived_department = _school_from_designation(record["designation"])
            school = derived_school
            department = derived_department
        accounts.append({
            "email": email,
            "name": record["name"],
            "role": "faculty",
            "school": school or None,
            "department": department or None,
            "designation": record["designation"],
            "employeeCode": "",
            "qualification": "",
            "specialization": ", ".join(record["roles"]),
            "phone": "",
            "office": "",
        })
    return accounts


SEEDED_DIRECTORY: list[dict[str, str | None]] = _seeded_directory()


def _clean_text(value: Any) -> str:
    """Collapse whitespace and cap length for one directory text field."""
    return " ".join(str(value or "").split())[:120]


def _normalise_profile(values: dict[str, Any]) -> dict[str, str]:
    """Trim a professor's directory details to plain text (never None, never nested)."""
    return {key: _clean_text(values.get(key))
            for key in ("employeeCode", "qualification", "specialization", "phone", "office")}


def _user_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "email": row["email"], "name": row["full_name"],
        "designation": row["designation"] if "designation" in row.keys() else "",
        "employeeCode": row["employee_code"] if "employee_code" in row.keys() else "",
        "qualification": row["qualification"] if "qualification" in row.keys() else "",
        "specialization": row["specialization"] if "specialization" in row.keys() else "",
        "phone": row["phone"] if "phone" in row.keys() else "",
        "office": row["office"] if "office" in row.keys() else "",
        "role": row["role"], "active": bool(row["active"]),
        "schoolId": row["school_id"], "school": row["school_name"],
        "departmentId": row["department_id"], "department": row["department_name"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


#: One statement serves both lookups: the active filter is a bound parameter rather than
#: a string concatenated into the WHERE clause.
USER_BY_EMAIL = """SELECT u.*, s.name AS school_name, d.name AS department_name
    FROM users u LEFT JOIN schools s ON s.id=u.school_id
    LEFT JOIN departments d ON d.id=u.department_id
    WHERE u.email = ? AND (? = 0 OR u.active = 1)"""

USER_BY_ID = """SELECT u.*, s.name AS school_name, d.name AS department_name
    FROM users u LEFT JOIN schools s ON s.id=u.school_id
    LEFT JOIN departments d ON d.id=u.department_id
    WHERE u.id = ? AND (? = 0 OR u.active = 1)"""


def get_user_by_email(email: str, active_only: bool = False) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(USER_BY_EMAIL, (email.strip().lower(), int(bool(active_only)))).fetchone()
    return _user_dict(row) if row else None


def get_user_by_id(user_id: str, active_only: bool = True) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(USER_BY_ID, (user_id, int(bool(active_only)))).fetchone()
    return _user_dict(row) if row else None


def list_users() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("""SELECT u.*, s.name AS school_name, d.name AS department_name
            FROM users u LEFT JOIN schools s ON s.id=u.school_id
            LEFT JOIN departments d ON d.id=u.department_id
            ORDER BY CASE u.role WHEN 'system_admin' THEN 0 WHEN 'academic_office' THEN 1 WHEN 'faculty' THEN 2 ELSE 3 END,
                     u.full_name COLLATE NOCASE""").fetchall()
    return [_user_dict(row) for row in rows]


def add_user(email: str, name: str, role: str, school: str | None = None, department: str | None = None,
             designation: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    email = email.strip().lower()
    name = name.strip()
    if role not in ROLES:
        raise ValueError("Choose a valid application role.")
    if role == "faculty" and (not school or not department):
        raise ValueError("Faculty accounts must be assigned a school and department.")
    if role in {"system_admin", "academic_office", "external_member"}:
        school = school or None
        department = department or None
    details = _normalise_profile(profile or {})
    with connect() as db:
        school_id, department_id = _school_department_ids(db, school, department)
        stamp = now_iso()
        user_id = uuid.uuid4().hex
        db.execute("""INSERT INTO users(id,email,full_name,designation,employee_code,qualification,specialization,
                      phone,office,role,school_id,department_id,active,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                   (user_id, email, _clean_text(name), _clean_text(designation), details["employeeCode"],
                    details["qualification"], details["specialization"], details["phone"], details["office"],
                    role, school_id, department_id, stamp, stamp))
        db.commit()
    result = get_user_by_id(user_id)
    assert result is not None
    return result


def update_user(user_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"name", "role", "school", "department", "active",
               "designation", "employeeCode", "qualification", "specialization", "phone", "office"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError("Unsupported user fields: " + ", ".join(sorted(unknown)))
    with connect() as db:
        current = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not current:
            return None
        role = str(changes.get("role", current["role"]))
        if role not in ROLES:
            raise ValueError("Choose a valid application role.")
        name = str(changes.get("name", current["full_name"])).strip()
        if not name:
            raise ValueError("Name cannot be blank.")
        school = changes.get("school")
        if "school" not in changes and current["school_id"]:
            school = db.execute("SELECT name FROM schools WHERE id = ?", (current["school_id"],)).fetchone()["name"]
        department = changes.get("department")
        if "department" not in changes and current["department_id"]:
            department = db.execute("SELECT name FROM departments WHERE id = ?", (current["department_id"],)).fetchone()["name"]
        if role == "faculty" and (not school or not department):
            raise ValueError("Faculty accounts must be assigned a school and department.")
        if role != "faculty" and not school:
            school = None
            department = None
        school_id, department_id = _school_department_ids(db, school, department)
        active = int(bool(changes.get("active", current["active"])))
        designation = _clean_text(changes.get("designation", current["designation"] if "designation" in current.keys() else ""))
        profile = _normalise_profile({key: changes.get(key, current[column] if column in current.keys() else "")
                                      for key, column in (("employeeCode", "employee_code"), ("qualification", "qualification"),
                                                          ("specialization", "specialization"), ("phone", "phone"),
                                                          ("office", "office"))})
        db.execute("""UPDATE users SET full_name=?, designation=?, employee_code=?, qualification=?, specialization=?,
                      phone=?, office=?, role=?, school_id=?, department_id=?, active=?, updated_at=? WHERE id=?""",
                   (name, designation, profile["employeeCode"], profile["qualification"], profile["specialization"],
                    profile["phone"], profile["office"], role, school_id, department_id, active, now_iso(), user_id))
        db.commit()
    return get_user_by_id(user_id, active_only=False)


def get_catalog() -> dict[str, Any]:
    with connect() as db:
        rows = db.execute("""SELECT s.id AS school_id, s.name AS school_name, d.id AS department_id, d.name AS department_name
            FROM schools s LEFT JOIN departments d ON d.school_id=s.id AND d.active=1
            WHERE s.active=1 ORDER BY s.name COLLATE NOCASE, d.name COLLATE NOCASE""").fetchall()
    catalog: dict[int, dict[str, Any]] = {}
    for row in rows:
        entry = catalog.setdefault(row["school_id"], {"id": row["school_id"], "name": row["school_name"], "departments": []})
        if row["department_id"] is not None:
            entry["departments"].append({"id": row["department_id"], "name": row["department_name"]})
    for entry in catalog.values():
        entry["code"] = SCHOOL_CODES.get(entry["name"], "")
        entry["hasDepartments"] = bool(entry["departments"])
        per_department = PROGRAMMES.get(entry["name"], {})
        entry["programmes"] = per_department.get("", []) if not entry["departments"] else []
        for department in entry["departments"]:
            department["programmes"] = per_department.get(department["name"], [])
    return {"schools": list(catalog.values())}


def get_workspace(workspace_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except json.JSONDecodeError:
        payload = {}
    return {"workspaceId": row["workspace_id"], "ownerId": row["owner_id"], "status": row["status"],
            "payload": payload, "createdAt": row["created_at"], "updatedAt": row["updated_at"]}


def workspace_for_owner(owner_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT workspace_id FROM workspaces WHERE owner_id=? ORDER BY updated_at DESC LIMIT 1", (owner_id,)).fetchone()
    return get_workspace(row["workspace_id"]) if row else None


def latest_pending_workspace() -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT workspace_id FROM workspaces WHERE status='pending' ORDER BY updated_at ASC LIMIT 1").fetchone()
    return get_workspace(row["workspace_id"]) if row else None


def list_workspaces_for_owner(owner_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT workspace_id,status,updated_at,payload_json FROM workspaces WHERE owner_id=? ORDER BY updated_at DESC", (owner_id,)).fetchall()
        results = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                payload = {}
            meeting = payload.get("meeting") or {}
            results.append({"workspaceId": row["workspace_id"], "status": row["status"], "updatedAt": row["updated_at"],
                "meetingNo": meeting.get("meetingNo"), "school": meeting.get("school"),
                "department": meeting.get("department"), "date": meeting.get("date")})
    return results


def list_pending_workspaces(include_chairperson: bool = False) -> list[dict[str, Any]]:
    """Requests awaiting a decision. ``include_chairperson`` also returns those with the Chairperson."""
    with connect() as db:
        rows = db.execute(
            """SELECT w.workspace_id,w.owner_id,w.status,w.updated_at,
                      u.full_name AS owner_name,u.email AS owner_email
               FROM workspaces w JOIN users u ON u.id=w.owner_id
               WHERE w.status = 'pending' OR (? = 1 AND w.status = 'pending_chairperson')
               ORDER BY w.created_at ASC""",
            (int(bool(include_chairperson)),)).fetchall()
        results = []
        for row in rows:
            try:
                payload = json.loads(db.execute("SELECT payload_json FROM workspaces WHERE workspace_id=?", (row["workspace_id"],)).fetchone()["payload_json"])
            except (json.JSONDecodeError, TypeError):
                payload = {}
            meeting = payload.get("meeting") or {}
            results.append({"workspaceId": row["workspace_id"], "status": row["status"], "updatedAt": row["updated_at"],
                "ownerName": row["owner_name"], "ownerEmail": row["owner_email"],
                "meetingNo": meeting.get("meetingNo"), "school": meeting.get("school"),
                "department": meeting.get("department"), "date": meeting.get("date")})
    return results


def save_workspace(workspace_id: str, owner_id: str, payload: dict[str, Any], status: str | None = None) -> None:
    stamp = now_iso()
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with connect() as db:
        existing = db.execute("SELECT owner_id,created_at FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()
        if existing:
            if existing["owner_id"] != owner_id:
                raise PermissionError("This workspace belongs to another account.")
            db.execute("UPDATE workspaces SET status=?,payload_json=?,updated_at=? WHERE workspace_id=?",
                       (status or payload.get("status", "draft"), data, stamp, workspace_id))
        else:
            db.execute("INSERT INTO workspaces(workspace_id,owner_id,status,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                       (workspace_id, owner_id, status or payload.get("status", "draft"), data, stamp, stamp))
        db.commit()


def owner_for_workspace(workspace_id: str) -> str | None:
    with connect() as db:
        row = db.execute("SELECT owner_id FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()
    return row["owner_id"] if row else None


def create_upload_record(file_id: str, owner_id: str, filename: str, extension: str, size: int) -> None:
    with connect() as db:
        db.execute("INSERT INTO uploads(id,owner_id,filename,extension,size,created_at) VALUES(?,?,?,?,?,?)",
                   (file_id, owner_id, filename, extension, size, now_iso()))
        db.commit()


def get_upload_record(file_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM uploads WHERE id=?", (file_id,)).fetchone()
    return dict(row) if row else None


def store_login_code(email: str, code_hash: str, expires_at: float, now_ts: float, source_ip: str) -> None:
    with connect() as db:
        row = db.execute("SELECT requested_at FROM login_codes WHERE email=?", (email,)).fetchone()
        if row and now_ts - float(row["requested_at"]) < 20:
            raise TimeoutError("Wait a few seconds before requesting another sign-in code.")
        db.execute("INSERT INTO login_codes(email,code_hash,expires_at,attempts,requested_at,source_ip) VALUES(?,?,?,0,?,?) "
                   "ON CONFLICT(email) DO UPDATE SET code_hash=excluded.code_hash,expires_at=excluded.expires_at,attempts=0,requested_at=excluded.requested_at,source_ip=excluded.source_ip",
                   (email, code_hash, expires_at, now_ts, source_ip))
        db.commit()


def verify_login_code(email: str, code_hash: str, now_ts: float) -> bool:
    with connect() as db:
        row = db.execute("SELECT * FROM login_codes WHERE email=?", (email,)).fetchone()
        if not row or float(row["expires_at"]) < now_ts or int(row["attempts"]) >= 5:
            db.execute("DELETE FROM login_codes WHERE email=?", (email,))
            db.commit()
            return False
        if not hmac.compare_digest(str(row["code_hash"]), code_hash):
            db.execute("UPDATE login_codes SET attempts=attempts+1 WHERE email=?", (email,))
            db.commit()
            return False
        db.execute("DELETE FROM login_codes WHERE email=?", (email,))
        db.commit()
        return True


def count_active_admins() -> int:
    with connect() as db:
        return int(db.execute("SELECT COUNT(*) FROM users WHERE role='system_admin' AND active=1").fetchone()[0])


def workspace_access_for_email(workspace_id: str, email: str) -> bool:
    workspace = get_workspace(workspace_id)
    if not workspace or workspace["status"] != "approved":
        return False
    members = (workspace["payload"].get("meeting") or {}).get("members") or []
    return any(member.get("role") == "External Member" and str(member.get("email", "")).strip().lower() == email.lower() for member in members)


#: The two offices that may chair a Departmental Academic Committee meeting.
CHAIRPERSON_MARKERS = ("dean", "head", "hod")


def is_eligible_chairperson(user: dict[str, Any] | None) -> bool:
    """A Chairperson is the Dean or a Head of Department of the meeting's school."""
    if not user or user.get("role") != "faculty" or not user.get("active", True):
        return False
    designation = str(user.get("designation") or "").lower()
    return any(marker in designation for marker in CHAIRPERSON_MARKERS)


def _clean_school(value: str | None) -> str:
    """Compare "School of Engineering" and "Engineering" as the same school."""
    text = str(value or "").strip().casefold()
    return text[len("school of "):] if text.startswith("school of ") else text


def chairperson_candidates(school: str | None = None) -> list[dict[str, Any]]:
    """Active Deans and Heads of Department, optionally limited to one school."""
    people = [user for user in list_users() if is_eligible_chairperson(user)]
    if school:
        people = [user for user in people if _clean_school(user.get("school")) == _clean_school(school)]
    return sorted(people, key=lambda user: (str(user.get("school") or ""), str(user.get("name") or "")))


# --------------------------------------------------------------------------- sessions
#: A cookie session is the normal mechanism, but it cannot work everywhere: a browser
#: that renders the app inside a sandboxed iframe (an opaque origin) is refused access to
#: `document.cookie`, so the session is never stored and every API call answers 401.
#: The sign-in endpoint therefore also issues an opaque bearer token, stored hashed on
#: this server, which the interface sends as `Authorization: Bearer …`. The cookie flow is
#: unchanged and still used wherever cookies work.
TOKEN_LIFETIME_SECONDS = 8 * 60 * 60


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def create_api_token(user: dict[str, Any], csrf: str | None = None) -> dict[str, Any]:
    """Issue a bearer token for a signed-in account. Only the hash is stored.

    ``csrf`` must be the CSRF token the browser was already given for this sign-in.
    Issuing a *second, different* value would break every write: the interface sends the
    value from its sign-in response, while the bearer session would expect its own.
    """
    token = secrets.token_urlsafe(32)
    csrf = str(csrf or "").strip() or secrets.token_urlsafe(32)
    now = time.time()
    with connect() as db:
        db.execute("""INSERT INTO api_tokens(token_hash, user_id, email, csrf, created_at, expires_at, last_used)
                      VALUES(?,?,?,?,?,?,NULL)""",
                   (_token_hash(token), str(user["id"]), str(user["email"]).lower(), csrf,
                    now_iso(), now + TOKEN_LIFETIME_SECONDS))
        # A token that has expired is dead weight; keep the table small.
        db.execute("DELETE FROM api_tokens WHERE expires_at < ?", (now,))
        db.commit()
    return {"token": token, "csrf": csrf, "expiresAt": now + TOKEN_LIFETIME_SECONDS}


def resolve_api_token(token: str) -> dict[str, Any] | None:
    """The account behind a bearer token, or None when it is unknown or expired."""
    if not token:
        return None
    digest = _token_hash(token)
    with connect() as db:
        row = db.execute("SELECT * FROM api_tokens WHERE token_hash = ?", (digest,)).fetchone()
        if not row:
            return None
        if float(row["expires_at"]) < time.time():
            db.execute("DELETE FROM api_tokens WHERE token_hash = ?", (digest,))
            db.commit()
            return None
        db.execute("UPDATE api_tokens SET last_used = ? WHERE token_hash = ?", (now_iso(), digest))
        db.commit()
    return {"userId": row["user_id"], "email": row["email"], "csrf": row["csrf"],
            "expiresAt": float(row["expires_at"])}


def revoke_api_token(token: str) -> None:
    if not token:
        return
    with connect() as db:
        db.execute("DELETE FROM api_tokens WHERE token_hash = ?", (_token_hash(token),))
        db.commit()


def revoke_user_tokens(user_id: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM api_tokens WHERE user_id = ?", (str(user_id),))
        db.commit()
