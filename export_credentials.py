"""Export the seeded roster — every account, with its full professor details.

Writes two files that are meant to be **permanent**:

* ``PROFESSOR-CREDENTIALS.md``  — the human-readable sign-in sheet
* ``professor-credentials.csv`` — the same rows for Excel / a mail merge

The accounts come from the database, which is re-seeded from ``auth_store.SEEDED_DIRECTORY``
on every start-up (``INSERT OR IGNORE``), so re-running this script always lists the
same roster even if somebody deletes a row by accident.

Run:  cd DAC-MOM && ./.venv/bin/python export_credentials.py
"""

from __future__ import annotations

import csv
import pathlib
from datetime import datetime

import auth_store
from signatures import signature_for_email

ROOT = pathlib.Path(__file__).resolve().parent


def _sample(role: str) -> str:
    """The first active account of a role, so the sheet never names a retired person."""
    for person in auth_store.list_users():
        if person.get("role") == role and person.get("active", True):
            return person["email"]
    return "(none provisioned)"


def _r1_cast() -> tuple[str, str, str]:
    """R1's own Member Secretary / Chairperson / External Member for the example row."""
    import r1_registry
    unit = next(dac for dac in r1_registry.dacs()
                if dac.get("department") and dac.get("memberSecretary") and dac.get("externalMembers"))
    return (unit["memberSecretary"]["email"], unit["hod"]["email"],
            unit["externalMembers"][0]["email"])


_member_secretary, _chairperson, _external = _r1_cast()
#: The sheet ships inside the project so it is always found next to the code.
DOCS_DIR = ROOT / "DOCS"
DOCS_DIR.mkdir(exist_ok=True)
MD_PATH = DOCS_DIR / "CREDENTIALS.md"
CSV_PATH = DOCS_DIR / "professor-credentials.csv"

ROLE_LABEL = {
    "system_admin": "System Administrator",
    "academic_office": "Academic Office",
    "faculty": "Faculty",
    "external_member": "External Member",
}
ROLE_ORDER = {"system_admin": 0, "academic_office": 1, "faculty": 2, "external_member": 3}
SCHOOL_ORDER = ["Computer Engineering", "Engineering", "Information Science", "Commerce",
                "Arts", "Design", "Health Care", "Science"]


def rows() -> list[dict]:
    auth_store.init_db()
    out = []
    for person in auth_store.list_users():
        signature = signature_for_email(person["email"])
        out.append({
            "role": person["role"],
            "roleLabel": ROLE_LABEL.get(person["role"], person["role"]),
            "name": person["name"],
            "email": person["email"],
            "designation": person.get("designation") or "",
            "school": person.get("school") or "",
            "department": person.get("department") or "",
            "employeeCode": person.get("employeeCode") or "",
            "qualification": person.get("qualification") or "",
            "specialization": person.get("specialization") or "",
            "phone": person.get("phone") or "",
            "office": person.get("office") or "",
            "chairperson": "yes" if auth_store.is_eligible_chairperson(person) else "",
            "active": "yes" if person.get("active", True) else "no",
            "signedIn": "yes" if signature else "",
        })
    out.sort(key=lambda r: (ROLE_ORDER.get(r["role"], 9),
                            SCHOOL_ORDER.index(r["school"]) if r["school"] in SCHOOL_ORDER else 99,
                            r["school"], r["department"], r["name"]))
    return out


def main() -> None:
    people = rows()
    faculty = [p for p in people if p["role"] == "faculty"]
    chairs = [p for p in people if p["chairperson"] == "yes"]
    office = [p for p in people if p["role"] == "academic_office"]
    externals = [p for p in people if p["role"] == "external_member"]

    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(people[0].keys()))
        writer.writeheader()
        writer.writerows(people)

    lines = [
        "# Professor & staff credentials — permanent roster",
        "",
        f"**Generated:** {datetime.now().strftime('%d %b %Y, %H:%M')}  ",
        f"**Accounts:** {len(people)} total · **{len(faculty)} faculty** · {len(chairs)} chairperson-eligible "
        f"(Dean / Head of Department) · {len(office)} Academic Office · {len(externals)} External Member · "
        f"1 System Administrator",
        "",
        "> **These accounts are permanent.** They are stored in `auth_store.SEEDED_DIRECTORY` and re-created "
        "on every application start (`INSERT OR IGNORE`). No code path in the project deletes a user — "
        "`grep -r \"DELETE FROM users\" ` returns nothing. They will stay until you explicitly ask for them "
        "to be removed.",
        "",
        "## How to sign in (no password is used)",
        "",
        "1. Open the app at **http://localhost:8000** — the sign-in screen lists every account below, searchable.",
        "2. Click an account (or type its email) and click **Email me a sign-in code**.",
        "3. Read the code: it is emailed when a mail transport is configured; otherwise it is printed "
        "in the terminal running `python app.py` and written to `data/mail-outbox/`.",
        "4. Type the code and click **Verify and continue**.",
        "5. The **first sign-in asks for a digital signature** — draw it or upload an image. Every later "
        "sign-in reuses it, and it is stamped on every document that account signs.",
        "",
        "## Who does what",
        "",
        "| Role | Can do | Test with |",
        "| --- | --- | --- |",
        f"| System Administrator | Provision accounts, see the access directory, mail queue, audit | `{_sample('system_admin')}` |",
        f"| Academic Office | Review / approve / return requests and minutes, document vault | `{_sample('academic_office')}` |",
        f"| Faculty (Member Secretary) | Schedule a meeting, write the minutes, download the signed form | `{_member_secretary}` |",
        f"| Faculty (Chairperson) | Must be Dean / HoD of the same school; signs the request and the minutes | `{_chairperson}` |",
        f"| External Member | Files the observation report for an approved meeting | `{_external}` (R1's External Member of that DAC) |",
        "",
        "**Chairperson rule:** the person who chairs must be a Dean or Head of Department of the meeting's "
        "own school and must not be the Member Secretary. The rows marked ✓ below are the only accounts the "
        "app will accept.",
        "",
        "---",
        "",
    ]

    def table(group: list[dict], heading: str) -> None:
        if not group:
            return
        lines.extend([f"## {heading}", "",
                      "| Name | Email | Designation | Qualification | Specialisation | Staff ID | Phone | Office | Chair ✓ | Signed |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"])
        for person in group:
            lines.append(
                f"| {person['name']} | `{person['email']}` | {person['designation']} | {person['qualification']} | "
                f"{person['specialization']} | {person['employeeCode']} | {person['phone']} | {person['office']} | "
                f"{person['chairperson'] or '—'} | {person['signedIn'] or '—'} |")
        lines.append("")

    table([p for p in people if p["role"] == "system_admin"], "System Administrator")
    table(office, "Academic Office")
    table(externals, "External Members")

    by_school: dict[str, list[dict]] = {}
    for person in faculty:
        by_school.setdefault(person["school"] or "Unassigned", []).append(person)
    for school in sorted(by_school, key=lambda s: SCHOOL_ORDER.index(s) if s in SCHOOL_ORDER else 99):
        table(by_school[school], f"Faculty — School of {school} ({len(by_school[school])} accounts)")

    lines.extend([
        "---",
        "",
        "## Permanence, in plain terms",
        "",
        "* The roster lives in code (`auth_store.SEEDED_DIRECTORY`), not in a hand-made database, so a fresh "
        "machine, a wiped database or a restart all produce the same accounts.",
        "* `self_test.py` asserts that every seeded account exists and is active — if a future change ever "
        "removes or deactivates one, the test fails before it can ship.",
        "* Regenerate this sheet at any time: `cd DAC-MOM && ./.venv/bin/python export_credentials.py`",
        "* The sign-in screen reads this roster from `GET /api/directory/roster`; the System "
        "Administrator manages it through `GET/POST/PATCH /api/admin/users`.",
    ])
    MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT.parent / "PROFESSOR-CREDENTIALS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(people)} accounts · {len(faculty)} faculty · {len(chairs)} chairperson-eligible")
    print(f"written: {MD_PATH}")
    print(f"written: {CSV_PATH}")


if __name__ == "__main__":
    main()
