"""AI content verification for Discussion and Resolution text.

Two review questions are asked of every agenda item:

1. **Discussion based on Agenda** - does the recorded deliberation address the
   approved agenda item?
2. **Resolution based on Discussion** - is the recorded resolution grounded in
   the discussion that precedes it (and is it free of content that nothing in
   the record supports)?

Design notes
------------
* **Hybrid by default.** When an API key is configured the text is sent to a
  hosted model (OpenAI-compatible, Azure OpenAI or Google Gemini) and the model
  returns structured findings. When no key is configured - or when the call
  fails - the transparent offline engine in :mod:`content_check` runs instead,
  so the feature always works.
* **Human in the loop.** The model is instructed never to rewrite or invent
  record text. It returns a status, a score, verbatim evidence and a
  conditional human-review suggestion. Suggestions never edit the MoM.
* **Only standard library HTTP.** No extra dependency is added for the call.

Configuration (environment variables)
-------------------------------------
``AI_PROVIDER``                 ``auto`` (default), ``openai``, ``azure``,
                               ``gemini`` or ``offline``.
``AI_API_KEY``                  generic key (or provider-specific keys below).
``OPENAI_API_KEY`` / ``AZURE_OPENAI_API_KEY`` / ``GEMINI_API_KEY`` (or
``GOOGLE_API_KEY``) are also read.
``AI_MODEL``                    model id (defaults per provider).
``AI_BASE_URL``                 OpenAI-compatible base URL.
``AZURE_OPENAI_ENDPOINT``       e.g. ``https://my-resource.openai.azure.com``.
``AZURE_OPENAI_DEPLOYMENT``     deployment name.
``AZURE_OPENAI_API_VERSION``    defaults to ``2024-08-01-preview``.
``AI_TIMEOUT``                  seconds per request (default 45).
``AI_MAX_ITEMS``                agenda items per request (default 12).
``AI_ALLOW_CONTENT_UPLOAD``     set to ``0`` to forbid sending MoM text to a
                               hosted model even when a key exists.
``AI_ENV_FILE``                 path to a different ``.env`` file. Defaults to
                               ``.env`` beside ``app.py``. Tests and side-by-side
                               deployments use it to keep their settings apart.
"""
from __future__ import annotations

import json
import os
import re
import time as time_module
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from content_check import check_item, check_items
from doc_theme import BODY_SIZE, FAMILY_NAME, HEADING_SIZE, LINE_SPACING
from mom_shared import item_resolution

# Gemini model ids, in the order the client tries them. The first entry is the
# default when ``AI_MODEL`` is unset. Ordering matters: ``-latest`` aliases track
# Google's current release, and the pinned ids cover the case where an alias is
# throttled or a pinned id is retired for a given key.
GEMINI_MODEL_CHAIN = (
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
)
# HTTP statuses that mean "this model, not this key": try the next id in the chain.
GEMINI_RETRY_STATUSES = frozenset({404, 429, 500, 502, 503})
# Seconds allowed per model attempt, so one hung model cannot consume AI_TIMEOUT.
GEMINI_ATTEMPT_TIMEOUT = 15.0

COLLEGE_TZ = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = Path(os.environ.get("AI_ENV_FILE") or (PROJECT_ROOT / ".env"))


def load_env_file(path: Path | None = None) -> bool:
    """Populate os.environ from a simple KEY=VALUE ``.env`` file.

    This exists so "just add the API key" works even when the key is dropped in a
    file instead of exported in the shell. Real environment variables always win,
    so a shell export or a systemd/container setting overrides the file.
    """
    target = Path(path or ENV_FILE)
    loaded = False
    if not target.is_file():
        return False
    try:
        for raw_line in target.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[7:].strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded = True
    except OSError:
        return False
    return loaded


ENV_FILE_LOADED = load_env_file()

STATUS_ALIASES = {
    "aligned": "aligned", "ok": "aligned", "pass": "aligned", "passed": "aligned",
    "supported": "aligned", "good": "aligned", "consistent": "aligned",
    "review": "review", "needs_review": "review", "needs review": "review",
    "warning": "review", "warn": "review", "partial": "review", "unclear": "review",
    "needs_revision": "needs_revision", "needs revision": "needs_revision",
    "revision": "needs_revision", "fail": "needs_revision", "failed": "needs_revision",
    "unsupported": "needs_revision", "conflict": "needs_revision", "error": "needs_revision",
}
STATUS_RANK = {"aligned": 0, "review": 1, "needs_revision": 2}
CORE_CHECKS = ("Agenda ↔ Discussion", "Discussion ↔ Resolution")

SYSTEM_PROMPT = (
    "You verify the internal consistency of Minutes of Meeting (MoM) records written for a "
    "college Departmental Academic Committee (DAC). You are a review assistant, not a decision "
    "maker, and you never rewrite or improve the record.\n"
    "\n"
    "For each agenda item you receive the approved agenda wording, the recorded Discussion and "
    "the recorded Resolution. Perform exactly these checks:\n"
    "1. \"Agenda ↔ Discussion\" - does the written Discussion address the agenda item that it is "
    "recorded under? Look for the subject, the intended outcome and the agenda's distinctive "
    "terms, not merely one shared keyword.\n"
    "2. \"Discussion ↔ Resolution\" - is the written Resolution grounded in the written "
    "Discussion? Flag content in the Resolution (decisions, figures, approvals, names, courses, "
    "dates) that the Discussion does not support, and flag outcome conflicts such as a "
    "discussion that reads as deferred while the resolution reads as approved.\n"
    "You may add \"Agenda ↔ Resolution\" when the resolution appears not to answer the agenda "
    "item, and \"Numeric / factual consistency\" when figures, credits, marks or course codes in "
    "the resolution cannot be found in the agenda or discussion.\n"
    "\n"
    "Rules:\n"
    "- Judge only the supplied text. You cannot know what was actually said in the meeting, so "
    "never claim to verify facts; describe what the written record does or does not support.\n"
    "- Quote evidence verbatim from the supplied text. Never invent quotes.\n"
    "- Suggestions must be conditional review prompts for a human, never edited text. Do not "
    "write replacement minutes, do not add facts and do not give legal or academic verdicts.\n"
    "- If the author marked that no separate resolution was recorded, treat that as valid and do "
    "not demand a resolution.\n"
    "- An empty discussion or resolution must be reported honestly as empty.\n"
    "- Score 0-100 as a rough proportion of the check that is satisfied.\n"
    "- Reply with JSON only, no prose outside the JSON."
)

RESPONSE_SCHEMA_HINT = (
    "Return JSON with this exact shape:\n"
    '{"items":[{"agendaNo":1,"agendaTitle":"...","status":"aligned|review|needs_revision",'
    '"checks":[{"name":"Agenda ↔ Discussion","status":"aligned|review|needs_revision","score":0,'
    '"message":"one or two sentences for a reviewer","evidence":"verbatim quote(s) from the '
    'supplied text","suggestion":"conditional human-review prompt or \'No change required by this '
    'check.\'","findings":["short bullet, optional"]}]}],"summaryNote":"optional one-line note"}\n'
    "Include every agenda item you were given, in the same order, with the same agendaNo."
)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def _truthy(value: str, default: bool = True) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on"}


def provider_config() -> dict:
    """Resolve the configured verification provider from the environment."""
    requested = (_env("AI_PROVIDER", "auto") or "auto").lower()
    if requested not in {"auto", "openai", "azure", "gemini", "offline"}:
        requested = "auto"

    generic_key = _env("AI_API_KEY")
    openai_key = _env("OPENAI_API_KEY") or generic_key
    azure_key = _env("AZURE_OPENAI_API_KEY") or generic_key
    gemini_key = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY") or generic_key

    azure_endpoint = _env("AZURE_OPENAI_ENDPOINT")
    azure_deployment = _env("AZURE_OPENAI_DEPLOYMENT")
    azure_ready = bool(azure_key and azure_endpoint and azure_deployment)

    candidates = {
        "azure": azure_ready,
        "openai": bool(openai_key),
        "gemini": bool(gemini_key),
    }
    if requested != "auto":
        provider = requested if requested != "offline" else "offline"
    else:
        provider = next((name for name in ("azure", "openai", "gemini") if candidates[name]), "offline")

    if not _truthy(_env("AI_ALLOW_CONTENT_UPLOAD"), True):
        provider = "offline"

    default_models = {"openai": "gpt-4o-mini", "azure": azure_deployment or "gpt-4o-mini", "gemini": GEMINI_MODEL_CHAIN[0]}
    key = {"openai": openai_key, "azure": azure_key, "gemini": gemini_key, "offline": ""}.get(provider, "")
    if provider == "azure" and not azure_ready:
        provider, key = "offline", ""
    elif provider in {"openai", "gemini"} and not key:
        # A provider was requested by name but its key is missing: stay offline
        # instead of sending an unauthenticated request.
        provider, key = "offline", ""

    return {
        "requested": requested,
        "provider": provider,
        "model": _env("AI_MODEL") or default_models.get(provider, ""),
        "apiKey": key,
        "baseUrl": _env("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "azureEndpoint": azure_endpoint.rstrip("/"),
        "azureDeployment": azure_deployment,
        "azureApiVersion": _env("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        "timeout": float(_env("AI_TIMEOUT", "45") or 45),
        "maxItems": max(1, int(float(_env("AI_MAX_ITEMS", "12") or 12))),
    }


def provider_status() -> dict:
    """Sanitised provider status for the API and UI (never exposes the key)."""
    config = provider_config()
    online = config["provider"] != "offline"
    key_present = bool(_env("AI_API_KEY") or _env("OPENAI_API_KEY") or _env("AZURE_OPENAI_API_KEY")
                       or _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY"))
    return {
        "provider": config["provider"],
        "requested": config["requested"],
        "model": config["model"] if online else "",
        "online": online,
        "label": {
            "openai": "OpenAI-compatible model",
            "azure": "Azure OpenAI deployment",
            "gemini": "Google Gemini model",
            "offline": "Offline review rules (no model connected)",
        }.get(config["provider"], config["provider"]),
        "keyPresent": key_present,
        "envFile": str(ENV_FILE) if ENV_FILE.is_file() else "",
        "envFileLoaded": ENV_FILE_LOADED,
        "detail": (
            f"Text is sent to {config['provider']} ({config['model']}) for review."
            if online else
            (
                f"AI_PROVIDER={config['requested']} is set but no usable API key was found, so the offline rules run. "
                "Add the key to the environment or to a .env file next to app.py, then restart the API."
                if config["requested"] not in {"auto", "offline"} else
                "No AI key is configured (or content uploads are disabled), so the deterministic offline rules run instead. "
                "Set AI_API_KEY (or OPENAI_API_KEY / AZURE_OPENAI_API_KEY / GEMINI_API_KEY) and restart to use a model."
            )
        ),
    }


def _agenda_payload(items: list[dict], meeting: dict | None) -> list[dict]:
    payload = []
    for index, item in enumerate(items or [], start=1):
        payload.append({
            "agendaNo": int(item.get("agendaNo") or index),
            "agendaTitle": str(item.get("title") or f"Agenda {index}").strip(),
            "discussion": str(item.get("discussion") or "").strip(),
            "resolution": item_resolution(item),
            "noSeparateResolutionRecorded": bool(item.get("noResolution") or item.get("noRecommendation")),
        })
    return payload


def _user_prompt(items: list[dict], meeting: dict | None) -> str:
    meeting = meeting or {}
    context = ""
    if meeting:
        context = (
            "Meeting context (for tone only, do not verify it):\n"
            f"- School: {meeting.get('school', '')}\n"
            f"- Department: {meeting.get('department', '')}\n"
            f"- Meeting number: {meeting.get('meetingNo', '')}\n"
            f"- Date: {meeting.get('date', '')}\n"
            f"- Academic year / semester: {meeting.get('academicYear', '')} / {meeting.get('semester', '')}\n\n"
        )
    return (
        f"{context}Agenda items to verify (JSON):\n"
        f"{json.dumps({'items': _agenda_payload(items, meeting)}, ensure_ascii=False, indent=1)}\n\n"
        f"{RESPONSE_SCHEMA_HINT}"
    )


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed https endpoint
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body)


def _call_openai(messages: list[dict], config: dict) -> str:
    if config["provider"] == "azure":
        url = (f"{config['azureEndpoint']}/openai/deployments/{config['azureDeployment']}"
               f"/chat/completions?api-version={config['azureApiVersion']}")
        headers = {"api-key": config["apiKey"]}
    else:
        url = f"{config['baseUrl']}/chat/completions"
        headers = {"Authorization": f"Bearer {config['apiKey']}"}
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    data = _post_json(url, payload, headers, config["timeout"])
    return str((data.get("choices") or [{}])[0].get("message", {}).get("content") or "")


def _gemini_generate(model: str, payload: dict, config: dict) -> dict:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
           f":generateContent?key={config['apiKey']}")
    return _post_json(url, payload, {}, config["timeout"])


def _call_gemini(messages: list[dict], config: dict) -> str:
    """Call Gemini, walking the model chain when a model id is unusable.

    Google retires model ids (404 ``NOT_FOUND``) and throttles busy ones (429/503).
    A valid key must not fail just because the configured or default model id went
    away, so the caller tries the remaining ids in :data:`GEMINI_MODEL_CHAIN` and
    records the id that actually answered in ``config['model']``.
    """
    system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
    user = "\n\n".join(message["content"] for message in messages if message["role"] != "system")
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    preferred = str(config.get("model") or "").strip()
    chain = [name for name in dict.fromkeys([preferred, *GEMINI_MODEL_CHAIN]) if name]
    # Give each attempt its own slice of the budget: a throttled alias can hang
    # instead of answering, and one hung request must not consume the whole timeout.
    attempt_timeout = max(5.0, min(float(config["timeout"]), GEMINI_ATTEMPT_TIMEOUT))
    last_error: Exception | None = None
    for index, model in enumerate(chain):
        attempt = {**config, "timeout": attempt_timeout}
        try:
            data = _gemini_generate(model, payload, attempt)
        except urllib.error.HTTPError as exc:
            if exc.code not in GEMINI_RETRY_STATUSES or index == len(chain) - 1:
                raise
            last_error = exc
            exc.close()
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # A timeout or dropped connection on one model id: try the next one.
            if index == len(chain) - 1:
                raise
            last_error = exc
            continue
        config["model"] = model
        config["tried"] = chain[:index + 1]
        candidates = data.get("candidates") or [{}]
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(str(part.get("text") or "") for part in parts)
    raise last_error if last_error else RuntimeError("No Gemini model could be reached.")


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"```\s*$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"The model reply was not valid JSON: {exc}") from exc
    raise ValueError("The model reply contained no JSON object.")


def _coerce_status(value) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return STATUS_ALIASES.get(text, STATUS_ALIASES.get(text.replace("_", " "), "review"))


def _coerce_score(value) -> int:
    match = re.search(r"-?\d+(\.\d+)?", str(value if value is not None else ""))
    if not match:
        return 0
    return max(0, min(100, int(round(float(match.group(0))))))


def _clean_text(value, limit: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _normalize_check(raw: dict, name: str, fallback: dict | None, source: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    fallback = fallback or {}
    findings = raw.get("findings")
    if isinstance(findings, str):
        findings = [findings]
    clean_findings = [_clean_text(entry, 200) for entry in (findings or []) if _clean_text(entry, 200)][:6]
    check = {
        "name": name,
        "status": _coerce_status(raw.get("status") or fallback.get("status")),
        "score": _coerce_score(raw.get("score") if raw.get("score") is not None else fallback.get("score")),
        "message": _clean_text(raw.get("message") or fallback.get("message"), 500) or "No explanation was returned.",
        "evidence": _clean_text(raw.get("evidence") or fallback.get("evidence"), 400),
        "suggestion": _clean_text(raw.get("suggestion") or fallback.get("suggestion"), 400) or "Review the record against the agenda and discussion.",
        "source": source,
    }
    if clean_findings:
        check["findings"] = clean_findings
    elif fallback.get("findings"):
        check["findings"] = fallback["findings"]
    return check


def _merge_model_output(raw_items: list, items: list[dict], meeting: dict | None, model_label: str) -> list[dict]:
    """Merge model output with the offline engine so nothing is ever missing."""
    offline_rows = [check_item(item, index) for index, item in enumerate(items or [], start=1)]
    by_number: dict[int, dict] = {}
    for position, entry in enumerate(raw_items or []):
        if not isinstance(entry, dict):
            continue
        number = _coerce_score(entry.get("agendaNo")) if entry.get("agendaNo") is not None else position + 1
        by_number.setdefault(int(number) or position + 1, entry)

    results = []
    for index, row in enumerate(offline_rows):
        number = row["agendaNo"]
        model_row = by_number.get(number) or (raw_items[index] if index < len(raw_items or []) and isinstance(raw_items[index], dict) else {})
        model_checks = {}
        for check in (model_row.get("checks") or []):
            if isinstance(check, dict) and check.get("name"):
                model_checks[str(check["name"]).strip().lower()] = check

        merged_checks = []
        used_model_names = set()
        for offline_check in row["checks"]:
            key = offline_check["name"].lower()
            model_check = model_checks.get(key)
            if model_check:
                used_model_names.add(key)
                merged = _normalize_check(model_check, offline_check["name"], offline_check, "ai-model")
                # A model must never be allowed to wave through something the deterministic
                # rules flagged: keep the more severe of the two verdicts and say so, because
                # these documents are a governance record. The model's own wording is kept
                # whenever it is at least as severe as the offline finding.
                if STATUS_RANK[offline_check["status"]] > STATUS_RANK[merged["status"]]:
                    offline_severity = dict(offline_check)
                    offline_severity["status"] = offline_check["status"]
                    offline_severity["message"] = (
                        f"{offline_check['message']} (the offline rules flagged this; the model did not.)")
                    offline_severity["source"] = "offline-rules"
                    offline_severity["modelStatus"] = merged["status"]
                    offline_severity["modelMessage"] = merged.get("message", "")
                    merged = offline_severity
                merged_checks.append(merged)
            else:
                offline_check = dict(offline_check)
                offline_check["source"] = "offline-rules"
                merged_checks.append(offline_check)

        # Keep any extra checks the model volunteered (e.g. factual consistency).
        for key, model_check in model_checks.items():
            if key in used_model_names:
                continue
            name = str(model_check.get("name") or "").strip() or "Model check"
            if name.lower() in {check["name"].lower() for check in merged_checks}:
                continue
            merged_checks.append(_normalize_check(model_check, name, None, "ai-model"))

        overall = max((check["status"] for check in merged_checks), key=lambda status: STATUS_RANK[status])
        results.append({
            "agendaNo": number,
            "agendaTitle": row["agendaTitle"],
            "status": overall,
            "checks": merged_checks,
        })

    # Safety net: the two core checks must always be present, even if the model
    # skipped one. Missing checks are filled from the offline engine and marked
    # with source "offline-rules" so the reviewer can see which engine ran.
    for index, row in enumerate(results):
        filled = {
            check["name"]: check for check in offline_rows[index]["checks"]
        }
        for name in CORE_CHECKS:
            if not any(check["name"] == name for check in row["checks"]) and name in filled:
                fallback_check = dict(filled[name])
                fallback_check["source"] = "offline-rules"
                row["checks"].append(fallback_check)
        row["status"] = max((check["status"] for check in row["checks"]), key=lambda status: STATUS_RANK[status])
    return results


def _summarise(results: list[dict]) -> dict:
    return {
        "items": len(results),
        "aligned": sum(row["status"] == "aligned" for row in results),
        "review": sum(row["status"] == "review" for row in results),
        "needsRevision": sum(row["status"] == "needs_revision" for row in results),
    }


def _offline_report(items: list[dict], reason: str | None = None) -> dict:
    report = check_items(items)
    report["generatedAt"] = datetime.now(COLLEGE_TZ).isoformat(timespec="seconds")
    report["provider"] = provider_status()
    report["notes"] = []
    if reason:
        report["fallbackReason"] = reason
        report["notes"].append(reason)
    return report


def probe() -> dict:
    """Send a one-line request to confirm the configured provider really answers.

    Used by the in-app "Test AI connection" button, so a wrong key, wrong model,
    missing Azure deployment or a blocked network is reported immediately instead
    of only appearing as a silent fallback during a review.
    """
    config = provider_config()
    status = provider_status()
    checked_at = datetime.now(COLLEGE_TZ).isoformat(timespec="seconds")
    if config["provider"] == "offline":
        return {
            "ok": False, "online": False, "checkedAt": checked_at, "provider": status,
            "message": status["detail"],
            "hint": "Verification still works: it runs the deterministic offline rules. No text leaves this machine.",
        }
    messages = [
        {"role": "system", "content": "You are a connectivity probe. Reply with JSON only, no prose."},
        {"role": "user", "content": 'Reply exactly with {"ok":true} and nothing else.'},
    ]
    started = time_module.perf_counter()
    try:
        raw = _call_gemini(messages, config) if config["provider"] == "gemini" else _call_openai(messages, config)
        elapsed = round((time_module.perf_counter() - started) * 1000)
        return {
            "ok": True, "online": True, "checkedAt": checked_at, "latencyMs": elapsed,
            "provider": status, "model": config["model"], "reply": _clean_text(raw, 120),
            "message": f"{config['provider']} answered in {elapsed} ms using {config['model']}. "
                       "AI-assisted verification is active; MoM text is sent to this provider when you run a review.",
        }
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = _clean_text(exc.read().decode("utf-8", errors="replace"), 240)
        except Exception:  # pragma: no cover - body already consumed
            detail = ""
        hints = {
            401: "The API key was rejected. Check for a typo, an expired key, or a key from a different provider.",
            403: "The key is valid but not authorised for this model or deployment.",
            404: "The model (or Azure deployment) name was not found. Check AI_MODEL / AZURE_OPENAI_DEPLOYMENT.",
            429: "Rate limit or quota reached for this key.",
        }
        return {
            "ok": False, "online": True, "checkedAt": checked_at, "httpStatus": exc.code,
            "provider": status, "model": config["model"],
            "message": f"The {config['provider']} request failed with HTTP {exc.code}. {detail}".strip(),
            "hint": hints.get(exc.code, "Check the provider status page and your account settings."),
        }
    except Exception as exc:
        return {
            "ok": False, "online": True, "checkedAt": checked_at, "provider": status, "model": config["model"],
            "message": f"The {config['provider']} request could not be completed: {exc}",
            "hint": "Check the base URL / endpoint, the network path from this machine, and AI_TIMEOUT.",
        }


def verify(mom_items: list[dict], meeting: dict | None = None) -> dict:
    """Verify every agenda item and return a UI-ready report.

    Uses the hosted model when one is configured, otherwise (or on any failure)
    the deterministic offline engine. The returned shape is stable across both.
    """
    items = list(mom_items or [])
    if not items:
        report = _offline_report([])
        report["notice"] = "No agenda items were supplied, so there was nothing to verify."
        return report

    config = provider_config()
    if config["provider"] == "offline":
        report = _offline_report(items)
        report["notice"] = (
            "Offline word-overlap rules only. They cannot verify what was actually said in the meeting and "
            "cannot establish academic truth. Configure an AI key (see README) to run model-assisted verification."
        )
        return report

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(items, meeting)},
    ]
    try:
        if config["provider"] == "gemini":
            raw_text = _call_gemini(messages, config)
        else:
            raw_text = _call_openai(messages, config)
        parsed = _extract_json(raw_text)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # pragma: no cover - body already consumed
            detail = ""
        return _offline_report(items, f"The {config['provider']} request failed with HTTP {exc.code}. {detail}".strip())
    except Exception as exc:
        return _offline_report(items, f"The {config['provider']} request could not be completed: {exc}")

    model_label = f"{config['provider']}:{config['model']}"
    raw_items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(raw_items, list) or not raw_items:
        return _offline_report(items, "The model reply did not contain any per-agenda findings.")

    results = _merge_model_output(raw_items, items, meeting, model_label)
    used_model = sum(1 for row in results for check in row["checks"] if check.get("source") == "ai-model")
    mode = "ai-model" if used_model else "offline-rules"
    notes = []
    if parsed.get("summaryNote"):
        notes.append(_clean_text(parsed["summaryNote"], 300))
    # The model answered, but nothing it said could be used, so every finding below comes
    # from the deterministic rules. Saying "model-assisted" here would misreport the
    # provenance of a governance record, so the reply is described as what it is.
    unusable_reason = None if used_model else (
        f"{config['provider']} replied, but its reply contained no usable per-agenda findings, "
        "so the deterministic rules produced every finding below."
    )
    if unusable_reason:
        notes.append(unusable_reason)
    styling = (f"Document styling: {FAMILY_NAME} {BODY_SIZE} pt, sub-headings {HEADING_SIZE} pt, "
               f"{LINE_SPACING} line spacing.")
    report = {
        "mode": mode,
        "engine": (f"AI-assisted verification · {config['provider']} {config['model']}" if used_model
                   else "Offline rules (the model replied, but nothing in its reply was usable)"),
        "model": model_label if used_model else "",
        "provider": provider_status(),
        "generatedAt": datetime.now(COLLEGE_TZ).isoformat(timespec="seconds"),
        "summary": _summarise(results),
        "items": results,
        "notes": notes,
        "notice": (
            (f"Model-assisted review of the written record using {config['provider']} ({config['model']}). "
             "The model reads the text you submitted; it cannot verify what was actually said in the meeting and "
             f"it never edits the record. Findings are prompts for human review only. {styling}")
            if used_model else
            ("Word-overlap rules only, because the model's reply could not be used. These rules "
             "cannot verify what was actually said in the meeting; they only show whether the "
             f"written discussion and resolution mention the same things. {styling}")
        ),
        "gates": CORE_CHECKS,
    }
    if unusable_reason:
        report["fallbackReason"] = unusable_reason
    return report
