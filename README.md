<<<<<<< HEAD
# DAC Minutes Studio — DAC and BOS meeting request and minutes workflow

A document-first application for **two committees** — the Departmental Academic Committee (DAC) and the Board of Studies (BOS) — with one shared, signed meeting request and Minutes of Meeting workflow. **One Flask process serves both the API and the compiled interface on port 8000** — open `http://localhost:8000` and the whole product works, with no second server to manage. For frontend development, Vite (`:3000`) proxies same-origin `/api` requests to Flask. A SQLite database is the shared source of truth for accounts, academic affiliations and meeting workspaces.

**Template fidelity note:** the workspace contains `assets/reference-mom-template.pdf`, a four-page PDF copy of the supplied reference. The named master file `DAC MoM Template (2)(1).docx` was not available in the workspace while this version was generated. The implementation follows the user-provided master specification and the PDF’s sequence and wording; it does **not** claim a pixel-perfect comparison to the missing DOCX.

> **Deployment note.** Sign-in is an emailed one-time code against the active access directory. With **no** mail transport configured, the code is printed **on the sign-in screen** (large, copyable digits), written to `data/mail-outbox/` and logged — so the app can be exercised end to end without a mail server. As soon as Graph or SMTP is configured the code is emailed only and the on-screen box disappears. Microsoft 365 Graph send-as, college SSO, TLS termination, malware scanning and off-host document storage are configuration work described in [Production readiness](#production-readiness).

**What changed in this revision**

1. **Two committees.** A new request starts by choosing **DAC** or **BOS**; the request form, the minutes, the agenda series, the reference prefix and the schedule wording all follow the choice. DAC meets twice per semester (four MoMs a year), BOS once per semester (two a year) — see [Committees](#committees-dac-and-bos).
2. **The Chairperson is in the loop on every version.** A correction after an Academic Office revision goes back to the Chairperson for review and signature before the office sees it again — nothing reaches the office unsigned, for the request or for the minutes.
3. **Academic Office archive** of every DAC and BOS meeting held so far, filterable by committee, school and department/branch, with the request form and the completion form readable on screen and downloadable.
4. **The sign-in code is shown on screen** while no mail transport is configured.
5. **Signature bookkeeping fixed** — a signature stamped into a workspace is now resolvable on screen as well as in the PDF, so a document never says “Signature awaited” for someone who has signed.

Earlier revisions: AI content verification (hybrid hosted/offline), *Recommendation* → *Resolution* rename with data migration, Cambria house style with Word export.

## Requirements

- Python 3.10+
- Node.js 20+
- npm

## Install and run

From the project root:

```bash
python -m venv .venv
# macOS/Linux
. .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cd frontend
npm install
cd ..
```

Start everything with one command:

```bash
./run.sh          # macOS / Linux   (--rebuild forces a fresh interface build)
run.bat           # Windows: double-click, or run it from the project folder
```

It creates the Python environment, installs packages and builds the interface on first run, then serves the application on **http://localhost:8000**. `./bootstrap.sh --run` does the same after a repair pass.

Prefer the two-terminal developer loop? Run the API and Vite separately:

```bash
# Terminal 1 — project root
python app.py              # API + interface on 0.0.0.0:8000
# Terminal 2 — project root
cd frontend && npm run dev # Vite on 0.0.0.0:3000, proxying /api to 8000
```

Port 8000 always serves the built interface; port 3000 is only the Vite dev server.

## Sign-in and account management

Access is a **SQLite active-email allow-list**: only an active address in the directory can complete sign-in. No password is ever collected or stored. A six-digit, single-use code is valid for five minutes and is delivered by the configured mail transport. When no transport is configured — `MAIL_TRANSPORT=file`, the default — the code is printed in the server console and written as an `.eml` file in `data/mail-outbox/`, so a fresh installation is operable without a mail server. In production the code is never returned to the browser.

The directory seeds **45 permanent accounts** — 1 System Administrator, 2 Academic Office
reviewers, **38 faculty** covering every school and department (16 of them Deans or Heads of
Department, i.e. eligible to chair a DAC meeting) and 4 external members.

**These accounts are permanent and are never removed.** They are defined in
`auth_store.SEEDED_DIRECTORY` and re-created on every start-up (`INSERT OR IGNORE`); no code path
deletes a user, and `self_test.py` fails if any seeded account goes missing, is deactivated or loses
its profile. The complete list with every professor detail is in **`PROFESSOR-CREDENTIALS.md`**
(and `professor-credentials.csv`), regenerated any time with:

```bash
./.venv/bin/python export_credentials.py
```

The sign-in screen does not list accounts; the directory itself (`GET /api/admin/users`, System
Administrator only) is the record of who exists, and `DOCS/CREDENTIALS.md` is the printable copy.
Each account carries its campus designation:

| Email | Name & designation | Role / scope |
| --- | --- | --- |
| `admin@presidencyuniversity.in` | System Administrator (IT Services) | System Administrator — access directory only |
| `academic.office@presidencyuniversity.in` | Deputy Registrar, Academic Office | Academic Office — reviews, approvals, vault |
| `academic.office2@presidencyuniversity.in` | Assistant Registrar, Academic Office | Academic Office (backup) |
| `deansoe@presidencyuniversity.in` | Dr. Ramesh Sengottuvelu — Professor & Dean, School of Engineering | Faculty (Chairperson for Engineering) |
| `hod_civ@presidencyuniversity.in` | Dr. Nakul Ramanna — Head of the Department, Civil Engineering | Faculty (Chairperson for the Civil DAC) |
| `ajay@presidencyuniversity.in` | Mr. Ajay H A — Member Secretary (DAC), Civil Engineering | Faculty (Member Secretary — schedules meetings) |
| `chandrasekar.v@presidencyuniversity.in` | Dr. Chandrasekar Vadivelraju — Professor, PSAIAC | Faculty (R1's External Member for the Civil DAC) |

The full roster — all **81 accounts, every school, department, DAC office holder and External Member** —
is in **`DOCS/CREDENTIALS.md`** and `DOCS/professor-credentials.csv`, both generated from the same
registry (`r1_registry.py`) the application itself uses, so the sheet can never drift from the app.
Schools that R1 gives no department are school-level DACs; their Chairperson is the Dean (or the HOD
where R1 names one) and the department field does not appear at all.

Every faculty account is therefore a usable meeting organizer for its own school/department, so the full
role and scope model can be exercised without editing the directory. The list is seeded by
`auth_store._seed_users()` with `INSERT OR IGNORE` (set `APP_ENV=production` to skip all fixture
identities); `python ../TESTS/run_multidepartment_tests.py` drives a complete MoM through the school
organizers, and `../TESTS/run_gemini_flow.py` runs one meeting end to end with model-assisted verification.
Designations were added as a real column (`users.designation`) with an automatic migration, so an existing
existing databases upgrade in place and the seed pass backfills the titles.

Sign out and sign in with another seeded address to test another role; the removed “Acting as” role switcher is not used for authorization. A System Administrator can add, activate, deactivate, or change accounts in **Access directory**. Faculty accounts require a school and dependent department assignment. A faculty member can create and edit only that account’s meetings; the signed-in scheduling faculty member becomes the organizer/Chairperson **for that meeting only**. There is no global Chairperson account role.

The academic catalog includes Computer Engineering, Engineering, Information Science, Commerce, Arts, Design, Health Care and Science, with dependent department lists (including Engineering → Mechanical/Electrical/Civil, Computer Engineering → AI/ML/Cyber Security and Information Science → MCA/BCA/BCA (Data Science)).

## Committees: DAC and BOS

Everything committee-specific lives in `committees.py`, so a future change (a third committee, a
different cadence, different titles) is one edit there and nothing else.

| | **DAC** | **BOS** |
| --- | --- | --- |
| Full name | Departmental Academic Committee | Board of Studies |
| Meetings per semester | 2 — start of semester and end of semester | 1 |
| Meetings per academic year | 4 | 2 |
| Agenda series | DAC #1, DAC #2 | BOS #1 |
| Reference prefix | `PU/<school>-<dept>/DAC-01/…` | `PU/<school>-<dept>/BOS-01/…` |
| Request form title | DAC Meeting Request and Agenda Approval Form | BOS Meeting Request and Agenda Approval Form |
| Minutes title | DAC Minutes of Meeting | BOS Minutes of Meeting |

The meeting number is validated against the committee: a third DAC meeting in one semester, or a
second BOS meeting in the same semester, is refused with a message that states the rule.

### Who signs what, and when

```
Member Secretary signs the request
        ↓
Chairperson  (Dean / Head of Department) reviews and signs
        ↓
Academic Office approves  → the signed request form is archived in the Document vault
        ↓
meeting held → Member Secretary records the minutes → submits
        ↓
Chairperson signs the minutes
        ↓
Academic Office approves → the completion form is archived, the download opens
```

* The Chairperson is a **different person** from the Member Secretary and must be the Dean or a Head
  of Department of the same school.
* **Any revision goes back to the Chairperson.** If the Academic Office returns the request (or the
  minutes) for correction, the corrected version is unsigned again and re-enters the Chairperson's
  inbox; the earlier decision is kept in `chairApprovalHistory` / `chairSignatureHistory`. The
  Academic Office inbox never contains a document without the Chairperson's current signature.
* Rejection, revision and approval are always recorded with a comment, an actor and a timestamp.

## Document structure and workflow

The request and MoM editors use an A4-like document canvas as the primary workspace, with contextual controls alongside it. One structured meeting record feeds the proposal, Academic Office preview, approved MoM and final PDF; users do not re-enter the meeting details.

The PDF renderer preserves the reference’s main sequence:

1. **Page 1:** “Minutes of Meeting Template,” School and Department headings, generated reference/date, meeting title and description, and the appropriate roster. Before the meeting this is a proposed invitee table with **Official Email**; the final MoM contains actual attendees only, with the template’s **Signature** column.
2. **Page 2 onward:** opening statement, one generated section per approved agenda (agenda count is not hardcoded), Discussion, Resolution, and the agenda’s Document / Ref. Document / Annexure area. Previous-MoM approval and ATR use the previous meeting number/date when supplied. Additional discussion points remain separate and audit-labelled.
3. **Photos and action table:** “Geo-Tagged Photos and Online Platform Screenshots – Departmental Academic Committee,” aspect-ratio-preserving images with captions and available location/date-time metadata, then the template action table.
4. **Closing:** the template closing statement, Member Secretary and Chairperson signature locations, and “Encl: Annexures.” Long content expands past four pages when needed.

### Try the complete flow

1. Sign in as a **Faculty** account. Open **Meeting request** → **New meeting (DAC or BOS)** and choose the committee, then edit the meeting details in the document, select any number of common agendas, and add meeting-specific proposals where needed. The school and department are constrained to that account’s provisioned scope. Every proposed invitee must also be active in the access directory; external invitees must be provisioned as External Members first.
2. Submit the proposal — it goes to the Chairperson, who reviews the full request and signs it. While pending, agenda wording and invitees are read-only.
3. Sign in as **Academic Office**. In **Approval queue**, select a request and approve, return it with a comment, or reject it. A returned request goes back to the Member Secretary, and its corrected version goes to the **Chairperson** again before returning to the office. Approval creates locked MoM sections from the approved agenda snapshot and records a simulated invitation; **no email is sent**.
4. Sign back in as the owning **Faculty** account. Open **My meeting workspaces** or the MoM workspace. Record actual attendance separately; the final Members Present table excludes absent invitees. Discussion, Resolution and annexure fields unlock only after **both** the scheduled end time has passed **and** the meeting is marked **COMPLETED**. The development-only “Demo: fast-forward scheduled end” control is available to test that gate.
5. Once unlocked, enter the recorded discussion and resolution, attach agenda-linked annexures, add photos and actions, and run the AI content verification. Export the final MoM as the consolidated PDF (MoM pages, photos, Annexure Index and agenda-linked attachments) or as an editable Word document with the same content.

Approved agenda wording is read-only in the MoM. Significant pre-meeting changes go back through Academic Office reapproval. Each faculty member can maintain multiple independently owned meeting workspaces.

## External Member scope

An active allow-listed External Member can see only an approved meeting whose invitee roster explicitly includes that email. The guest view is a redacted schedule/agenda only. It does **not** expose the final MoM, attendee roster, annexures, uploaded files or file links to guests; explicit document-level sharing and revocation are not implemented here.

## Final documents: PDF and Word

**PDF (consolidated).** One PDF containing the MoM sections, photos, an Annexure Index and agenda-linked attachments. Annexures are indexed under their agenda and appended after the MoM. PDF files are appended; images are converted while preserving aspect ratio; DOCX/XLSX/PPTX/TXT/CSV are rendered into readable text/table pages in this demo. Office conversion is not pixel-perfect and may omit embedded objects or complex layout. Verification findings are excluded from the official documents.

**Word (.docx, editable).** `POST /api/export-docx` renders the same MoM as an editable Word file: title page, reference/date, members table, one block per agenda (Discussion, Resolution, Document/Ref. Document), additional discussion points, photos with captions, the action-items table, signature block and enclosure note.

Both exports follow the required house style: **the entire document is set in Cambria**, **sub-headings are 12 pt**, **normal text is 11 pt**, and **line spacing is 1.15** (the page footer uses 9 pt Cambria). The UI itself keeps its existing theme; the style applies to the generated documents.

Cambria is a proprietary Microsoft font that cannot be redistributed, so the PDF embeds **Caladea** — Google’s metric-compatible Cambria substitute released under the SIL Open Font License — from `assets/fonts/` (see `assets/fonts/OFL.txt`). Metrically identical, so line breaks and pagination match Cambria, and the PDF names the family Cambria so viewers report it that way. The Word file specifies `Cambria` directly, so Word uses the real font installed on the machine. If the font files are removed, the PDF falls back to Times-Roman and `GET /api/ai/status` reports the fallback.

## AI content verification

The **AI content verification** panel answers two review questions for every agenda item:

1. **Discussion based on Agenda** — does the recorded discussion address the approved agenda item?
2. **Resolution based on Discussion** — is the recorded resolution grounded in the discussion, and does it contain decisions, figures, names or outcomes that the discussion does not support?

It is **hybrid** by design:

* **Model-assisted** when an API key is configured. The typed agenda, discussion and resolution text is sent to the provider; the model returns, per agenda item, a status (`aligned` / `review` / `needs_revision`), a 0-100 score, plain-language reasoning, verbatim evidence and a conditional human-review suggestion. Supporting checks such as *Agenda ↔ Resolution* and *Numeric / factual consistency* are reported when they trigger.
* **Offline rules** when no key is configured, or whenever the model call fails. The deterministic engine in `content_check.py` reports the same structure using traceable word-overlap, unsupported-sentence and figure checks, and the panel states clearly that no model ran.

**Just add the key** — that is the whole switch. Either export it in the environment, or drop it in a
`.env` file next to `app.py` (loaded automatically; real environment variables win), then restart the API:

```bash
# Option A - .env file (simplest)
cp .env.example .env
#   .env:  AI_PROVIDER=openai
#          AI_API_KEY=sk-...
#          AI_MODEL=gpt-4o-mini

# Option B - environment variables
export AI_PROVIDER=openai AI_API_KEY=sk-... AI_MODEL=gpt-4o-mini

python app.py
```

Verify it in one click: the **AI content verification** panel has a **Test AI connection** button
(`POST /api/ai/check`) that sends a one-line probe and reports the provider, model, latency or the exact
failure (rejected key, wrong model/deployment, quota, network). `GET /api/ai/status` shows the same
diagnostics, including whether a `.env` file was loaded. If the key is wrong or absent the panel says so
and the review silently falls back to the offline rules **with the reason shown** — it never fails silently.
`.env` is gitignored so a key can never be committed.

Configure the provider with environment variables (nothing else changes):

| Variable | Purpose |
| --- | --- |
| `AI_PROVIDER` | `auto` (default), `openai`, `azure`, `gemini` or `offline`. `auto` picks the first provider that has a key. |
| `AI_API_KEY` | Generic key; provider-specific keys `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, `GEMINI_API_KEY` / `GOOGLE_API_KEY` are also honoured. |
| `AI_MODEL` | Model id. Defaults: `gpt-4o-mini` (OpenAI/Azure), `gemini-3.5-flash` (Gemini). For Gemini the client walks a fallback chain — `gemini-3.5-flash` → `gemini-3-flash-preview` → `gemini-flash-latest` → `gemini-3.1-flash-lite` — so a retired id (404), a throttled model (429/503) or a hung request never breaks a working key; the id that answered is reported. |
| `AI_BASE_URL` | OpenAI-compatible base URL (default `https://api.openai.com/v1`). |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION` | Azure OpenAI routing (API version defaults to `2024-08-01-preview`). |
| `AI_TIMEOUT` | Seconds per request (default 45). |
| `AI_MAX_ITEMS` | Agenda items per request (default 12). |
| `AI_ALLOW_CONTENT_UPLOAD` | Set to `0` to forbid sending MoM text to a hosted model even when a key exists. |
| `AI_ENV_FILE` | Path to a different `.env` file (default: `.env` beside `app.py`). Useful for a second deployment or to keep tests away from a real key. |

Example:

```bash
export AI_PROVIDER=openai AI_API_KEY=sk-... AI_MODEL=gpt-4o-mini
python app.py
```

The calls use only the Python standard library (`urllib`), so **no new dependency is added**. `GET /api/ai/status` (and `GET /api/health`) report which engine is active.

**Boundary:** the model judges only the text you submit. It cannot verify what was actually said in the meeting, it is instructed never to rewrite or invent record text, annexures and photos are never analysed, and every finding is a prompt for human review. Findings are shown in the app only and stay out of the exported PDF and Word documents. Only send text you are permitted to share with the configured provider.

## Resolution triage: what becomes an action item

The **Action item entry** panel classifies every agenda **Resolution** into one of three categories and
decides whether it belongs in the Action Items table:

| Category | Meaning | Action item? |
| --- | --- | --- |
| **Approved** | approved / accepted / ratified / sanctioned / endorsed | **No** — the matter is closed |
| **In process** | deferred, pending, under review, awaiting a report, or a second discussion is needed | **Yes** |
| **Not approved** | rejected, declined, or it cannot be approved as submitted | **Yes** |

Only **In process** and **Not approved** resolutions are proposed for Action Items, and what is proposed
is a deliberately *very short* next step rather than the resolution again — for example
`In process — needs a second discussion at the next meeting` or
`Not approved — revise and resubmit at the next meeting`. Every proposed line is capped at 120
characters and the full resolution is never rewritten: it stays exactly as recorded in the minutes.

* **Hybrid, like the verification panel.** With an API key the model reads the typed resolution text and
  returns, per agenda, the category, a short action line, a confidence, a rationale and the verbatim
  evidence it used. Without a key (or if the call fails) the deterministic cue rules in
  `resolution_triage.py` decide, and the panel says which engine ran. A refusal is always read before a
  plain approval, so *"not approved"* is never mistaken for *"approved"*, and wording such as
  *"approved subject to ratification at the next meeting"* is correctly **In process**.
* **Human in the loop.** The triage proposes; the organiser adds the item and names the person
  responsible (click **Use this text** to fill the short line, then complete owner and target date). Each
  row carries a **Reviewer override** selector, and overriding a category is written to the audit trail.
* **Enforced, not just suggested.** Once a resolution is categorised **Approved**, the Action item entry
  panel refuses to create an action for it and explains why. Resolutions with no recorded text are
  reported as **Not classified** and produce nothing.
* **Nothing internal reaches the document.** The category is shown in the app (and kept in the saved
  workspace) but the exported PDF and Word keep the four template columns and carry only the short action
  text — verified by the test suite.

`POST /api/ai/triage` returns the report; `GET /api/ai/status` advertises the categories and the rule.

## Security and production boundary

Sessions, CSRF checks, active-account checks and API role gates are enforced on every request. Faculty workspace access is owner-scoped; external file access is denied by default. Data is stored under `data/` (SQLite database, uploads, mail outbox).

### Production readiness

Set these before the college uses the system:

| Setting | What to do |
| --- | --- |
| `APP_ENV=production` | Disables the test clock hooks and stops the sign-in code being echoed to the browser. Requires `FLASK_SECRET_KEY`. |
| `FLASK_SECRET_KEY` | A long random value: `python -c "import secrets;print(secrets.token_urlsafe(48))"`. |
| `MAIL_TRANSPORT=smtp` or `graph` | Sign-in codes and workflow mail are emailed instead of written to `data/mail-outbox/`. Fill the matching `SMTP_*` or `GRAPH_*` values in `.env`. |
| HTTPS/TLS | Terminate TLS in front of the app and set `SESSION_COOKIE_SECURE=1`. |
| `data/` | Back it up, and move uploads to encrypted private storage with malware scanning and retention rules. |
| College SSO | Optional next step: replace the emailed code with single-tenant Entra sign-in and Conditional Access. Not implemented. |

`APP_ENV=production` never returns a sign-in code to the browser and never enables the test hooks
(`/api/testing/*`). A production start-up without `FLASK_SECRET_KEY` refuses to boot rather than
running with an ephemeral key.

## Supported uploads

`.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.docx`, `.xlsx`, `.pptx`, `.txt`, `.csv` (15 MB per file). Password-protected PDFs are rejected. These checks are not a substitute for production malware scanning or file validation.

## Quick checks

```bash
python -m py_compile app.py auth_store.py self_test.py mom_shared.py doc_theme.py content_check.py ai_verify.py mom_docx.py resolution_triage.py
python self_test.py                     # workflow, role gates, AI/offline verification, rename migration, PDF + Word export
python tests/full_workflow_test.py      # DAC + BOS end to end, both revision paths, archive, exports
python tests/signoff_matrix.py          # feature-by-feature sign-off → SIGNOFF-REPORT.md
python tests/feature_audit.py           # every advertised feature, against the live server
cd frontend && npm run build && npm run ui:smoke
```

The three integration suites expect the app to be running (`./run.sh`); they sign in with the seeded
accounts, drive real meetings through the API and write their reports (`WORKFLOW-TEST-REPORT.md`,
`SIGNOFF-REPORT.md`, `FEATURE-AUDIT-REPORT.md`).

Static analysis is clean and can be re-run at any time (the three tools are developer-only; they are
not needed to run the product):

```bash
pip install pyflakes bandit vulture
python -m pyflakes *.py tests/*.py          # no unused imports, undefined names or dead locals
python -m bandit -q -r . -x ./.venv,./node_modules,./tests
python -m vulture *.py --min-confidence 80  # no unused functions, classes or constants
```

`python -m py_compile` and `python self_test.py` cover the resolution rename (including legacy `recommendation` payloads), the verification report shape, the Cambria 11/12 pt + 1.15 style metadata and both export endpoints.

## Module map

| File | Responsibility |
| --- | --- |
| `app.py` | Flask API, workflow gates, PDF rendering, exports, legacy-key migration. |
| `auth_store.py` | SQLite allow-list, catalog and workspace storage. |
| `mom_shared.py` | Pure text helpers shared by the PDF and Word renderers (dates, reference numbers, agenda titles, annexure labels, key migration). |
| `doc_theme.py` | Cambria house style: font registration/embedding, 11/12 pt sizes, 1.15 spacing, Word style helpers. |
| `content_check.py` | Offline deterministic Discussion/Resolution rule engine. |
| `ai_verify.py` | Provider adapter (OpenAI / Azure / Gemini), prompt, JSON validation and hybrid fallback. |
| `resolution_triage.py` | Three-way Resolution category (Approved / In process / Not approved), the short action line and the action-item rule. |
| `mom_docx.py` | Editable Word (.docx) renderer. |
| `committees.py` | The DAC/BOS registry: names, cadence, agenda series, reference prefix, document titles. |
| `archive.py` | The Academic Office archive: every meeting held, with its committee, school, department and available forms. |
| `documents.py` | Document vault: approved forms and minutes, checksummed, versioned, indexed by committee/school/department/year. |
| `signatures.py` | Signature capture, storage, stamping and history. |
| `audit.py` | The governance trail: every event appended as one SQLite row (never truncated, never lost to a concurrent write). |
| `mailer.py` | Mail queue and transports (file / SMTP / Microsoft 365 Graph), sender rules per step. |
| `notifications.py` | In-app notifications, each of which also queues its email. |
| `request_form.py`, `mom_docx.py`, `external_report.py` | The three generated documents. |

## Verify a running server

With the API and UI up, this audits **every feature over HTTP** and writes a verdict table:

```bash
cd DAC-MOM
./.venv/bin/python tests/feature_audit.py     # 106 checks, exits 1 on any failure
```

It produces `FEATURE-AUDIT-REPORT.md` plus the signed request form, the External Member's
observation report and the approved minutes (PDF + Word) under `tests/exports-feature-audit/`.
Point it at another host with `DAC_BASE_URL=https://mom.presidencyuniversity.in`.

=======
# Presidency-DAC-BOS-MoM
An AI-powered Departmental Academic Committee (DAC) Meeting Management System for managing meeting requests, agendas, minutes, approvals, digital signatures, resolutions, and Action Taken Reports (ATR) through a secure, role-based workflow.
>>>>>>> 7f64d827f1ecb584fe77b27f645d45b75b7b7cf2
