"""DAC units and their offices — who may chair, who may schedule, who observes.

A **DAC unit** is one Departmental Academic Committee:

* a department of a school that has departments (School of Engineering → 8 units,
  School of Artificial Intelligence and Advanced Computing → 3 units), or
* the school itself when the school has no departments (9 units).

For every unit the registry stores the three offices R1 names:

* **chairs**      — the Dean and the Head(s) of Department of that unit,
* **secretaries** — the Member Secretary (or Secretaries) of that DAC: only these
                    accounts may schedule a meeting for the unit,
* **externals**   — the External Member(s) of that DAC, with the designation R1 prints.

Where R1 prints a gap (School of Allied Health Care Professions has no Member
Secretary, School of Management has no HOD, three schools have no Dean) the list is
simply empty. Nothing is invented, and an administrator can add the missing person
later through ``POST /api/admin/dac/office``.

Storage is **append-only**: seeding this module runs ``INSERT OR IGNORE`` and there is
no code path anywhere in the project that deletes a unit, an office or an external
member. Upgrades re-seed, they never replace.
"""

from __future__ import annotations

import json
from typing import Any

import r1_registry

SOURCE = "R1"


# --------------------------------------------------------------------------- tables
def ensure_tables(db) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS dac_units (
        unit_id        TEXT PRIMARY KEY,
        school         TEXT NOT NULL,
        department     TEXT,
        code           TEXT NOT NULL DEFAULT '',
        programmes_json TEXT NOT NULL DEFAULT '[]',
        source         TEXT NOT NULL DEFAULT 'R1',
        created_at     TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS dac_office (
        unit_id   TEXT NOT NULL,
        role      TEXT NOT NULL,
        email     TEXT NOT NULL,
        source    TEXT NOT NULL DEFAULT 'R1',
        created_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (unit_id, role, email)
    );
    CREATE TABLE IF NOT EXISTS dac_external (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id      TEXT NOT NULL,
        name         TEXT NOT NULL DEFAULT '',
        designation  TEXT NOT NULL DEFAULT '',
        email        TEXT NOT NULL DEFAULT '',
        source       TEXT NOT NULL DEFAULT 'R1',
        created_at   TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_dac_office_email ON dac_office(email);
    CREATE INDEX IF NOT EXISTS idx_dac_external_unit ON dac_external(unit_id);
    """)


def _clean(value: str | None) -> str:
    return " ".join(str(value or "").split())


def norm(value: str | None) -> str:
    """Compare "School of Engineering" / "Engineering" and "Department of X" / "X" alike.

    Meetings store the names as they appear on the document ("Department of Civil
    Engineering") while the registry stores R1's own wording ("Civil Engineering"), so
    every comparison goes through this normaliser.
    """
    text = _clean(value).casefold()
    for prefix in ("school of ", "department of ", "dept. of ", "dept of "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def unit_id(school: str, department: str | None) -> str:
    """A stable id: ``SOE::Civil Engineering`` or ``SOCSE::`` for a school-level DAC."""
    return f"{_clean(school)}::{_clean(department or '')}"


# --------------------------------------------------------------------------- seeding
def seed(db, stamp: str) -> dict[str, int]:
    """Insert the R1 units, offices and external members. Idempotent and additive."""
    ensure_tables(db)
    counts = {"units": 0, "chairs": 0, "secretaries": 0, "externals": 0}

    def add_unit(school: str, department: str | None, code: str, programmes: list[str]) -> str:
        identifier = unit_id(school, department)
        db.execute("""INSERT OR IGNORE INTO dac_units(unit_id, school, department, code,
                        programmes_json, source, created_at) VALUES (?,?,?,?,?,?,?)""",
                   (identifier, _clean(school), _clean(department) or None, code or "",
                    json.dumps(programmes), SOURCE, stamp))
        counts["units"] += 1
        return identifier

    def add_office(identifier: str, role: str, email: str) -> None:
        if not email:
            return
        cur = db.execute("""INSERT OR IGNORE INTO dac_office(unit_id, role, email, source, created_at)
                            VALUES (?,?,?,?,?)""",
                         (identifier, role, email.lower(), SOURCE, stamp))
        if cur.rowcount:
            counts[role + "s" if role == "chair" else "secretaries"] += 1

    def add_external(identifier: str, person: dict) -> None:
        existing = db.execute("SELECT 1 FROM dac_external WHERE unit_id=? AND email=?",
                              (identifier, str(person["email"]).lower())).fetchone()
        if existing:
            return
        db.execute("""INSERT INTO dac_external(unit_id, name, designation, email, source, created_at)
                      VALUES (?,?,?,?,?,?)""",
                   (identifier, person["name"], person.get("designation", ""),
                    str(person["email"]).lower(), SOURCE, stamp))
        counts["externals"] += 1

    for school in r1_registry.R1_SCHOOLS:
        dean = school.get("dean")
        if school["departments"]:
            for department in school["departments"]:
                identifier = add_unit(school["name"], department["department"],
                                      department["code"], department["programmes"])
                if dean:
                    add_office(identifier, "chair", dean["email"])
                add_office(identifier, "chair", department["hod"]["email"])
                add_office(identifier, "secretary", department["memberSecretary"]["email"])
                for external in department["externalMembers"]:
                    add_external(identifier, external)
        else:
            level = school["schoolLevel"]
            identifier = add_unit(school["name"], None, level["code"], level["programmes"])
            if dean:
                add_office(identifier, "chair", dean["email"])
            for hod in level["hodCandidates"]:
                add_office(identifier, "chair", hod["email"])
            for secretary in level["secretaryCandidates"]:
                add_office(identifier, "secretary", secretary["email"])
            for external in level["externalMembers"]:
                add_external(identifier, external)
    db.commit()
    return counts


# --------------------------------------------------------------------------- reading
def _unit_row(db, school: str, department: str | None):
    target_school, target_department = norm(school), norm(department)
    for row in db.execute("SELECT * FROM dac_units").fetchall():
        if norm(row["school"]) == target_school and norm(row["department"]) == target_department:
            return row
    return None


def _office_match(db, table: str, email: str, school: str, department: str | None) -> bool:
    target_school, target_department = norm(school), norm(department)
    column = "email"
    for row in db.execute(f"""SELECT u.school, u.department FROM {table} o
                              JOIN dac_units u ON u.unit_id=o.unit_id
                              WHERE o.{column}=?""", (str(email or "").lower(),)):
        if norm(row["school"]) == target_school and norm(row["department"]) == target_department:
            return True
    return False


def all_units(db) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM dac_units ORDER BY school COLLATE NOCASE, department COLLATE NOCASE").fetchall()
    return [_unit_payload(db, row) for row in rows]


def unit_for(db, school: str, department: str | None) -> dict[str, Any] | None:
    row = _unit_row(db, school, department)
    if row is None:
        # Fall back to the school-level unit when a department is not part of the DAC.
        target = norm(school)
        row = next((candidate for candidate in db.execute("SELECT * FROM dac_units").fetchall()
                    if norm(candidate["school"]) == target and not _clean(candidate["department"])), None)
    return _unit_payload(db, row) if row else None


def _unit_payload(db, row) -> dict[str, Any]:
    try:
        programmes = json.loads(row["programmes_json"] or "[]")
    except json.JSONDecodeError:
        programmes = []
    chairs = [r["email"] for r in db.execute(
        "SELECT email FROM dac_office WHERE unit_id=? AND role='chair' ORDER BY rowid", (row["unit_id"],))]
    secretaries = [r["email"] for r in db.execute(
        "SELECT email FROM dac_office WHERE unit_id=? AND role='secretary' ORDER BY rowid", (row["unit_id"],))]
    externals = [dict(r) for r in db.execute(
        "SELECT name, designation, email, source FROM dac_external WHERE unit_id=? ORDER BY id",
        (row["unit_id"],))]
    return {"unitId": row["unit_id"], "school": row["school"], "department": row["department"] or "",
            "code": row["code"], "programmes": programmes, "chairs": chairs,
            "secretaries": secretaries, "externals": externals,
            "schoolLevel": not bool(row["department"])}


def units_for_secretary(db, email: str) -> list[dict[str, Any]]:
    rows = db.execute("""SELECT u.* FROM dac_units u JOIN dac_office o ON o.unit_id=u.unit_id
                         WHERE o.role='secretary' AND o.email=? ORDER BY u.school, u.department""",
                      (str(email or "").lower(),)).fetchall()
    return [_unit_payload(db, row) for row in rows]


def units_for_chair(db, email: str) -> list[dict[str, Any]]:
    rows = db.execute("""SELECT u.* FROM dac_units u JOIN dac_office o ON o.unit_id=u.unit_id
                         WHERE o.role='chair' AND o.email=? ORDER BY u.school, u.department""",
                      (str(email or "").lower(),)).fetchall()
    return [_unit_payload(db, row) for row in rows]


def units_for_external(db, email: str) -> list[dict[str, Any]]:
    rows = db.execute("""SELECT u.* FROM dac_units u JOIN dac_external e ON e.unit_id=u.unit_id
                         WHERE e.email=? ORDER BY u.school, u.department""",
                      (str(email or "").lower(),)).fetchall()
    return [_unit_payload(db, row) for row in rows]


def is_secretary(db, email: str, school: str, department: str | None) -> bool:
    target_school, target_department = norm(school), norm(department)
    for row in db.execute("""SELECT u.school, u.department FROM dac_office o
                             JOIN dac_units u ON u.unit_id=o.unit_id
                             WHERE o.role='secretary' AND o.email=?""", (str(email or "").lower(),)):
        if norm(row["school"]) == target_school and norm(row["department"]) == target_department:
            return True
    return False


def may_chair(db, email: str, school: str, department: str | None) -> bool:
    target_school, target_department = norm(school), norm(department)
    for row in db.execute("""SELECT u.school, u.department FROM dac_office o
                             JOIN dac_units u ON u.unit_id=o.unit_id
                             WHERE o.role='chair' AND o.email=?""", (str(email or "").lower(),)):
        if norm(row["school"]) == target_school and norm(row["department"]) == target_department:
            return True
    return False


def external_for(db, email: str, school: str, department: str | None) -> bool:
    target_school, target_department = norm(school), norm(department)
    for row in db.execute("""SELECT u.school, u.department FROM dac_external e
                             JOIN dac_units u ON u.unit_id=e.unit_id
                             WHERE e.email=?""", (str(email or "").lower(),)):
        if norm(row["school"]) == target_school and norm(row["department"]) == target_department:
            return True
    return False


# --------------------------------------------------------------------------- writing
def add_office(db, school: str, department: str | None, role: str, email: str, stamp: str,
               source: str = "admin") -> bool:
    """Give one account an office on a unit (used to fill R1's gaps later)."""
    if role not in {"chair", "secretary"}:
        raise ValueError("role must be chair or secretary")
    row = _unit_row(db, school, department)
    if row is None:
        raise ValueError("Unknown DAC unit.")
    identifier = row["unit_id"]
    cur = db.execute("""INSERT OR IGNORE INTO dac_office(unit_id, role, email, source, created_at)
                        VALUES (?,?,?,?,?)""", (identifier, role, str(email).lower(), source, stamp))
    db.commit()
    return bool(cur.rowcount)


def remove_office(db, school: str, department: str | None, role: str, email: str) -> bool:
    """Only an office added by an administrator can be withdrawn; R1 offices are fixed."""
    row = _unit_row(db, school, department)
    if row is None:
        return False
    identifier = row["unit_id"]
    cur = db.execute("""DELETE FROM dac_office WHERE unit_id=? AND role=? AND email=? AND source<>'R1'""",
                     (identifier, role, str(email).lower()))
    db.commit()
    return bool(cur.rowcount)


def add_external(db, school: str, department: str | None, name: str, designation: str,
                 email: str, stamp: str, source: str = "admin") -> dict[str, Any]:
    row = _unit_row(db, school, department)
    if row is None:
        raise ValueError("Unknown DAC unit.")
    identifier = row["unit_id"]
    db.execute("""INSERT INTO dac_external(unit_id, name, designation, email, source, created_at)
                  VALUES (?,?,?,?,?,?)""",
               (identifier, _clean(name), _clean(designation), str(email).lower(), source, stamp))
    db.commit()
    return {"name": _clean(name), "designation": _clean(designation), "email": str(email).lower(),
            "source": source}


def summary() -> dict[str, int]:
    return {"schools": len(r1_registry.R1_SCHOOLS), "units": len(r1_registry.dacs()),
            "people": len(r1_registry.all_people())}


if __name__ == "__main__":
    print(json.dumps(summary(), indent=2))
