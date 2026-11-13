"""Offline, deterministic content checks for Discussion and Resolution text.

This module is the always-available fallback for :mod:`ai_verify`. It performs
transparent lexical checks - it cannot understand meaning and it cannot verify
what was actually said in a meeting. It answers two review questions:

1. Does the written **Discussion** address the approved **Agenda** item?
2. Is the written **Resolution** grounded in the written **Discussion**?

Everything it reports is traceable to a word overlap, so a reviewer can see
exactly why a flag was raised. Field names follow the current schema
(``resolution``); legacy ``recommendation`` values are still read.
"""
from __future__ import annotations

import re

from mom_shared import item_resolution, item_has_no_resolution

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "for", "from",
    "had", "has", "have", "in", "into", "is", "it", "its", "of", "on", "or", "our",
    "the", "their", "them", "there", "this", "to", "was", "were", "with", "will", "would",
    "not", "no", "nor", "than", "that", "they", "then", "such",
    "committee", "department", "meeting", "members", "member", "regarding", "concerning",
}
#: Very common academic/administrative words that should not decide a check alone.
WEAK_TERMS = {
    "academic", "review", "consider", "approve", "record", "discuss", "note", "matter",
    "propose", "recommend", "resolve", "approval", "item", "agenda", "process",
    "also", "any", "other", "shall", "may", "been", "after", "before", "during", "same",
    # Formatting / boilerplate words that appear in almost every agenda title and
    # therefore say nothing about whether the discussion is on the right subject.
    "various", "including", "include", "along", "offered", "offer", "upcoming", "forthcoming",
    "previous", "last", "next", "taken", "take", "component", "continuous", "list",
    "semester", "term", "tentative", "concerned", "respective", "necessary", "required",
    "kind", "type", "detail", "details", "case", "regard", "related",
    "permitted", "permission", "permit",
    # Words from the standard DAC agenda templates: they are on every meeting's
    # agenda and say nothing about whether the discussion matches the subject.
    "held", "departmental", "department", "committee", "meeting", "members", "member",
    "minutes", "report", "reports", "point", "points", "placed", "place",
}
#: Decision vocabulary. A resolution legitimately says things the discussion of the
#: same item need not say ("the committee approved / adopted / directed that ...").
#: These stems are ignored when measuring whether a decision is grounded in the
#: record, otherwise every well-written resolution looks unsupported.
DECISION_VOCAB = {
    "adopt", "agree", "direct", "implement", "plan", "suggest", "proceed", "continue",
    "request", "effect", "forthcoming", "each", "incorperat", "incorpor", "revis",
    "examin", "consider", "inform", "accord", "thereof", "hereby", "accordingly",
}
ALIASES = {
    "mom": "minutes", "minute": "minutes", "minutes": "minutes", "previously": "previous",
    "last": "previous", "approved": "approve", "approval": "approve", "approving": "approve",
    "ratified": "approve", "ratification": "approve", "accepted": "approve", "acceptance": "approve",
    "examined": "review", "reviewed": "review", "reviewing": "review", "considered": "review",
    "discussed": "discuss", "discussion": "discuss", "discussing": "discuss",
    "action": "action", "actions": "action", "atr": "action", "syllabi": "syllabus",
    "curricular": "curriculum", "deferred": "defer", "postponed": "defer",
    "rejected": "reject", "declined": "reject", "noted": "note",
    "referred": "refer", "referral": "refer", "resolutions": "resolve", "resolution": "resolve",
    "resolved": "resolve", "resolves": "resolve", "recommendation": "resolve",
    "recommendations": "resolve", "recommended": "resolve", "recommends": "resolve",
    "recommend": "resolve",
    "po": "outcome", "pos": "outcome", "co": "outcome", "cos": "outcome", "co's": "outcome",
    "implementation": "implement", "implementing": "implement", "implemented": "implement",
    "sanctioned": "approve", "sanction": "approve", "sanctions": "approve",
    "permitted": "approve", "permit": "approve", "permits": "approve", "permission": "approve",
    "allowed": "approve", "condoned": "approve", "condone": "approve", "cleared": "approve",
    "assessments": "assessment", "outcomes": "outcome",
}
NUMBER_RE = re.compile(r"\b\d[\d.,/%-]*\b")
CODE_RE = re.compile(r"\b[A-Z]{2,5}[\s-]?\d{2,4}[A-Z]?\b")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+|\s*[•·]\s*")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _stem(word: str) -> str:
    """Reduce one word to the comparison stem used by the offline checks."""
    raw = word
    word = ALIASES.get(word.lower(), word.lower())
    if word in STOP_WORDS:
        return ""
    if len(word) < 3:
        # Keep two-letter acronyms that the record actually writes in capitals (NP, PO, CO).
        return word if raw.isupper() else ""
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("ing") and len(word) > 5:
        word = word[:-3]
    elif word.endswith("ed") and len(word) > 4:
        word = word[:-2]
    elif word.endswith("s") and len(word) > 4:
        word = word[:-1]
    return ALIASES.get(word, word)


PHRASE_ALIASES = {
    # Keep the topical noun when expanding an acronym, otherwise the very word the
    # agenda is about ("course", "action") disappears from the comparison.
    "action taken report": "atr action", "m.o.m.": "minutes", "mo m": "minutes", "mom": "minutes",
    "board of studies": "bos board", "continuous assessment": "ca assessment",
    "program outcome": "po outcome", "programme outcome": "po outcome",
    "course outcome": "co course outcome", "not permitted": "np",
}


def _normalized_terms(text: str) -> set[str]:
    value = (text or "").lower().replace("&", " and ")
    for phrase, replacement in PHRASE_ALIASES.items():
        value = value.replace(phrase, replacement)
    # Stem from the original text so two-letter acronyms keep their capitalisation.
    words = [match.group(0) for match in re.finditer(r"[A-Za-z0-9]+", text or "")]
    lowered = [match.group(0) for match in re.finditer(r"[A-Za-z0-9]+", value)]
    tokens = words if len(words) == len(lowered) else lowered
    stems = {_stem(token) for token in tokens}
    stems |= {_stem(token) for token in lowered}
    return {stem for stem in stems if stem}


def _readable_terms(stems: set[str], *texts: str, limit: int = 6) -> list[str]:
    """Map comparison stems back to the words a reviewer can actually see in the text."""
    labels: dict[str, str] = {}
    for text in texts:
        for match in WORD_RE.finditer(text or ""):
            word = match.group(0)
            stem = _stem(word)
            if stem and stem in stems and stem not in labels:
                labels[stem] = word
    return [labels[stem] for stem in sorted(labels)][:limit]


def _stem_set(words) -> set[str]:
    """Normalise a word list to the same stems the checks compare."""
    return {stem for stem in (_stem(word) for word in words) if stem}


#: Stems, not words: "including" and "includ" must be the same term to a check.
WEAK_STEMS = _stem_set(WEAK_TERMS)
DECISION_STEMS = _stem_set(DECISION_VOCAB)
#: Agenda items that are open-ended by definition cannot be "off-topic".
GENERIC_AGENDA_RE = re.compile(r"any other (matter|item|business)|permission of the chair", re.I)


REFERENCE_MARKER_RE = re.compile(r"^(?:\d+(?:st|nd|rd|th)?|\d{4}|[ivxlc]+)$", re.I)


def _strong_terms(terms: set[str]) -> set[str]:
    """Content terms that carry meaning, used for coverage decisions.

    Dates, ordinals and meeting numbers ("3rd", "2026") are reference markers: an
    agenda title carries them, a discussion of that item rarely repeats them, and
    they say nothing about whether the discussion is on the right subject.
    """
    return {term for term in terms
            if term not in WEAK_STEMS and not REFERENCE_MARKER_RE.match(term)}


#: Below these word counts the offline rules cannot certify a match: there is not enough
#: text to compare, so the check asks for the record instead of reporting "aligned".
MIN_DISCUSSION_WORDS = 2
MIN_RESOLUTION_WORDS = 1


def _coverage(expected: set[str], actual: set[str]) -> float:
    if not expected:
        return 1.0
    return len(expected & actual) / len(expected)


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(text or "") if len(sentence.strip()) > 3]


def _missing_terms(expected: set[str], actual: set[str], *texts: str, limit: int = 6) -> list[str]:
    """Stems present in `expected` but absent from `actual`, quoted as readable words."""
    missing = expected - actual
    readable = _readable_terms(missing, *texts)
    return readable or sorted(missing)[:limit]


#: An outcome reading is only treated as *contradicting* another when the two cannot
#: both be true of the same decision ("noted the corrections and approved the minutes"
#: is perfectly normal; "deferred the item and approved it" is not).
OUTCOME_CONFLICTS = {
    frozenset({"approved", "deferred"}), frozenset({"approved", "rejected"}),
    frozenset({"noted", "rejected"}), frozenset({"deferred", "rejected"}),
}
#: Phrases that postpone a decision even though no outcome verb is used.
DEFERRAL_CUES = (
    "could not", "cannot be", "can not be", "unable to", "not finali", "could not be finali",
    "could not complete", "could not be complete", "could not verify", "not be verified",
    "not be taken", "no decision", "awaiting", "still being verified", "still being computed",
    "carried forward", "carried over", "deferred", "postponed", "held over", "left to the department office",
    "before any decision",
)
NEGATED_APPROVAL = ("not approved", "did not approve", "was not approve", "were not approve",
                    "not be approved", "did not accept", "not accepted")
#: "the plans had not been submitted", "the report was not yet consolidated" - the record
#: itself says the item could not be decided at that meeting.
#: "...the remaining course owners will present their plans at the next meeting".
DEFERRAL_TRAILING = re.compile(
    r"\b(?:remaining|pending|balance|left over|rest)\b[^.]{0,80}\bnext meeting\b", re.I)
DEFERRAL_PATTERN = re.compile(
    r"\bnot (?:yet )?(?:been |be )?(?:submit|finalis|finaliz|consolidat|compil|verif|comput|receiv|"
    r"available|placed|circulat|complete)", re.I)


DECISION_VERB_RE = re.compile(
    r"\b(approv\w*|adopt\w*|ratif\w*|sanction\w*|implement\w*|resolv\w*|resolved|direct\w*|reject\w*)\b", re.I)


def _trailing_deferral(text: str) -> bool:
    """'pending items ... at the next meeting' only reads as a deferral when the sentence
    does not itself record a decision ("directed that the pending action be completed")."""
    for sentence in _sentences(text):
        if not DEFERRAL_TRAILING.search(sentence):
            continue
        if DECISION_VERB_RE.search(sentence) and not re.search(
                r"\b(deferred|postponed|carried forward|could not|not be taken)\b", sentence, re.I):
            continue
        return True
    return False


def _outcome(text: str) -> str | None:
    value = (text or "").lower()
    terms = _normalized_terms(value)
    if any(cue in value for cue in NEGATED_APPROVAL):
        return "rejected"
    if "reject" in terms or "decline" in terms:
        return "rejected"
    if ("defer" in terms or any(cue in value for cue in DEFERRAL_CUES)
            or DEFERRAL_PATTERN.search(value) or _trailing_deferral(value)):
        return "deferred"
    if "approve" in terms or "implement" in terms:
        return "approved"
    if any(cue in value for cue in ("support", "endorse", "in favour", "favourab", "welcomed the proposal")):
        return "approved"
    if "note" in terms:
        return "noted"
    if "refer" in terms:
        return "referred"
    return None


#: Opposite directions. A resolution that flips the direction of a figure the discussion
#: reported is almost always a transcription error, so it is worth naming explicitly.
POLARITY = (
    ("increas", "decreas"), ("increas", "reduc"), ("increas", "cut"), ("raise", "reduc"),
    ("raise", "cut"), ("raise", "lower"), ("decreas", "increas"), ("reduc", "increas"),
    ("cut", "increas"), ("reduc", "raise"), ("cut", "raise"), ("lower", "raise"),
    ("extend", "shorten"), ("increase", "slash"), ("approve", "not approve"),
)


def _polarity(text: str) -> set[str]:
    value = (text or "").lower()
    found = set()
    for left, right in POLARITY:
        if left in value:
            found.add((left, right))
    return found


NUMBER_WORDS = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20",
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80",
    "ninety": "90", "hundred": "100",
}


def _numbers(text: str) -> set[str]:
    values = {match.group(0).strip(".,") for match in NUMBER_RE.finditer(text or "")}
    values |= {re.sub(r"\s+", "", match.group(0)).upper() for match in CODE_RE.finditer(text or "")}
    values |= {NUMBER_WORDS[word] for word in re.findall(r"[a-z]+", (text or "").lower()) if word in NUMBER_WORDS}
    return {value for value in values if len(value) > 1 or value.isdigit()}


#: Decision vocabulary. A resolution is *expected* to contain these words and a
#: discussion of the same item need not, so they must not count as "content the
#: discussion never mentioned" — otherwise every terse but honest resolution
#: ("the committee approved the proposals placed before it") is flagged.
DECISION_VOCAB = {
    "adopt", "agree", "approv", "approve", "decid", "decision", "direct", "implement",
    "accept", "endors", "endorse", "ratif", "record", "note", "recommend", "resolv",
    "resolve", "sanction", "support", "welcom", "allow", "permit", "reject", "return",
    "plan", "proceed", "continu", "continue", "request", "member", "members", "committee",
    "matter", "item", "point", "accord", "accordance", "princip", "accordingli",
    "accordingly", "effect", "forthcom", "forthcoming", "ensur", "ensure", "also", "may",
}


#: Procedural tails that appear in honest resolutions and carry no verifiable content:
#: "the matter will be placed before the committee again at the next meeting".
PROCEDURAL_WORDS = (
    "again", "next", "meeting", "place", "placed", "put", "forward", "information",
    "record", "due", "course", "time", "confirm", "confirmation", "according",
    "henceforth", "herein", "herewith", "above", "aforesaid", "unanimous", "unanimously",
    "resolution", "resolutions", "minutes", "circulated", "circulation", "intimated",
    "communicated", "follow", "following", "follows", "regard", "reference", "refer",
)
DECISION_VOCAB |= {stem for stem in (_stem(word) for word in PROCEDURAL_WORDS) if stem}


def _content_terms(text: str) -> set[str]:
    """Meaning-carrying stems of a text, with the decision vocabulary removed."""
    return {term for term in _normalized_terms(text) if term not in DECISION_VOCAB}


def _is_unsupported(sentence: str, support_sentences: list[str], support_strong: set[str]) -> bool:
    """A resolution sentence is unsupported only when it carries content the record lacks."""
    content = _strong_terms(_content_terms(sentence))
    if not content:
        return False                     # decision or procedural wording only
    if content <= support_strong:
        return False                     # every content word is already on the record
    return _sentence_support(sentence, support_sentences) < 0.05


THRESHOLD_RE = re.compile(r"(?:%s)\s+(\d{1,3})\s*(?:per\s*cent|percent|%%)?" % "|".join(
    ("above", "more than", "over", "at least", "minimum", "not less than", "below", "less than", "under",
     "at most", "maximum", "not more than")), re.I)


def _thresholds(text: str, cues: tuple[str, ...]) -> list[tuple[str, str]]:
    """'below seventy per cent' → ('70', 'below seven...') for near-threshold comparison."""
    values: list[tuple[str, str]] = []
    for match in THRESHOLD_RE.finditer(text or ""):
        number = match.group(1)
        cue = match.group(0).lower().split()[0]
        if cue not in cues:
            continue
        values.append((number, number))
    for word, digit in NUMBER_WORDS.items():
        for cue in cues:
            if re.search(rf"\b{re.escape(cue)}\s+{word}\b", (text or ""), re.I) or \
               re.search(rf"\b{re.escape(cue)}\s+{word}\s*-", (text or ""), re.I):
                values.append((digit, digit))
    return values


def _sentence_support(sentence: str, discussion_sentences: list[str]) -> float:
    """Best lexical coverage a discussion sentence gives to one resolution sentence."""
    terms = _strong_terms(_normalized_terms(sentence))
    if not terms:
        return 1.0
    best = 0.0
    for candidate in discussion_sentences:
        best = max(best, _coverage(terms, _normalized_terms(candidate)))
    return best


def _check(name: str, status: str, score: int, message: str, evidence: str, suggestion: str,
           findings: list[str] | None = None) -> dict:
    check = {
        "name": name,
        "status": status,
        "score": max(0, min(100, int(score))),
        "message": message,
        "evidence": evidence,
        "suggestion": suggestion,
        "source": "offline-rules",
    }
    if findings:
        check["findings"] = findings
    return check


def check_item(item: dict, index: int) -> dict:
    """Run every offline check for one agenda item."""
    title = str(item.get("title") or f"Agenda {index}").strip()
    discussion = str(item.get("discussion") or "").strip()
    resolution = item_resolution(item)
    no_resolution = item_has_no_resolution(item)

    agenda_terms = _normalized_terms(title)
    discussion_terms = _normalized_terms(discussion)
    resolution_terms = _normalized_terms(resolution)
    # A title such as "Approval of the previous minutes" is made of nothing but decision
    # vocabulary, which leaves no strong terms to compare against. Falling back to the
    # full term set keeps the check honest: it used to score 0 and still report "aligned",
    # because an empty comparison was treated as perfect agreement.
    agenda_strong = _strong_terms(agenda_terms) or agenda_terms
    discussion_strong = _strong_terms(discussion_terms)

    ad_score = _coverage(agenda_terms, discussion_terms)
    ad_strong = _coverage(agenda_strong, discussion_strong)
    ar_score = _coverage(agenda_terms, resolution_terms)

    checks: list[dict] = []
    generic_agenda = bool(GENERIC_AGENDA_RE.search(title))
    discussion_words = len(re.findall(r"[A-Za-z0-9]+", discussion))
    resolution_words = len(re.findall(r"[A-Za-z0-9]+", resolution))

    # 1. Agenda -> Discussion
    agenda_is_weak_only = not _strong_terms(agenda_terms)
    if generic_agenda and discussion:
        checks.append(_check(
            "Agenda ↔ Discussion", "aligned", 100,
            "This agenda item is open-ended (\u201cany other matter\u201d), so no subject match is expected or required.",
            discussion[:240],
            "No change required by this check.",
        ))
    elif not discussion:
        checks.append(_check(
            "Agenda ↔ Discussion", "needs_revision", 0,
            "Discussion is empty. Record what the committee actually deliberated; do not infer it from the agenda.",
            "No discussion text was supplied.",
            f"Add the recorded deliberation that addresses \u201c{title or 'this agenda item'}\u201d.",
        ))
    elif agenda_is_weak_only:
        if ad_score < 0.05:
            checks.append(_check(
                "Agenda ↔ Discussion", "needs_revision", round(ad_score * 100),
                "The discussion does not appear to address this agenda item: the distinctive terms of the agenda are absent from the recorded discussion.",
                f"Agenda: {title[:180]} | Discussion: {discussion[:180]}",
                f"Confirm the discussion belongs to this agenda item. Terms not found in the discussion: {', '.join(_missing_terms(agenda_terms, discussion_terms, title, discussion)) or 'n/a'}.",
                findings=[f"Agenda term not found in discussion: \u201c{term}\u201d" for term in _missing_terms(agenda_terms, discussion_terms, title, discussion, limit=4)],
            ))
        elif ad_score < 0.085:
            checks.append(_check(
                "Agenda ↔ Discussion", "review", round(ad_score * 100),
                "Some agenda terms appear in the discussion, but the link between the agenda question and the recorded deliberation is partial.",
                f"Agenda: {title[:160]} | Discussion: {discussion[:160]}",
                "Check that the discussion answers the agenda question itself, not just a shared keyword.",
                findings=[f"Agenda term not found in discussion: \u201c{term}\u201d" for term in _missing_terms(agenda_terms, discussion_terms, title, discussion, limit=4)],
            ))
        else:
            checks.append(_check(
                "Agenda ↔ Discussion", "aligned", round(ad_score * 100),
                "The recorded discussion reflects the distinctive terms of the agenda item.",
                discussion[:240],
                "No change required by this check.",
            ))
    elif ad_strong < 0.05 and ad_score < 0.075:
        checks.append(_check(
            "Agenda ↔ Discussion", "needs_revision", round(ad_score * 100),
            "The discussion does not appear to address this agenda item: the distinctive terms of the agenda are absent from the recorded discussion.",
            f"Agenda: {title[:180]} | Discussion: {discussion[:180]}",
            f"Confirm the discussion belongs to this agenda item. Terms not found in the discussion: {', '.join(_missing_terms(agenda_strong, discussion_strong, title, discussion)) or 'n/a'}.",
            findings=[f"Agenda term not found in discussion: \u201c{term}\u201d" for term in _missing_terms(agenda_strong, discussion_strong, title, discussion, limit=4)],
        ))
    elif ad_strong < 0.085:
        checks.append(_check(
            "Agenda ↔ Discussion", "review", round(ad_score * 100),
            "Some agenda terms appear in the discussion, but the link between the agenda question and the recorded deliberation is partial.",
            f"Agenda: {title[:160]} | Discussion: {discussion[:160]}",
            "Check that the discussion answers the agenda question itself, not just a shared keyword.",
            findings=[f"Agenda term not found in discussion: \u201c{term}\u201d" for term in _missing_terms(agenda_strong, discussion_strong, title, discussion, limit=4)],
        ))
    else:
        checks.append(_check(
            "Agenda ↔ Discussion", "aligned", round(ad_score * 100),
            "The recorded discussion reflects the distinctive terms of the agenda item.",
            discussion[:240],
            "No change required by this check.",
        ))

    # 2. Discussion -> Resolution
    unsupported: list[str] = []
    if no_resolution and not resolution:
        checks.append(_check(
            "Discussion ↔ Resolution", "aligned", 100,
            "No separate resolution was recorded for this agenda item; nothing needs to be supported.",
            "Author marked this item as having no separate resolution.",
            "No resolution text is required unless the committee recorded one.",
        ))
    elif not resolution:
        checks.append(_check(
            "Discussion ↔ Resolution", "review", 0,
            "Resolution is empty. Confirm whether the committee recorded an outcome or decision.",
            "No resolution text was supplied.",
            "Record the actual outcome, or mark that no separate resolution was recorded.",
        ))
    elif not discussion:
        checks.append(_check(
            "Discussion ↔ Resolution", "needs_revision", 0,
            "A resolution is present, but there is no written discussion to support it.",
            resolution[:240],
            "Add the recorded discussion, or revise the resolution to reflect what was documented.",
        ))
    else:
        # A resolution may legitimately restate the agenda and use decision vocabulary,
        # so support is measured against the discussion *and* the agenda item, on
        # content words only. Otherwise nearly every honest resolution is flagged.
        support_strong = discussion_strong | agenda_strong
        resolution_content = _strong_terms(_content_terms(resolution))
        dr_content = _coverage(resolution_content, support_strong)
        if not resolution_content:
            # Nothing but decision vocabulary: a plain "approved the proposals" outcome,
            # which is grounded by construction and covered by the outcome check below.
            dr_content = 1.0
        support_sentences = _sentences(discussion) + [title]
        for sentence in _sentences(resolution):
            if _is_unsupported(sentence, support_sentences, support_strong):
                unsupported.append(sentence)
        # A single stray sentence is not evidence of a problem; two or more, or a
        # resolution whose content words are absent from the whole record, is.
        if dr_content < 0.05 and len(unsupported) >= 2:
            checks.append(_check(
                "Discussion ↔ Resolution", "needs_revision", round(dr_content * 100),
                "The resolution contains content that does not appear in the discussion and may be unsupported by the record.",
                f"Discussion: {discussion[:150]} | Resolution: {resolution[:150]}",
                "Point to the recorded discussion that supports this resolution. Do not add a new decision that was not discussed.",
                findings=[f"Unsupported resolution sentence: “{sentence[:120]}”" for sentence in unsupported[:3]]
                + [f"Resolution term not found in the discussion or the agenda: “{term}”"
                   for term in _missing_terms(resolution_content, support_strong, resolution, title, limit=3)],
            ))
        elif dr_content < 0.05 or unsupported or any(
                _sentence_support(sentence, support_sentences) < 0.075
                and re.search(r"\b(approv|adopt|ratif|sanction|implement|authoris|authoriz|transfer|reject|defer)\w*",
                              sentence, re.I)
                for sentence in _sentences(resolution)):
            checks.append(_check(
                "Discussion ↔ Resolution", "review", round(dr_content * 100),
                "The resolution has some textual support in the discussion, but a reviewer should confirm the reasoning.",
                f"Discussion: {discussion[:150]} | Resolution: {resolution[:150]}",
                "Make the link between the deliberation and the resolution explicit where the record supports it.",
                findings=[f"Unsupported resolution sentence: “{sentence[:120]}”" for sentence in unsupported[:3]]
                + [f"Resolution term not found in the discussion or the agenda: “{term}”"
                   for term in _missing_terms(resolution_content, support_strong, resolution, title, limit=3)],
            ))
        else:
            checks.append(_check(
                "Discussion ↔ Resolution", "aligned", round(dr_content * 100),
                "Every content word in the resolution also appears in the recorded discussion or the agenda item.",
                f"Discussion: {discussion[:150]} | Resolution: {resolution[:150]}",
                "No change required by this check.",
            ))

    # 2b. A record this thin cannot be certified as aligned — nothing was written to
    #     compare. Both checks drop to "review" with the word count as the reason, which
    #     asks the Secretary for the real record instead of inventing a verdict.
    if discussion and not generic_agenda and discussion_words < MIN_DISCUSSION_WORDS:
        for check in checks:
            if check["name"] == "Agenda ↔ Discussion" and check["status"] == "aligned":
                check["status"] = "review"
                check["message"] = (f"The discussion is very brief ({discussion_words} word"
                                    f"{'' if discussion_words == 1 else 's'}), so it cannot be confirmed to "
                                    "address the agenda item.")
                check["suggestion"] = ("Record what the committee actually deliberated, in enough detail "
                                       "for a reader of the minutes to follow the reasoning.")
    if resolution and not no_resolution and resolution_words < MIN_RESOLUTION_WORDS:
        for check in checks:
            if check["name"] == "Discussion ↔ Resolution" and check["status"] == "aligned":
                check["status"] = "review"
                check["message"] = (f"The resolution is a bare acknowledgement ({resolution_words} word"
                                    f"{'' if resolution_words == 1 else 's'}), not a recorded decision.")
                check["suggestion"] = ("State the decision the committee actually took, so the minutes "
                                       "record an outcome rather than an acknowledgement.")

    # 3. Agenda -> Resolution (only meaningful when a resolution exists)
    if resolution and agenda_terms and not generic_agenda and ar_score < 0.06 and ad_strong < 0.11:
        checks.append(_check(
            "Agenda ↔ Resolution", "review", round(ar_score * 100),
            "The resolution may not answer the agenda item it sits under.",
            resolution[:220],
            "Confirm that this outcome responds to the agenda question.",
        ))

    # 4. Numeric / factual consistency (numbers, marks, credits, course codes)
    resolution_numbers = _numbers(resolution)
    if resolution_numbers:
        discussion_numbers = _numbers(discussion) | _numbers(title)
        new_numbers = sorted(resolution_numbers - discussion_numbers)
        if new_numbers and not no_resolution:
            checks.append(_check(
                "Numeric / factual consistency", "review", 0,
                "The resolution states figures, dates or course codes that do not appear in the agenda or the discussion.",
                "Not found in agenda/discussion: " + ", ".join(new_numbers[:8]),
                "Verify each figure against the record. Numbers that appear only in the resolution are the most common source of MoM errors.",
                findings=[f"Unverified figure in resolution: “{value}”" for value in new_numbers[:5]],
            ))

    # 4b. A figure the discussion reports in one direction, flipped in the resolution
    shared_numbers = resolution_numbers & _numbers(discussion)
    if shared_numbers and not no_resolution:
        discussion_directions = _polarity(discussion)
        resolution_directions = _polarity(resolution)
        flipped = {(left, right) for (left, right) in resolution_directions
                   if any(other_left in {"reduc", "decreas", "cut", "lower", "shorten", "slash"}
                          and left in {"increas", "raise", "extend"} for other_left, _ in discussion_directions)
                   or any(other_left in {"increas", "raise", "extend"}
                          and left in {"reduc", "decreas", "cut", "lower", "shorten", "slash"}
                          for other_left, _ in discussion_directions)}
        if flipped:
            checks.append(_check(
                "Numeric / factual consistency", "needs_revision", 0,
                "The resolution reverses the direction of a figure the discussion reports (for example a reduction "
                "recorded as an increase).",
                f"Discussion: {discussion[:180]} | Resolution: {resolution[:180]}",
                "Confirm the direction of the figure against the record; this is the most common transcription error.",
                findings=[f"Direction conflict on {', '.join(sorted(shared_numbers)[:4])}"],
            ))

    # 4c. A threshold stated in the opposite direction from the discussion's threshold
    up = _thresholds(resolution, ("above", "more than", "over", "at least", "minimum", "not less than"))
    down = _thresholds(discussion, ("below", "less than", "under", "at most", "maximum", "not more than"))
    near = [(value, other) for value, _ in up for other, _ in down
            if abs(float(value) - float(other)) <= 10]
    if near and not no_resolution:
        checks.append(_check(
            "Numeric / factual consistency", "review", 0,
            "A cut-off is stated in the opposite direction from the discussion: the record describes who fell below a "
            "threshold, the resolution describes who was above a similar one.",
            f"Discussion: {discussion[:180]} | Resolution: {resolution[:180]}",
            "Re-check which students or items met the condition before signing the minutes.",
            findings=[f"Threshold in the resolution: above {near[0][0]} · threshold in the discussion: below {near[0][1]}"],
        ))

    # 5. Outcome consistency
    discussion_outcome = _outcome(discussion)
    resolution_outcome = _outcome(resolution)
    if (discussion_outcome and resolution_outcome
            and frozenset((discussion_outcome, resolution_outcome)) in OUTCOME_CONFLICTS):
        checks.append(_check(
            "Outcome consistency", "needs_revision", 0,
            f"Possible outcome conflict: the discussion reads as {discussion_outcome}, while the resolution reads as {resolution_outcome}.",
            f"Discussion: {discussion[:180]} | Resolution: {resolution[:180]}",
            "Verify the committee's recorded outcome and correct the text; this check cannot determine which version is true.",
        ))

    status_rank = {"aligned": 0, "review": 1, "needs_revision": 2}
    overall = max((check["status"] for check in checks), key=lambda status: status_rank[status])
    return {
        "agendaNo": int(item.get("agendaNo") or index),
        "agendaTitle": title,
        "status": overall,
        "checks": checks,
    }


def check_items(items: list[dict]) -> dict:
    """Run the offline engine over every agenda item and summarise the result."""
    results = [check_item(item, index) for index, item in enumerate(items or [], start=1)]
    return {
        "mode": "offline-rules",
        "engine": "Offline review rules (deterministic, no model)",
        "summary": {
            "items": len(results),
            "aligned": sum(row["status"] == "aligned" for row in results),
            "review": sum(row["status"] == "review" for row in results),
            "needsRevision": sum(row["status"] == "needs_revision" for row in results),
        },
        "items": results,
        "notice": "Offline word-overlap rules only. They cannot verify what was actually said in the meeting and cannot establish academic truth.",
    }
