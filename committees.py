"""The two committees this application runs: DAC and BOS.

A Departmental Academic Committee (DAC) is constituted inside one department and
meets twice in a semester — once at the start of the semester and once at the end —
so four meetings (and four Minutes of Meeting) fall in an academic year.

A Board of Studies (BOS) is constituted for the department's programmes and meets
once in a semester, so two meetings fall in an academic year.

Both use the same workflow: the Member Secretary schedules the meeting and signs
the request, the Chairperson (Dean / Head of Department) signs it, the Academic
Office approves it and archives the signed form; after the meeting the minutes go
back through the Chairperson and then the Academic Office.

Everything committee-specific lives in this module so a future change (an extra
meeting in the year, a different title, a different agenda set) is one edit here
and nothing else.
"""

from __future__ import annotations

#: ``code`` is stored on every workspace; the rest is presentation and policy.
COMMITTEES: dict[str, dict] = {
    "DAC": {
        "code": "DAC",
        "short": "DAC",
        "name": "Departmental Academic Committee",
        "full": "Departmental Academic Committee",
        "meetingsPerSemester": 2,
        "meetingsPerYear": 4,
        "schedule": "twice in every semester — at the start of the semester and again at the end",
        "scheduleShort": "2 per semester · 4 in a year",
        "agendaSeries": "DAC #1 and DAC #2",
        "requestTitle": "DAC Meeting Request and Agenda Approval Form",
        "momTitle": "DAC Minutes of Meeting",
        "requestSubtitle": "Request for Approval of Agenda and Members",
        "referencePrefix": "DAC",
        "startNote": ("The Departmental Academic Committee meets twice in a semester — at the start "
                      "and at the end — so four DAC meetings are held in an academic year."),
    },
    "BOS": {
        "code": "BOS",
        "short": "BOS",
        "name": "Board of Studies",
        "full": "Board of Studies",
        "meetingsPerSemester": 1,
        "meetingsPerYear": 2,
        "schedule": "once in every semester — so twice in an academic year",
        "scheduleShort": "1 per semester · 2 in a year",
        "agendaSeries": "BOS #1",
        "requestTitle": "BOS Meeting Request and Agenda Approval Form",
        "momTitle": "BOS Minutes of Meeting",
        "requestSubtitle": "Request for Approval of Agenda and Members",
        "referencePrefix": "BOS",
        "startNote": ("The Board of Studies meets once in a semester — so two BOS meetings are held "
                      "in an academic year."),
    },
}

DEFAULT_COMMITTEE = "DAC"


def codes() -> tuple[str, ...]:
    return tuple(COMMITTEES)


def normalise(value: object) -> str:
    """Any stored value → a known committee code (defaults to DAC)."""
    text = str(value or "").strip().upper()
    return text if text in COMMITTEES else DEFAULT_COMMITTEE


def meta(value: object) -> dict:
    """Presentation and policy for one committee."""
    return COMMITTEES[normalise(value)]


def label(value: object) -> str:
    return normalise(value)


def name(value: object) -> str:
    return meta(value)["name"]


def meetings_per_semester(value: object) -> int:
    return int(meta(value)["meetingsPerSemester"])


def meeting_number_limit(value: object) -> int:
    """Highest legal meeting number inside one semester for this committee."""
    return int(meta(value)["meetingsPerSemester"])


def document_title(value: object, kind: str = "request") -> str:
    key = "momTitle" if kind in {"mom", "minutes"} else "requestTitle"
    return meta(value)[key]


def reference_prefix(value: object) -> str:
    return meta(value)["referencePrefix"]


def schedule_text(value: object) -> str:
    return meta(value)["schedule"]


def meeting_label(value: object, meeting_no: object) -> str:
    """``1`` → ``DAC #1`` / ``BOS #1`` — the way the committee's meetings are cited."""
    number = str(meeting_no or "").strip()
    return f"{normalise(value)} #{number}" if number else normalise(value)


def series_catalogue() -> list[dict]:
    """What the interface shows on the 'choose a committee' screen."""
    return [
        {
            "code": entry["code"],
            "name": entry["name"],
            "meetingsPerSemester": entry["meetingsPerSemester"],
            "meetingsPerYear": entry["meetingsPerYear"],
            "schedule": entry["schedule"],
            "scheduleShort": entry["scheduleShort"],
            "agendaSeries": entry["agendaSeries"],
            "note": entry["startNote"],
            "requestTitle": entry["requestTitle"],
            "momTitle": entry["momTitle"],
        }
        for entry in COMMITTEES.values()
    ]


__all__ = [
    "COMMITTEES", "DEFAULT_COMMITTEE", "codes", "normalise", "meta", "label", "name",
    "meetings_per_semester", "meeting_number_limit", "document_title",
    "reference_prefix", "schedule_text", "meeting_label", "series_catalogue",
]
