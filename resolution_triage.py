"""Read each agenda's Resolution, place it in one of three categories, and decide
whether it belongs in the Action Items table.

The three categories
--------------------
``approved``        the committee approved / accepted / ratified it. Nothing is
                    outstanding, so **no action item** is produced.
``in_process``      a decision is still awaited: deferred, pending, under review,
                    a second discussion is needed. **One action item.**
``not_approved``    the committee declined it, or it cannot be approved as
                    submitted. **One action item.**
``unclassified``    there is no resolution text to read (or the author marked
                    that no separate resolution was recorded). The item is
                    reported honestly and **no action item** is produced.

Only ``in_process`` and ``not_approved`` resolutions are proposed for the Action
Items table, and what is proposed is a deliberately *very short* version of the
resolution - the next step, not the minutes again. For example::

    "In process - needs a second discussion at the next meeting."

Design notes
------------
* **Hybrid by default**, exactly like :mod:`ai_verify`. With an API key the text
  is sent to the configured model; without one (or when the call fails) the
  transparent cue rules below run, so the feature always works.
* **Nothing is rewritten.** The classifier returns a category, a short action
  phrasing and the evidence it used. It never edits the resolution itself; the
  resolution stays exactly as the author typed it.
* **Human in the loop.** The report proposes; the organiser adds the action item
  (and names the person responsible). A category can be overridden by the
  reviewer, and every override is visible in the audit trail.
* **Additive.** The module imports the provider plumbing from :mod:`ai_verify`
  and changes nothing there - the existing verification behaviour is untouched.
"""
from __future__ import annotations

import json
import re
import urllib.error
from datetime import datetime

from ai_verify import _call_gemini, _call_openai, _extract_json, provider_config, provider_status
from mom_shared import item_has_no_resolution, item_resolution

CATEGORY_APPROVED = "approved"
CATEGORY_IN_PROCESS = "in_process"
CATEGORY_NOT_APPROVED = "not_approved"
CATEGORY_UNCLASSIFIED = "unclassified"

CATEGORIES = (CATEGORY_APPROVED, CATEGORY_IN_PROCESS, CATEGORY_NOT_APPROVED, CATEGORY_UNCLASSIFIED)
CATEGORY_LABELS = {
    CATEGORY_APPROVED: "Recommended",
    CATEGORY_IN_PROCESS: "In process",
    CATEGORY_NOT_APPROVED: "Not recommended",
    CATEGORY_UNCLASSIFIED: "Not classified",
}
#: The categories that produce an Action Items row. Approved resolutions are closed.
ACTIONABLE_CATEGORIES = (CATEGORY_IN_PROCESS, CATEGORY_NOT_APPROVED)

CATEGORY_ALIASES = {
    "approved": CATEGORY_APPROVED, "approve": CATEGORY_APPROVED, "approval": CATEGORY_APPROVED,
    "accepted": CATEGORY_APPROVED, "ratified": CATEGORY_APPROVED, "sanctioned": CATEGORY_APPROVED,
    "in process": CATEGORY_IN_PROCESS, "in_process": CATEGORY_IN_PROCESS, "in-process": CATEGORY_IN_PROCESS,
    "inprocess": CATEGORY_IN_PROCESS, "pending": CATEGORY_IN_PROCESS, "deferred": CATEGORY_IN_PROCESS,
    "under process": CATEGORY_IN_PROCESS, "under review": CATEGORY_IN_PROCESS, "wip": CATEGORY_IN_PROCESS,
    "not approved": CATEGORY_NOT_APPROVED, "not_approved": CATEGORY_NOT_APPROVED,
    "not-approved": CATEGORY_NOT_APPROVED, "notapproved": CATEGORY_NOT_APPROVED,
    "rejected": CATEGORY_NOT_APPROVED, "reject": CATEGORY_NOT_APPROVED, "declined": CATEGORY_NOT_APPROVED,
    "unclassified": CATEGORY_UNCLASSIFIED, "none": CATEGORY_UNCLASSIFIED, "unknown": CATEGORY_UNCLASSIFIED,
    "": CATEGORY_UNCLASSIFIED,
}

#: Short action phrasings, most specific pattern first. The first match wins, so
#: a refusal ("not approved") is always read before a plain approval.
SHORT_ACTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    CATEGORY_NOT_APPROVED: (
        (r"\bnot\s+approved\b|\bnot\s+approve[ds]?\b|\bnot\s+accorded\b",
         "Not recommended - revise and resubmit at the next meeting"),
        (r"\b(?:rejected|rejection|declined|refused|turned\s+down|vetoed)\b",
         "Not recommended - rejected; revise before resubmission"),
        (r"\bnot\s+(?:accepted|sanctioned|ratified|endorsed|agreed|cleared|concurred)\b",
         "Not recommended - revise and place it again at the next meeting"),
        (r"\bdid\s+not\s+(?:approve|accept|agree|concur)\b|\bno\s+approval\b|\bcannot\s+be\s+approved\b"
         r"|\bcan\s*not\s+be\s+approved\b|\bshall\s+not\s+be\s+approved\b",
         "Not recommended - rework the proposal before the next meeting"),
        (r"\bwithheld\b|\bnot\s+recommended\b",
         "Not recommended - to be reworked and placed again"),
    ),
    CATEGORY_IN_PROCESS: (
        (r"\bin[\s-]?process\b|\bunder\s+process\b|\bin\s+progress\b",
         "In process - needs a second discussion at the next meeting"),
        (r"\b(?:deferred|postponed|adjourned|tabled|held\s+over|on\s+hold|abeyance|kept\s+pending)\b",
         "In process - deferred; second discussion at the next meeting"),
        (r"\b(?:pending|awaiting|await\w*|dependent\s+on|subject\s+to)\b",
         "In process - awaiting a reply; revisit at the next meeting"),
        (r"\bunder\s+(?:review|consideration|examination|scrutiny|process|preparation)\b"
         r"|\bbeing\s+(?:examined|reviewed|prepared|processed)\b",
         "In process - under review; to be taken up at the next meeting"),
        (r"\b(?:second|further|next|another|subsequent|fresh)\s+(?:discussion|deliberation|meeting|review)\b"
         r"|\b(?:discuss|deliberate|review|place|bring|take\s+up|revisit)\w*\s+(?:it\s+|this\s+|the\s+same\s+)?"
         r"(?:again\s+)?(?:in|at|during)\s+the\s+next\s+meeting\b",
         "In process - needs a second discussion at the next meeting"),
        (r"\b(?:will|to|shall)\s+be\s+(?:placed|brought|taken\s+up|circulated|revisited|re-?examined)\b",
         "In process - to be taken up again at the next meeting"),
        (r"\b(?:sought|circulated|explor\w*|prepared|collected|compiled|provisional|draft)\b",
         "In process - input being gathered; revisit at the next meeting"),
        (r"\b(?:referred|action\s+taken\s+report|atr)\b",
         "In process - referred for a report; follow up at the next meeting"),
    ),
    CATEGORY_APPROVED: (
        (r"\b(?:approved|approve[ds]?|approval|accorded)\b|\bnoted\s+and\s+approved\b",
         "Recommended - recorded; no action item required"),
        (r"\b(?:ratified|sanctioned|endorsed|accepted|agreed|cleared|confirmed|adopted)\b",
         "Recommended - recorded; no action item required"),
    ),
}
#: Used when the text carries no recognisable decision wording at all.
DEFAULT_SHORT_ACTION = {
    CATEGORY_IN_PROCESS: "In process - needs a second discussion at the next meeting",
    CATEGORY_NOT_APPROVED: "Not recommended - to be reworked and placed again at the next meeting",
    CATEGORY_APPROVED: "Recommended - recorded; no action item required",
    CATEGORY_UNCLASSIFIED: "",
}
#: An action line is a next step for a person, not a restatement of the resolution.
#: 60 characters is the enforced ceiling, applied to model output as well, so the
#: Action Items table stays scannable however verbose the provider is.
MAX_SHORT_ACTION = 60
MAX_EVIDENCE = 240

SYSTEM_PROMPT = (
    "You triage the Resolutions recorded in the Minutes of Meeting (MoM) of a college Departmental "
    "Academic Committee (DAC). For each agenda item you receive the approved agenda wording, the "
    "recorded Discussion and the recorded Resolution.\n"
    "\n"
    "Place each agenda's resolution in exactly one of three categories:\n"
    "1. \"approved\" - the committee approved, accepted, ratified, sanctioned or endorsed it. The matter "
    "is closed.\n"
    "2. \"in_process\" - no final decision was reached: it was deferred, postponed, kept pending, left "
    "open, referred onwards, or a further/second discussion is needed.\n"
    "3. \"not_approved\" - the committee rejected, declined, did not accept it, or it cannot be approved "
    "as submitted.\n"
    "\n"
    "Then decide whether the resolution must appear in the Action Items table of the MoM:\n"
    "- \"in_process\" and \"not_approved\" DO belong in the Action Items table, because something is still "
    "outstanding.\n"
    "- \"approved\" does NOT: nothing is pending, so no action item is produced.\n"
    "\n"
    "For every resolution that belongs in the Action Items table, write ONE very short action line: the "
    "next step in plain words, at most 15 words and never more than 120 characters. It must read like a "
    "task list entry, for example \"In process - needs a second discussion at the next meeting\", "
    "\"In process - awaiting the examination report; revisit next meeting\", \"Not approved - revise the "
    "credit distribution and resubmit\". Do not repeat the whole resolution, do not copy long clauses, "
    "never invent a person, a date or a document that is not in the record.\n"
    "\n"
    "Rules:\n"
    "- Judge only the supplied text. You cannot know what was actually said in the meeting.\n"
    "- A resolution that reads as deferred while the others are approved is \"in_process\".\n"
    "- Quote evidence verbatim from the resolution when you give it.\n"
    "- If no resolution text was recorded, use the category \"unclassified\" and an empty short action.\n"
    "- Reply with JSON only, no prose outside the JSON."
)

RESPONSE_SCHEMA_HINT = (
    "Return JSON with this exact shape:\n"
    '{"items":[{"agendaNo":1,"category":"approved|in_process|not_approved|unclassified",'
    '"addToActionItems":false,"shortAction":"very short next step, empty when nothing is pending",'
    '"confidence":0.0,"rationale":"one sentence for the reviewer",'
    '"evidence":"short verbatim quote from the resolution"}],"summaryNote":"optional one-line note"}\n'
    "Include every agenda item you were given, in the same order, with the same agendaNo."
)


def _compact(value, limit: int = 400) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _short(value: str, limit: int = MAX_SHORT_ACTION) -> str:
    """One line, no more than ``limit`` characters, cut at a word boundary."""
    text = _compact(value, limit + 60).rstrip(" .,;:-")
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[:cut.rstrip().rfind(" ")]
    return cut.rstrip(" .,;:-")


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(str(category or ""), CATEGORY_LABELS[CATEGORY_UNCLASSIFIED])


def should_add_to_action_items(category: str) -> bool:
    """Only In process and Not approved resolutions reach the Action Items table."""
    return str(category or "") in ACTIONABLE_CATEGORIES


def _coerce_category(value) -> str:
    text = _compact(value, 40).lower().replace("_", " ")
    return CATEGORY_ALIASES.get(text, CATEGORY_ALIASES.get(text.replace("-", " "), CATEGORY_UNCLASSIFIED))


def _coerce_confidence(value, default: float = 0.6) -> float:
    match = re.search(r"\d+(\.\d+)?", str(value if value is not None else ""))
    if not match:
        return default
    number = float(match.group(0))
    if number > 1:  # a model that answered 85 means 85 %
        number = number / 100
    return round(max(0.0, min(1.0, number)), 2)


def _short_action_for(resolution: str, category: str) -> str:
    """Pick the short next-step line for a category, using the text's own wording."""
    text = _compact(resolution, 2000)
    for pattern, phrase in SHORT_ACTIONS.get(category, ()):
        if re.search(pattern, text, re.IGNORECASE):
            return _short(phrase)
    return _short(DEFAULT_SHORT_ACTION.get(category, ""))


def classify_offline(resolution: str, no_resolution: bool = False) -> dict:
    """Deterministic three-way classification, with the cue that decided it.

    Order is deliberate: a refusal is read before a plain approval, and anything
    that still needs a decision (deferred, pending, under review, a second
    discussion) is read before a bare "approved" so that wording such as
    "approved subject to ratification at the next meeting" lands in
    ``in_process``.
    """
    text = _compact(resolution, 4000)
    if not text or no_resolution:
        return {
            "category": CATEGORY_UNCLASSIFIED,
            "shortAction": "",
            "confidence": 1.0 if no_resolution else 0.5,
            "rationale": (
                "The author marked that no separate resolution was recorded, so there is nothing to classify."
                if no_resolution else
                "No resolution text was recorded for this agenda, so no category could be assigned."
            ),
            "evidence": "",
            "matched": "",
            "source": "offline-rules",
        }
    for category in (CATEGORY_NOT_APPROVED, CATEGORY_IN_PROCESS, CATEGORY_APPROVED):
        for pattern, phrase in SHORT_ACTIONS[category]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                actionable = should_add_to_action_items(category)
                rationale = f"Matched the wording \u201c{_compact(match.group(0), 60)}\u201d in the resolution."
                if not actionable:
                    rationale += " Nothing is outstanding, so no action item is produced."
                return {
                    # Only In process / Not approved resolutions carry an action line:
                    # an approved resolution is closed and produces no Action Items row.
                    "category": category,
                    "shortAction": _short(phrase) if actionable else "",
                    "confidence": 0.85,
                    "rationale": rationale,
                    "evidence": _compact(match.group(0), MAX_EVIDENCE),
                    "matched": _compact(match.group(0), 60),
                    "source": "offline-rules",
                }
    return {
        "category": CATEGORY_IN_PROCESS,
        "shortAction": _short(DEFAULT_SHORT_ACTION[CATEGORY_IN_PROCESS]),
        "confidence": 0.35,
        "rationale": (
            "The resolution carries no clear approval wording, so it is treated as In process: "
            "something still needs a follow-up discussion."
        ),
        "evidence": text[:MAX_EVIDENCE],
        "matched": "",
        "source": "offline-rules",
    }


def _payload(mom_items: list[dict]) -> list[dict]:
    rows = []
    for index, item in enumerate(mom_items or [], start=1):
        rows.append({
            "agendaId": str(item.get("id") or item.get("agendaId") or ""),
            "agendaNo": int(item.get("agendaNo") or index),
            "agendaTitle": _compact(item.get("title") or f"Agenda {index}", 300),
            "resolution": item_resolution(item),
            "noSeparateResolutionRecorded": item_has_no_resolution(item),
        })
    return rows


def _user_prompt(mom_items: list[dict], meeting: dict | None) -> str:
    meeting = meeting or {}
    context = ""
    if meeting:
        context = (
            "Meeting context (for tone only, do not verify it):\n"
            f"- School: {meeting.get('school', '')}\n"
            f"- Department: {meeting.get('department', '')}\n"
            f"- Meeting number: {meeting.get('meetingNo', '')}\n"
            f"- Date: {meeting.get('date', '')}\n\n"
        )
    body = json.dumps(
        {"items": [{"agendaNo": row["agendaNo"], "agendaTitle": row["agendaTitle"],
                    "resolution": row["resolution"],
                    "noSeparateResolutionRecorded": row["noSeparateResolutionRecorded"]}
                   for row in _payload(mom_items)]},
        ensure_ascii=False, indent=1,
    )
    return f"{context}Agenda resolutions to triage (JSON):\n{body}\n\n{RESPONSE_SCHEMA_HINT}"


def _offline_rows(mom_items: list[dict]) -> list[dict]:
    rows = []
    for entry in _payload(mom_items):
        verdict = classify_offline(entry["resolution"], entry["noSeparateResolutionRecorded"])
        rows.append({
            **entry,
            "category": verdict["category"],
            "categoryLabel": category_label(verdict["category"]),
            "addToActionItems": should_add_to_action_items(verdict["category"]),
            "shortAction": verdict["shortAction"],
            "confidence": verdict["confidence"],
            "rationale": verdict["rationale"],
            "evidence": verdict["evidence"],
            "source": verdict["source"],
        })
    return rows


def _merge_model_output(raw_items: list, offline_rows: list[dict]) -> list[dict]:
    """Let a valid model verdict win over the offline cue rules, item by item."""
    by_number: dict[int, dict] = {}
    for position, entry in enumerate(raw_items or []):
        if not isinstance(entry, dict):
            continue
        number = entry.get("agendaNo")
        try:
            key = int(str(number).strip())
        except (TypeError, ValueError):
            key = position + 1
        by_number.setdefault(key, entry)

    merged = []
    for index, row in enumerate(offline_rows):
        model_row = by_number.get(row["agendaNo"]) or (raw_items[index] if index < len(raw_items or [])
                                                       and isinstance(raw_items[index], dict) else None)
        if not model_row:
            merged.append(row)
            continue
        category = _coerce_category(model_row.get("category"))
        if category == CATEGORY_UNCLASSIFIED and row["category"] != CATEGORY_UNCLASSIFIED:
            # The model did not commit to a category for a resolution that exists:
            # keep the transparent cue-rule verdict instead of losing the finding.
            merged.append(row)
            continue
        short_action = _short(model_row.get("shortAction") or "", MAX_SHORT_ACTION)
        if should_add_to_action_items(category):
            short_action = short_action or _short_action_for(row["resolution"], category)
        else:
            short_action = ""  # Approved / unclassified items never carry an action line.
        merged.append({
            **row,
            "category": category,
            "categoryLabel": category_label(category),
            "addToActionItems": should_add_to_action_items(category),
            "shortAction": short_action,
            "confidence": _coerce_confidence(model_row.get("confidence"), 0.7),
            "rationale": _compact(model_row.get("rationale"), 400) or row["rationale"],
            "evidence": _compact(model_row.get("evidence"), MAX_EVIDENCE) or row["evidence"],
            "source": "ai-model",
        })
    return merged


def _summarise(rows: list[dict]) -> dict:
    return {
        "items": len(rows),
        "approved": sum(row["category"] == CATEGORY_APPROVED for row in rows),
        "inProcess": sum(row["category"] == CATEGORY_IN_PROCESS for row in rows),
        "notApproved": sum(row["category"] == CATEGORY_NOT_APPROVED for row in rows),
        "unclassified": sum(row["category"] == CATEGORY_UNCLASSIFIED for row in rows),
        "proposedActionItems": sum(bool(row["addToActionItems"]) for row in rows),
    }


def _report(rows: list[dict], mode: str, provider: dict, engine: str, notes: list[str] | None = None,
            fallback_reason: str | None = None) -> dict:
    report = {
        "mode": mode,
        "engine": engine,
        "provider": provider,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "categories": {key: CATEGORY_LABELS[key] for key in CATEGORIES},
        "actionableCategories": list(ACTIONABLE_CATEGORIES),
        "maxShortActionLength": MAX_SHORT_ACTION,
        "summary": _summarise(rows),
        "items": rows,
        "notes": notes or [],
    }
    if fallback_reason:
        report["fallbackReason"] = fallback_reason
    report["notice"] = (
        "Only resolutions categorised In process or Not approved are proposed for the Action Items table; "
        "Approved resolutions are closed and produce no action. The short action line is a next step, not a "
        "replacement for the resolution - the recorded resolution is never edited. "
        f"Engine: {engine}."
    )
    return report


def triage_resolutions(mom_items: list[dict], meeting: dict | None = None) -> dict:
    """Categorise every agenda resolution and propose the action items.

    Uses the configured model when a key is available, otherwise (or on any
    failure) the deterministic cue rules. The returned shape is identical either
    way, so the UI and the tests can rely on it.
    """
    items = list(mom_items or [])
    offline_rows = _offline_rows(items)
    if not items:
        report = _report(offline_rows, "offline-rules", provider_status(),
                         "Offline resolution rules (deterministic, no model)")
        report["notes"] = ["No agenda items were supplied, so there was nothing to classify."]
        return report

    config = provider_config()
    if config["provider"] == "offline":
        return _report(offline_rows, "offline-rules", provider_status(),
                       "Offline resolution rules (deterministic, no model)")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(items, meeting)},
    ]
    try:
        raw_text = (_call_gemini(messages, config) if config["provider"] == "gemini"
                    else _call_openai(messages, config))
        parsed = _extract_json(raw_text)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # pragma: no cover - body already consumed
            detail = ""
        return _report(offline_rows, "offline-rules", provider_status(),
                       "Offline resolution rules (deterministic, no model)",
                       fallback_reason=f"The {config['provider']} request failed with HTTP {exc.code}. {detail}".strip())
    except Exception as exc:
        return _report(offline_rows, "offline-rules", provider_status(),
                       "Offline resolution rules (deterministic, no model)",
                       fallback_reason=f"The {config['provider']} request could not be completed: {exc}")

    raw_items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(raw_items, list) or not raw_items:
        return _report(offline_rows, "offline-rules", provider_status(),
                       "Offline resolution rules (deterministic, no model)",
                       fallback_reason="The model reply did not contain any per-agenda categories.")

    rows = _merge_model_output(raw_items, offline_rows)
    notes = []
    if isinstance(parsed, dict) and parsed.get("summaryNote"):
        notes.append(_compact(parsed["summaryNote"], 300))
    used_model = any(row["source"] == "ai-model" for row in rows)
    # The model answered, but none of its categories survived the merge, so every category
    # below came from the cue rules. The screen has to say which engine actually ran.
    unusable_reason = None if used_model else (
        f"{config['provider']} replied, but none of its categories could be used for these "
        "resolutions, so the deterministic cue rules classified every one below."
    )
    if unusable_reason:
        notes.append(unusable_reason)
    return _report(
        rows,
        "ai-model" if used_model else "offline-rules",
        provider_status(),
        (f"Model-assisted triage · {config['provider']} {config['model']}" if used_model
         else "Offline cue rules (the model replied, but nothing in its reply was usable)"),
        notes=notes,
        fallback_reason=unusable_reason,
    )
