# Build information

- **Package:** DAC-MOM-FULL-COMPLETE-20261113.zip (final, fully complete)
- **Built:** 2026-11-13 (Asia/Kolkata), after the full self-test suite passed
- **Frontend bundle:** `frontend/dist/assets/index-BW1Lyq7O.js` (pre-built and included —
  `python app.py` serves it directly; no npm build needed to run)

## What this package contains (all verified inside the zip)

1. **"Template" removed** — screen + Word titles read "DAC · Minutes of Meeting" /
   "BOS · Minutes of Meeting"; zero user-visible "Template".
2. **Notice / MoM reference split** — Meeting request Ref ends `Notice-NN`; MoM workspace,
   Word export and the Minutes section of the consolidated PDF end `MoM-NN`.
3. **Approval queue lists every pending request** (Minutes-review pattern) — open and
   approve any request in any order; no first-come-first-served auto-open.
4. **External Member observation-report review queue** for the Academic Office —
   all reports listed (submitted first), open/approve/return any of them.
5. **AI validation loosened again** (all overlap thresholds halved a second time).
6. **Instructional filler removed** from the MoM document and sidebar hints.
7. **Resolution triage display wording:** Recommended / In process / Not recommended
   (internal keys `approved` / `in_process` / `not_approved` unchanged).
8. **Access directory label:** "Phone".
9. **Demo-style text removed** (login "Identity boundary" box, "Simulated" tags).
10. **Login labels:** "Sign in for DAC & BOS Module", "College faculty email".
11. **Drawn signatures embedded in downloads** — Member Secretary + Chairperson signature
    images with names and "Signed <date>" stamps on the request form PDF and on both the
    Notice section and the Minutes closing of the consolidated PDF.

12. **Approval queue opens as a list first** — every pending request from every school is
    listed (school, department, meeting, Member Secretary, date); a request document opens
    only on "Open request", with a "← Back to approval queue" button; after approve/return/
    reject the office lands back on the list.
13. **External reports nav entry for the Academic Office** — "External reports" in the
    sidebar lists every observation report (submitted first) with Open report, PDF download,
    Approve & archive / Return for revision — the same list pattern as Minutes review.

Plus the standing fixes: Chairperson/member photo access (`/api/file`), member order
Chairperson → Members → External Member → Member Secretary, agenda page 1 / members +
signatures page 2, reactive signature box on chairperson change, calendar From–To date
range (issue table + archive filters), previous-meeting auto-fetch from the last approved
meeting, Copy-To block on downloads only.

## Verify after extracting

    grep -c 'Minutes of Meeting Template' DAC-MOM/frontend/src/App.jsx        # 0
    grep -c 'Sign in for DAC & BOS Module' DAC-MOM/frontend/src/LoginScreen.jsx  # 1
    grep -c 'approved: "Recommended"' DAC-MOM/frontend/src/App.jsx            # 1
    grep -c 'dac-page-members' DAC-MOM/frontend/src/styles.css                # 1
    grep -c 'units_for_chair(_chair_db' DAC-MOM/app.py                        # 1
    grep -c '_request_signature_table' DAC-MOM/app.py                         # 2
    unzip -l <zip> | grep -c 'frontend/dist'                                  # > 0

## Run

    pip install -r requirements.txt   # or: flask flask-cors reportlab pypdf python-docx pillow
    python app.py                     # serves the included frontend/dist bundle
