"""Official DAC agenda library (Office of the Dean Academics, GD-2 / Annexure-A).

The university publishes the agenda items a Departmental Academic Committee may
take up.  They are reproduced here verbatim so the application never invents,
re-words or silently drops an official item.  Each entry records the meeting(s)
it belongs to:

``dac1``      the first DAC meeting of a semester
``dac2``      the second DAC meeting of a semester
``anywhere``  "Any other agenda items may be discussed with the permission of the Chair"

Items marked "Wherever applicable" (and the Summer Term item, which is a second
(DAC#2) meeting of an even semester only) carry that note unchanged, so the
organiser sees the same condition the university printed.

Nothing in this module touches the workflow: it is a read-only catalogue plus a
few helpers used by the API and the PDF/DOCX renderers.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# The nineteen published entries.  ``id`` values are stable: they are stored in
# saved workspaces, referenced by annexure labels and asserted by the tests.
# ``std-mom`` and ``std-atr`` keep their original identifiers because they are
# the official agenda #1 and #2 -- existing workspaces keep working untouched.
# ---------------------------------------------------------------------------

AGENDA_LIBRARY: tuple[dict[str, Any], ...] = (
    {
        "id": "std-mom",
        "no": 1,
        "text": "Review and approval of minutes of the previous meeting.",
        "groups": ("dac1", "dac2"),
        "applies": "",
        "keywords": ("minutes", "previous meeting", "approval of minutes", "mom"),
    },
    {
        "id": "std-atr",
        "no": 2,
        "text": "Action Taken Report (ATR) - Review of actions taken on decisions from the previous meeting.",
        "groups": ("dac1", "dac2"),
        "applies": "",
        "keywords": ("action taken report", "atr", "actions taken", "previous decisions"),
    },
    {
        "id": "std-courses",
        "no": 3,
        "text": "Approval of courses available for registration in the upcoming semester.",
        "groups": ("dac1",),
        "applies": "",
        "keywords": ("courses", "registration", "upcoming semester", "course list"),
    },
    {
        "id": "std-course-plan",
        "no": 4,
        "text": "Approval of Course Plans including various components of Continuous Assessments, "
                "the distribution of weightage among such components, and the method of "
                "evaluation/assessment of the courses offered in the concerned Academic Term.",
        "groups": ("dac1",),
        "applies": "",
        "keywords": ("course plan", "continuous assessment", "weightage", "evaluation method",
                     "co-po", "bloom"),
    },
    {
        "id": "std-ntcc",
        "no": 5,
        "text": "Discussion on assessment method for NTCC courses with clear rubrics.",
        "groups": ("dac1",),
        "applies": "",
        "keywords": ("ntcc", "rubrics", "non-teaching credit", "capstone"),
    },
    {
        "id": "std-electives",
        "no": 6,
        "text": "Electives to be offered in the upcoming semester along with the list of students.",
        "groups": ("dac1",),
        "applies": "",
        "keywords": ("electives", "list of students", "open elective"),
    },
    {
        "id": "std-audit",
        "no": 7,
        "text": "Discussion on Audit Course(s) shown interest by the student, if any.",
        "groups": ("dac1",),
        "applies": "",
        "keywords": ("audit course", "audit", "nptel", "mooc"),
    },
    {
        "id": "std-class-committee",
        "no": 8,
        "text": "Discussion on Class Committee meetings conducted during the semester and upon the "
                "Resolutions passed by Class Committee.",
        "groups": ("dac2",),
        "applies": "",
        "keywords": ("class committee", "resolutions of class committee"),
    },
    {
        "id": "std-feedback",
        "no": 9,
        "text": "Student and Faculty feedback on courses - Review of student feedback and "
                "suggestions for course improvements.",
        "groups": ("dac2",),
        "applies": "",
        "keywords": ("feedback", "student feedback", "course improvement"),
    },
    {
        "id": "std-curriculum",
        "no": 10,
        "text": "Deliberation on curriculum Structure and Course content based on various "
                "stakeholders (Faculty, Students, Alumni and Industry) feedback and suggestions.",
        "groups": ("dac1",),
        "applies": "",
        "keywords": ("curriculum", "course content", "stakeholders", "syllabus", "alumni", "industry"),
    },
    {
        "id": "std-bos",
        "no": 11,
        "text": "Implementation of the resolutions of the BOS, if any, for the upcoming batches "
                "and semesters.",
        "groups": ("dac1", "dac2"),
        "applies": "Wherever applicable",
        "keywords": ("bos", "board of studies", "implementation of resolutions"),
    },
    {
        "id": "std-new-course",
        "no": 12,
        "text": "New Course Proposals for new courses including Massive Open Online Course (MOOC) courses.",
        "groups": ("dac1",),
        "applies": "",
        "keywords": ("new course", "proposal", "mooc", "certificate course"),
    },
    {
        "id": "std-intake",
        "no": 13,
        "text": "Closure of the Program and Change of Intake - Assessment and recommendations for "
                "modifications in program intake and, if required, program closure.",
        "groups": ("dac1", "dac2"),
        "applies": "Wherever applicable",
        "keywords": ("intake", "program closure", "sanctioned strength"),
    },
    {
        "id": "std-po-co",
        "no": 14,
        "text": "Program Outcomes (POs) and Course Outcomes (COs) attainment for the courses "
                "offered in the last semester.",
        "groups": ("dac2",),
        "applies": "",
        "keywords": ("po attainment", "co attainment", "program outcomes", "course outcomes"),
    },
    {
        "id": "std-research",
        "no": 15,
        "text": "Exploration on Faculty and Student Research Initiative.",
        "groups": ("dac1", "dac2"),
        "applies": "Wherever applicable",
        "keywords": ("research", "publication", "student project", "innovation"),
    },
    {
        "id": "std-faculty-dev",
        "no": 16,
        "text": "Faculty Training and Professional Development need analysis.",
        "groups": ("dac1", "dac2"),
        "applies": "Wherever applicable",
        "keywords": ("faculty training", "professional development", "fdp", "workshop"),
    },
    {
        "id": "std-np",
        "no": 17,
        "text": "Tentative Not Permitted (NP) list.",
        "groups": ("dac2",),
        "applies": "",
        "keywords": ("np list", "not permitted", "detained"),
    },
    {
        "id": "std-summer",
        "no": 18,
        "text": "Summer Term courses tentative list and further planning.",
        "groups": ("dac2",),
        "applies": "DAC#2 of even semester only",
        "keywords": ("summer term", "summer courses"),
    },
    {
        "id": "std-other",
        "no": 19,
        "text": "Any other agenda items may be discussed with the permission of the Chair.",
        "groups": ("anywhere",),
        "applies": "",
        "keywords": ("any other", "with the permission of the chair"),
    },
)

LIBRARY_BY_ID: dict[str, dict[str, Any]] = {item["id"]: item for item in AGENDA_LIBRARY}

GROUP_LABELS: dict[str, str] = {
    "dac1": "DAC #1 — first meeting of the semester",
    "dac2": "DAC #2 — second meeting of the semester",
    "anywhere": "Any meeting — with the permission of the Chair",
}

#: The same series, worded for the committee the reader is working on. A committee that
#: meets once per semester has no "#2" group at all, so it must not be offered.
SINGLE_MEETING_LABELS: dict[str, str] = {
    "dac1": "{code} #1 — the semester's meeting",
    "anywhere": "Any meeting — with the permission of the Chair",
}

SOURCE = ("Office of the Dean Academics, GD-2 / Annexure-A — Guidelines for Agenda item "
          "for Departmental Academic Committee")


def library_item(agenda_id: str) -> dict[str, Any] | None:
    """Return the published entry for ``agenda_id`` (or ``None`` for a custom item)."""
    return LIBRARY_BY_ID.get(str(agenda_id or "").strip())


def meeting_group(meeting_no: Any) -> str:
    """Map a meeting number onto the published DAC#1 / DAC#2 grouping."""
    text = str(meeting_no or "").strip()
    match = re.search(r"\d+", text)
    number = int(match.group(0)) if match else 1
    return "dac1" if number <= 1 else "dac2"


def groups_for(agenda_id: str) -> tuple[str, ...]:
    item = library_item(agenda_id)
    return tuple(item["groups"]) if item else ("anywhere",)


def default_title(agenda_id: str) -> str:
    item = library_item(agenda_id)
    return item["text"] if item else ""


def group_payload(meeting_no: Any = "1", committee: Any = "DAC") -> dict[str, Any]:
    """Grouped catalogue for the UI (and the tests).

    Items that belong to both meetings appear in both groups -- that is exactly
    how the university printed them, and hiding an item from one group would
    quietly change the official list.
    """
    import committees as committee_registry

    code = committee_registry.normalise(committee)
    per_semester = committee_registry.meetings_per_semester(code)
    single = per_semester <= 1
    labels = (SINGLE_MEETING_LABELS if single else GROUP_LABELS)
    current = "dac1" if single else meeting_group(meeting_no)
    keys = ("dac1", "anywhere") if single else ("dac1", "dac2", "anywhere")
    groups = []
    for key in keys:
        items = [dict(item) for item in AGENDA_LIBRARY if key in item["groups"] or "anywhere" in item["groups"]]
        for item in items:
            item["groups"] = list(item["groups"])
        groups.append({
            "key": key,
            "label": labels[key].format(code=code),
            "current": key == current or key == "anywhere",
            "items": items,
        })
    return {"source": SOURCE, "meetingGroup": current, "committee": code,
            "meetingsPerSemester": per_semester, "groups": groups,
            "count": len(AGENDA_LIBRARY)}


