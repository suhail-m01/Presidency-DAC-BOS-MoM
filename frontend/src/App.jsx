import { useEffect, useRef, useState } from "react";
import LoginScreen from "./LoginScreen.jsx";

let csrfToken = "";
//: The bearer token issued at sign-in. A browser showing this app inside a sandboxed
//: iframe cannot read or store cookies, so the cookie session is silently dropped there
//: and every API call came back 401 ("click sign in, land back on the sign-in page").
//: The token is sent as `Authorization: Bearer …` on every request. Where storage is
//: available it is also kept in sessionStorage so a reload keeps the session.
let sessionToken = "";
try {
  sessionToken = window.sessionStorage.getItem("dac-session-token") || "";
} catch { /* opaque origin: keep it in memory only */ }
function rememberSessionToken(token) {
  sessionToken = token || "";
  try {
    if (sessionToken) window.sessionStorage.setItem("dac-session-token", sessionToken);
    else window.sessionStorage.removeItem("dac-session-token");
  } catch { /* storage unavailable; the in-memory copy still works */ }
}
const STATE_KEY = "dac-minutes-studio-react-v3";

// Resolution triage — the three categories a resolution can fall into. Only
// "In process" and "Not approved" resolutions reach the Action Items table.
const RESOLUTION_CATEGORIES = { approved: "Recommended", in_process: "In process", not_approved: "Not recommended", unclassified: "Not classified" };
const ACTIONABLE_CATEGORIES = ["in_process", "not_approved"];
function categoryLabel(category) { return RESOLUTION_CATEGORIES[category] || RESOLUTION_CATEGORIES.unclassified; }

// Member hierarchy for every printed table: Chairperson → Members → External Member → Member Secretary.
const MEMBER_ROLE_ORDER = { Chairperson: 0, Member: 1, "External Member": 2, "Member Secretary": 3 };
function sortedMembers(members) {
  return [...(members || [])].sort((a, b) => (MEMBER_ROLE_ORDER[a.role] ?? 99) - (MEMBER_ROLE_ORDER[b.role] ?? 99));
}
function categoryCannotBeActioned(category) { return !!category && !ACTIONABLE_CATEGORIES.includes(category); }
function apiFetch(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  if (sessionToken) headers.set("Authorization", `Bearer ${sessionToken}`);
  return fetch(url, { ...options, headers, credentials: "same-origin" }).then(response => {
    // 428: the account has not recorded its signature yet — open the signature dialog
    // instead of failing the action silently.
    if (response.status === 428) window.dispatchEvent(new CustomEvent("dac:signature-required"));
    // 401 anywhere outside the sign-in endpoints means the session is gone (expired, or
    // the server restarted). Say so and return to the sign-in screen: before this, the
    // shell stayed on screen and pages such as the access directory simply looked empty.
    if (response.status === 401 && !String(url).startsWith("/api/auth/")) {
      window.dispatchEvent(new CustomEvent("dac:session-expired"));
    }
    return response;
  });
}
// `localStorage` throws in a page that is sandboxed without `allow-same-origin` (the
// operator's preview pane is exactly that), so every access goes through these guards.
const safeStorage = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); return true; } catch { return false; } },
  remove(key) { try { localStorage.removeItem(key); return true; } catch { return false; } },
};

const ALLOWED_ANNEXURES = ".pdf,.png,.jpg,.jpeg,.webp,.docx,.xlsx,.pptx,.txt,.csv";
// Office of the Dean Academics, GD-2 / Annexure-A — the official DAC agenda list.
// Kept client-side as a fallback so the form works before /api/catalog answers; the
// server sends the same list (and the workflow validates against it).
const OFFICIAL_AGENDAS = [
  { id: "std-mom", no: 1, groups: ["dac1", "dac2"], applies: "", text: "Review and approval of minutes of the previous meeting." },
  { id: "std-atr", no: 2, groups: ["dac1", "dac2"], applies: "", text: "Action Taken Report (ATR) - Review of actions taken on decisions from the previous meeting." },
  { id: "std-courses", no: 3, groups: ["dac1"], applies: "", text: "Approval of courses available for registration in the upcoming semester." },
  { id: "std-course-plan", no: 4, groups: ["dac1"], applies: "", text: "Approval of Course Plans including various components of Continuous Assessments, the distribution of weightage among such components, and the method of evaluation/assessment of the courses offered in the concerned Academic Term." },
  { id: "std-ntcc", no: 5, groups: ["dac1"], applies: "", text: "Discussion on assessment method for NTCC courses with clear rubrics." },
  { id: "std-electives", no: 6, groups: ["dac1"], applies: "", text: "Electives to be offered in the upcoming semester along with the list of students." },
  { id: "std-audit", no: 7, groups: ["dac1"], applies: "", text: "Discussion on Audit Course(s) shown interest by the student, if any." },
  { id: "std-class-committee", no: 8, groups: ["dac2"], applies: "", text: "Discussion on Class Committee meetings conducted during the semester and upon the Resolutions passed by Class Committee." },
  { id: "std-feedback", no: 9, groups: ["dac2"], applies: "", text: "Student and Faculty feedback on courses - Review of student feedback and suggestions for course improvements." },
  { id: "std-curriculum", no: 10, groups: ["dac1"], applies: "", text: "Deliberation on curriculum Structure and Course content based on various stakeholders (Faculty, Students, Alumni and Industry) feedback and suggestions." },
  { id: "std-bos", no: 11, groups: ["dac1", "dac2"], applies: "Wherever applicable", text: "Implementation of the resolutions of the BOS, if any, for the upcoming batches and semesters." },
  { id: "std-new-course", no: 12, groups: ["dac1"], applies: "", text: "New Course Proposals for new courses including Massive Open Online Course (MOOC) courses." },
  { id: "std-intake", no: 13, groups: ["dac1", "dac2"], applies: "Wherever applicable", text: "Closure of the Program and Change of Intake - Assessment and recommendations for modifications in program intake and, if required, program closure." },
  { id: "std-po-co", no: 14, groups: ["dac2"], applies: "", text: "Program Outcomes (POs) and Course Outcomes (COs) attainment for the courses offered in the last semester." },
  { id: "std-research", no: 15, groups: ["dac1", "dac2"], applies: "Wherever applicable", text: "Exploration on Faculty and Student Research Initiative." },
  { id: "std-faculty-dev", no: 16, groups: ["dac1", "dac2"], applies: "Wherever applicable", text: "Faculty Training and Professional Development need analysis." },
  { id: "std-np", no: 17, groups: ["dac2"], applies: "", text: "Tentative Not Permitted (NP) list." },
  { id: "std-summer", no: 18, groups: ["dac2"], applies: "DAC#2 of even semester only", text: "Summer Term courses tentative list and further planning." },
  { id: "std-other", no: 19, groups: ["anywhere"], applies: "", text: "Any other agenda items may be discussed with the permission of the Chair." },
];
const DEFAULT_BANK = OFFICIAL_AGENDAS.map(item => ({ id: item.id, title: item.text, note: item.applies || `Official agenda #${item.no}` }));

// ---------------------------------------------------------------- DAC and BOS
// Two committees, one workflow. A Departmental Academic Committee meets twice in a
// semester (start and end) — four meetings a year; a Board of Studies meets once in a
// semester — two meetings a year. Everything that names the committee reads it here.
const COMMITTEE_META = {
  DAC: {
    code: "DAC",
    name: "Departmental Academic Committee",
    meetingsPerSemester: 2,
    meetingsPerYear: 4,
    schedule: "twice in every semester — at the start of the semester and again at the end",
    scheduleShort: "2 per semester · 4 in a year",
    agendaSeries: "DAC #1 and DAC #2",
    note: "The Departmental Academic Committee meets twice in a semester — at the start and at the end — so four DAC meetings are held in an academic year.",
    requestTitle: "Meeting Request and Agenda Approval Form",
    momTitle: "Minutes of Meeting",
    icon: "▤",
  },
  BOS: {
    code: "BOS",
    name: "Board of Studies",
    meetingsPerSemester: 1,
    meetingsPerYear: 2,
    schedule: "once in every semester — so twice in an academic year",
    scheduleShort: "1 per semester · 2 in a year",
    agendaSeries: "BOS #1",
    note: "The Board of Studies meets once in a semester — so two BOS meetings are held in an academic year.",
    requestTitle: "Meeting Request and Agenda Approval Form",
    momTitle: "Minutes of Meeting",
    icon: "▥",
  },
};
const COMMITTEE_CODES = Object.keys(COMMITTEE_META);
function committeeCode(meeting) {
  const code = String(meeting?.committee || "").toUpperCase();
  return COMMITTEE_META[code] ? code : "DAC";
}
function committeeMeta(meeting, registry = null) {
  const code = committeeCode(meeting);
  return (registry && registry[code]) || COMMITTEE_META[code];
}
function committeeName(meeting) { return committeeMeta(meeting).name; }
function committeeLimit(meeting) { return committeeMeta(meeting).meetingsPerSemester; }

// The agenda bank on the meeting-request screen offers the series for the meeting being
// convened. The "any meeting, with the permission of the Chair" items are not offered as
// tick-boxes any more: an item that belongs to no scheduled series is added deliberately
// through "Add meeting-specific agenda", where its wording and the reason it is sought are
// recorded. (The published catalogue still carries them — see /api/catalog — and they stay
// listed in the Academic Office agenda library.)
function agendaGroupsFor(meetingNo, committee = "DAC") {
  const code = COMMITTEE_META[String(committee).toUpperCase()] ? String(committee).toUpperCase() : "DAC";
  const limit = COMMITTEE_META[code].meetingsPerSemester;
  const number = Math.min(Math.max(1, Number(String(meetingNo || "1").match(/\d+/)?.[0] || 1)), limit);
  const current = number <= 1 ? "dac1" : "dac2";
  const groups = [
    { key: "dac1", label: `${code} #1 — ${limit > 1 ? "first meeting of the semester" : "the semester's meeting"}`, items: OFFICIAL_AGENDAS.filter(item => item.groups.includes("dac1")) },
  ];
  if (limit > 1) {
    groups.push({ key: "dac2", label: `${code} #2 — second meeting of the semester`,
      items: OFFICIAL_AGENDAS.filter(item => item.groups.includes("dac2")) });
  }
  return groups.map(group => ({ ...group, current: group.key === current }));
}
const NAV = {
  system_admin: [["overview", "Overview", "◫"], ["directory", "Access directory", "♙"], ["vault", "Document vault", "▣"], ["archive", "Committee archive", "▤"], ["atr", "Action Taken Reports", "▦"], ["alerts", "Notifications", "◔"], ["security", "Security & audit", "◇"]],
  faculty: [["overview", "Overview", "◫"], ["request", "Meeting request", "▤"], ["mom", "MoM workspace", "✎"], ["atr", "Action Taken Report", "▦"], ["minutes", "Minutes to sign", "✒"], ["member", "My external observations", "☑"], ["outbox", "Invitations", "↗"], ["alerts", "Notifications", "◔"], ["security", "Security & audit", "◇"]],
  academic_office: [["overview", "Overview", "◫"], ["review", "Approval queue", "✓"], ["minutes", "Minutes review", "✒"], ["member", "External reports", "☑"], ["atr", "Action Taken Reports", "▦"], ["calendar", "Meeting calendar", "▤"], ["archive", "Committee archive", "▤"], ["vault", "Document vault", "▣"], ["library", "Agenda library", "▦"], ["outbox", "Invitation log", "↗"], ["alerts", "Notifications", "◔"], ["security", "Security & audit", "◇"]],
  external_member: [["member", "Observation report", "☑"], ["alerts", "Notifications", "◔"], ["security", "Security notes", "◇"]],
};
const ROLE_LABEL = { system_admin: "System Administrator", academic_office: "Academic Office", faculty: "Faculty / meeting organizer", external_member: "External Member" };
const VIEW_LABEL = { atr: "Action Taken Report", calendar: "Meeting calendar", overview: "Overview", directory: "Access directory", request: "Meeting request", review: "Academic Office review", library: "Common agenda library", mom: "MoM workspace", outbox: "Invitation log", security: "Security & audit", member: "External observation report", vault: "Document vault", archive: "Committee archive", minutes: "Minutes review", alerts: "Notifications" };
const REVIEW_LABELS = { draft: "Not submitted", pending_chairperson: "Awaiting Chairperson", chair_revision: "Returned by the Chairperson", pending_office: "Awaiting Academic Office", office_revision: "Returned by the Academic Office", approved: "Approved by the Academic Office" };
const VAULT_TYPES = { request: "Meeting request form", mom: "Minutes of Meeting", external_report: "External Member report", atr: "Action Taken Report" };

function pad2(value) { return String(value ?? "").padStart(2, "0"); }
function isoDate(date) { return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`; }
function daysFromNow(days) { const date = new Date(); date.setDate(date.getDate() + days); return isoDate(date); }
function uid(prefix = "id") { return `${prefix}-${Math.random().toString(36).slice(2, 8)}-${Date.now().toString(36)}`; }
function copy(value) { return JSON.parse(JSON.stringify(value)); }
function ordinal(value) {
  const match = String(value || "1").match(/\d+/);
  if (!match) return String(value || "1");
  const number = Number(match[0]);
  const suffix = number % 100 >= 11 && number % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[number % 10] || "th");
  return `${number}${suffix}`;
}
function numberOnly(value) { const match = String(value ?? "").match(/\d+/); return match ? String(Number(match[0])) : String(value ?? "").trim(); }
function dmy(value) {
  if (!value) return "DD.MM.YYYY";
  const parts = String(value).slice(0, 10).split("-");
  return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : String(value);
}
function longDate(value) {
  if (!value) return "Not set";
  const date = new Date(`${value}T12:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}
function stripPrefix(value, prefix) { return String(value || "").replace(new RegExp(`^${prefix}\\s*`, "i"), "").trim(); }
function schoolName(meeting) { return stripPrefix(meeting.school, "School of") || "__________"; }
function departmentName(meeting) { return stripPrefix(meeting.department, "Department of") || "__________"; }
function referenceNumber(meeting, kind = "mom") {
  const num = String(Number(numberOnly(meeting.meetingNo)) || "xx").padStart(2, "0");
  const school = (String(meeting.schoolCode || "School").replace(/[^a-z0-9]/gi, "") || "School").toUpperCase();
  const dept = (String(meeting.departmentCode || "Dept").replace(/[^a-z0-9]/gi, "") || "Dept").toUpperCase();
  // The meeting request carries "Notice"; the MoM workspace carries "MoM" — never both.
  const suffix = kind === "request" ? "Notice" : "MoM";
  return `PU/${school}-${dept}/${committeeCode(meeting)}-${num}/${meeting.academicYear || "Academic Year"}/${meeting.semester || "Semester"}/${suffix}-${num}`;
}
function agendaTitle(item, meeting) {
  const id = item.agendaId || item.id;
  const previousNumber = ordinal(meeting.previousMeetingNo || Math.max(1, Number(numberOnly(meeting.meetingNo) || 1) - 1));
  const previousDate = dmy(meeting.previousMeetingDate);
  if (id === "std-mom") return `To consider the approval of the MoM of the ${previousNumber} ${committeeName(meeting)} meeting held on ${previousDate}.`;
  if (id === "std-atr") return `To consider the approval of the Action Taken Report (ATR) of the ${previousNumber} ${committeeName(meeting)} meeting held on ${previousDate}.`;
  return item.title || "Agenda";
}
function defaultState(user = {}) {
  const school = user.school || "";
  const department = user.department || "";
  const organizerName = user.name || "Faculty Organizer";
  const organizerEmail = user.email || "";
  const schoolLabel = school ? (/^School of/i.test(school) ? school : `School of ${school}`) : "";
  const departmentLabel = department ? (/^Department of/i.test(department) ? department : `Department of ${department}`) : "";
  // A fresh workspace id per meeting; the account id keeps it readable in support tickets.
  const workspaceId = `DAC-${String(user.id || "anon").slice(0, 7)}-${Date.now().toString(36)}`;
  return {
    status: "draft", workspaceId, committee: "DAC",
    meeting: {
      id: workspaceId, committee: "DAC", meetingNo: "1", academicYear: "2026-27", semester: "Odd",
      school: schoolLabel, department: departmentLabel,
      schoolCode: String(school).replace(/^School of\s*/i, "").replace(/[^A-Z]/gi, "").slice(0, 3).toUpperCase(),
      departmentCode: String(department).replace(/^Department of\s*/i, "").replace(/[^A-Z]/gi, "").slice(0, 3).toUpperCase(),
      previousMeetingNo: "1", previousMeetingDate: daysFromNow(-90), date: daysFromNow(7), startTime: "10:30", endTime: "12:00",
      venue: "Seminar Hall, Block B", mode: "Offline", onlineLink: "", chairName: "", chairEmail: "",
      secretaryName: organizerName, secretaryEmail: organizerEmail, attendanceConfirmed: false,
      agendas: [
        { id: "std-mom", kind: "standard", title: DEFAULT_BANK[0].title, rationale: "" },
        { id: "std-atr", kind: "standard", title: DEFAULT_BANK[1].title, rationale: "" },
        { id: "std-curriculum", kind: "standard", title: DEFAULT_BANK[2].title, rationale: "" },
      ],
      members: [
        // A fresh request contains exactly two people: the signed-in Member Secretary who
        // scheduled it, and the Chairperson seated from this DAC's own office holders.
        // Nobody is hard-coded — the roster grows from the real access directory as the
        // Member Secretary adds the DAC's members.
        { id: "m-sec", name: organizerName, designation: user.designation || "Member Secretary", role: "Member Secretary", email: organizerEmail, external: false, present: false },
      ],
    },
    agendaBank: copy(DEFAULT_BANK), approvedMeeting: null, approvalVersion: 0, submittedVersion: 0,
    submittedAt: "", officeComment: "", changeRequest: false, meetingCompletedAt: "", momItems: [],
    additionalDiscussions: [], photos: [], actionItems: [], aiReport: null, aiCheck: null, resolutionTriage: null, outbox: [], audit: [], pdfGenerated: false,
  };
}
function migrateLegacyResolutionKeys(state) {
  // "Recommendation" was renamed to "Resolution". Older localStorage copies used the
  // legacy key, so rename it on load and drop it once the new key holds the value.
  const fixRows = rows => (rows || []).map(row => {
    const next = { ...row };
    if ("recommendation" in next) { if (next.resolution === undefined) next.resolution = next.recommendation; delete next.recommendation; }
    if ("noRecommendation" in next) { if (next.noResolution === undefined) next.noResolution = next.noRecommendation; delete next.noRecommendation; }
    if ("sourceRecommendation" in next) { if (next.sourceResolution === undefined) next.sourceResolution = next.sourceRecommendation; delete next.sourceRecommendation; }
    return next;
  });
  return { ...state, momItems: fixRows(state.momItems), additionalDiscussions: fixRows(state.additionalDiscussions), actionItems: fixRows(state.actionItems) };
}
function loadState(user = {}) {
  const storageKey = `${STATE_KEY}:${user.id || "anonymous"}`;
  const fresh = defaultState(user);
  try {
    const savedRaw = JSON.parse(safeStorage.get(storageKey) || "null");
    if (!savedRaw) return fresh;
    const saved = migrateLegacyResolutionKeys(savedRaw);
    const meeting = { ...fresh.meeting, ...(saved.meeting || {}) };
    if (saved.meeting && saved.meeting.attendanceConfirmed !== true) {
      meeting.members = (meeting.members || []).map(member => ({ ...member, present: false }));
      meeting.attendanceConfirmed = false;
    }
    return { ...fresh, ...saved, workspaceId: saved.workspaceId || meeting.id, meeting, agendaBank: saved.agendaBank || fresh.agendaBank };
  } catch {
    return fresh;
  }
}
function endTimePassed(meeting) {
  if (!meeting?.date || !meeting?.endTime) return false;
  const end = new Date(`${meeting.date}T${meeting.endTime}:00`);
  return !Number.isNaN(end.getTime()) && Date.now() >= end.getTime();
}
function meetingStarted(meeting) {
  if (!meeting?.date || !meeting?.startTime) return false;
  const start = new Date(`${meeting.date}T${meeting.startTime}:00`);
  return !Number.isNaN(start.getTime()) && Date.now() >= start.getTime();
}
function unlocked(state) {
  return state.status === "approved" && state.meeting?.completed === true && endTimePassed(state.meeting);
}
function pillClass(status) {
  return ({ draft: "draft", pending: "pending", revision: "revision", rejected: "rejected", approved: "approved", complete: "complete", aligned: "aligned", review: "review", needs_revision: "needs_revision" })[status] || "neutral";
}
function statusText(status) {
  return ({ draft: "Draft", pending_chairperson: "With the Chairperson", chairApproval: "Signed by the Chairperson", pending: "With the Academic Office", revision: "Revision requested", rejected: "Rejected", approved: "Approved", complete: "Complete", aligned: "No mismatch found", review: "Review suggested", needs_revision: "Needs revision" })[status] || "In progress";
}
const STATUS_PILL = { pending_chairperson: "pending", chair_revision: "pending", pending_office: "pending" };
function StatusPill({ status = "neutral", children }) { return <span className={`status-pill status-${pillClass(status)}`}><span>{children || statusText(status)}</span></span>; }
function InlineInput({ value, onChange, className = "", type = "text", disabled = false, ariaLabel, placeholder, ...rest }) {
  return <input className={`doc-inline-field ${className}`} type={type} value={value ?? ""} onChange={event => onChange(event.target.value)} disabled={disabled} aria-label={ariaLabel} placeholder={placeholder} {...rest} />;
}
function InlineSelect({ value, onChange, className = "", disabled = false, ariaLabel, options }) {
  return <select className={`doc-inline-select ${className}`} value={value} onChange={event => onChange(event.target.value)} disabled={disabled} aria-label={ariaLabel}>{options.map(option => <option key={option} value={option}>{option}</option>)}</select>;
}
function ToolCard({ title, tag, children, className = "" }) {
  return <section className={`doc-tool-card ${className}`}><div className="doc-tool-heading"><h3>{title}</h3>{tag && <span className="tag">{tag}</span>}</div>{children}</section>;
}
function Page({ className = "", children }) { return <section className={`dac-page ${className}`}>{children}</section>; }
function SectionHeading({ eyebrow, title, description, actions }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="heading-actions">{actions}</div>}</div>;
}

function MeetingDescription({ meeting, editable, premeeting, onChange }) {
  const numberInput = editable
    ? <InlineInput className="doc-number-input" value={ordinal(meeting.meetingNo)} onChange={value => onChange("meetingNo", numberOnly(value))} ariaLabel="Meeting number" />
    : ordinal(meeting.meetingNo);
  const deptInput = departmentName(meeting);
  const schoolInput = schoolName(meeting);
  const dateInput = editable
    ? <InlineInput type="date" className="doc-date-input" value={meeting.date} onChange={value => onChange("date", value)} ariaLabel="Meeting date" />
    : dmy(meeting.date);
  const startTime = editable
    ? <InlineInput type="time" className="doc-time-input" value={meeting.startTime} onChange={value => onChange("startTime", value)} ariaLabel="Meeting start time" />
    : meeting.startTime || "—";
  const endTime = editable
    ? <InlineInput type="time" className="doc-time-input" value={meeting.endTime} onChange={value => onChange("endTime", value)} ariaLabel="Meeting end time" />
    : meeting.endTime || "—";
  const venue = editable
    ? <InlineInput className="doc-name-input" value={meeting.venue} onChange={value => onChange("venue", value)} ariaLabel="Venue" placeholder="Venue" />
    : meeting.venue || "Venue not recorded";
  const mode = editable
    ? <InlineSelect value={meeting.mode} onChange={value => onChange("mode", value)} ariaLabel="Meeting mode" options={["Offline", "Online", "Hybrid"]} />
    : String(meeting.mode || "Offline").toLowerCase();
  const modeSentence = <span>The meeting {premeeting ? "will be held" : "was held"} in {mode} mode{meeting.mode === "Online" ? "" : " at the University campus in Bengaluru"}.</span>;
  const link = meeting.onlineLink
    ? <> The meeting link is provided below: {editable ? <InlineInput className="doc-link-input" value={meeting.onlineLink} onChange={value => onChange("onlineLink", value)} ariaLabel="Online meeting link" /> : meeting.onlineLink}</>
    : <> The meeting link is provided below.{editable && meeting.mode !== "Offline" && <> {<InlineInput className="doc-link-input" value="" onChange={value => onChange("onlineLink", value)} ariaLabel="Online meeting link" placeholder="Paste meeting link" />}</>}</>;
  return <>
    The {numberInput} Meeting of the {committeeName(meeting)} of the Department of {deptInput}, School of {schoolInput}, University, {premeeting ? "is proposed to be held" : "was convened"} on {dateInput}, at {startTime}{editable && <span className="doc-end-time-inline"> (expected end {endTime})</span>} in the {venue}. {modeSentence}{link}
  </>;
}

function ReferenceLine({ meeting, editable, onChange, kind = "mom" }) {
  const number = String(Number(numberOnly(meeting.meetingNo)) || 0).padStart(2, "0");
  if (!editable) return <><span>Ref No. {referenceNumber(meeting, kind)}</span><span>Date: {dmy(meeting.date)}</span></>;
  return <>
    <span className="doc-ref-edit">Ref No. PU/<InlineInput className="doc-code-input" value={meeting.schoolCode} onChange={value => onChange("schoolCode", value.toUpperCase())} ariaLabel="School code" />-<InlineInput className="doc-code-input" value={meeting.departmentCode} onChange={value => onChange("departmentCode", value.toUpperCase())} ariaLabel="Department code" />/DAC-{number}/{<InlineInput className="doc-year-input" value={meeting.academicYear} onChange={value => onChange("academicYear", value)} ariaLabel="Academic year" />}/{<InlineSelect className="doc-semester-select" value={meeting.semester} onChange={value => onChange("semester", value)} ariaLabel="Semester" options={["Odd", "Even", "Annual"]} />}/{kind === "request" ? "Notice" : "MoM"}-{number}</span>
    <span>Date: <InlineInput type="date" className="doc-date-input" value={meeting.date} onChange={value => onChange("date", value)} ariaLabel="Meeting date" /></span>
  </>;
}

// The server sends either an ISO stamp (`2026-10-26T16:36:04+00:00`) or an already
// readable one (`26 Oct 2026, 16:36`). Slicing both to 16 characters cut the readable
// form down to `26 Oct 2026, 22:` on screen, so only trim the machine format.
function signedStampLabel(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const flattened = raw.replace("T", " ").replace(/(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/, "");
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(flattened)) return flattened.slice(0, 16);
  return raw;
}

// One signature block, reused everywhere a committee document is shown, so the
// screen always carries the same signatures the PDF prints.
function SignatureBlock({ title = "Signatures", rows = [], legend, emptyHint, className = "" }) {
  const list = (rows || []).filter(Boolean);
  return <div className={`doc-signature-block ${className}`.trim()}>
    <div className="doc-signature-title">{title}</div>
    <div className="doc-signature-grid">
      {list.map((row, index) => <div className={`doc-signature-cell ${row.signed ? "signed" : "pending"}`}
                                      key={`${row.role}-${row.email || index}`}>
        <div className="doc-signature-image">
          {row.image ? <img src={row.image} alt={`${row.role} signature`} />
            : <span className="doc-signature-pending">{row.signed ? "Signature on file" : "Awaiting signature"}</span>}
        </div>
        <b>{row.name || "—"}</b>
        <small>{row.role}</small>
        {row.designation && <small>{row.designation}</small>}
        <small className="doc-signature-when">
          {row.signedAt ? `Signed ${signedStampLabel(row.signedAt)}`
            : (row.decision === "revision" ? "Returned for revision" : (row.note || "Not signed yet"))}
        </small>
      </div>)}
      {!list.length && emptyHint}
    </div>
    {legend && <div className="doc-signature-legend">{legend}</div>}
  </div>;
}

// The signature box follows the Chairperson picker immediately: when the chair is
// changed, the box shows the new chair as "awaiting signature" without waiting for
// a save + server round-trip. A row only counts as signed for the chair it names.
function reactiveSignatures(meeting, serverRows) {
  const chairEmail = String(meeting?.chairEmail || "").toLowerCase();
  const chairName = meeting?.chairName || "";
  const rows = (serverRows || []).map(row => {
    if (row.role !== "Chairperson") return row;
    const matches = Boolean(row.email) && row.email.toLowerCase() === chairEmail;
    return { ...row, name: chairName || row.name, email: chairEmail || row.email,
             signed: matches ? row.signed : false, image: matches ? row.image : "",
             signedAt: matches ? row.signedAt : "" };
  });
  if (chairName && !rows.some(row => row.role === "Chairperson")) {
    rows.push({ role: "Chairperson", name: chairName, email: chairEmail, signed: false,
                image: "", signedAt: "", note: "Signs before the Academic Office review" });
  }
  return rows;
}

function RequestDocument({ meeting, editable, catalog, signatures, onMeetingChange, onSchoolChange, onDepartmentChange, onMemberChange, onMemberRoleChange, onRemoveMember, onRemoveAgenda }) {
  const meetingNo = editable
    ? <InlineInput className="doc-number-input" value={ordinal(meeting.meetingNo)} onChange={value => onMeetingChange("meetingNo", String(Math.min(committeeLimit(meeting), Math.max(1, Number(numberOnly(value)) || 1))))} ariaLabel="Meeting number" />
    : ordinal(meeting.meetingNo);
  const schoolOptions = (catalog?.schools || []).map(school => stripPrefix(school.name, "School of"));
  const currentSchool = (catalog?.schools || []).find(school => school.name === schoolName(meeting))
    || (catalog?.schools || []).find(school => stripPrefix(school.name, "School of") === schoolName(meeting));
  const departmentOptions = (currentSchool?.departments || []).map(department => department.name);
  // A school-level DAC has no department: the heading line is not printed at all.
  const showDepartment = departmentOptions.length > 0 || Boolean(departmentName(meeting) && departmentName(meeting) !== "__________");
  // Page 1 carries the Ref (Notice) + agenda; proposed members and signatures
  // start on the next page, exactly as the downloaded Notice prints them.
  return <div className="document-stack request-document-stack">
    <Page className="dac-page-one">
      <div className="doc-template-title"><b>{committeeCode(meeting)} · {committeeMeta(meeting).requestTitle}</b></div>
      <div className="doc-school-heading">SCHOOL OF {editable && schoolOptions.length ? <InlineSelect className="doc-heading-select" value={schoolName(meeting)} options={schoolOptions} onChange={onSchoolChange} ariaLabel="School" /> : schoolName(meeting)}</div>
      {showDepartment && <div className="doc-department-heading">DEPARTMENT OF {editable && departmentOptions.length ? <InlineSelect className="doc-heading-select" value={departmentName(meeting)} options={departmentOptions} onChange={onDepartmentChange} ariaLabel="Department" /> : departmentName(meeting)}</div>}
      <div className="doc-reference-line"><ReferenceLine meeting={meeting} editable={editable} onChange={onMeetingChange} kind="request" /></div>
      <h1 className="doc-meeting-title">Meeting Request · the {meetingNo} Meeting of {committeeName(meeting)}</h1>
      <p className="doc-description"><MeetingDescription meeting={meeting} editable={editable} premeeting onChange={onMeetingChange} /></p>
      <h2 className="doc-section-title">Proposed Agenda Items</h2>
      <p className="doc-premeeting-context">Agenda wording shown here is submitted for Academic Office approval. Discussion and Resolution are intentionally not presented as completed content before the meeting.</p>
      {(meeting.agendas || []).map((agenda, index) => <div className="doc-proposed-agenda" key={agenda.id}>
        <p><b>Agenda No: {pad2(index + 1)}</b> &nbsp; {agendaTitle(agenda, meeting)}</p>
        <div className="doc-agenda-meta no-print"><span className={`doc-source-label ${agenda.kind === "custom" ? "doc-custom-label" : ""}`}>{agenda.kind === "custom" ? "Meeting-specific proposal" : "Academic Office common agenda"}</span>{agenda.rationale && <span className="doc-rationale">Reason: {agenda.rationale}</span>}{editable && <button className="doc-remove" onClick={() => onRemoveAgenda(agenda.id)}>Remove</button>}</div>
      </div>)}
      {!meeting.agendas?.length && <p className="doc-empty-row">No agenda items selected for approval.</p>}
      {(meeting.agendas || []).some(item => ["std-mom", "std-atr"].includes(item.id)) && <p className="doc-previous-reference">Previous meeting reference: {ordinal(meeting.previousMeetingNo)} DAC meeting held on {dmy(meeting.previousMeetingDate)}.</p>}
      <div className="doc-page-footnote">Approval copy · Agenda sequence becomes read-only after approval</div>
    </Page>
    <Page className="dac-page-members">
      <div className="doc-continuation-heading">{committeeCode(meeting)} meeting request · continued</div>
      <p className="doc-section-intro"><b>Proposed Members / Invitees:</b> <span className="doc-premeeting-note">(For invitation approval; this list is not a record of attendance.)</span></p>
      <table className="doc-table doc-members-table"><thead><tr><th>Sl. No.</th><th>Name and Designation</th><th>Role</th><th>Official Email</th></tr></thead><tbody>
        {sortedMembers(meeting.members).map((member, index) => <tr key={member.id}>
          <td className="doc-center">{pad2(index + 1)}</td>
          <td>{editable && member.role !== "Chairperson" ? <><InlineInput className="doc-table-input" value={member.name} onChange={value => onMemberChange(member.id, "name", value)} ariaLabel="Member name" /><br /><InlineInput className="doc-table-input doc-designation-input" value={member.designation} onChange={value => onMemberChange(member.id, "designation", value)} ariaLabel="Member designation" /></> : <>{member.name}<br /><span className="doc-designation">{member.designation}{member.role === "Chairperson" ? " · scheduled by signed-in faculty" : ""}</span></>}</td>
          <td>{editable && member.role !== "Chairperson" ? <select className="doc-inline-select doc-role-select" value={member.role} onChange={event => onMemberRoleChange(member.id, event.target.value)} aria-label="Member role">{["Member Secretary", "Member", "External Member"].map(role => <option key={role}>{role}</option>)}</select> : member.role}</td>
          <td>{editable && member.role !== "Chairperson" ? <><InlineInput type="email" className="doc-table-input" value={member.email} onChange={value => onMemberChange(member.id, "email", value)} ariaLabel="Official email" /><button className="doc-remove no-print" onClick={() => onRemoveMember(member.id)} aria-label={`Remove ${member.name}`}>×</button></> : member.email}{member.external && <span className="doc-guest-tag no-print">Guest</span>}</td>
        </tr>)}
        {!meeting.members?.length && <tr><td colSpan="4" className="doc-empty-row">No proposed members added.</td></tr>}
      </tbody></table>
      <SignatureBlock rows={reactiveSignatures(meeting, signatures)}
        emptyHint={<>
          <div className="doc-signature-cell pending"><div className="doc-signature-image"><span className="doc-signature-pending">Awaiting signature</span></div><b>Member Secretary</b><small>Signs on submission</small></div>
          <div className="doc-signature-cell pending"><div className="doc-signature-image"><span className="doc-signature-pending">Awaiting signature</span></div><b>Chairperson</b><small>Signs before the Academic Office review</small></div>
        </>} />
      <div className="doc-page-footnote">Pre-meeting approval copy · Proposed invitees only</div>
    </Page>
  </div>;
}

function FileList({ files = [], onRemove, canRemove = false }) {
  if (!files.length) return <div className="doc-annexure-empty no-print">No annexure attached.</div>;
  return <div className="file-list">{files.map(file => <div className="file-item" key={file.id}>
    <span className="file-icon">{String(file.extension || file.name?.split(".").pop() || "FILE").replace(".", "").slice(0, 4).toUpperCase()}</span>
    <span className="file-meta"><b title={file.name}>{file.name}</b><small>{Math.round((file.size || 0) / 1024)} KB · {file.type || "file"}</small></span>
    <a href={file.previewUrl || `/api/file/${file.id}`} target="_blank" rel="noreferrer">Open</a>
    {canRemove && <button className="no-print" onClick={() => onRemove(file.id)} aria-label={`Remove ${file.name}`}>×</button>}
  </div>)}</div>;
}

function FinalDocument({ meeting, momItems, additionalDiscussions, photos, actionItems, signatures, isUnlocked, onMomChange, onToggleNoResolution, onUploadAgenda, onRemoveFile, onPhotoChange, onUploadPhotos, onRemovePhoto, onAdditionalChange, onRemoveAdditional, onRemoveAction }) {
  const present = sortedMembers(meeting.members).filter(member => member.present);
  return <div className="document-stack final-document-stack">
    <Page className="dac-page-one">
      <div className="doc-template-title"><b>{committeeCode(meeting)} · {committeeMeta(meeting).momTitle}</b></div>
      <div className="doc-school-heading">SCHOOL OF {schoolName(meeting)}</div>
      <div className="doc-department-heading">DEPARTMENT OF {departmentName(meeting)}</div>
      <div className="doc-reference-line"><ReferenceLine meeting={meeting} editable={false} kind="mom" /></div>
      <h1 className="doc-meeting-title">Minutes of the {ordinal(meeting.meetingNo)} Meeting of {committeeName(meeting)}</h1>
      <p className="doc-description"><MeetingDescription meeting={meeting} editable={false} premeeting={false} onChange={() => {}} /></p>
      <p className="doc-section-intro"><b>Members Present:</b></p>
      <table className="doc-table doc-members-table"><thead><tr><th>Sl. No.</th><th>Name and Designation</th><th>Role</th><th>Signature</th></tr></thead><tbody>
        {present.map((member, index) => <tr key={member.id}><td className="doc-center">{pad2(index + 1)}</td><td>{member.name}<br /><span className="doc-designation">{member.designation}</span></td><td>{member.role}</td><td className="doc-signature-cell">&nbsp;</td></tr>)}
        {!present.length && <tr><td className="doc-empty-row" colSpan="4">No actual attendees have been marked present.</td></tr>}
      </tbody></table>
    </Page>
    <Page className="dac-page-agenda">
      <div className="doc-continuation-heading">{committeeCode(meeting)} minutes · continued</div>
      <p className="doc-opening-statement">The Chairperson welcomed all the members. The member secretary delivered the opening remarks and deliberated on the following agenda points.</p>
      {momItems.map((item, index) => {
        const agendaNumber = Number(item.agendaNo || index + 1);
        const files = item.attachments || [];
        const refs = files.length ? files.map((file, fileIndex) => <span className="doc-annexure-name" key={file.id}>Annexure {agendaNumber}.{fileIndex + 1} · {file.name}</span>) : <span className="doc-annexure-name">Annexure {pad2(agendaNumber)}</span>;
        return <article className="doc-agenda-item" key={item.id}>
          <p className="doc-agenda-title"><b>Agenda No: {pad2(agendaNumber)}</b> &nbsp; {item.title}</p>
          <div className={`doc-form-field ${isUnlocked ? "" : "doc-form-locked"}`}><label>Discussion:</label><textarea className="doc-textarea" rows="3" value={item.discussion || ""} onChange={event => onMomChange(item.id, "discussion", event.target.value)} disabled={!isUnlocked} aria-label={`Discussion for Agenda ${agendaNumber}`} placeholder={isUnlocked ? "Record what the committee actually discussed." : "Locked until the scheduled end time has passed AND the meeting is marked COMPLETED."} /></div>
          <div className={`doc-form-field ${isUnlocked ? "" : "doc-form-locked"}`}><label>Resolution:</label><textarea className="doc-textarea" rows="3" value={item.resolution || ""} onChange={event => onMomChange(item.id, "resolution", event.target.value)} disabled={!isUnlocked || item.noResolution} aria-label={`Resolution for Agenda ${agendaNumber}`} placeholder={item.noResolution ? "Uncheck ‘No separate resolution’ to enter text." : isUnlocked ? "Record the resolution — the outcome, advice or action arising from this agenda." : "Locked until both meeting gates are satisfied."} /></div>
          {item.noResolution && <p className="doc-no-resolution">No separate resolution was recorded for this agenda item.</p>}
          <label className="doc-no-rec-toggle no-print"><input type="checkbox" checked={!!item.noResolution} onChange={() => onToggleNoResolution(item.id)} disabled={!isUnlocked} /> No separate resolution was recorded</label>
          <div className="doc-ref-area"><b>{item.agendaId === "std-mom" ? "Document:" : "Ref. Document:"}</b> {refs}
            <div className="doc-annexure-editor no-print"><label className="doc-file-button">Attach document<input type="file" accept={ALLOWED_ANNEXURES} multiple disabled={!isUnlocked} onChange={event => onUploadAgenda(item.id, event)} /></label><span>Files stay with this approved agenda.</span></div>
            <FileList files={files} canRemove={isUnlocked} onRemove={fileId => onRemoveFile(item.id, fileId)} />
          </div>
        </article>;
      })}
      {!momItems.length && <p className="doc-empty-row">No approved agenda items were recorded.</p>}
      <section className="doc-additional-section"><h2 className="doc-section-title">Additional discussion points (if any)</h2>
        {additionalDiscussions.map((item, index) => <article className="doc-additional-item" key={item.id}>
          <p className="doc-agenda-title"><b>Additional discussion {pad2(index + 1)}:</b> {item.title} <span className="doc-audit-label no-print">Additional · not on the approved agenda</span><button className="doc-remove no-print" onClick={() => onRemoveAdditional(item.id)} disabled={!isUnlocked}>Remove</button></p>
          <div className="doc-form-field"><label>Discussion:</label><textarea className="doc-textarea" rows="3" value={item.discussion || ""} onChange={event => onAdditionalChange(item.id, "discussion", event.target.value)} disabled={!isUnlocked} aria-label={`Additional discussion ${index + 1}`} placeholder={isUnlocked ? "Record only what was actually discussed." : "Locked until both meeting gates are satisfied."} /></div>
          <div className="doc-form-field"><label>Resolution:</label><textarea className="doc-textarea" rows="3" value={item.resolution || ""} onChange={event => onAdditionalChange(item.id, "resolution", event.target.value)} disabled={!isUnlocked} aria-label={`Additional resolution ${index + 1}`} placeholder={isUnlocked ? "Record the outcome or action, if any." : "Locked until both meeting gates are satisfied."} /></div>
        </article>)}
        {!additionalDiscussions.length && <p className="doc-empty-row">No additional discussion points recorded.</p>}
      </section>
    </Page>
    <Page className="dac-page-photos">
      <h2 className="doc-section-title doc-photo-title">Geo-Tagged Photos and Online Platform Screenshots – {committeeName(meeting)}</h2>
      {photos.map((photo, index) => <figure className="doc-photo-entry" key={photo.id}>
        {(photo.file?.previewUrl || photo.file?.id) && <img src={photo.file?.previewUrl || `/api/file/${photo.file.id}`} alt={photo.caption || photo.file.name || `Image ${index + 1}`} />}
        <figcaption><b>Image {index + 1}:</b> {photo.caption || photo.file?.name || "Description or caption of the image"}{photo.location && <> · Location: {photo.location}</>}{photo.capturedAt && <> · Date/time: {photo.capturedAt}</>}</figcaption>
        <div className="doc-photo-edit no-print"><span className="doc-file-name">{photo.file?.name}</span>
          <input className="doc-tool-input" value={photo.caption || ""} onChange={event => onPhotoChange(photo.id, "caption", event.target.value)} placeholder="Caption" aria-label="Photo caption" disabled={!isUnlocked} />
          <input className="doc-tool-input" value={photo.location || ""} onChange={event => onPhotoChange(photo.id, "location", event.target.value)} placeholder="Location (if known)" aria-label="Photo location" disabled={!isUnlocked} />
          <input className="doc-tool-input" value={photo.capturedAt || ""} onChange={event => onPhotoChange(photo.id, "capturedAt", event.target.value)} placeholder="Date/time (if known)" aria-label="Photo date and time" disabled={!isUnlocked} />
          <button className="doc-remove" onClick={() => onRemovePhoto(photo.id)} disabled={!isUnlocked}>Remove image</button>
        </div>
      </figure>)}
      <div className="doc-photo-upload no-print"><label className="doc-file-button">Add images / screenshots<input type="file" accept=".png,.jpg,.jpeg,.webp" multiple disabled={!isUnlocked} onChange={onUploadPhotos} /></label><span>Multiple images · original aspect ratio retained · captions and available location/time metadata are included.</span></div>
      <h2 className="doc-action-title">Action Items:</h2>
      <table className="doc-table doc-actions-table"><thead><tr><th>Agenda No</th><th>Action(s) to be Taken</th><th>Person(s) Responsible</th><th>Target Date</th></tr></thead><tbody>
        {actionItems.map(item => <tr key={item.id}><td>{item.agendaNo}</td><td>{item.text}<div className="doc-source-resolution no-print">Linked resolution: {item.sourceResolution}</div></td><td>{item.owner}</td><td>{item.targetDate ? dmy(item.targetDate) : ""}<button className="doc-remove no-print" onClick={() => onRemoveAction(item.id)} disabled={!isUnlocked}>Remove</button></td></tr>)}
        {!actionItems.length && <tr><td colSpan="4">&nbsp;</td></tr>}
      </tbody></table>
      {!actionItems.length && <p className="doc-empty-row no-print">No action rows added. Add only actions linked to a recorded resolution.</p>}
    </Page>
    <Page className="dac-page-closing">
      <p className="doc-closing-statement">The Chairperson and the Member Secretary thanked all the members for their contributions and requested their continued support.</p>
      <SignatureBlock title="Signatures on the minutes" rows={reactiveSignatures(meeting, signatures)}
        className="doc-signature-block-closing"
        legend="The minutes carry the signature of the Member Secretary who recorded them, the Chairperson who approved them, and the Academic Office that gave the final approval."
        emptyHint={<>
          <div className="doc-signature-cell pending"><div className="doc-signature-image"><span className="doc-signature-pending">Awaiting signature</span></div><b>Member Secretary</b><small>Signs when the minutes are submitted</small></div>
          <div className="doc-signature-cell pending"><div className="doc-signature-image"><span className="doc-signature-pending">Awaiting signature</span></div><b>Chairperson</b><small>Signs when approving the minutes</small></div>
        </>} />
      <p className="doc-enclosures">Encl: Annexures</p>
    </Page>
  </div>;
}

function App() {
  const [authUser, setAuthUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");
  useEffect(() => {
    apiFetch("/api/auth/me").then(async response => {
      if (!response.ok) throw new Error("Sign in to continue.");
      const data = await response.json();
      csrfToken = data.csrfToken || "";
      if (data.sessionToken) rememberSessionToken(data.sessionToken);
      setAuthUser(data.user);
    }).catch(() => setAuthUser(null)).finally(() => setAuthLoading(false));
  }, []);
  async function signedOut() {
    try { await apiFetch("/api/auth/logout", { method: "POST" }); } catch { /* session may already have expired */ }
    csrfToken = ""; rememberSessionToken(""); setAuthUser(null); setAuthError("");
  }
  // A dead session must never leave a half-rendered workspace on screen.
  useEffect(() => {
    function sessionExpired() {
      csrfToken = "";
      rememberSessionToken("");
      setAuthUser(null);
      setAuthError("Your session ended — sign in again to continue. Nothing you saved was lost.");
    }
    window.addEventListener("dac:session-expired", sessionExpired);
    return () => window.removeEventListener("dac:session-expired", sessionExpired);
  }, []);
  if (authLoading) return <div className="auth-loading"><div className="brand-mark"><span /><span /><span /></div><b>Loading secure workspace…</b></div>;
  if (authError || !authUser) return <LoginScreen onAuthenticated={data => {
    csrfToken = data.csrfToken || "";
    rememberSessionToken(data.sessionToken);
    setAuthUser(data.user);
    setAuthError("");
  }} />;
  return <Workspace key={authUser.id} user={authUser} onLogout={signedOut} />;
}

function Workspace({ user, onLogout }) {
  const role = user.role;
  const initialView = role === "academic_office" ? "review" : role === "external_member" ? "member" : role === "system_admin" ? "vault" : "overview";
  const [state, setState] = useState(() => loadState(user));
  const [view, setView] = useState(initialView);
  const [loaded, setLoaded] = useState(role === "system_admin");
  const [catalog, setCatalog] = useState({ schools: [] });
  const [inbox, setInbox] = useState([]);
  // The Approval queue always opens as a list; a request document is opened only on demand.
  const [queueMode, setQueueMode] = useState(true);
  const [mine, setMine] = useState([]);
  const [lastSaved, setLastSaved] = useState("");
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [, setClock] = useState(Date.now());
  const [customAgenda, setCustomAgenda] = useState({ title: "", reason: "" });
  const [memberDraft, setMemberDraft] = useState({ name: "", designation: "", role: "Member", email: "" });
  const [additionalTitle, setAdditionalTitle] = useState("");
  const [actionDraft, setActionDraft] = useState({ agendaId: "", text: "", owner: "", targetDate: "" });
  const [reviewComment, setReviewComment] = useState("");
  const [chairPick, setChairPick] = useState("");
  const [externalPick, setExternalPick] = useState("");
  const [directory, setDirectory] = useState([]);
  const [notifications, setNotifications] = useState({ items: [], unread: 0 });
  const [gate, setGate] = useState({ momReview: null, downloadGate: null, externalReport: null });
  const [report, setReport] = useState({ inbox: [], draft: null, canFill: false, workspaceId: "", status: "", comment: "" });
  const [vault, setVault] = useState({ summary: null, documents: [], school: "", department: "", committee: "", docType: "" });
  // The committee registry comes from the server (committees.py), so a cadence, title or
  // reference-prefix change lands in the interface without editing this file.
  const [registry, setRegistry] = useState({});
  const [signature, setSignature] = useState(null);
  const [signatureRequired, setSignatureRequired] = useState(false);
  const [signatureOpen, setSignatureOpen] = useState(false);
  const [chairpersons, setChairpersons] = useState([]);
  const [dacOffice, setDacOffice] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  // Offered by the server only in a demonstration build (never in production).
  const fastTrackEnabled = Boolean(capabilities?.fastTrack?.enabled);
  const [externalForm, setExternalForm] = useState({ name: "", designation: "", email: "" });
  const [externalFormOpen, setExternalFormOpen] = useState(false);
  const [chairInbox, setChairInbox] = useState([]);
  // The Chairperson reviews a request in full before signing it: the whole document,
  // not the one-line summary row. Kept out of `state` so it can never autosave over
  // the organizer's document.
  const [chairReview, setChairReview] = useState(null);
  // Signature evidence for the document on screen (both signatories, or an "awaiting" row).
  const [requestSignatures, setRequestSignatures] = useState([]);
  const [momSignatures, setMomSignatures] = useState([]);
  // Only a brand-new account starts on "which committee?". An account that already has a
  // request must land on that request — most of all when it has been returned for
  // revision, because that is where the Member Secretary has to make the corrections.
  const [committeePicker, setCommitteePicker] = useState(false);
  // Action Taken Report: the reports this account may see, and the one on screen.
  const [atr, setAtr] = useState({ reports: [], rules: null, choices: [], loading: false,
    selected: null, report: null, window: null, history: [], meeting: null, busy: false, comment: "" });
  const [calendar, setCalendar] = useState({ entries: [], rules: null, loading: false, busy: false,
    year: "", draft: [] });
  const [archive, setArchive] = useState({ rows: [], summary: null, filters: null, loading: false,
    query: { committee: "", school: "", department: "", academicYear: "", docType: "", status: "", q: "", dateFrom: "", dateTo: "" } });
  const [archiveViewer, setArchiveViewer] = useState(null);
  const [minutesInbox, setMinutesInbox] = useState([]);
  const [minutesReview, setMinutesReview] = useState(null);
  const [pendingChairDecision, setPendingChairDecision] = useState(null);
  const [chairComment, setChairComment] = useState("");
  const [requestFormState, setRequestFormState] = useState({ allowed: false, reason: "" });

  useEffect(() => {
    apiFetch("/api/committees")
      .then(response => response.ok ? response.json() : { committees: [] })
      .then(data => {
        const next = {};
        for (const entry of (data.committees || [])) {
          const local = COMMITTEE_META[entry.code] || {};
          next[entry.code] = { ...local, ...entry, note: entry.startNote || local.note, icon: local.icon || "▤" };
        }
        if (Object.keys(next).length) setRegistry(next);
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    const storageKey = `${STATE_KEY}:${user.id}`;
    if (role === "system_admin") { setLoaded(true); return; }
    Promise.all([
      apiFetch("/api/workspace").then(response => response.ok ? response.json() : null).catch(() => null),
      (["faculty", "academic_office"].includes(role)
        ? apiFetch("/api/catalog").then(response => response.ok ? response.json() : { schools: [] }).catch(() => ({ schools: [] }))
        : Promise.resolve({ schools: [] })),
    ]).then(([workspaceData, catalogData]) => {
      setCatalog(catalogData || { schools: [] });
      if (workspaceData?.state) {
        const loadedState = { ...loadState(user), ...workspaceData.state, workspaceId: workspaceData.workspaceId || workspaceData.state.workspaceId || workspaceData.state.meeting?.id };
        // Older documents can carry two rows with the same id; keep the first of each.
        const seenMemberIds = new Set();
        loadedState.meeting = { ...(loadedState.meeting || {}), members: ((loadedState.meeting || {}).members || []).filter(member => {
          if (!member?.id || seenMemberIds.has(member.id)) return false;
          seenMemberIds.add(member.id);
          return true;
        }) };
        setState(loadedState); setReviewComment(loadedState.officeComment || "");
      } else {
        // Nothing saved yet: this is the one case where asking "DAC or BOS?" is the
        // helpful first screen.
        const fresh = defaultState(user); setState(fresh);
        if (["faculty"].includes(role)) setCommitteePicker(true);
      }
    }).finally(() => setLoaded(true));
  }, [role, user]);
  useEffect(() => {
    if (!loaded || role === "system_admin") return;
    // When the browser refuses storage (sandboxed frame) the workspace simply keeps the
    // draft in memory and the server copy remains authoritative.
    safeStorage.set(`${STATE_KEY}:${user.id}`, JSON.stringify(state));
  }, [state, loaded, role, user.id]);
  useEffect(() => {
    // Only a draft the Member Secretary can still edit is autosaved; once the request is
    // with the Chairperson or the office the server refuses the write, so do not ask.
    if (!loaded || role !== "faculty" || !["draft", "revision", "rejected"].includes(state.status)) return undefined;
    const timer = setTimeout(async () => {
      try {
        const response = await apiFetch("/api/workspace/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspaceId: state.workspaceId || state.meeting.id, state }) });
        const result = await response.json();
        if (response.ok) {
          setLastSaved(new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }));
          if (!mine.some(item => item.workspaceId === (state.workspaceId || state.meeting.id))) {
            apiFetch("/api/workspaces/mine").then(listResponse => listResponse.ok ? listResponse.json() : { workspaces: [] }).then(data => setMine(data.workspaces || [])).catch(() => {});
          }
        } else if (response.status !== 409) showToast(result.error || "Autosave failed.", true);
      } catch { /* the local cache remains available if the API is briefly unavailable */ }
    }, 500);
    return () => clearTimeout(timer);
  }, [state, loaded, role, mine]);
  useEffect(() => {
    if (!loaded || !["faculty", "academic_office"].includes(role)) return;
    apiFetch("/api/outbox").then(response => response.ok ? response.json() : []).then(rows => {
      if (Array.isArray(rows)) setState(current => ({ ...current, outbox: rows.slice(-100) }));
    }).catch(() => {});
  }, [loaded, role]);
  useEffect(() => {
    if (!loaded || !["system_admin", "academic_office"].includes(role)) return;
    apiFetch("/api/audit").then(response => response.ok ? response.json() : []).then(rows => {
      if (Array.isArray(rows)) setState(current => ({ ...current, audit: [...rows].reverse().slice(0, 100) }));
    }).catch(() => {});
  }, [loaded, role]);
  useEffect(() => {
    if (!loaded || role !== "faculty") return;
    apiFetch("/api/workspaces/mine").then(response => response.ok ? response.json() : { workspaces: [] }).then(data => setMine(data.workspaces || [])).catch(() => setMine([]));
  }, [loaded, role, state.status]);
  useEffect(() => {
    if (role !== "academic_office" || view !== "review") return;
    apiFetch("/api/workspaces/inbox").then(response => response.ok ? response.json() : { workspaces: [] }).then(async data => {
      const rows = data.workspaces || []; setInbox(rows);
    }).catch(() => setInbox([]));
  }, [role, state.status, view]);
  useEffect(() => {
    if (!loaded) return;
    if (view === "atr" && ["faculty", "academic_office", "system_admin"].includes(role)) loadAtr();
    if (view === "calendar" && ["faculty", "academic_office", "system_admin"].includes(role)) loadCalendar();
  }, [view, loaded, role]);
  useEffect(() => { if (!toast) return undefined; const timer = setTimeout(() => setToast(null), 4400); return () => clearTimeout(timer); }, [toast]);
  // What this account may do: a DAC may only be scheduled by one of its own Member
  // Secretaries, and only one live request may exist for a DAC at a time.
  useEffect(() => {
    if (!loaded) return;
    apiFetch("/api/capabilities").then(response => response.ok ? response.json() : null)
      .then(data => setCapabilities(data)).catch(() => setCapabilities(null));
  }, [loaded]);
  useEffect(() => {
    if (!loaded || !["faculty", "academic_office"].includes(role)) return;
    const school = state.meeting?.school || "";
    const department = state.meeting?.department || "";
    // The offices of the selected DAC: who may chair it, who observes it.
    if (school) {
      apiFetch(`/api/dac/office?school=${encodeURIComponent(school)}&department=${encodeURIComponent(department)}`)
        .then(response => response.ok ? response.json() : null)
        .then(data => {
          setDacOffice(data?.unit || null);
          setChairpersons((data?.unit?.chairPeople || []).filter(person => person.active !== false));
        }).catch(() => { setDacOffice(null); setChairpersons([]); });
    } else {
      setDacOffice(null);
    }
    if (role === "faculty") {
      apiFetch("/api/workspaces/chair-inbox").then(response => response.ok ? response.json() : { workspaces: [] })
        .then(data => setChairInbox(data.workspaces || [])).catch(() => setChairInbox([]));
    }
    apiFetch("/api/directory/faculty").then(response => response.ok ? response.json() : { people: [] })
      .then(data => setDirectory(data.people || [])).catch(() => setDirectory([]));
  }, [loaded, role, state.meeting?.school, state.meeting?.department]);
  useEffect(() => {
    if (!loaded || role === "system_admin") return;
    apiFetch("/api/notifications").then(response => response.ok ? response.json() : { items: [], unread: 0 })
      .then(data => setNotifications({ items: data.items || [], unread: data.unread || 0 })).catch(() => {});
  }, [loaded, role, state.status, view]);
  async function refreshGate() {
    const workspaceId = state.workspaceId || state.meeting?.id;
    if (!workspaceId) return;
    const response = await apiFetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
    if (!response.ok) return;
    const detail = await response.json();
    setGate({ momReview: detail.momReview || null, downloadGate: detail.downloadGate || null, externalReport: detail.externalReport || null });
    if (detail.state) setState(current => ({ ...current, ...detail.state, workspaceId: detail.workspaceId || current.workspaceId }));
  }
  useEffect(() => { if (loaded && state.status === "approved" && ["faculty", "academic_office"].includes(role)) refreshGate(); }, [loaded, state.status, state.workspaceId]);
  useEffect(() => {
    apiFetch("/api/signature/me").then(response => response.ok ? response.json() : null)
      .then(data => { if (!data) return; setSignature(data.signature); if (data.required) setSignatureRequired(true); })
      .catch(() => {});
  }, []);
  useEffect(() => {
    function onSignatureRequired() { setSignatureRequired(true); }
    window.addEventListener("dac:signature-required", onSignatureRequired);
    return () => window.removeEventListener("dac:signature-required", onSignatureRequired);
  }, []);
  useEffect(() => {
    if (view !== "vault" || !["academic_office", "system_admin"].includes(role)) return;
    apiFetch("/api/documents").then(response => response.ok ? response.json() : { summary: null, documents: [] })
      .then(data => setVault({ summary: data.summary || null, documents: data.documents || [],
                               school: "", department: "", committee: "", docType: "" })).catch(() => {});
  }, [view, role]);
  useEffect(() => {
    if (view !== "member") return;
    apiFetch("/api/external-report/inbox").then(response => response.ok ? response.json() : { meetings: [] })
      .then(data => {
        const meetings = data.meetings || [];
        setReport(current => ({ ...current, inbox: meetings }));
        if (meetings.length && !report.workspaceId && role !== "academic_office") loadReport(meetings[0].workspaceId);
      }).catch(() => setReport(current => ({ ...current, inbox: [] })));
  }, [view, role]);
  useEffect(() => { const timer = setInterval(() => setClock(Date.now()), 15000); return () => clearInterval(timer); }, []);

  const isUnlocked = unlocked(state);
  const endPassed = endTimePassed(state.meeting);
  const canEditRequest = role === "faculty" && ["draft", "revision", "rejected"].includes(state.status);
  const meetingLabel = `${committeeCode(state.meeting)}-${String(Number(numberOnly(state.meeting.meetingNo)) || 0).padStart(2, "0")} · ${state.meeting.department || "Department not set"}`;
  const presentCount = (state.meeting.members || []).filter(member => member.present).length;
  const agendaBank = state.agendaBank || DEFAULT_BANK;
  const selectedActionAgenda = state.momItems.find(item => item.id === actionDraft.agendaId) || state.momItems[0];
  const triageRows = state.resolutionTriage?.items || [];
  function triageFor(agendaId) { return triageRows.find(row => row.agendaId === agendaId) || null; }
  function actionCategoryFor(agenda) {
    const verdict = triageFor(agenda?.id);
    if (verdict) return verdict.category;
    const attached = state.actionItems.find(action => action.agendaId === agenda?.id && action.category);
    return attached ? attached.category : "";
  }

  function showToast(message, isError = false) { setToast({ message, isError }); }
  async function openWorkspace(workspaceId) {
    try {
      const response = await apiFetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Meeting request could not be opened.");
      setState({ ...loadState(user), ...result.state, workspaceId: result.workspaceId });
      setReviewComment(result.state.officeComment || "");
      if (role === "faculty") { setCommitteePicker(false); setView(result.state.status === "approved" ? "mom" : "request"); }
    } catch (error) { showToast(error.message || "Meeting request could not be opened.", true); }
  }
  function createNewMeeting(committee = "") {
    if (role !== "faculty") return;
    if (scheduleBlocked) { showToast(scheduleReason, true); return; }
    const fresh = defaultState(user);
    const code = COMMITTEE_META[String(committee || "").toUpperCase()] ? String(committee).toUpperCase() : committeeCode(state.meeting);
    fresh.committee = code;
    fresh.meeting = { ...fresh.meeting, committee: code };
    setState(fresh); setView("request");
    showToast(`New ${code} meeting request created for your provisioned school and department.`);
  }
  // The first screen of the meeting request: DAC or BOS.
  function startCommittee(code) {
    const meta = COMMITTEE_META[code];
    if (!meta) return;
    const untouched = ["draft", "revision", "rejected"].includes(state.status)
      && !state.submittedVersion && !(state.meeting.members || []).some(member => member.role === "Chairperson")
      && state.meeting.agendas?.length <= 3;
    if (untouched) {
      setState(current => ({ ...current, committee: code,
        meeting: { ...current.meeting, committee: code, meetingNo: "1" } }));
      showToast(`${code} meeting request started — ${meta.scheduleShort}.`);
    } else {
      createNewMeeting(code);
    }
    setCommitteePicker(false);
    setView("request");
  }
  // ------------------------------------------------------------------ Action Taken Report
  async function loadAtr(preferredId = "") {
    setAtr(current => ({ ...current, loading: true }));
    try {
      const response = await apiFetch("/api/atr");
      const data = response.ok ? await response.json() : { reports: [] };
      const reports = data.reports || [];
      setAtr(current => ({ ...current, reports, rules: data.rules || null,
        choices: data.statusChoices || [], loading: false }));
      const target = preferredId || atr.selected
        || (reports.find(row => row.isOwner && row.window?.canFill) || reports[0])?.workspaceId;
      if (target) await openAtr(target);
    } catch (error) {
      setAtr(current => ({ ...current, loading: false }));
      showToast(error.message || "The Action Taken Reports could not be loaded.", true);
    }
  }
  async function openAtr(workspaceId) {
    try {
      const response = await apiFetch(`/api/atr/${encodeURIComponent(workspaceId)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "That report could not be opened.");
      setAtr(current => ({ ...current, selected: workspaceId, report: data.report,
        window: data.window, history: data.history || [], meeting: data.meeting || null,
        choices: data.statusChoices || current.choices, comment: "" }));
    } catch (error) { showToast(error.message || "That report could not be opened.", true); }
  }
  function editAtrRow(index, field, value) {
    setAtr(current => ({
      ...current,
      report: { ...current.report,
        rows: (current.report?.rows || []).map((row, position) =>
          position === index ? { ...row, [field]: value } : row) },
    }));
  }
  async function saveAtr(silent = false) {
    if (!atr.report) return;
    setAtr(current => ({ ...current, busy: true }));
    try {
      const response = await apiFetch(`/api/atr/${encodeURIComponent(atr.report.workspaceId)}/save`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows: atr.report.rows }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The report could not be saved.");
      setAtr(current => ({ ...current, report: data.report, window: data.window, busy: false }));
      if (!silent) showToast("Report saved. It stays in your record until you submit it.");
    } catch (error) {
      setAtr(current => ({ ...current, busy: false }));
      showToast(error.message, true);
    }
  }
  async function submitAtr() {
    if (!atr.report) return;
    setAtr(current => ({ ...current, busy: true }));
    try {
      const response = await apiFetch(`/api/atr/${encodeURIComponent(atr.report.workspaceId)}/submit`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows: atr.report.rows }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The report could not be submitted.");
      setAtr(current => ({ ...current, report: data.report, window: data.window, busy: false }));
      showToast("Report signed and sent to the Chairperson.");
      await loadAtr(atr.report.workspaceId);
    } catch (error) {
      setAtr(current => ({ ...current, busy: false }));
      showToast(error.message, true);
    }
  }
  async function atrChairDecide(decision) {
    if (!atr.report) return;
    if (decision === "revision" && !atr.comment.trim()) {
      showToast("Add a note explaining what should be corrected.", true); return;
    }
    setAtr(current => ({ ...current, busy: true }));
    try {
      const response = await apiFetch(`/api/atr/${encodeURIComponent(atr.report.workspaceId)}/chair-decision`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, comment: atr.comment }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The decision could not be recorded.");
      setAtr(current => ({ ...current, report: data.report, window: null, busy: false, comment: "" }));
      showToast(decision === "approved" ? "Report signed and filed with the meeting record."
                                        : "Report returned to the Member Secretary.");
      await loadAtr(atr.report.workspaceId);
    } catch (error) {
      setAtr(current => ({ ...current, busy: false }));
      showToast(error.message, true);
    }
  }
  async function loadCalendar() {
    setCalendar(current => ({ ...current, loading: true }));
    try {
      const response = await apiFetch("/api/atr/calendar");
      const data = response.ok ? await response.json() : { entries: [] };
      const entries = data.entries || [];
      setCalendar(current => ({ ...current, entries, rules: data.rules || null, loading: false }));
    } catch { setCalendar(current => ({ ...current, loading: false })); }
  }
  function startCalendar(academicYear) {
    const year = academicYear || calendar.year || "2026-27";
    const draft = [];
    ["Odd", "Even"].forEach(semester => {
      ["DAC", "BOS"].forEach(committee => {
        const count = committee === "DAC" ? 2 : 1;
        for (let index = 1; index <= count; index += 1) {
          const meetingNo = semester === "Odd" ? index : index + count;
          const existing = calendar.entries.find(entry => entry.academicYear === year
            && entry.semester === semester && entry.committee === committee && entry.meetingNo === meetingNo);
          draft.push({ academicYear: year, semester, committee, meetingNo,
            date: existing?.fromDate || existing?.date || "", fromDate: existing?.fromDate || existing?.date || "",
            toDate: existing?.toDate || "", note: existing?.note || "" });
        }
      });
    });
    setCalendar(current => ({ ...current, year, draft }));
  }
  async function saveCalendar() {
    setCalendar(current => ({ ...current, busy: true }));
    try {
      const response = await apiFetch("/api/atr/calendar", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: calendar.draft }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The calendar could not be saved.");
      setCalendar(current => ({ ...current, busy: false, entries: data.entries || current.entries }));
      showToast(`Calendar issued: ${data.written} date(s) recorded. Reports recalculated.`);
    } catch (error) {
      setCalendar(current => ({ ...current, busy: false }));
      showToast(error.message, true);
    }
  }

  function auditEvent(event, note = "") {
    const record = { at: new Date().toISOString(), event, role, details: { note, meetingId: state.meeting.id, status: state.status } };
    setState(current => ({ ...current, audit: [record, ...(current.audit || [])].slice(0, 100) }));
    apiFetch("/api/audit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(record) }).catch(() => {});
  }
  function updateSchool(name) {
    if (role === "faculty") {
      if (name !== user.school) showToast("This faculty account is scoped to its provisioned school.", true);
      return;
    }
    const school = (catalog.schools || []).find(item => item.name === name)
      || (catalog.schools || []).find(item => item.name === `School of ${name}`);
    if (!school) return;
    const firstDepartment = school.departments?.[0] || null;
    // A school that R1 gives no department is a school-level DAC: the department field
    // does not exist for it, so it is cleared rather than invented.
    setState(current => ({ ...current, meeting: { ...current.meeting,
      school: school.name,
      department: firstDepartment ? firstDepartment.name : "",
      schoolCode: String(school.code || school.name).toUpperCase(),
      departmentCode: firstDepartment ? String(firstDepartment.code || firstDepartment.name.replace(/[^A-Z]/gi, "").slice(0, 3)).toUpperCase() : "" } }));
  }
  function updateDepartment(name) {
    if (role === "faculty" && name !== user.department) { showToast("This faculty account is scoped to its provisioned department.", true); return; }
    const school = (catalog.schools || []).find(item => item.name === state.meeting.school);
    const match = (school?.departments || []).find(department => department.name === name);
    setState(current => ({ ...current, meeting: { ...current.meeting, department: match ? match.name : name,
      departmentCode: String(match?.code || name.replace(/[^A-Z]/gi, "").slice(0, 3)).toUpperCase() } }));
  }
  function updateMeeting(field, value) {
    setState(current => {
      const meeting = { ...current.meeting, [field]: value };
      if (field === "chairName" || field === "chairEmail") {
        meeting.members = current.meeting.members.map(member => member.role === "Chairperson"
          ? { ...member, [field === "chairName" ? "name" : "email"]: value }
          : member);
      }
      return { ...current, meeting, pdfGenerated: false };
    });
  }
  function updateMember(memberId, field, value) {
    setState(current => {
      const meeting = { ...current.meeting };
      meeting.members = current.meeting.members.map(member => {
        if (member.id !== memberId) return member;
        const updated = { ...member, [field]: value };
        if (updated.role === "Chairperson") {
          if (field === "name") meeting.chairName = value;
          if (field === "email") meeting.chairEmail = value;
        }
        if (updated.role === "Member Secretary") {
          if (field === "name") meeting.secretaryName = value;
          if (field === "email") meeting.secretaryEmail = value;
        }
        return updated;
      });
      return { ...current, meeting, pdfGenerated: false };
    });
  }
  function updateMemberRole(memberId, value) {
    const existingChair = state.meeting.members.find(member => member.role === "Chairperson" && member.id !== memberId);
    if (value === "Chairperson" && existingChair) { showToast("Only one Chairperson may be in the proposed roster.", true); return; }
    setState(current => {
      const meeting = { ...current.meeting };
      meeting.members = current.meeting.members.map(member => {
        if (member.id !== memberId) return member;
        if (member.role === "Chairperson" && value !== "Chairperson") { meeting.chairName = ""; meeting.chairEmail = ""; }
        if (member.role === "Member Secretary" && value !== "Member Secretary") { meeting.secretaryName = ""; meeting.secretaryEmail = ""; }
        const updated = { ...member, role: value, external: value === "External Member" };
        if (value === "Chairperson") { meeting.chairName = updated.name; meeting.chairEmail = updated.email; }
        if (value === "Member Secretary") { meeting.secretaryName = updated.name; meeting.secretaryEmail = updated.email; }
        return updated;
      });
      return { ...current, meeting };
    });
  }
  function updateMomItem(itemId, field, value) {
    setState(current => {
      const momItems = current.momItems.map(item => item.id === itemId ? { ...item, [field]: value } : item);
      const actionItems = field === "resolution" ? current.actionItems.map(action => action.agendaId === itemId ? { ...action, sourceResolution: value } : action) : current.actionItems;
      // A revised resolution invalidates the previous verification and triage verdicts.
      return { ...current, momItems, actionItems, aiReport: null, resolutionTriage: field === "resolution" ? null : current.resolutionTriage, pdfGenerated: false };
    });
  }
  function updatePhoto(photoId, field, value) {
    setState(current => ({ ...current, photos: current.photos.map(photo => photo.id === photoId ? { ...photo, [field]: value } : photo), pdfGenerated: false }));
  }
  function updateAdditional(itemId, field, value) {
    setState(current => ({ ...current, additionalDiscussions: current.additionalDiscussions.map(item => item.id === itemId ? { ...item, [field]: value } : item), pdfGenerated: false }));
  }
  function toggleCommonAgenda(id, checked) {
    const common = agendaBank.find(item => item.id === id);
    if (!common) return;
    setState(current => ({ ...current, meeting: { ...current.meeting, agendas: checked
      ? [...current.meeting.agendas, { id: common.id, kind: "standard", title: common.title, rationale: "" }]
      : current.meeting.agendas.filter(item => item.id !== id) }, aiReport: null, pdfGenerated: false }));
    auditEvent(checked ? "common_agenda_selected" : "proposal_agenda_removed", "Meeting request agenda list updated");
    // The MoM/ATR agenda needs the previous meeting's number and date: take them from
    // the last approved meeting of this committee instead of making the user type them.
    if (checked && ["std-mom", "std-atr"].includes(id)) {
      const meeting = state.meeting;
      const params = new URLSearchParams({ school: meeting.school || "", department: meeting.department || "",
        committee: meeting.committee || "DAC", exclude: state.workspaceId || meeting.id || "" });
      apiFetch(`/api/workspaces/previous-meeting?${params.toString()}`)
        .then(response => response.ok ? response.json() : null)
        .then(data => {
          if (!data || !data.meetingNo) return;
          setState(current => ({ ...current, meeting: { ...current.meeting,
            previousMeetingNo: data.meetingNo,
            previousMeetingDate: data.date || current.meeting.previousMeetingDate } }));
          showToast(`Previous meeting reference filled from the approved record: meeting ${data.meetingNo}, ${data.date ? dmy(data.date) : "date on record"}.`);
        })
        .catch(() => {});
    }
  }
  function addCustomAgenda() {
    const title = customAgenda.title.trim();
    if (!title) { showToast("Enter a proposed agenda title.", true); return; }
    if (state.meeting.agendas.some(item => item.title.toLowerCase() === title.toLowerCase())) { showToast("That agenda is already selected.", true); return; }
    setState(current => ({ ...current, meeting: { ...current.meeting, agendas: [...current.meeting.agendas, { id: uid("custom"), kind: "custom", title, rationale: customAgenda.reason.trim() }] }, aiReport: null, pdfGenerated: false }));
    setCustomAgenda({ title: "", reason: "" }); auditEvent("meeting_specific_agenda_proposed", "Meeting-specific agenda added to request draft");
  }
  function removeAgenda(id) {
    setState(current => ({ ...current, meeting: { ...current.meeting, agendas: current.meeting.agendas.filter(item => item.id !== id) }, aiReport: null, pdfGenerated: false }));
    auditEvent("proposal_agenda_removed", "Agenda removed from current request draft");
  }
  function addMember() {
    const { name, designation, role: memberRole, email } = memberDraft;
    if (!name.trim() || !email.trim()) { showToast("Enter the proposed member’s name and email.", true); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { showToast("Enter a valid email address.", true); return; }
    if (state.meeting.members.some(member => member.email.toLowerCase() === email.toLowerCase())) { showToast("That email is already on the proposed roster.", true); return; }
    const newMember = { id: uid("member"), name: name.trim(), designation: designation.trim(), role: memberRole, email: email.trim(), external: memberRole === "External Member", present: false };
    setState(current => ({ ...current, meeting: { ...current.meeting, members: [...current.meeting.members, newMember] } }));
    setMemberDraft({ name: "", designation: "", role: "Member", email: "" }); auditEvent("proposed_invitee_added", "Invitee added to current request roster");
  }
  function removeMember(id) {
    const target = state.meeting.members.find(member => member.id === id);
    if (target?.role === "Chairperson") { showToast("Assign another Chairperson before removing this roster entry.", true); return; }
    setState(current => ({ ...current, meeting: { ...current.meeting, members: current.meeting.members.filter(member => member.id !== id) } }));
    auditEvent("proposed_invitee_removed", "Invitee removed from current request roster");
  }
  // A meeting always needs one eligible Chairperson who is not the organizer. Fill the
  // seat automatically once the school's Deans/HoDs are known, so a fresh request is
  // submittable without the user hunting for the picker — and correct state saved by an
  // older build (chair = organizer) is repaired on load.
  useEffect(() => {
    if (role !== "faculty" || !chairpersons.length) return;
    const self = String(user.email || "").toLowerCase();
    const current = String(state.meeting?.chairEmail || "").toLowerCase();
    if (current && current !== self) return;
    const candidate = chairpersons.find(person => String(person.email || "").toLowerCase() !== self);
    if (!candidate) return;
    seatChair(candidate);
  }, [chairpersons, state.meeting?.chairEmail, user.email, role]);

  function validateRequest() {
    const meeting = state.meeting;
    const catalogSchool = (catalog.schools || []).find(item => item.name === meeting.school);
    const needsDepartment = Boolean(catalogSchool?.departments?.length);
    const required = ["meetingNo", "academicYear", "semester", "school", "schoolCode", "chairName", "chairEmail", "date", "startTime", "endTime", "venue"];
    if (needsDepartment) required.push("department", "departmentCode");
    const missing = required.filter(field => !String(meeting[field] || "").trim());
    if (missing.length) return `Complete required meeting details: ${missing.join(", ")}.`;
    if (!Number(numberOnly(meeting.meetingNo))) return "Meeting number must be a positive number.";
    if (!meeting.agendas.length) return "Select or add at least one agenda item.";
    if (meeting.agendas.some(item => ["std-mom", "std-atr"].includes(item.id)) && (!meeting.previousMeetingNo || !meeting.previousMeetingDate)) return "Add the previous meeting number and date for the selected MoM / ATR agenda.";
    if (meeting.members.filter(member => member.role === "Chairperson").length !== 1) return "Keep exactly one Chairperson in the proposed member roster.";
    if (meeting.members.some(member => !member.name.trim() || !member.email.trim())) return "Complete the name and email for every proposed member.";
    const badEmail = meeting.members.find(member => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(member.email || ""));
    if (badEmail) return `Check the email address for ${badEmail.name || "a proposed member"}.`;
    const chairEmail = String(meeting.chairEmail || "").toLowerCase();
    if (!chairEmail) return "Select the Chairperson — the Dean or a Head of Department of this school.";
    if (chairEmail === String(user.email || "").toLowerCase()) return "The Chairperson must be a different person: you are the Member Secretary who schedules and signs this request. Choose the Dean or a Head of Department of your school.";
    if (chairpersons.length && !chairpersons.some(person => String(person.email || "").toLowerCase() === chairEmail)) return "Choose the Chairperson from the eligible Deans and Heads of Department of this school.";
    const sameSchool = stripPrefix(meeting.school, "School of") === stripPrefix(user.school, "School of");
    const sameDepartment = !needsDepartment || stripPrefix(meeting.department, "Department of") === stripPrefix(user.department, "Department of");
    if (!sameSchool || !sameDepartment) return "The selected school and department must match your provisioned faculty scope. Ask the System Administrator to change your assignment if needed.";
    if (new Set(meeting.members.map(member => member.email.toLowerCase())).size !== meeting.members.length) return "The proposed member list contains a duplicate email address.";
    if (meeting.startTime >= meeting.endTime) return "Expected end time must be after start time.";
    if (meeting.mode !== "Offline" && !meeting.onlineLink.trim()) return "Add an online meeting link for the Online or Hybrid meeting.";
    return "";
  }
  async function submitRequest() {
    const error = validateRequest();
    if (error) { showToast(error, true); return; }
    setBusy(true);
    try {
      const response = await apiFetch("/api/workspace/submit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspaceId: state.workspaceId || state.meeting.id, state }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Request could not be submitted.");
      setState(result.state); setView("overview");
      loadRequestSignatures(state.workspaceId || result.state?.meeting?.id);
      auditEvent("request_submitted", result.state.changeRequest ? "Change request submitted for reapproval" : "Meeting proposal submitted");
      const code = committeeCode(result.state?.meeting || state.meeting);
      // The Chairperson reviews every version, so a resubmission is announced as such.
      const resubmission = (result.state?.submittedVersion || 1) > 1;
      showToast(resubmission
        ? `Corrected ${code} request sent back to the Chairperson for review and signature. The Academic Office sees it after that.`
        : `${code} request sent to the Chairperson for signature. The Academic Office sees it after that.`);
    } catch (error) { showToast(error.message || "Request could not be submitted.", true); }
    finally { setBusy(false); }
  }
  async function loadRequestSignatures(workspaceId) {
    if (!workspaceId) { setRequestSignatures([]); return; }
    try {
      const response = await apiFetch(`/api/workspace/${encodeURIComponent(workspaceId)}/signatures`);
      if (!response.ok) { setRequestSignatures([]); setMomSignatures([]); return; }
      const data = await response.json();
      setRequestSignatures(data.signatures || []);
      setMomSignatures(data.momSignatures || []);
    } catch { setRequestSignatures([]); setMomSignatures([]); }
  }
  useEffect(() => {
    if (view !== "minutes") return;
    if (!["faculty", "academic_office"].includes(role)) return;
    loadMinutesInbox();
  }, [view, role]);

  useEffect(() => {
    if (view !== "archive") return;
    if (!["academic_office", "system_admin"].includes(role)) return;
    if (archive.filters) return;         // already loaded once
    loadArchive({});
  }, [view, role]);

  useEffect(() => {
    if (!loaded) return;
    loadRequestSignatures(state.workspaceId || state.meeting?.id);
  }, [loaded, state.workspaceId, state.submittedAt, state.status, state.meeting?.chairEmail, state.chairApproval?.signedAt]);

  // A decision that was interrupted by the mandatory-signature dialog: finish it as soon
  // as the signature exists, so the Chairperson does not have to press approve twice.
  useEffect(() => {
    if (!pendingChairDecision) return;
    if (!signature) return;
    const { workspaceId, decision, comment } = pendingChairDecision;
    setPendingChairDecision(null);
    chairDecide(workspaceId, decision, comment);
  }, [signature, pendingChairDecision]);

  async function loadMinutesInbox() {
    try {
      const response = await apiFetch("/api/workspaces/minutes-inbox");
      if (!response.ok) { setMinutesInbox([]); return; }
      const data = await response.json();
      setMinutesInbox(data.workspaces || []);
    } catch { setMinutesInbox([]); }
  }
  async function openMinutesReview(workspaceId) {
    setBusy(true);
    try {
      const response = await apiFetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "These minutes could not be opened.");
      const signatures = await apiFetch(`/api/workspace/${encodeURIComponent(workspaceId)}/signatures`)
        .then(answer => answer.ok ? answer.json() : { momSignatures: [] });
      setMinutesReview({ workspaceId, state: data.state, momReview: data.momReview,
        signatures: signatures.momSignatures || [], comment: "" });
    } catch (error) { showToast(error.message || "These minutes could not be opened.", true); }
    finally { setBusy(false); }
  }
  async function decideMinutes(decision) {
    if (!minutesReview) return;
    const endpoint = role === "academic_office" ? "/api/workspace/mom/office-decision"
      : "/api/workspace/mom/chair-decision";
    const comment = (minutesReview.comment || "").trim();
    if (decision === "revision" && !comment) {
      showToast("Add a note so the Member Secretary knows what to correct.", true);
      return;
    }
    setBusy(true);
    try {
      const response = await apiFetch(endpoint, { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspaceId: minutesReview.workspaceId, decision, comment }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The minutes decision could not be recorded.");
      showToast(decision === "approved"
        ? (role === "academic_office" ? "Minutes approved and archived. The download is now open to the Member Secretary."
          : "Minutes signed — they now go to the Academic Office.")
        : "Minutes returned to the Member Secretary.");
      setMinutesReview(null);
      await loadMinutesInbox();
      loadRequestSignatures(state.workspaceId || state.meeting?.id);
    } catch (error) { showToast(error.message || "The minutes decision could not be recorded.", true); }
    finally { setBusy(false); }
  }
  async function loadArchive(patch = {}) {
    setArchive(current => ({ ...current, loading: true,
      query: { ...current.query, ...patch } }));
    const query = { ...archive.query, ...patch };
    const params = new URLSearchParams();
    if (query.committee) params.set("committee", query.committee);
    if (query.school) params.set("school", query.school);
    if (query.department) params.set("department", query.department);
    if (query.academicYear) params.set("academicYear", query.academicYear);
    if (query.docType) params.set("docType", query.docType);
    if (query.status) params.set("status", query.status);
    if (query.q) params.set("q", query.q);
    if (query.dateFrom) params.set("dateFrom", query.dateFrom);
    if (query.dateTo) params.set("dateTo", query.dateTo);
    try {
      const response = await apiFetch(`/api/archive/committees?${params.toString()}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The archive could not be loaded.");
      setArchive(current => ({ ...current, rows: data.rows || [], summary: data.summary || null,
        filters: data.filters || null, loading: false, query }));
    } catch (error) {
      setArchive(current => ({ ...current, loading: false }));
      showToast(error.message || "The archive could not be loaded.", true);
    }
  }
  // The archive table passes a workspace id; keep accepting the whole row too, so a
  // stale call site can never send "undefined" to the server.
  async function openArchiveMeeting(rowOrId) {
    const workspaceId = typeof rowOrId === "string" ? rowOrId : (rowOrId && rowOrId.workspaceId);
    if (!workspaceId) { showToast("That meeting could not be identified. Reload the archive.", true); return; }
    const row = (typeof rowOrId === "object" && rowOrId)
      || (archive.rows || []).find(entry => entry.workspaceId === workspaceId) || { workspaceId };
    setBusy(true);
    try {
      const response = await apiFetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "This meeting could not be opened.");
      const signatures = await apiFetch(`/api/workspace/${encodeURIComponent(workspaceId)}/signatures`)
        .then(answer => answer.ok ? answer.json() : { signatures: [], momSignatures: [] });
      setArchiveViewer({ row, state: data.state, status: data.status,
        signatures: signatures.signatures || [], momSignatures: signatures.momSignatures || [] });
    } catch (error) { showToast(error.message || "This meeting could not be opened.", true); }
    finally { setBusy(false); }
  }
  async function openChairRequest(workspaceId) {
    setBusy(true);
    try {
      const response = await apiFetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The request could not be opened.");
      setChairReview({ workspaceId, state: result.state });
      setChairComment("");
    } catch (error) { showToast(error.message || "The request could not be opened.", true); }
    finally { setBusy(false); }
  }
  async function chairDecide(workspaceId, decision, commentGiven) {
    const comment = decision === "approved"
      ? (commentGiven || "")
      : (commentGiven ?? window.prompt("What should the Member Secretary change?", ""));
    if (decision !== "approved" && !String(comment || "").trim()) {
      showToast("Add a note so the Member Secretary knows what to change.", true);
      return;
    }
    setBusy(true);
    try {
      const response = await apiFetch("/api/workspace/chair-decision", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspaceId, decision, comment: comment || "" }),
      });
      const result = await response.json();
      if (response.status === 428 || result.signatureRequired) {
        // The signature dialog is opening: remember the decision and finish it after signing.
        setPendingChairDecision({ workspaceId, decision, comment: comment || "" });
        showToast("Record your signature to complete this approval.");
        return;
      }
      if (!response.ok) throw new Error(result.error || "The decision could not be recorded.");
      showToast(decision === "approved" ? "Signed — the request now goes to the Academic Office." : "Returned to the Member Secretary.");
      const refreshed = await apiFetch("/api/workspaces/chair-inbox").then(row => row.ok ? row.json() : { workspaces: [] });
      setChairInbox(refreshed.workspaces || []);
      setChairReview(null); setChairComment("");
      loadRequestSignatures(workspaceId);
      auditEvent("chairperson_request_decision", decision);
    } catch (error) { showToast(error.message || "The decision could not be recorded.", true); }
    finally { setBusy(false); }
  }
  function downloadRequestForm() {
    const workspaceId = state.workspaceId || state.meeting.id;
    window.location.assign(`/api/workspace/${encodeURIComponent(workspaceId)}/request-form`);
  }
  async function sendInvitation(meeting, isUpdate) {
    const payload = {
      from: meeting.chairEmail,
      recipients: meeting.members.map(member => member.email),
      subject: `${isUpdate ? "Updated invitation" : "Invitation"}: DAC Meeting ${meeting.meetingNo} — ${meeting.department}`,
      meeting: { ...meeting, agendas: meeting.agendas.map(item => ({ ...item, title: agendaTitle(item, meeting) })) },
    };
    let result;
    try {
      const response = await apiFetch("/api/outbox", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not send the invitation");
      result = data;
    } catch {
      result = { ...payload, id: uid("outbox"), createdAt: new Date().toISOString(), status: "Queued" };
    }
    setState(current => ({ ...current, outbox: [...current.outbox, result].slice(-100) }));
    auditEvent("invitation_queued", result.status ? `Invitation ${result.status}` : "Invitation queued for delivery");
  }
  async function decideRequest(decision) {
    if (role !== "academic_office" || state.status !== "pending") return;
    const comment = reviewComment.trim();
    if (["revision", "rejected"].includes(decision) && !comment) { showToast(decision === "revision" ? "Add a comment explaining what should be revised." : "Add a reason before rejecting the request.", true); return; }
    setBusy(true);
    try {
      const response = await apiFetch("/api/workspace/decision", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspaceId: state.workspaceId || state.meeting.id, decision, comment }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The review decision could not be saved.");
      setState(result.state); setReviewComment("");
      if (decision === "approved") {
        await sendInvitation(result.state.meeting, !!result.state.changeRequest);
        showToast("Approved. A locked MoM snapshot was created and the invitation was logged."); setQueueMode(true);
      } else {
        showToast(decision === "revision" ? "Returned to the meeting organizer for revision." : "Request rejected.", decision === "rejected"); setQueueMode(true);
      }
    } catch (error) { showToast(error.message || "The review decision could not be saved.", true); }
    finally { setBusy(false); }
  }
  function approveRequest() { return decideRequest("approved"); }
  function getOfficeComment() { return reviewComment.trim(); }
  function returnForRevision() { return decideRequest("revision"); }
  function rejectRequest() { return decideRequest("rejected"); }
  function proposeChange() {
    if (state.status !== "approved" || isUnlocked || meetingStarted(state.meeting)) return;
    setState(current => ({ ...current, changeRequest: true, status: "revision", officeComment: "Chairperson proposed changes to an approved meeting request. Review the updated version." }));
    auditEvent("approved_request_change_started", "Changes require Academic Office reapproval"); setView("request");
  }
  function addBankItem(title, note) {
    const cleanTitle = title.trim();
    if (!cleanTitle) { showToast("Enter an agenda title.", true); return; }
    if (state.agendaBank.some(item => item.title.toLowerCase() === cleanTitle.toLowerCase())) { showToast("That common agenda already exists.", true); return; }
    setState(current => ({ ...current, agendaBank: [...current.agendaBank, { id: uid("std"), title: cleanTitle, note: note.trim() || "Common agenda item" }] }));
    auditEvent("common_agenda_added", "Academic Office added an item to the shared agenda bank"); showToast("Added to the common agenda bank.");
  }
  function removeBankItem(id) {
    setState(current => ({ ...current, agendaBank: current.agendaBank.filter(item => item.id !== id), meeting: ["draft", "revision", "rejected"].includes(current.status) ? { ...current.meeting, agendas: current.meeting.agendas.filter(item => item.id !== id) } : current.meeting }));
    auditEvent("common_agenda_removed", "Shared bank changed; submitted and approved meeting snapshots were preserved");
  }
  function restoreBank() { setState(current => ({ ...current, agendaBank: copy(DEFAULT_BANK) })); showToast("Restored the sample agenda bank."); }
  function toggleAttendance(memberId, checked) {
    setState(current => ({ ...current, meeting: { ...current.meeting, attendanceConfirmed: true, members: current.meeting.members.map(member => member.id === memberId ? { ...member, present: checked } : member) }, pdfGenerated: false }));
    auditEvent("actual_attendance_updated", "Attendance changed for the final Members Present table");
  }
  async function loadReport(workspaceId) {
    const response = await apiFetch(`/api/external-report/${encodeURIComponent(workspaceId)}`);
    const data = await response.json();
    if (!response.ok) { showToast(data.error || "The report could not be opened.", true); return; }
    setReport(current => ({ ...current, workspaceId, id: data.report?.id || "", draft: data.draft, canFill: !!data.canFill,
                            status: data.report?.status || "not_started", comment: data.report?.comment || "" }));
  }
  function updateReportRow(index, field, value) {
    setReport(current => {
      const draft = { ...current.draft, agenda: current.draft.agenda.map((row, position) => position === index ? { ...row, [field]: value } : row) };
      return { ...current, draft };
    });
  }
  function updateReportObservation(index, field, value) {
    setReport(current => {
      const observations = (current.draft.observations || []).map((row, position) => position === index ? { ...row, [field]: value } : row);
      return { ...current, draft: { ...current.draft, observations } };
    });
  }
  async function saveReport(submit) {
    if (!report.workspaceId) return;
    setBusy(true);
    try {
      const response = await apiFetch(`/api/external-report/${encodeURIComponent(report.workspaceId)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: report.draft, submit }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The report could not be saved.");
      setReport(current => ({ ...current, status: result.report?.status || current.status }));
      showToast(submit ? "Observation report submitted to the Academic Office." : "Draft observation report saved.");
      if (submit) loadReport(report.workspaceId);
    } catch (error) { showToast(error.message || "The report could not be saved.", true); }
    finally { setBusy(false); }
  }
  async function decideReport(reportId, decision) {
    const comment = window.prompt(decision === "approved" ? "Approval remark (optional):" : "Why is the report being returned?", "");
    if (decision === "returned" && !comment) return;
    setBusy(true);
    try {
      const response = await apiFetch(`/api/external-report/${encodeURIComponent(reportId)}/decision`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, comment: comment || "" }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The decision could not be recorded.");
      showToast(decision === "approved" ? "Observation report approved and archived in the vault." : "Report returned to the External Member.");
      loadReport(report.workspaceId);
    } catch (error) { showToast(error.message || "The decision could not be recorded.", true); }
    finally { setBusy(false); }
  }
  async function momReviewAction(path, payload = {}) {
    setBusy(true);
    try {
      const workspaceId = state.workspaceId || state.meeting.id;
      // Submit sends the *stored* minutes, so the minutes on screen are saved first.
      // Without this the Chairperson would receive the last exported copy instead of
      // what the Member Secretary has just written, and a fresh form would be refused
      // as "incomplete" even though every field is filled in.
      if (path.endsWith("/workspace/mom/submit")) {
        const saved = await apiFetch("/api/workspace/save", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ workspaceId, state }) });
        if (!saved.ok) {
          const problem = await saved.json();
          throw new Error(problem.error || "The minutes could not be saved before submission.");
        }
      }
      const response = await apiFetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspaceId, ...payload }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The minutes review step failed.");
      if (result.state) setState(current => ({ ...current, ...result.state }));
      setGate({ momReview: result.momReview || null, downloadGate: result.downloadGate || null, externalReport: result.externalReport || null });
      setReviewComment("");
      showToast(path.includes("submit") ? "Minutes submitted — the Chairperson has been notified."
        : path.includes("chair") ? "Chairperson decision recorded." : "Academic Office decision recorded.");
      auditEvent("minutes_review_step", path.split("/").pop());
    } catch (error) { showToast(error.message || "The minutes review step failed.", true); }
    finally { setBusy(false); }
  }
  function seatChair(person) {
    if (!person) return;
    setState(current => {
      const members = (current.meeting.members || []).map(member => member.role === "Chairperson"
        ? { ...member, name: person.name, email: person.email, designation: person.designation || member.designation }
        : member);
      const hasChair = (current.meeting.members || []).some(member => member.role === "Chairperson");
      return { ...current, meeting: { ...current.meeting, chairName: person.name, chairEmail: person.email,
        members: hasChair ? members : [{ id: uid("member"), name: person.name, designation: person.designation || "Professor", role: "Chairperson", email: person.email, external: false, present: false }, ...members] } };
    });
  }
  function applyChair(email) {
    setChairPick(email);
    const person = chairpersons.find(entry => entry.email === email)
      || directory.find(entry => entry.email === email);
    if (!person) return;
    setState(current => {
      const members = (current.meeting.members || []).map(member => member.role === "Chairperson"
        ? { ...member, name: person.name, email: person.email, designation: person.designation || member.designation }
        : member);
      const hasChair = (current.meeting.members || []).some(member => member.role === "Chairperson");
      return { ...current, meeting: { ...current.meeting, chairName: person.name, chairEmail: person.email,
        members: hasChair ? members : [{ id: uid("member"), name: person.name, designation: person.designation || "Professor", role: "Chairperson", email: person.email, external: false, present: false }, ...members] } };
    });
  }
  function applyExternal(email) {
    setExternalPick(email);
    // R1's external members live on the DAC, not in the general directory list, so
    // resolve the person from the DAC office first and fall back to the directory.
    const person = (dacOffice?.externals || []).find(entry => entry.email === email)
      || directory.find(entry => entry.email === email);
    if (!person) return;
    setState(current => {
      const others = (current.meeting.members || []).filter(member => member.role !== "External Member");
      return { ...current, meeting: { ...current.meeting, members: [...others, {
        id: uid("member"), name: person.name, designation: person.designation || "Professor",
        role: "External Member", email: person.email, external: true, present: false }] } };
    });
    showToast(`${person.name} (${person.school}) nominated as the External Member.`);
  }
  async function addDacExternal() {
    const { name, designation, email } = externalForm;
    if (!name.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      showToast("Give the external member's full name and a valid email address.", true);
      return;
    }
    try {
      const response = await apiFetch("/api/dac/external", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ school: state.meeting.school, department: state.meeting.department, name, designation, email }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The external member could not be added.");
      setExternalForm({ name: "", designation: "", email: "" });
      setExternalFormOpen(false);
      const refreshed = await apiFetch(`/api/dac/office?school=${encodeURIComponent(state.meeting.school)}&department=${encodeURIComponent(state.meeting.department)}`).then(row => row.ok ? row.json() : null);
      if (refreshed?.unit) setDacOffice(refreshed.unit);
      applyExternal(result.external.email);
      showToast(`${result.external.name} added to this DAC as its External Member.`);
    } catch (error) { showToast(error.message || "The external member could not be added.", true); }
  }
  async function markCompleted() {
    try {
      const response = await apiFetch("/api/workspace/complete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspaceId: state.workspaceId || state.meeting.id }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Completion could not be recorded.");
      setState(result.state);
      showToast(endPassed ? "Meeting marked COMPLETED; both gates are satisfied." : "Meeting marked COMPLETED. Minutes remain locked until the scheduled end time passes.");
    } catch (error) { showToast(error.message || "Completion could not be recorded.", true); }
  }
  function addAdditional() {
    const title = additionalTitle.trim();
    if (!title) { showToast("Enter the title of the additional discussion point.", true); return; }
    setState(current => ({ ...current, additionalDiscussions: [...current.additionalDiscussions, { id: uid("additional"), title, discussion: "", resolution: "" }], pdfGenerated: false }));
    setAdditionalTitle(""); auditEvent("additional_discussion_point_added", "Additional discussion point added outside the approved agenda");
  }
  function removeAdditional(id) {
    setState(current => ({ ...current, additionalDiscussions: current.additionalDiscussions.filter(item => item.id !== id), pdfGenerated: false }));
    auditEvent("additional_discussion_point_removed", "Additional discussion point removed");
  }
  function toggleNoResolution(item) {
    const linked = state.actionItems.some(action => action.agendaId === item.id);
    if (!item.noResolution && linked) { showToast("Remove linked actions before marking this agenda as having no resolution.", true); return; }
    setState(current => ({ ...current, momItems: current.momItems.map(row => row.id === item.id ? { ...row, noResolution: !row.noResolution, resolution: !row.noResolution ? "" : row.resolution } : row), aiReport: null, pdfGenerated: false }));
  }
  function addActionItem() {
    const agenda = selectedActionAgenda;
    if (!agenda) { showToast("Select an approved agenda for the action.", true); return; }
    if (!agenda.resolution?.trim() || agenda.noResolution) { showToast("Record a resolution for this agenda before linking an action.", true); return; }
    // Only In process / Not approved resolutions belong to the Action Items table.
    const category = actionCategoryFor(agenda);
    if (categoryCannotBeActioned(category)) { showToast(`This resolution is categorised ${categoryLabel(category)} — a recommended resolution is closed and produces no action item.`, true); return; }
    if (!actionDraft.text.trim() || !actionDraft.owner.trim()) { showToast("Enter the action and person responsible.", true); return; }
    const verdict = triageFor(agenda.id);
    const item = { id: uid("action"), agendaId: agenda.id, agendaNo: String(agenda.agendaNo), sourceResolution: agenda.resolution, text: actionDraft.text.trim(), owner: actionDraft.owner.trim(), targetDate: actionDraft.targetDate,
      ...(category ? { category, categoryLabel: categoryLabel(category), triageSource: verdict?.source || "reviewer" } : {}),
      ...(verdict?.shortAction && verdict.shortAction === actionDraft.text.trim() ? { shortAction: verdict.shortAction } : {}) };
    setState(current => ({ ...current, actionItems: [...current.actionItems, item], pdfGenerated: false }));
    setActionDraft({ agendaId: agenda.id, text: "", owner: "", targetDate: "" });
    auditEvent("resolution_linked_action_added", `Action linked to approved agenda ${agenda.agendaNo}`); showToast("Action linked to its agenda and resolution.");
  }
  function removeAction(id) {
    setState(current => ({ ...current, actionItems: current.actionItems.filter(item => item.id !== id), pdfGenerated: false }));
    auditEvent("resolution_linked_action_removed", "Action item removed from the MoM");
  }
  async function uploadOne(file) {
    const form = new FormData(); form.append("file", file);
    const response = await apiFetch("/api/upload", { method: "POST", body: form });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Upload failed.");
    auditEvent("file_uploaded", `${result.name} uploaded`);
    return result;
  }
  async function uploadAgendaFiles(agendaId, event) {
    const files = [...(event.target.files || [])];
    for (const file of files) {
      try {
        const result = await uploadOne(file);
        setState(current => ({ ...current, momItems: current.momItems.map(item => item.id === agendaId ? { ...item, attachments: [...item.attachments, result] } : item), pdfGenerated: false }));
        showToast(`${result.name} attached to the agenda.`);
      } catch (error) { showToast(error.message || "Upload failed.", true); }
    }
    event.target.value = "";
  }
  async function uploadPhotos(event) {
    const files = [...(event.target.files || [])];
    for (const file of files) {
      if (!/\.(png|jpe?g|webp)$/i.test(file.name)) { showToast("Only PNG, JPG or WEBP photos are accepted.", true); continue; }
      try {
        const result = await uploadOne(file);
        setState(current => ({ ...current, photos: [...current.photos, { id: uid("photo"), file: result, caption: file.name.replace(/\.[^.]+$/, ""), location: "", capturedAt: "" }], pdfGenerated: false }));
        showToast(`${result.name} added to the photo section.`);
      } catch (error) { showToast(error.message || "Upload failed.", true); }
    }
    event.target.value = "";
  }
  function removeAgendaFile(agendaId, fileId) {
    setState(current => ({ ...current, momItems: current.momItems.map(item => item.id === agendaId ? { ...item, attachments: item.attachments.filter(file => file.id !== fileId) } : item), pdfGenerated: false }));
    auditEvent("agenda_annexure_removed", "Agenda-linked annexure removed from MoM");
  }
  function removePhoto(photoId) {
    setState(current => ({ ...current, photos: current.photos.filter(photo => photo.id !== photoId), pdfGenerated: false }));
    auditEvent("photo_removed", "Photo removed from the template photo section");
  }
  async function checkAiConnection() {
    setBusy(true);
    try {
      const response = await apiFetch("/api/ai/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The connection check could not run.");
      setState(current => ({ ...current, aiCheck: result }));
      auditEvent("ai_connection_checked", result.ok ? "Hosted model answered the probe" : "Hosted model not active; offline rules in use");
      showToast(result.ok ? "AI connection OK — model-assisted verification is active." : (result.message || "Offline rules are in use."));
    } catch (error) { showToast(error.message || "The connection check could not run.", true); }
    finally { setBusy(false); }
  }
  async function runResolutionTriage() {
    setBusy(true);
    try {
      const momItems = state.momItems.map(item => ({ id: item.id, agendaNo: item.agendaNo, title: item.title, discussion: item.discussion, resolution: item.resolution, noResolution: item.noResolution }));
      const response = await apiFetch("/api/ai/triage", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ momItems, meeting: state.meeting }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The resolution triage could not run.");
      setState(current => ({ ...current, resolutionTriage: result }));
      const s2 = result.summary || {};
      auditEvent(result.mode === "ai-model" ? "ai_resolution_triage_run" : "offline_resolution_triage_run", `Category per resolution; ${s2.proposedActionItems || 0} proposed action item(s)`);
      showToast(`Triage complete — ${s2.approved || 0} approved, ${s2.inProcess || 0} in process, ${s2.notApproved || 0} not approved. Only the outstanding ${s2.proposedActionItems || 0} are proposed for action items.`);
    } catch (error) { showToast(error.message || "The resolution triage could not run.", true); }
    finally { setBusy(false); }
  }
  function useTriageText(agendaId) {
    const verdict = triageFor(agendaId);
    if (!verdict || !verdict.addToActionItems) { showToast("Only In process or Not approved resolutions can become action items.", true); return; }
    setActionDraft(current => ({ ...current, agendaId, text: verdict.shortAction, owner: "", targetDate: "" }));
    showToast("Short action text filled in. Name the person responsible and add the item.");
  }
  function overrideCategory(agendaId, category) {
    setState(current => {
      const triage = current.resolutionTriage;
      if (!triage) return current;
      const actionable = ACTIONABLE_CATEGORIES.includes(category);
      return { ...current, resolutionTriage: { ...triage,
        items: (triage.items || []).map(row => row.agendaId === agendaId ? { ...row, category, categoryLabel: categoryLabel(category), addToActionItems: actionable, shortAction: actionable && !row.shortAction ? `Needs follow-up - ${categoryLabel(category).toLowerCase()}` : (actionable ? row.shortAction : ""), source: `${row.source}+reviewer` } : row),
        summary: { ...(triage.summary || {}),
          approved: (triage.items || []).filter(row => row.agendaId !== agendaId ? row.category === "approved" : category === "approved").length,
          inProcess: (triage.items || []).filter(row => row.agendaId !== agendaId ? row.category === "in_process" : category === "in_process").length,
          notApproved: (triage.items || []).filter(row => row.agendaId !== agendaId ? row.category === "not_approved" : category === "not_approved").length,
          unclassified: (triage.items || []).filter(row => row.agendaId !== agendaId ? row.category === "unclassified" : category === "unclassified").length,
          proposedActionItems: (triage.items || []).filter(row => row.agendaId !== agendaId ? row.addToActionItems : actionable).length } } };
    });
    auditEvent("resolution_category_overridden", `Reviewer set agenda ${agendaId} to ${categoryLabel(category)}`);
    showToast(`Category set to ${categoryLabel(category)} by the reviewer.`);
  }
  async function runTextCheck() {
    const payload = state.momItems.map(item => ({ title: item.title, discussion: item.discussion, resolution: item.resolution, noResolution: item.noResolution }));
    const additional = state.additionalDiscussions.map(item => ({ title: item.title, discussion: item.discussion, resolution: item.resolution }));
    try {
      const response = await apiFetch("/api/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ momItems: [...payload, ...additional], meeting: state.meeting }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The verification could not run.");
      setState(current => ({ ...current, aiReport: result }));
      auditEvent(result.mode === "ai-model" ? "ai_content_verification_run" : "offline_content_verification_run", "Discussion/Resolution text only; no annexures or photos are analysed");
      showToast(result.mode === "ai-model" ? "AI content verification complete. Review the findings; no text was changed." : "Offline content verification complete. Review the findings; no text was changed.");
    } catch (error) { showToast(error.message || "The verification could not run.", true); }
  }
  // ---------------------------------------------------------------- demonstration fast-forward
  // A meeting's minutes stay locked until its scheduled end has passed AND the meeting is
  // marked completed. That is the rule, and it cannot be shown in a short demonstration.
  // The server offers this control only in a demonstration build; in production the flag is
  // absent, so the button is never rendered and the route answers 404.
  async function fastTrack(stage = "meeting") {
    setBusy(true);
    try {
      const response = await apiFetch("/api/demo/fast-track", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspaceId: state.workspaceId || state.meeting.id, stage }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The clock could not be fast-tracked.");
      if (result.state) setState(current => ({ ...current, ...result.state }));
      if (stage === "atr") {
        await loadAtr(atr.selected || atr.report?.workspaceId);
        showToast("Fast-tracked: the action-item target dates have passed, so the Action Taken Report is open.");
      } else {
        setGate(current => ({ ...current, momReview: result.momReview || current.momReview }));
        showToast("Fast-tracked: the meeting is now in the past and marked completed, so the minutes are unlocked.");
      }
      auditEvent("demo_fast_track", stage === "atr" ? "Action-item target dates moved into the past" : "Meeting clock moved into the past for the demonstration");
    } catch (error) { showToast(error.message || "The clock could not be fast-tracked.", true); }
    finally { setBusy(false); }
  }

  async function exportPdf(printMode = false) {
    if (!isUnlocked) { showToast("The final MoM stays locked until the scheduled end time has passed AND the meeting is marked COMPLETED.", true); return; }
    const printWindow = printMode ? window.open("about:blank", "_blank") : null;
    setBusy(true);
    try {
      // Approved MoM is frozen by design — don't block download with a stale save.
      if (state.status !== "approved" || (gate.downloadGate?.allowed !== true)) {
        const saveResponse = await apiFetch("/api/workspace/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspaceId: state.workspaceId || state.meeting.id, state }) });
        if (!saveResponse.ok) {
          const saveResult = await saveResponse.json().catch(()=> ({}));
          // Approved records are intentionally read-only (409 frozen); still allow export.
          const isFrozen409 = saveResponse.status === 409 && state.status === "approved";
          if (!isFrozen409) throw new Error(saveResult.error || "The latest minutes could not be saved.");
        }
      }
      const response = await apiFetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ meeting: state.meeting }) });
      if (!response.ok) { const err = await response.json(); throw new Error(err.error || "PDF generation failed."); }
      const blob = await response.blob(); const url = URL.createObjectURL(blob);
      if (printMode && printWindow) {
        printWindow.location.href = url;
        setState(current => ({ ...current, pdfGenerated: true })); auditEvent("final_pdf_print_opened", "Consolidated PDF opened using the download renderer");
        showToast("The consolidated PDF opened in a new tab. Use its PDF viewer Print control.");
      } else {
        if (printMode) showToast("Pop-up blocked; the consolidated PDF will download for printing.");
        const link = document.createElement("a"); link.href = url; link.download = `DAC-${state.meeting.meetingNo}-${state.meeting.department.replace(/[^a-z0-9]+/gi, "-")}.pdf`; document.body.appendChild(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        setState(current => ({ ...current, pdfGenerated: true })); auditEvent(printMode ? "final_pdf_print_fallback" : "final_pdf_generated", "Consolidated MoM PDF generated");
        showToast(printMode ? "PDF downloaded; open it and print." : "Consolidated PDF downloaded.");
      }
    } catch (error) {
      if (printWindow && !printWindow.closed) printWindow.close();
      showToast(error.message || "PDF generation failed.", true);
    } finally { setBusy(false); }
  }
  async function exportDocx() {
    if (!isUnlocked) { showToast("The final MoM stays locked until the scheduled end time has passed AND the meeting is marked COMPLETED.", true); return; }
    setBusy(true);
    try {
      if (state.status !== "approved" || (gate.downloadGate?.allowed !== true)) {
        const saveResponse = await apiFetch("/api/workspace/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspaceId: state.workspaceId || state.meeting.id, state }) });
        if (!saveResponse.ok) {
          const saveResult = await saveResponse.json().catch(()=> ({}));
          const isFrozen409 = saveResponse.status === 409 && state.status === "approved";
          if (!isFrozen409) throw new Error(saveResult.error || "The latest minutes could not be saved.");
        }
      }
      const response = await apiFetch("/api/export-docx", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ meeting: state.meeting }) });
      if (!response.ok) { const err = await response.json(); throw new Error(err.error || "Word export failed."); }
      const blob = await response.blob(); const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = `DAC-${state.meeting.meetingNo}-${state.meeting.department.replace(/[^a-z0-9]+/gi, "-")}.docx`; document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      auditEvent("final_docx_generated", "Editable Word MoM generated (Cambria 11 pt, 1.15 spacing)");
      showToast("Editable Word document downloaded with Cambria 11 pt text and 1.15 line spacing.");
    } catch (error) { showToast(error.message || "Word export failed.", true); }
    finally { setBusy(false); }
  }

  const workflow = <div className="workflow">{[
    ["Meeting proposal", ["draft", "pending", "revision", "rejected", "approved"].includes(state.status)],
    ["Office approval", state.status === "approved"],
    ["Meeting completed", isUnlocked],
    ["Final MoM", !!state.pdfGenerated],
  ].map(([label, done], index) => <div className={`workflow-step ${done ? "done" : ""} ${index === (state.status === "draft" || state.status === "revision" || state.status === "rejected" ? 0 : state.status === "pending" ? 1 : isUnlocked ? 3 : 2) ? "active" : ""}`} key={label}><span className="step-num">{done ? "✓" : index + 1}</span><span>{label}</span></div>)}</div>;

  function meetingControls(editable) {
    const selected = new Set(state.meeting.agendas.filter(item => item.kind === "standard").map(item => item.id));
    const hasPrevious = state.meeting.agendas.some(item => ["std-mom", "std-atr"].includes(item.id));
    if (!editable) return <><ToolCard title="Request status" tag={statusText(state.status)}><p>{state.status === "pending" ? "This submitted approval copy is read-only while the Academic Office reviews it." : "The approved agenda wording is the baseline for the final MoM."}</p>{state.status === "approved" && <><div className="doc-tool-kv"><span>Approved version</span><b>{state.approvalVersion}</b></div><div className="doc-tool-kv"><span>Generated agenda blocks</span><b>{state.momItems.length}</b></div></>}</ToolCard>
      {state.status === "approved" && <ToolCard title="Signed request & agenda approval form" tag="PDF">
        <p>This is the form you submitted: meeting details, the approved agenda, the members, and both signatures — yours as Member Secretary and the Chairperson's. It is released for download once the Academic Office approves, and a copy is archived in the document vault.</p>
        <div className="signature-inline">{signature ? <img src={signature.url} alt="Your signature" /> : <small className="muted">No signature on file.</small>}<small>Member Secretary · {user.name}</small></div>
        <div className="doc-tool-actions"><button className="btn btn-primary" onClick={downloadRequestForm}>Download signed request form ↓</button></div>
      </ToolCard>}
      {state.status === "approved" && <ToolCard title="Approved request" tag="Read only"><p>Approved agenda wording is immutable in the MoM. Significant changes return to the Academic Office for reapproval.</p>{!isUnlocked && !meetingStarted(state.meeting) && <><div className="notice info"><span className="notice-icon">i</span><span>Discussion, Resolution and annexure fields unlock only after the scheduled end time has passed AND the meeting is marked COMPLETED.</span></div><div className="doc-tool-actions mt-16"><button className="btn btn-outline" onClick={proposeChange}>Propose a change</button><button className="btn btn-primary" onClick={() => setView("mom")}>Open MoM workspace</button></div></>}</ToolCard>}</>;
    return <ToolCard title="Request controls" tag={`${state.meeting.agendas.length} agendas`}><p>Edit the official-looking document directly. These controls manage the shared agenda bank and invitee roster.</p>
      <div className="doc-tool-subheading">Chairperson (Dean or Head of Department)</div>
      <select className="doc-tool-input" value={state.meeting.chairEmail || chairPick} onChange={event => applyChair(event.target.value)} aria-label="Chairperson">
        <option value="">Select the Chairperson…</option>
        {chairpersons.map(person => <option value={person.email} key={person.email}>{person.name} · {person.designation}{person.hasSignature ? "" : " · signature pending"}</option>)}
      </select>
      {!chairpersons.length && <div className="notice warning mt-8"><span className="notice-icon">!</span><span>No Dean or Head of Department is provisioned for this school yet. Ask the System Administrator to assign one.</span></div>}
      <div className="doc-tool-subheading">External Member of this DAC</div>
      <select className="doc-tool-input" value={externalPick || (state.meeting.members || []).find(member => member.role === "External Member")?.email || ""} onChange={event => applyExternal(event.target.value)} aria-label="External Member">
        <option value="">Select the External Member…</option>
        {(dacOffice?.externals || []).map(person => <option value={person.email} key={`${person.email}-${person.name}`}>{person.name} · {person.designation}{person.source && person.source !== "R1" ? " · added by the DAC" : ""}</option>)}
        {!dacOffice?.externals?.length && directory.filter(person => person.role === "faculty" && person.school && stripPrefix(person.school, "School of") !== stripPrefix(state.meeting.school, "School of"))
          .map(person => <option value={person.email} key={person.email}>{person.name} · {person.school} · {person.department}</option>)}
      </select>
      {!externalFormOpen ? <div className="doc-tool-actions mt-8"><button className="btn btn-outline btn-small" onClick={() => setExternalFormOpen(true)}>Add a new external member</button></div>
        : <div className="doc-external-form">
            <div className="doc-tool-grid mt-8">
              <input className="doc-tool-input" value={externalForm.name} onChange={event => setExternalForm(current => ({ ...current, name: event.target.value }))} placeholder="Full name (e.g. Dr. A. Sharma)" aria-label="New external member name" />
              <input className="doc-tool-input" value={externalForm.designation} onChange={event => setExternalForm(current => ({ ...current, designation: event.target.value }))} placeholder="Designation (e.g. Professor, SoE)" aria-label="New external member designation" />
            </div>
            <div className="doc-tool-grid mt-8">
              <input className="doc-tool-input" type="email" value={externalForm.email} onChange={event => setExternalForm(current => ({ ...current, email: event.target.value }))} placeholder="Official email" aria-label="New external member email" />
              <button className="btn btn-primary btn-small" onClick={addDacExternal}>Add to this DAC</button>
              <button className="btn btn-outline btn-small" onClick={() => { setExternalFormOpen(false); setExternalForm({ name: "", designation: "", email: "" }); }}>Cancel</button>
            </div>
          </div>}
      <div className="doc-tool-subheading">Official agenda list — Office of the Dean Academics (GD-2 / Annexure-A)</div>
      {agendaGroupsFor(state.meeting.meetingNo, state.meeting.committee).map(group => <div className="doc-bank-group" key={group.key}>
        <div className={`doc-bank-group-head ${group.current ? "current" : ""}`}>{group.label}{group.current ? " · this meeting" : ""}</div>
        <div className="doc-bank-list">{group.items.map(item => <label className="doc-bank-row" key={`${group.key}-${item.id}`}><input type="checkbox" checked={selected.has(item.id)} onChange={event => toggleCommonAgenda(item.id, event.target.checked)} /><span><b>{item.no}. {item.text}</b><small>{item.applies || `Official agenda #${item.no}`}{item.groups.length === 2 ? " · DAC#1 and DAC#2" : ""}</small></span></label>)}</div>
      </div>)}
      <div className="doc-tool-subheading">Add meeting-specific agenda</div><input className="doc-tool-input" value={customAgenda.title} onChange={event => setCustomAgenda(current => ({ ...current, title: event.target.value }))} placeholder="Proposed agenda wording" aria-label="New agenda title" /><input className="doc-tool-input mt-8" value={customAgenda.reason} onChange={event => setCustomAgenda(current => ({ ...current, reason: event.target.value }))} placeholder="Reason / decision sought" aria-label="Reason for agenda" /><button className="btn btn-outline btn-small mt-8" onClick={addCustomAgenda}>Add proposed agenda</button>
      {hasPrevious && <><div className="doc-tool-subheading">Previous meeting reference</div><div className="doc-tool-grid"><label>Meeting no.<input className="doc-tool-input" value={state.meeting.previousMeetingNo} onChange={event => updateMeeting("previousMeetingNo", event.target.value)} /></label><label>Meeting date<input type="date" className="doc-tool-input" value={state.meeting.previousMeetingDate} onChange={event => updateMeeting("previousMeetingDate", event.target.value)} /></label></div></>}
      <div className="doc-tool-subheading">Meeting-specific organizer</div><div className="doc-organizer-card"><b>{user.name}</b><span>{user.email}</span><small>For this meeting only · assigned from your active faculty account</small></div>
      <div className="doc-tool-subheading">Add proposed member / invitee</div><input className="doc-tool-input" value={memberDraft.name} onChange={event => setMemberDraft(current => ({ ...current, name: event.target.value }))} placeholder="Full name" aria-label="New member name" /><div className="doc-tool-grid mt-8"><input className="doc-tool-input" value={memberDraft.designation} onChange={event => setMemberDraft(current => ({ ...current, designation: event.target.value }))} placeholder="Designation" aria-label="Designation" /><select className="doc-tool-input" value={memberDraft.role} onChange={event => setMemberDraft(current => ({ ...current, role: event.target.value }))} aria-label="New member role"><option>Member</option><option>Member Secretary</option><option>External Member</option></select></div><div className="doc-tool-grid mt-8"><input className="doc-tool-input" type="email" value={memberDraft.email} onChange={event => setMemberDraft(current => ({ ...current, email: event.target.value }))} placeholder="Official email" aria-label="Official email" /><button className="btn btn-outline btn-small" onClick={addMember}>Add member</button></div>
      <div className="doc-tool-actions mt-16"><button className="btn btn-outline" onClick={() => showToast(lastSaved ? `Draft autosaved at ${lastSaved}.` : "Draft is syncing to the secure local database.")}>Save draft</button><button className="btn btn-primary" onClick={submitRequest}>{state.submittedVersion ? "Resubmit to the Chairperson for signature" : "Submit to the Chairperson for signature"} <span>→</span></button></div>
    </ToolCard>;
  }

  function committeePickerView() {
    return <>
      <SectionHeading eyebrow="New meeting request"
        title="Which committee are you scheduling?"
        description="DAC and BOS use the same signed workflow. Choose the committee now — the request form, the minutes, the agenda series and the schedule wording follow your choice." />
      <div className="committee-grid">
        {(Object.keys(registry).length ? Object.keys(registry) : COMMITTEE_CODES).map(code => {
          const meta = registry[code] || COMMITTEE_META[code];
          const current = committeeCode(state.meeting) === code && state.status !== "approved";
          return <article className={`committee-card ${current ? "current" : ""}`} key={code}>
            <div className="committee-card-head">
              <span className="committee-mark">{meta.icon}</span>
              <div><b>{code}</b><small>{meta.name}</small></div>
              {current && <span className="tag">in progress</span>}
            </div>
            <p>{meta.note}</p>
            <dl className="committee-facts">
              <div><dt>Meetings</dt><dd>{meta.scheduleShort}</dd></div>
              <div><dt>Agenda series</dt><dd>{meta.agendaSeries}</dd></div>
              <div><dt>Request form</dt><dd>{code} Meeting Request and Agenda Approval Form</dd></div>
              <div><dt>Record</dt><dd>{code} Minutes of Meeting</dd></div>
            </dl>
            <button className="btn btn-primary" onClick={() => startCommittee(code)}>
              Continue with {code} <span>→</span>
            </button>
          </article>;
        })}
      </div>
      <div className="notice info mt-16"><span className="notice-icon">i</span><span>
        Whichever you pick, the route is the same: the Member Secretary signs the request, the Chairperson
        reviews and signs it, the Academic Office approves it, and after the meeting the minutes are signed
        by both and approved by the Academic Office. Every corrected version goes back to the Chairperson
        first — the office only ever receives a signed document.
      </span></div>
    </>;
  }

  function requestView() {
    if (role !== "faculty") return <><SectionHeading eyebrow="Before the meeting" title="Meeting request & agenda approval" description="The signed-in faculty member schedules this DAC meeting and becomes its meeting-specific Chairperson/organizer." /><div className="empty-state"><h3>Faculty workspace</h3><p>Only an active, allow-listed faculty account may schedule a meeting.</p></div></>;
    if (committeePicker) return committeePickerView();
    const editable = canEditRequest;
    const side = <div className="document-side-panel"><ToolCard title="My meeting workspaces" tag={`${mine.length} saved`}><p>Each workspace is owned by your signed-in faculty account.</p><button className="btn btn-outline btn-small mb-8" title={scheduleBlocked ? scheduleReason : undefined} aria-disabled={scheduleBlocked || undefined} onClick={() => { if (scheduleBlocked) { showToast(scheduleReason, true); return; } setCommitteePicker(true); }}>＋ New meeting (DAC or BOS)</button>{mine.map(item => <button className={`workspace-pick-row ${item.workspaceId === state.workspaceId ? "selected" : ""}`} key={item.workspaceId} onClick={() => openWorkspace(item.workspaceId)}><b>{item.department} · {longDate(item.date)}</b><small>{item.school} · Meeting {item.meetingNo} · {statusText(item.status)}</small></button>)}</ToolCard>{meetingControls(editable)}</div>;
    return <><SectionHeading eyebrow="Before the meeting" title="Meeting request & agenda approval" description="One structured meeting record feeds the request, approval preview, locked MoM and final PDF." />{workflow}{statusBanner(state)}
      <div className="document-workspace request-workspace"><main className="document-canvas-column"><RequestDocument meeting={state.meeting} editable={editable} signatures={requestSignatures} catalog={role === "faculty" ? { schools: (catalog.schools || []).filter(school => school.name === user.school).map(school => ({ ...school, departments: (school.departments || []).filter(department => department.name === user.department) })) } : catalog} onSchoolChange={updateSchool} onDepartmentChange={updateDepartment} onMeetingChange={updateMeeting} onMemberChange={updateMember} onMemberRoleChange={updateMemberRole} onRemoveMember={removeMember} onRemoveAgenda={removeAgenda} /></main>{side}</div>
    </>;
  }
  // ------------------------------------------------------------------ Action Taken Report screen
  function atrWindowChip(win) {
    if (!win) return null;
    const tone = win.availability === "approved" ? "approved"
      : win.availability === "submitted" ? "pending"
      : win.availability === "overdue" ? "rejected"
      : win.availability === "open" ? "pending" : "draft";
    return <StatusPill status={tone}>{win.label}</StatusPill>;
  }

  function atrView() {
    if (!["faculty", "academic_office", "system_admin"].includes(role)) {
      return <><SectionHeading eyebrow="After the meeting" title="Action Taken Report" description="The Member Secretary fills the report and the Chairperson signs it." /><div className="empty-state"><h3>Not available to this account</h3></div></>;
    }
    const reports = atr.reports || [];
    const report = atr.report;
    const win = atr.window;
    const canEdit = report && atr.report?.isOwner !== false
      && ["faculty"].includes(role) && (win?.canFill) && ["draft", "returned"].includes(report.status);
    const isChair = report && String(report.chairEmail || "").toLowerCase() === String(user.email || "").toLowerCase();

    const list = <ToolCard title="Action Taken Reports" tag={`${reports.length} report(s)`}>
      <p>One report per completed meeting, filled after the latest action-item target date has passed and before the next meeting.</p>
      {reports.length ? reports.map(row => <button className={`workspace-pick-row ${row.workspaceId === atr.selected ? "selected" : ""}`} key={row.workspaceId} onClick={() => openAtr(row.workspaceId)}>
        <b>{row.committee} {row.meetingNo} · {row.department || row.school}</b>
        <small>{longDate(row.meetingDate)} · {row.status} · {row.completedRows}/{row.totalRows} rows filled</small>
        <small>{row.window?.label}</small>
      </button>) : <div className="empty-state"><h3>No report to fill</h3><p>A report appears once the Academic Office approves the minutes of a meeting that recorded action items.</p></div>}
    </ToolCard>;

    if (!report) {
      return <><SectionHeading eyebrow="After the meeting" title="Action Taken Report" description="Report on the action items of the last meeting, before the next one." />{atr.loading ? <div className="empty-state"><h3>Loading…</h3></div> : <div className="grid grid-2">{list}<ToolCard title="How the timing works" tag="Rules"><ul className="plain-list"><li>The report opens the day after the <b>latest</b> action-item target date has passed.</li><li>It is due <b>one week before the next meeting</b> of the same committee — the date the Academic Office issued for the year.</li><li>Reminders start <b>three weeks before</b> that meeting and repeat until the report is submitted.</li></ul></ToolCard></div>}</>;
    }

    const rows = report.rows || [];
    const timing = <ToolCard title="Timing" tag={win?.calendarIssued ? "Issued calendar" : "Date not issued"}>
      <ul className="plain-list">
        <li>Latest action-item target date: <b>{win?.latestTargetDate ? dmy(win.latestTargetDate) : "not recorded"}</b></li>
        <li>Report opens: <b>{win?.activationDate ? dmy(win.activationDate) : "—"}</b>{win?.daysUntilOpen ? ` (in ${win.daysUntilOpen} day(s))` : ""}</li>
        <li>Next meeting: <b>{win?.nextMeetingDate ? `${report.committee} ${win.nextMeetingNo} · ${dmy(win.nextMeetingDate)}` : "not yet issued by the Academic Office"}</b></li>
        <li>Due by: <b>{win?.dueBy ? `${dmy(win.dueBy)} (one week before the meeting)` : "set when the next meeting date is issued"}</b></li>
      </ul>
      {win?.scheduleConflict && <div className="notice warning"><span className="notice-icon">!</span><span>The next meeting is less than a week after the report opens, so the report is due from the day it opens.</span></div>}
      {!win?.calendarIssued && !["approved", "submitted"].includes(report.status) && <div className="notice info"><span className="notice-icon">i</span><span>The Academic Office has not issued the next meeting date yet. The report can be filled now, but its deadline appears once that date is issued.</span></div>}
      {fastTrackEnabled && report.status === "draft" && !win?.canFill && <div className="demo-fast-track mt-12"><div className="notice info"><span className="notice-icon">⏩</span><span><b>Demonstration fast-forward.</b> Pulls this meeting&apos;s action-item target dates into the past so the report opens now instead of after {win?.latestTargetDate ? dmy(win.latestTargetDate) : "its target dates"}.</span></div><div className="doc-tool-actions mt-8"><button className="btn btn-primary btn-small" disabled={atr.busy} onClick={() => fastTrack("atr")}>⏩ Fast-track the Action Taken Report window</button></div></div>}
    </ToolCard>;

    const table = <div className="atr-table-wrap"><table className="atr-table">
      <thead><tr><th>Agenda No.</th><th>Action item (as per previous MoM)</th><th>Responsible</th><th>Target date</th><th>Status</th><th>Action taken / reasons for pending</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={row.sl ?? index}>
        <td className="atr-agenda">{row.agendaNo || "—"}</td>
        <td>{row.actionItem}</td>
        <td>{row.responsible || "—"}</td>
        <td className="atr-date">{row.targetDate ? dmy(row.targetDate) : "—"}</td>
        <td>{canEdit
          ? <select className="doc-tool-input" aria-label={`Status for row ${index + 1}`} value={row.status || ""} onChange={event => editAtrRow(index, "status", event.target.value)}>
              <option value="">Select…</option>
              {["Completed", "In Progress", "Pending"].map(choice => <option value={choice} key={choice}>{choice}</option>)}
            </select>
          : (row.status || "—")}</td>
        <td>{canEdit
          ? <textarea className="doc-tool-input atr-details" aria-label={`Action taken for row ${index + 1}`} value={row.details || ""} onChange={event => editAtrRow(index, "details", event.target.value)} placeholder="What was done, or why it is pending" />
          : (row.details || "—")}</td>
      </tr>)}</tbody>
    </table></div>;

    const actions = <>
      {canEdit && <div className="doc-tool-actions mt-16">
        <button className="btn btn-outline" disabled={atr.busy} onClick={() => saveAtr()}>Save draft</button>
        <button className="btn btn-primary" disabled={atr.busy} onClick={submitAtr}>Sign & submit to the Chairperson <span>→</span></button>
      </div>}
      {isChair && report.status === "submitted" && <>
        <label className="doc-tool-label mt-16" htmlFor="atr-comment">Note for the Member Secretary (required when returning)</label>
        <textarea id="atr-comment" className="doc-tool-input doc-comment" value={atr.comment} onChange={event => setAtr(current => ({ ...current, comment: event.target.value }))} placeholder="Example: agenda 3 action is still pending — add the reason." />
        <div className="doc-tool-actions mt-12">
          <button className="btn btn-outline" disabled={atr.busy} onClick={() => atrChairDecide("revision")}>Return for correction</button>
          <button className="btn btn-primary" disabled={atr.busy} onClick={() => atrChairDecide("approved")}>Sign the report</button>
        </div>
      </>}
      {report.status === "approved" && <div className="doc-tool-actions mt-16">
        <a className="btn btn-primary" href={`/api/atr/${encodeURIComponent(report.workspaceId)}/document`}>Download the signed report ↓</a>
      </div>}
    </>;

    return <><SectionHeading eyebrow="After the meeting" title="Action Taken Report" description="Report the action taken on every action item of the last meeting, before the next one."
      actions={atrWindowChip(win)} />
      <div className="grid grid-2 mb-16">{list}{timing}</div>
      <section className="panel panel-pad">
        <div className="panel-header"><div><h2>{report.committee} {report.meetingNo} · {report.department || report.school}</h2>
          <p>Minutes of {longDate(report.meetingDate)} · {report.academicYear} {report.semester} semester</p></div>
          <StatusPill status={report.status === "approved" ? "approved" : report.status === "submitted" ? "pending" : report.status === "returned" ? "rejected" : "draft"}>{report.status}</StatusPill></div>
        {report.status === "returned" && report.chairComment && <div className="notice warning"><span className="notice-icon">↺</span><span><b>Returned by the Chairperson.</b> {report.chairComment}</span></div>}
        {!canEdit && report.status !== "submitted" && report.status !== "approved" && <div className="notice info"><span className="notice-icon">i</span><span>{win?.label}. {win?.activationDate ? `It opens on ${dmy(win.activationDate)}.` : ""}</span></div>}
        {table}
        {atr.history?.length > 0 && atr.history[0].pending?.length > 0 && <div className="notice info mt-16"><span className="notice-icon">i</span><span>Carried forward from the previous report: {atr.history[0].pending.length} action(s) still in progress or pending.</span></div>}
        {actions}
      </section></>;
  }

  // ------------------------------------------------------------------ issued meeting calendar
  function calendarView() {
    const editable = role === "academic_office";
    const rows = calendar.draft.length ? calendar.draft : [];
    return <><SectionHeading eyebrow="Academic Office" title="Meeting calendar"
      description="The dates on which each committee meets, issued before the academic year begins. These dates set the Action Taken Report deadline and the start of its reminders." />
      {!editable && <div className="notice info"><span className="notice-icon">i</span><span>The Academic Office issues these dates. They drive the Action Taken Report deadline.</span></div>}
      {editable && <section className="panel panel-pad mb-16">
        <div className="panel-header"><div><h2>Issue the calendar for an academic year</h2>
          <p>DAC meets twice a semester (4 dates a year); BOS meets once a semester (2 dates a year).</p></div></div>
        <div className="doc-tool-actions">
          <label className="doc-tool-label">Academic year
            <input className="doc-tool-input" value={calendar.year} placeholder="2026-27"
              onChange={event => setCalendar(current => ({ ...current, year: event.target.value }))} />
          </label>
          <button className="btn btn-outline" onClick={() => startCalendar(calendar.year)}>Load the six meetings</button>
        </div>
        {rows.length > 0 && <>
          <table className="atr-table mt-16"><thead><tr><th>Committee</th><th>Semester</th><th>Meeting</th><th>From date</th><th>To date</th><th>Note</th></tr></thead>
            <tbody>{rows.map((entry, index) => <tr key={`${entry.committee}-${entry.meetingNo}`}>
              <td>{entry.committee}</td><td>{entry.semester}</td><td>{entry.meetingNo}</td>
              <td><input type="date" className="doc-tool-input" aria-label={`From date for ${entry.committee} ${entry.meetingNo}`} value={entry.fromDate || entry.date || ""}
                onChange={event => setCalendar(current => ({ ...current, draft: current.draft.map((item, position) => position === index ? { ...item, fromDate: event.target.value, date: event.target.value } : item) }))} /></td>
              <td><input type="date" className="doc-tool-input" aria-label={`To date for ${entry.committee} ${entry.meetingNo}`} value={entry.toDate || ""}
                onChange={event => setCalendar(current => ({ ...current, draft: current.draft.map((item, position) => position === index ? { ...item, toDate: event.target.value } : item) }))} /></td>
              <td><input className="doc-tool-input" value={entry.note || ""} placeholder="Optional"
                onChange={event => setCalendar(current => ({ ...current, draft: current.draft.map((item, position) => position === index ? { ...item, note: event.target.value } : item) }))} /></td>
            </tr>)}</tbody></table>
          <div className="doc-tool-actions mt-16"><button className="btn btn-primary" disabled={calendar.busy} onClick={saveCalendar}>Issue these dates</button></div>
        </>}
      </section>}
      <section className="panel panel-pad">
        <div className="panel-header"><div><h2>Issued dates</h2><p>What the Action Taken Report deadlines are calculated from.</p></div></div>
        {(calendar.entries || []).length ? <table className="atr-table"><thead><tr><th>Academic year</th><th>Committee</th><th>Semester</th><th>Meeting</th><th>From date</th><th>To date</th><th>Issued by</th></tr></thead>
          <tbody>{calendar.entries.map(entry => <tr key={entry.id}>
            <td>{entry.academicYear}</td><td>{entry.committee}</td><td>{entry.semester}</td>
            <td>{entry.meetingNo}</td><td>{dmy(entry.fromDate || entry.date)}</td><td>{entry.toDate ? dmy(entry.toDate) : "—"}</td><td>{entry.issuedBy}</td>
          </tr>)}</tbody></table>
        : <div className="empty-state"><h3>No dates issued yet</h3><p>Until the Academic Office issues them, a report opens after the latest target date but has no deadline.</p></div>}
      </section></>;
  }

  function statusBanner(current) {
    if (current.status === "pending") return <div className="notice warning"><span className="notice-icon">…</span><span>Your request is with the Academic Office. Agenda wording and invitees are read-only while review is pending.</span></div>;
    if (current.status === "revision") return <div className="notice warning"><span className="notice-icon">↺</span><span><b>Revision requested.</b> {current.officeComment || "Review the office comment, update the document and resubmit."}</span></div>;
    if (current.status === "rejected") return <div className="notice error"><span className="notice-icon">!</span><span><b>Request rejected.</b> {current.officeComment || "The office rejected the proposal."} You can revise and resubmit.</span></div>;
    if (current.status === "approved") return <div className="notice success"><span className="notice-icon">✓</span><span>Approved. Invitations have been queued to the proposed members. Significant changes require reapproval.</span></div>;
    return <div className="notice info"><span className="notice-icon">i</span><span>Choose common agenda items, add meeting-specific proposals, and submit the complete package for review.</span></div>;
  }

  function reviewView() {
    if (role !== "academic_office") return <><SectionHeading eyebrow="Academic Office" title="Approval queue" description="Only Academic Office may approve the agenda and invitee package." /><div className="empty-state"><h3>Academic Office access required</h3></div></>;
    const openQueueItem = async workspaceId => { await openWorkspace(workspaceId); setQueueMode(false); };
    if (queueMode) return <><SectionHeading eyebrow="Academic Office" title="Approval queue" description={`Every meeting request waiting for a decision, from every school — ${inbox.length} in queue. Open any one and approve, return or reject it; the queue is not first-come-first-served.`} actions={<button className="btn btn-outline" onClick={() => setView("library")}>Manage common agenda list</button>} />
      {!inbox.length && <div className="empty-state"><h3>No pending request</h3><p>Current request status: {statusText(state.status)}.</p><button className="btn btn-outline mt-16" onClick={() => setView("library")}>Manage common agenda list</button></div>}
      {!!inbox.length && <div className="chair-list mt-16">{inbox.map(item => <div className="chair-row minutes-row" key={item.workspaceId}>
        <div>
          <b>Meeting {item.meetingNo || "—"} · {item.department || item.school}</b>
          <small>{item.school} · {item.date ? longDate(item.date) : "date not set"} · Member Secretary {item.ownerName || "—"} · {item.ownerEmail || ""}</small>
        </div>
        <div className="doc-tool-actions">
          <StatusPill status="pending">Awaiting Academic Office approval</StatusPill>
          <button className="btn btn-primary btn-small" onClick={() => openQueueItem(item.workspaceId)}>Open request</button>
        </div>
      </div>)}</div>}
    </>;
    return <><SectionHeading eyebrow="Academic Office" title="Review meeting request" description="The pre-meeting preview shows proposed invitees and agenda wording only—not completed Discussion or Resolution." actions={<button className="btn btn-outline" onClick={() => setQueueMode(true)}>← Back to approval queue</button>} />{workflow}
      <div className="document-workspace review-workspace mt-16"><main className="document-canvas-column"><RequestDocument meeting={state.meeting} editable={false} signatures={requestSignatures} catalog={catalog} /></main><aside className="document-side-panel">
        <ToolCard title="Pending requests" tag={`${inbox.length} in queue`}><p>Open any request in the queue — approve in any order.</p>{inbox.map(item => <button className={`admin-queue-row ${item.workspaceId === state.workspaceId ? "selected" : ""}`} key={item.workspaceId} onClick={() => openQueueItem(item.workspaceId)}><b>{item.ownerName} · {item.department}</b><small>{item.ownerEmail} · {item.school} · {longDate(item.date)}</small></button>)}</ToolCard>
        <ToolCard title="Approval checklist" tag="Human review"><ul className="doc-checklist"><li>Reference number and meeting details</li><li>Previous MoM / ATR reference if selected</li><li>Agenda order, clarity and scope</li><li>Proposed invitees and Official Email</li></ul><div className="notice warning mt-10"><span className="notice-icon">!</span><span>Approval generates locked MoM blocks and a simulated invitation log.</span></div></ToolCard>
        <ToolCard title="Review decision" tag="Office"><p>Return with a specific revision note, reject with a reason, or approve the agenda and roster.</p><label className="doc-tool-label" htmlFor="office-comment">Comments for the Chairperson</label><textarea id="office-comment" className="doc-tool-input doc-comment" value={reviewComment} onChange={event => setReviewComment(event.target.value)} placeholder="Example: Please clarify agenda 3 and correct the proposed time." /><div className="doc-tool-actions vertical mt-12"><button className="btn btn-outline" onClick={returnForRevision}>Return for revision</button><button className="btn btn-danger" onClick={rejectRequest}>Reject request</button><button className="btn btn-primary" disabled={busy} onClick={approveRequest}>Approve agenda & members <span>→</span></button></div></ToolCard>
        <ToolCard title="Shared agenda bank" tag={`${agendaBank.length} items`}>{agendaBank.map(item => <div className="doc-bank-summary" key={item.id}><b>{item.title}</b><small>{item.note}</small></div>)}</ToolCard>
      </aside></div>
    </>;
  }

  function renderAiReport() {
    const report = state.aiReport;
    if (!report) return <div className="ai-empty"><span className="ai-empty-mark">✦</span><b>No verification run yet</b><p>Run the content check to see findings on Discussion ↔ Agenda and Resolution ↔ Discussion.</p></div>;
    const summary = report.summary || {};
    return <div className="ai-report">
      <div className="ai-engine"><span className={`ai-engine-dot ${report.mode === "ai-model" ? "online" : ""}`} /><div><b>{report.engine || "Offline review rules"}</b><small>{report.mode === "ai-model"
          ? (report.provider?.detail || "The configured model reviewed this text.")
          : (report.fallbackReason
              ? "The model was reached, but its reply could not be used, so the deterministic rules answered. Nothing was skipped."
              : (report.provider?.keyPresent
                  ? `The AI model could not be reached, so the deterministic rules answered${report.provider?.provider ? ` (${report.provider.provider})` : ""}. Nothing was skipped.`
                  : "Deterministic word-overlap checks run locally — no AI key is configured."))}
        {report.generatedAt ? ` · ${report.generatedAt}` : ""}</small></div></div>
      <p className="ai-report-notice">{report.notice || "This is not factual verification."}</p>
      {summary.items ? <div className="ai-summary"><span><b>{summary.items}</b> agendas</span><span className="ok"><b>{summary.aligned || 0}</b> aligned</span><span className="warn"><b>{summary.review || 0}</b> review</span><span className="bad"><b>{summary.needsRevision || 0}</b> needs revision</span></div> : null}
      {report.fallbackReason ? <div className="notice warning mt-8"><span className="notice-icon">!</span><span><b>Offline rules used instead.</b> {report.fallbackReason}</span></div> : null}
      {(report.notes || []).map((note, index) => <p className="ai-note" key={`note-${index}`}>{note}</p>)}
      {(report.items || []).map(item => <article className="ai-review-item" key={item.agendaNo}><div className="ai-review-head"><b>Agenda {item.agendaNo}: {item.agendaTitle}</b><StatusPill status={item.status} /></div>{(item.checks || []).map((check, index) => <div className="ai-check" key={`${item.agendaNo}-${index}`}><div><b>{check.name}{check.source ? <span className={`ai-source ${check.source === "ai-model" ? "model" : ""}`}>{check.source === "ai-model" ? "model" : "rules"}</span> : null}</b><p>{check.message}</p>{check.evidence && <blockquote>{check.evidence}</blockquote>}{check.findings?.length ? <ul className="ai-findings">{check.findings.map((finding, findingIndex) => <li key={`f-${findingIndex}`}>{finding}</li>)}</ul> : null}<div className="ai-suggestion"><b>Human review suggestion:</b> {check.suggestion}</div></div><StatusPill status={check.status} /></div>)}</article>)}
      <div className="notice warning mt-10"><span className="notice-icon">!</span><span>Verification reads typed Discussion and Resolution text only. It cannot confirm what was said in the meeting, it never edits the record, and annexures/photos are not analysed. Findings stay out of the exported documents.</span></div>
    </div>;
  }
  function renderAttendanceCard() {
    return <ToolCard title="Actual attendance" tag={`${presentCount} present`}><p>Only members marked present appear in the final table. No invitee is treated as an attendee by default.</p><div className="doc-attendance-list">{state.meeting.members.map(member => <label className="doc-attendance-row" key={member.id}><input type="checkbox" checked={!!member.present} disabled={!isUnlocked} onChange={event => toggleAttendance(member.id, event.target.checked)} /><span><b>{member.name}</b><small>{member.role} · {member.designation}</small></span></label>)}</div></ToolCard>;
  }
  function renderActionsCard() {
    const triage = state.resolutionTriage;
    const triageSummary = triage?.summary || {};
    return <ToolCard title="Action item entry" tag="Agenda-linked"><p>Select an approved agenda with a recorded resolution. The official table keeps its four template columns.</p>
      <div className="triage-panel">
        <div className="triage-head"><b>Resolution triage — Recommended · In process · Not recommended</b><span>Only In process and Not recommended resolutions are proposed for the Action Items table.</span></div>
        <button className="btn btn-outline btn-small" onClick={runResolutionTriage} disabled={!isUnlocked || busy}>{busy ? "Reading resolutions…" : "Classify resolutions with AI"}</button>
        {triage && <div className="triage-body">
          <div className="triage-summary">{`${triageSummary.inProcess || 0} in process · ${triageSummary.notApproved || 0} not recommended · ${triageSummary.approved || 0} recommended · ${triageSummary.proposedActionItems || 0} proposed action item(s)`}<small>{triage.mode === "ai-model" ? `AI model: ${triage.engine}`
            : (triage.provider && triage.provider.keyPresent
                ? `Offline rules — the AI model could not be reached just now (${triage.provider.provider}), so the deterministic wording cues answered`
                : "Offline rules (no AI key configured — deterministic wording cues)")}</small></div>
          {triage.items.map(row => <div className={`triage-row triage-${row.category}`} key={row.agendaId || row.agendaNo}>
            <div className="triage-row-head"><b>Agenda {pad2(row.agendaNo)} · {row.agendaTitle}</b><span className={`triage-chip triage-chip-${row.category}`}>{row.categoryLabel}</span></div>
            <div className="triage-short">{row.addToActionItems ? row.shortAction : (row.category === "approved" ? "No action item: the resolution is recommended." : "No action item: no resolution was recorded.")}</div>
            <small className="triage-why">{row.rationale}{row.evidence ? ` · “${row.evidence}”` : ""}</small>
            <div className="triage-actions">
              <button className="btn-text" onClick={() => useTriageText(row.agendaId)} disabled={!isUnlocked || !row.addToActionItems}>Use this text</button>
              <label className="triage-override">Reviewer override
                <select className="doc-tool-input" value={row.category} onChange={event => overrideCategory(row.agendaId, event.target.value)} disabled={!isUnlocked}>
                  {Object.entries(RESOLUTION_CATEGORIES).map(([value, text]) => <option value={value} key={value}>{text}</option>)}
                </select>
              </label>
            </div>
          </div>)}
          <div className="triage-note">{triage.notice}</div>
        </div>}
      </div><label className="doc-tool-label" htmlFor="action-agenda">Approved agenda</label><select id="action-agenda" className="doc-tool-input" value={actionDraft.agendaId || state.momItems[0]?.id || ""} disabled={!isUnlocked} onChange={event => setActionDraft(current => ({ ...current, agendaId: event.target.value }))}>{state.momItems.map((item, index) => <option value={item.id} key={item.id}>Agenda {pad2(index + 1)} · {item.title}</option>)}</select><div className="doc-linked-resolution">{selectedActionAgenda?.resolution || "No resolution has been recorded for this agenda yet."}</div><label className="doc-tool-label mt-8" htmlFor="action-text">Action(s) to be taken</label><input id="action-text" className="doc-tool-input" value={actionDraft.text} onChange={event => setActionDraft(current => ({ ...current, text: event.target.value }))} placeholder="Action arising from the resolution" disabled={!isUnlocked} /><div className="doc-tool-grid mt-8"><label>Person(s) responsible<input className="doc-tool-input" value={actionDraft.owner} onChange={event => setActionDraft(current => ({ ...current, owner: event.target.value }))} placeholder="Name / role" disabled={!isUnlocked} /></label><label>Target date<input className="doc-tool-input" type="date" value={actionDraft.targetDate} onChange={event => setActionDraft(current => ({ ...current, targetDate: event.target.value }))} disabled={!isUnlocked} /></label></div><button className="btn btn-outline btn-small mt-8" onClick={addActionItem} disabled={!isUnlocked}>Add action item</button>{state.actionItems.map(item => <div className="doc-tool-action-row" key={item.id}><div><b>Agenda {item.agendaNo} · {item.text}</b><small>{item.owner} · {item.targetDate ? dmy(item.targetDate) : "Target date not set"}</small><small>Linked resolution: {item.sourceResolution}</small>{item.category && <small>Category: {item.categoryLabel || categoryLabel(item.category)} · {item.shortAction ? "short action text" : "manual text"}</small>}</div><button className="btn-text" onClick={() => removeAction(item.id)} disabled={!isUnlocked}>Remove</button></div>)}</ToolCard>;
  }
  function renderAdditionalCard() {
    return <ToolCard title="Additional discussion" tag="Separate from approved agenda"><p>Add only a point actually discussed. It is separately labelled in the record and audit trail.</p><div className="doc-tool-grid"><input className="doc-tool-input" value={additionalTitle} onChange={event => setAdditionalTitle(event.target.value)} placeholder="Additional discussion point" disabled={!isUnlocked} /><button className="btn btn-outline btn-small" onClick={addAdditional} disabled={!isUnlocked}>Add point</button></div>{state.additionalDiscussions.map((item, index) => <div className="doc-tool-action-row" key={item.id}><div><b>Additional {pad2(index + 1)} · {item.title}</b><small>Not part of the approved agenda</small></div><button className="btn-text" onClick={() => removeAdditional(item.id)} disabled={!isUnlocked}>Remove</button></div>)}</ToolCard>;
  }
  function momView() {
    if (role !== "faculty") return <><SectionHeading eyebrow="After the meeting" title="MoM workspace" description="The authorized meeting team completes the minutes after the meeting." /><div className="empty-state"><h3>Faculty meeting workspace</h3><p>This account does not have the faculty permission required to complete these minutes.</p></div></>;
    if (state.status !== "approved") return <><SectionHeading eyebrow="After the meeting" title="MoM workspace" description="Agenda blocks are generated from the approved snapshot only." />{workflow}<div className="empty-state"><h3>Waiting for Academic Office approval</h3><p>No Discussion or Resolution blocks are created before approval.</p><button className="btn btn-outline mt-16" onClick={() => setView("request")}>Return to meeting request</button></div></>;
    const lockMessage = isUnlocked
      ? <div className="notice success"><span className="notice-icon">✓</span><span>Both gates are satisfied: the scheduled end time has passed AND the meeting is marked COMPLETED. MoM fields are editable.</span></div>
      : <div className="notice warning"><span className="notice-icon">◷</span><span>Discussion, Resolution and Ref. Document remain locked until BOTH conditions are true: scheduled end time has passed {endPassed ? "(satisfied)" : `(${dmy(state.meeting.date)} at ${state.meeting.endTime} Asia/Kolkata)`} AND meeting is marked COMPLETED {state.meeting.completed ? "(satisfied)" : "(not yet marked)"}.</span></div>;
    return <><SectionHeading eyebrow="After the meeting" title="Complete the minutes" description="Edit the official A4 document in place. Approved agenda wording remains read-only; this structured record also feeds the final PDF." actions={<button className="btn btn-outline" onClick={() => setView("request")}>View approved request</button>} />{workflow}
      <div className="document-workspace mom-document-workspace"><main className="document-canvas-column"><div className="doc-status-bar"><div><b>{meetingLabel}</b><span>{dmy(state.meeting.date)} · {state.meeting.startTime}–{state.meeting.endTime} · {state.meeting.venue}</span></div><StatusPill status={isUnlocked ? "complete" : "pending"}>{isUnlocked ? "Editable" : "Locked"}</StatusPill></div>{lockMessage}
        <FinalDocument meeting={state.meeting} momItems={state.momItems} signatures={momSignatures} additionalDiscussions={state.additionalDiscussions} photos={state.photos} actionItems={state.actionItems} isUnlocked={isUnlocked} onMomChange={updateMomItem} onToggleNoResolution={id => toggleNoResolution(state.momItems.find(item => item.id === id))} onUploadAgenda={uploadAgendaFiles} onRemoveFile={removeAgendaFile} onPhotoChange={updatePhoto} onUploadPhotos={uploadPhotos} onRemovePhoto={removePhoto} onAdditionalChange={updateAdditional} onRemoveAdditional={removeAdditional} onRemoveAction={removeAction} />
      </main><aside className="document-side-panel">
        <ToolCard title="Meeting completion gate" tag={state.meeting.completed ? "Completed" : "Not completed"}><p>The minutes unlock only after the scheduled end time has passed <i>and</i> the meeting is marked completed by its organizer.</p><div className="doc-tool-actions">{!state.meeting.completed ? <button className="btn btn-outline btn-small" onClick={markCompleted}>Mark meeting COMPLETED</button> : <span className="tag">Meeting marked COMPLETED {state.meetingCompletedAt && `· ${state.meetingCompletedAt}`}</span>}{!endPassed && <span className="muted small">Scheduled end has not passed yet.</span>}</div>
          {fastTrackEnabled && !isUnlocked && <div className="demo-fast-track mt-12"><div className="notice info"><span className="notice-icon">⏩</span><span><b>Demonstration fast-forward.</b> Moves this meeting&apos;s date into the past and marks it completed, so the minutes unlock now instead of on {dmy(state.meeting.date)}. Only this meeting is touched, and the control is absent from a production deployment.</span></div><div className="doc-tool-actions mt-8"><button className="btn btn-primary btn-small" disabled={busy} onClick={() => fastTrack("meeting")}>⏩ Fast-track the clock to unlock the minutes</button></div></div>}</ToolCard>
        {renderAttendanceCard()}{renderActionsCard()}{renderAdditionalCard()}
        <ToolCard title="AI content verification" tag="Agenda → Discussion → Resolution" className="ai-context-panel"><p>Checks the recorded Discussion against the approved Agenda, and the Resolution against the Discussion. A hosted model runs when an API key is configured; otherwise the offline rules run. It never edits the record or inspects annexures/photos.</p><div className="doc-tool-actions"><button className="btn btn-outline btn-small" onClick={runTextCheck} disabled={!isUnlocked}>Run AI content verification</button><button className="btn btn-outline btn-small" onClick={checkAiConnection} disabled={busy}>Test AI connection</button></div>
        {state.aiCheck && <div className={`ai-probe ${state.aiCheck.ok ? "ok" : "off"}`}><b>{state.aiCheck.ok ? "Model connected" : "Offline rules active"}</b><span>{state.aiCheck.message}</span>{state.aiCheck.hint && <small>{state.aiCheck.hint}</small>}<small>{`Provider: ${state.aiCheck.provider?.provider || "offline"}${state.aiCheck.model || state.aiCheck.provider?.model ? ` · Model: ${state.aiCheck.model || state.aiCheck.provider?.model}` : ""}${state.aiCheck.latencyMs ? ` · ${state.aiCheck.latencyMs} ms` : ""}`}</small></div>}<div className="ai-annotation-note">Human review required · no silent edits · findings are excluded from the exported documents.</div>{renderAiReport()}</ToolCard>
        {(() => {
          const review = gate.momReview || { status: "draft", label: "Not submitted", history: [] };
          const download = gate.downloadGate || { allowed: false, reason: "Submit the minutes for review to unlock the download." };
          const reportGate = gate.externalReport || {};
          const isChair = role === "faculty" && String(state.meeting.chairEmail || "").toLowerCase() === String(user.email || "").toLowerCase();
          return <ToolCard title="Minutes approval chain" tag={review.label || REVIEW_LABELS[review.status] || review.status}>
            <p>The filled minutes go to the <b>Chairperson</b> first and then to the <b>Academic Office</b>. The office cannot approve until the External Member has submitted the observation report.</p>
            <div className="review-steps">
              <div className={`review-step ${["pending_chairperson","pending_office","approved"].includes(review.status) ? "done" : ""}`}><b>1 · Chairperson</b><small>{review.chairName || state.meeting.chairName || "Not selected"}{review.chairDecisionAt ? ` · ${review.chairDecisionAt}` : ""}</small></div>
              <div className={`review-step ${["pending_office","approved"].includes(review.status) ? "done" : ""}`}><b>2 · External Member report</b><small>{reportGate.submitted ? "Submitted to the Academic Office" : (reportGate.message || "Awaited")}</small></div>
              <div className={`review-step ${review.status === "approved" ? "done" : ""}`}><b>3 · Academic Office</b><small>{review.officeDecisionAt || "Final approval"}</small></div>
            </div>
            {review.chairComment ? <div className="notice warning mt-8"><span className="notice-icon">↺</span><span><b>Chairperson:</b> {review.chairComment}</span></div> : null}
            {review.officeComment ? <div className="notice warning mt-8"><span className="notice-icon">↺</span><span><b>Academic Office:</b> {review.officeComment}</span></div> : null}
            <textarea className="doc-tool-input doc-comment mt-8" value={reviewComment} onChange={event => setReviewComment(event.target.value)} placeholder="Comment / clarification for this decision" aria-label="Review comment" />
            <div className="doc-tool-actions vertical mt-12">
              {role === "faculty" && ["draft", "chair_revision", "office_revision"].includes(review.status) && (() => {
              const aiReport = state.aiReport;
              const summary = aiReport?.summary || {};
              const isAiVerified = aiReport && summary.items > 0 && (summary.needsRevision || 0) === 0 && (summary.review || 0) === 0 && (summary.aligned || 0) === summary.items && (aiReport.items || []).every(i => i.status === "aligned");
              const aiGateMessage = !aiReport
                ? "Run AI content verification above — Agenda → Discussion → Resolution must all be relevant before the minutes can be submitted."
                : !isAiVerified
                ? `AI verification found issues: ${summary.review || 0} need review, ${summary.needsRevision || 0} need revision. Revise Discussion/Resolution to match the agenda and re-run verification until every agenda is aligned.`
                : "";
              return (<><button className="btn btn-primary" disabled={busy || !isAiVerified} onClick={() => momReviewAction("/api/workspace/mom/submit")}>{isAiVerified ? "Submit minutes for approval →" : "Submit blocked — run AI verification"}</button>
                {!isAiVerified && <div className="notice warning mt-8"><span className="notice-icon">◷</span><span><b>AI gate:</b> {aiGateMessage}</span></div>}
                {isAiVerified && <div className="notice success mt-8"><span className="notice-icon">✓</span><span>All agendas aligned — submission is open.</span></div>}</>);
            })()}
              {isChair && review.status === "pending_chairperson" && <><button className="btn btn-primary" disabled={busy} onClick={() => momReviewAction("/api/workspace/mom/chair-decision", { decision: "approved" })}>Chairperson: approve minutes</button><button className="btn btn-outline" disabled={busy} onClick={() => momReviewAction("/api/workspace/mom/chair-decision", { decision: "revision", comment: reviewComment })}>Return to Member Secretary</button></>}
              {role === "academic_office" && review.status === "pending_office" && <><button className="btn btn-primary" disabled={busy || !reportGate.submitted} onClick={() => momReviewAction("/api/workspace/mom/office-decision", { decision: "approved" })}>Academic Office: approve minutes</button><button className="btn btn-outline" disabled={busy} onClick={() => momReviewAction("/api/workspace/mom/office-decision", { decision: "revision", comment: reviewComment })}>Return for clarification</button></>}
            </div>
            <div className={`notice ${download.allowed ? "success" : "warning"} mt-10`}><span className="notice-icon">{download.allowed ? "✓" : "◷"}</span><span>{download.reason}</span></div>
            {review.history?.length ? <div className="review-history">{review.history.slice(-6).map((row, index) => <div key={`${row.at}-${index}`}><b>{row.role}</b> · {row.action} · {row.at}{row.comment ? ` — ${row.comment}` : ""}</div>)}</div> : null}
          </ToolCard>;
        })()}
        <ToolCard title="Final document" tag="PDF + editable Word"><p>Print and PDF download use the consolidated renderer: MoM pages, photos, Annexure Index and agenda-linked attachments. The Word export carries the same content as an editable .docx.</p><div className="doc-tool-actions vertical"><button className="btn btn-outline" onClick={() => exportPdf(true)} disabled={!gate.downloadGate?.allowed || busy}>Print</button><button className="btn btn-primary" onClick={() => exportPdf(false)} disabled={!gate.downloadGate?.allowed || busy}>{busy ? "Preparing PDF…" : "Download consolidated PDF ↓"}</button><button className="btn btn-outline" onClick={exportDocx} disabled={!gate.downloadGate?.allowed || busy}>{busy ? "Preparing document…" : "Download editable Word (.docx) ↓"}</button></div><div className={`notice ${isUnlocked ? "success" : "warning"} mt-10`}><span className="notice-icon">{isUnlocked ? "✓" : "◷"}</span><span>{isUnlocked ? "Exports use Cambria 11 pt text, 12 pt sub-headings and 1.15 line spacing. Annexures are bundled in the PDF; the Word file lists them by reference." : "Exports remain locked until both meeting gates are satisfied."}</span></div></ToolCard>
      </aside></div>
    </>;
  }

  function overviewView() {
    if (role === "system_admin") return <><SectionHeading eyebrow="System administration" title="Manage who can enter the DAC workspace." description="Add professor accounts, assign application permissions and scope faculty to their school and department." actions={<button className="btn btn-primary" onClick={() => setView("directory")}>Open access directory →</button>} /><div className="grid grid-2"><section className="panel panel-pad"><div className="panel-header"><div><h2>Allow-list is the front door</h2><p>Every login code request is checked against the active SQLite directory.</p></div><StatusPill status="approved">Enabled</StatusPill></div><p className="muted">No account-wide Chairperson exists. The faculty member who creates a meeting request is set as the organizer for that meeting only.</p></section><section className="panel panel-pad"><div className="panel-header"><div><h2>Sign-in</h2><p>Email one-time code against this allow-list; no password is ever collected or stored.</p></div><span className="tag tag-new">Email OTP</span></div><p className="muted">Connect the college’s Microsoft 365 tenant for mail delivery and, if required, federate sign-in with Entra ID.</p></section></div></>;
    const actions = role === "faculty" ? <button className="btn btn-primary" onClick={() => setView(state.status === "approved" ? "mom" : "request")}>{state.status === "approved" ? "Open MoM workspace" : "Continue meeting request"} →</button> : role === "academic_office" ? <button className="btn btn-primary" onClick={() => setView("review")}>Open approval queue →</button> : <button className="btn btn-primary" onClick={() => setView("member")}>View approved meeting →</button>;
    return <><SectionHeading eyebrow="DAC · meeting lifecycle" title="Minutes, with a clear chain of accountability." description="Prepare the request, secure Academic Office approval, then complete the MoM only after the meeting." actions={actions} />{workflow}
      <div className="stat-grid"><div className="stat-card"><span className="stat-label">Request state</span><strong style={{ fontSize: 17 }}>{statusText(state.status)}</strong><small>Academic Office is the final approver</small></div><div className="stat-card"><span className="stat-label">Agenda items</span><strong>{state.meeting.agendas.length}</strong><small>Common + meeting-specific</small></div><div className="stat-card"><span className="stat-label">Proposed invitees</span><strong>{state.meeting.members.length}</strong><small>Attendance not assumed</small></div><div className="stat-card"><span className="stat-label">MoM sections</span><strong>{state.momItems.length}</strong><small>{state.status === "approved" ? "Generated at approval" : "Generated only after approval"}</small></div></div>
      {role === "faculty" && chairInbox.length > 0 && <section className="panel panel-pad mt-16">
        <div className="panel-header"><div><h2>Requests waiting for your signature</h2><p>You are the nominated Chairperson. Approving signs the request form and forwards it to the Academic Office.</p></div><StatusPill status="pending">{chairInbox.length} waiting</StatusPill></div>
        <div className="chair-list">{chairInbox.map(row => <div className="chair-row" key={row.workspaceId}>
          <div><b>{row.department}</b><small>{longDate(row.date)} · {row.agendaCount} agenda items · {row.memberCount} members · submitted by {row.proposedBy} {row.submittedAt && `on ${row.submittedAt}`}</small></div>
          <div className="doc-tool-actions">
            <button className="btn btn-outline btn-small" disabled={busy} onClick={() => openChairRequest(row.workspaceId)}>Review request</button>
            <button className="btn btn-primary btn-small" disabled={busy} onClick={() => chairDecide(row.workspaceId, "approved")}>Sign &amp; approve</button>
            <button className="btn btn-outline btn-small" disabled={busy} onClick={() => chairDecide(row.workspaceId, "revision")}>Return for revision</button>
          </div>
        </div>)}</div>
      </section>}
      <div className="grid grid-2 mt-16"><section className="panel panel-pad"><div className="panel-header"><div><h2>Your next step</h2><p>Approved agenda wording is the reference for the final minutes.</p></div><StatusPill status={state.status} /></div><div className="meeting-card"><div className="card-label">Current request</div><h3>{meetingLabel}</h3><p>{state.meeting.school} · Academic year {state.meeting.academicYear} · {state.meeting.semester} semester</p><div className="meeting-card-grid"><div><span>Date</span><b>{longDate(state.meeting.date)}</b></div><div><span>Time</span><b>{state.meeting.startTime}–{state.meeting.endTime}</b></div><div><span>Venue</span><b>{state.meeting.venue}</b></div><div><span>Mode</span><b>{state.meeting.mode}</b></div></div></div></section>
        <section className="panel panel-pad"><div className="panel-header"><div><h2>{role === "academic_office" ? "Office review" : role === "external_member" ? "Guest access" : "Meeting at a glance"}</h2><p>Current meeting checkpoint</p></div></div>{role === "academic_office" ? <div className="timeline"><div className={`timeline-row ${state.status === "pending" ? "" : "pending"}`}><span className="timeline-dot" /><div><b>{state.status === "pending" ? "Request is waiting" : `Request status: ${statusText(state.status)}`}</b><small>Review agenda, members and meeting details.</small></div></div><div className="timeline-row"><span className="timeline-dot" /><div><b>Invitation follows approval</b><small>Invitations are queued as soon as the office approves.</small></div></div></div> : <div className="kv-list"><div className="kv"><span>Meeting</span><b>{ordinal(state.meeting.meetingNo)}</b></div><div className="kv"><span>School</span><b>{state.meeting.school}</b></div><div className="kv"><span>Department</span><b>{state.meeting.department}</b></div><div className="kv"><span>Scheduled</span><b>{longDate(state.meeting.date)} · {state.meeting.startTime}</b></div></div>}</section>
      </div>
      <section className="panel panel-pad mt-16"><div className="panel-header"><div><h2>How the workflow runs</h2><p>The meeting organizer is the faculty member who schedules this particular meeting; there is no global Chairperson account.</p></div></div><div className="grid grid-3"><div className="security-card"><div className="security-icon">1</div><h3>Submit the proposal</h3><p>Select common agenda items, add meeting-specific topics and proposed invitees.</p></div><div className="security-card"><div className="security-icon">2</div><h3>Review and approve</h3><p>The Academic Office may approve, return or reject; invitations follow approval.</p></div><div className="security-card"><div className="security-icon">3</div><h3>Complete the MoM</h3><p>Blocks appear at approval and stay locked until end time passed AND COMPLETED.</p></div></div></section>
    </>;
  }

  function outboxView() {
    return <><SectionHeading eyebrow="Notifications" title="Invitation log" description="Every invitation, approval and reminder the system queued for this meeting." actions={<span className="tag tag-new">Queued mail</span>} />{state.outbox.length ? [...state.outbox].reverse().map(mail => <article className="outbox-card" key={mail.id || mail.createdAt}><header><div><h3>{mail.subject || "DAC meeting invitation"}</h3><p>From {mail.from || "Organizer"} · {mail.createdAt || "—"}</p></div><span className="status-pill status-review">{(mail.status || "queued").toUpperCase()}</span></header><p><b>Recipients:</b> {(mail.recipients || []).join(", ")}</p><p><b>Meeting:</b> {mail.meeting?.meetingNo} · {mail.meeting?.department} · {longDate(mail.meeting?.date)}</p><pre>{`Agenda: ${(mail.meeting?.agendas || []).map(item => item.title).join("; ")}\nTime: ${mail.meeting?.startTime}–${mail.meeting?.endTime}\nVenue: ${mail.meeting?.venue}`}</pre></article>) : <div className="empty-state"><h3>No invitations recorded</h3><p>Approving the request emails the invitation to the nominated members.</p></div>}<div className="notice warning mt-16"><span className="notice-icon">!</span><span>Production mail should use scoped delegated Microsoft Graph permission, never stored mailbox passwords.</span></div></>;
  }
  function signatureCard() {
    return <ToolCard title="Digital signature" tag={signature ? `v${signature.version}` : "Required"}>
      <p>Your signature is embedded in the PDF forms you sign. Its checksum and version are stored, so any signed document can be traced back to the exact image used.</p>
      <div className="signature-inline">{signature ? <img src={signature.url} alt="Your signature" /> : <small className="muted">No signature recorded yet.</small>}
        <small>{signature ? `${signature.methodLabel} · recorded ${signature.createdAt?.slice(0, 10)} · ${signature.width}×${signature.height} px` : "Workflow actions stay locked until you record one."}</small></div>
      <div className="doc-tool-actions"><button className="btn btn-outline" onClick={() => setSignatureOpen(true)}>{signature ? "Replace signature" : "Add signature"}</button></div>
    </ToolCard>;
  }

  function securityView() {
    return <><SectionHeading eyebrow="Security baseline" title="Private data needs layered protection." description="The access directory, one-time-code sessions, CSRF checks and API role gates are enforced on every request. College SSO can be layered on top." /><div className="security-grid mt-16">{signatureCard()}<SecurityCard icon="◎" title="College Microsoft sign-in + MFA" text="Sign-in is an emailed one-time code against the active directory; a single-tenant Entra sign-in with MFA can replace it." tag="One-time code" /><SecurityCard icon="↗" title="Least-privilege Outlook sending" text="Mail is queued by the mail transport (file outbox, SMTP, or Microsoft Graph send-as once connected)." tag="Queued" /><SecurityCard icon="⇄" title="TLS in transit" text="Use HTTPS/TLS for every request, upload and download in production." tag="Deployment configuration" /><SecurityCard icon="▣" title="Private document storage" text="Uploads are stored on the application server. For production, mount encrypted private storage and add malware scanning and retention rules." tag="Server storage" /><SecurityCard icon="⌑" title="Meeting-scoped authorization" text="Role changes are enforced by the API, including meeting-scoped access to files and minutes." tag="Enforced" /><SecurityCard icon="◷" title="External guest access" text="Guests should see only explicitly shared meetings and files, read-only by default, auditable and revocable." tag="Audited" /></div><section className="panel panel-pad mt-16"><div className="panel-header"><div><h2>Activity log</h2><p>Workflow events only; avoid putting sensitive content in audit comments.</p></div><span className="tag">{state.audit.length} events</span></div>{state.audit.length ? <div className="timeline">{state.audit.slice(0, 15).map((row, index) => <div className="timeline-row" key={`${row.at}-${index}`}><span className="timeline-dot" /><div><b>{row.event}</b><small>{row.at} · {row.role} {row.details?.note && `· ${row.details.note}`}</small></div></div>)}</div> : <p className="muted">No workflow events yet.</p>}</section></>;
  }
  function memberView() {
    const isOffice = role === "academic_office";
    const meetings = report.inbox || [];
    const draft = report.draft;
    const frozen = ["submitted", "approved"].includes(report.status);
    const statusLabel = { not_started: "Not started", draft: "Draft saved", submitted: "Submitted to the Academic Office", approved: "Approved", returned: "Returned for revision" }[report.status] || report.status;
    if (!meetings.length) return <><SectionHeading eyebrow="External Member" title="Observation report" description="Nomination appears here once the Member Secretary lists you as the External Member of a DAC meeting." /><div className="empty-state"><h3>No meeting is assigned to this account</h3><p>{isOffice ? "Approved meetings with a nominated External Member will appear here." : "You will be notified in the app when a meeting is scheduled with you as the External Member."}</p></div></>;
    const queue = [...meetings].sort((a, b) => (a.reportStatus === "submitted" ? 0 : 1) - (b.reportStatus === "submitted" ? 0 : 1));
    return <><SectionHeading eyebrow={isOffice ? "Academic Office" : "External Member · observation report"} title={isOffice ? "External Member observation reports" : "Observation report to the Academic Office"} description={isOffice ? "Every observation report on record, submitted ones first. Open any report and approve or return it — the queue is not first-come-first-served." : "The agenda items below are taken from the DAC meeting itself. Mark Yes or No for every item and add remarks where they are needed; the report goes to the Academic Office for approval."} />
      {isOffice && <div className="chair-list mt-16">{queue.map(row => <div className="chair-row minutes-row" key={row.workspaceId}>
        <div>
          <b>Meeting {row.meetingNo || "—"} · {row.department}</b>
          <small>{row.school} · {row.date ? longDate(row.date) : "date not set"} · {row.completed ? "meeting completed" : "meeting pending"}</small>
        </div>
        <div className="doc-tool-actions">
          <StatusPill status={row.reportStatus === "submitted" ? "pending" : row.reportStatus === "approved" ? "approved" : "draft"}>{(row.reportStatus || "not started").replace(/_/g, " ")}</StatusPill>
          <button className={`btn btn-small ${row.reportStatus === "submitted" ? "btn-primary" : "btn-outline"}`} onClick={() => loadReport(row.workspaceId)}>Open report</button>
          {row.reportId && ["submitted", "approved"].includes(row.reportStatus) && <a className="btn btn-outline btn-small" href={`/api/external-report/${row.reportId}/pdf`}>PDF ↓</a>}
        </div>
      </div>)}</div>}
      <div className="document-workspace mt-16"><main className="document-canvas-column">
        <section className="panel panel-pad">
          <div className="panel-header"><div><h2>{meetings.find(row => row.workspaceId === report.workspaceId)?.department || "Meeting"}</h2><p>Academic Year · Semester · Meeting details</p></div><StatusPill status={report.status === "approved" ? "approved" : report.status === "submitted" ? "review" : "pending"}>{statusLabel}</StatusPill></div>
          {draft ? <>
            <div className="report-meta"><div><span>School</span><b>{draft.meeting.school}</b></div><div><span>Department</span><b>{draft.meeting.department}</b></div><div><span>Date</span><b>{longDate(draft.meeting.date)} · {draft.meeting.startTime}</b></div><div><span>Venue</span><b>{draft.meeting.venue}</b></div><div><span>Nominated member</span><b>{draft.member.name} · {draft.member.school}</b></div></div>
            <table className="report-table"><thead><tr><th>Agenda No.</th><th>Agenda Item</th><th>Response</th><th>Remarks (if any)</th></tr></thead><tbody>
              {(draft.agenda || []).map((row, index) => <tr key={row.agendaNo}>
                <td className="doc-center">{pad2(row.agendaNo)}</td>
                <td>{row.agendaItem}</td>
                <td className="report-response">{["yes", "no"].map(answer => <label key={answer}><input type="radio" name={`resp-${index}`} checked={row.response === answer} disabled={!report.canFill} onChange={() => updateReportRow(index, "response", answer)} /> {answer === "yes" ? "Yes" : "No"}</label>)}</td>
                <td><textarea className="report-remark" value={row.remarks} disabled={!report.canFill} onChange={event => updateReportRow(index, "remarks", event.target.value)} placeholder="Add a remark (required when the answer is No)" /></td>
              </tr>)}
            </tbody></table>
            <h3 className="report-subhead">D. Major observations on non-compliance (if any)</h3>
            <p className="muted">Including members&apos; attendance and timely commencement of the meeting.</p>
            {(draft.observations || []).map((row, index) => <div className="report-observation" key={`obs-${index}`}><b>{index + 1}. {row.observation}</b><textarea className="report-remark" value={row.remarks} disabled={!report.canFill} onChange={event => updateReportObservation(index, "remarks", event.target.value)} placeholder="Remarks (if any)" /></div>)}
            <textarea className="doc-tool-input mt-12" value={draft.declaration || ""} disabled={!report.canFill} onChange={event => setReport(current => ({ ...current, draft: { ...current.draft, declaration: event.target.value } }))} placeholder="Declaration by the nominated member (optional)" />
            {report.canFill && <div className="doc-tool-actions mt-12"><button className="btn btn-outline" disabled={busy} onClick={() => saveReport(false)}>Save draft</button><button className="btn btn-primary" disabled={busy} onClick={() => saveReport(true)}>Submit to the Academic Office →</button></div>}
            {isOffice && report.status === "submitted" && <div className="doc-tool-actions mt-12"><button className="btn btn-primary" disabled={busy} onClick={() => decideReport(meetings.find(row => row.workspaceId === report.workspaceId)?.reportId, "approved")}>Approve report &amp; archive</button><button className="btn btn-outline" disabled={busy} onClick={() => decideReport(meetings.find(row => row.workspaceId === report.workspaceId)?.reportId, "returned")}>Return for revision</button>{report.id && <a className="btn btn-outline" href={`/api/external-report/${report.id}/pdf`}>Download report PDF ↓</a>}</div>}
            {report.comment && <div className="notice warning mt-10"><span className="notice-icon">↺</span><span><b>Academic Office:</b> {report.comment}</span></div>}
          </> : <div className="empty-state"><h3>Select a meeting</h3></div>}
        </section>
      </main><aside className="document-side-panel">
        <ToolCard title="Meetings nominated to you" tag={`${meetings.length}`}>{meetings.map(row => <button className={`workspace-pick-row ${row.workspaceId === report.workspaceId ? "selected" : ""}`} key={row.workspaceId} onClick={() => loadReport(row.workspaceId)}><b>{row.department}</b><small>{longDate(row.date)} · {row.completed ? "meeting completed" : "meeting pending"} · {row.reportStatus.replace("_", " ")}</small></button>)}</ToolCard>
        <ToolCard title="How this report is used" tag="Separate document"><p>The observation report never edits the minutes. Once approved it is archived in the central document vault under this school and can be downloaded by the Academic Office.</p></ToolCard>
      </aside></div>
    </>;
  }

  function loadVault(patch = {}) {
    const next = { ...vault, ...patch };
    setVault(next);
    const params = new URLSearchParams();
    ["committee", "school", "department", "docType"].forEach(key => {
      if (next[key]) params.set(key, next[key]);
    });
    apiFetch(`/api/documents${params.toString() ? `?${params}` : ""}`)
      .then(response => response.ok ? response.json() : { summary: null, documents: [] })
      .then(data => setVault(current => ({ ...current, summary: data.summary || current.summary,
                                          documents: data.documents || [] })))
      .catch(() => {});
  }

  function vaultView() {
    if (!["academic_office", "system_admin"].includes(role)) return <><SectionHeading eyebrow="Document vault" title="Central document repository" description="Approved forms and minutes are archived here, grouped by school." /><div className="empty-state"><h3>Academic Office access required</h3></div></>;
    const summary = vault.summary || { schools: [], total: 0 };
    const documents = vault.documents || [];
    const departmentOptions = [...new Set(documents.map(document => document.department).filter(Boolean))].sort();
    return <><SectionHeading eyebrow="Document vault" title="Approved documents, grouped by school" description="Every approved Minutes of Meeting and External Member report is archived with a checksum, a version and the actor who approved it." actions={<span className="tag">{summary.total || 0} archived</span>} />
      <div className="stat-grid">{(summary.schools || []).slice(0, 4).map(entry => <div className="stat-card" key={entry.school}><span className="stat-label">{entry.school}</span><strong>{entry.total}</strong><small>{Object.entries(entry.types || {}).map(([type, count]) => `${VAULT_TYPES[type] || type}: ${count}`).join(" · ")}</small></div>)}</div>
      <section className="panel panel-pad mt-16"><div className="panel-header"><div><h2>Filter the vault</h2>
        <p>The office can narrow the shelf to one committee, one school, one department or one kind of form.</p></div>
        <button className="btn btn-outline btn-small" onClick={() => loadVault({ committee: "", school: "", department: "", docType: "" })}>Clear</button></div>
        <div className="archive-selects">
          <label className="doc-tool-label">Committee
            <select className="doc-tool-input" aria-label="Filter the vault by committee" value={vault.committee}
              onChange={event => loadVault({ committee: event.target.value, department: "" })}>
              <option value="">DAC and BOS</option>
              <option value="DAC">DAC — Departmental Academic Committee</option>
              <option value="BOS">BOS — Board of Studies</option>
            </select>
          </label>
          <label className="doc-tool-label">School
            <select className="doc-tool-input" aria-label="Filter the vault by school" value={vault.school}
              onChange={event => loadVault({ school: event.target.value, department: "" })}>
              <option value="">All schools</option>
              {(summary.schools || []).map(entry => <option value={entry.school} key={entry.school}>{entry.school}</option>)}
            </select>
          </label>
          <label className="doc-tool-label">Department / branch
            <select className="doc-tool-input" aria-label="Filter the vault by department" value={vault.department}
              onChange={event => loadVault({ department: event.target.value })}>
              <option value="">All departments</option>
              {departmentOptions.map(name => <option value={name} key={name}>{name}</option>)}
            </select>
          </label>
          <label className="doc-tool-label">Form
            <select className="doc-tool-input" aria-label="Filter the vault by form" value={vault.docType}
              onChange={event => loadVault({ docType: event.target.value })}>
              <option value="">Every form</option>
              <option value="request">Signed request forms</option>
              <option value="mom">Approved minutes</option>
              <option value="external_report">External observation reports</option>
              <option value="atr">Action Taken Reports</option>
            </select>
          </label>
        </div>
      </section>
      {documents.length ? <section className="panel panel-pad mt-16"><table className="report-table"><thead><tr><th>Committee</th><th>School</th><th>Department</th><th>Document</th><th>Year</th><th>Approved</th><th></th></tr></thead><tbody>{documents.map(document => <tr key={document.id}><td><b>{document.committee || "DAC"}</b></td><td>{document.school}</td><td>{document.department}</td><td><b>{document.docTypeLabel}</b><br /><small>{document.title}</small></td><td>{document.academicYear} · {document.semester}</td><td>{document.createdAt?.slice(0, 10)}<br /><small>v{document.version} · {document.createdBy}</small></td><td><a className="btn btn-outline btn-small" href={`/api/documents/${document.id}/download`}>Download ↓</a></td></tr>)}</tbody></table></section>
        : <div className="empty-state mt-16"><h3>No archived documents yet</h3><p>Approve minutes in the Academic Office queue (after the External Member reports) and the document lands here automatically.</p></div>}
    </>;
  }

  // The completed form, for the two people who sign it after the meeting.
  function minutesReviewView() {
    if (!["faculty", "academic_office"].includes(role)) {
      return <><SectionHeading eyebrow="Minutes review" title="Minutes waiting for a signature" />
        <div className="empty-state"><h3>Chairperson or Academic Office access required</h3></div></>;
    }
    const office = role === "academic_office";
    const waiting = minutesInbox || [];
    if (minutesReview) {
      const sheet = minutesReview.state || {};
      return <>
        <SectionHeading eyebrow={office ? "Academic Office · completed form" : "Chairperson · minutes"}
          title={`${committeeCode(sheet.meeting)} minutes — ${sheet.meeting?.department || ""}`}
          description="The completed form exactly as it will be archived, with the signatures already given."
          actions={<button className="btn btn-outline" onClick={() => setMinutesReview(null)}>← Back to the list</button>} />
        <div className="minutes-review-meta">
          <div><span>Meeting</span><b>{committeeCode(sheet.meeting)}-{sheet.meeting?.meetingNo} · {longDate(sheet.meeting?.date)}</b></div>
          <div><span>Chairperson</span><b>{sheet.meeting?.chairName || "—"}</b></div>
          <div><span>Member Secretary</span><b>{sheet.meeting?.secretaryName || "—"}</b></div>
          <div><span>Stage</span><b>{minutesReview.momReview?.label || "—"}</b></div>
        </div>
        <div className="document-workspace mt-16">
          <main className="document-canvas-column">
            <FinalDocument meeting={sheet.meeting} momItems={sheet.momItems || []}
              additionalDiscussions={sheet.additionalDiscussions || []} photos={sheet.photos || []}
              actionItems={sheet.actionItems || []} signatures={minutesReview.signatures} isUnlocked={false}
              onMomChange={() => {}} onToggleNoResolution={() => {}} onUploadAgenda={() => {}}
              onRemoveFile={() => {}} onPhotoChange={() => {}} onUploadPhotos={() => {}}
              onRemovePhoto={() => {}} onAdditionalChange={() => {}} onRemoveAdditional={() => {}}
              onRemoveAction={() => {}} />
          </main>
          <aside className="document-side-panel">
            <ToolCard title="Your decision" tag={office ? "Academic Office" : "Chairperson"}>
              <p>{office
                ? "Approving archives the signed minutes in the document vault and opens the download for the Member Secretary."
                : "Signing approves the minutes and sends them to the Academic Office. If anything is wrong, return them with a note. If the office later asks for a correction, the corrected minutes come back to you for review and signature before the office sees them again."}</p>
              <textarea className="doc-tool-input doc-comment" value={minutesReview.comment}
                onChange={event => setMinutesReview(current => ({ ...current, comment: event.target.value }))}
                placeholder="Note for the Member Secretary (required when returning)" aria-label="Minutes review comment" />
              <div className="doc-tool-actions vertical mt-12">
                <button className="btn btn-primary" disabled={busy} onClick={() => decideMinutes("approved")}>
                  {office ? "Approve & archive minutes" : "Sign & approve minutes"}
                </button>
                <button className="btn btn-outline" disabled={busy} onClick={() => decideMinutes("revision")}>
                  Return for correction
                </button>
              </div>
              <div className="notice info mt-10"><span className="notice-icon">i</span><span>
                The signatures above are the record: the Member Secretary's, the Chairperson's and — once the
                office approves — the Academic Office's.
              </span></div>
            </ToolCard>
            <ToolCard title="Approval trail" tag={`${(minutesReview.momReview?.history || []).length} events`}>
              {(minutesReview.momReview?.history || []).slice(-8).map((row, index) =>
                <div className="review-history-row" key={`${row.at}-${index}`}>
                  <b>{row.role}</b> · {row.action} · {row.at}{row.comment ? ` — ${row.comment}` : ""}</div>)}
              {!(minutesReview.momReview?.history || []).length && <p className="muted">No events yet.</p>}
            </ToolCard>
          </aside>
        </div>
      </>;
    }
    return <>
      <SectionHeading eyebrow={office ? "Academic Office" : "Chairperson"}
        title={office ? "Completed forms waiting for your approval" : "Minutes waiting for your signature"}
        description={office
          ? "Every completed Minutes of Meeting the Chairperson has already signed, with both signatures on the form."
          : "The minutes of the meetings you chair. Signing sends them to the Academic Office, and any correction the office asks for comes back to you before it returns there."} />
      {!waiting.length && <div className="empty-state"><h3>Nothing is waiting for you</h3>
        <p>{office ? "Minutes arrive here after the Chairperson signs them." : "Minutes arrive here after the Member Secretary submits the completed form."}</p></div>}
      {!!waiting.length && <div className="chair-list mt-16">{waiting.map(row => <div className="chair-row minutes-row" key={row.workspaceId}>
        <div>
          <b>{row.meetingLabel} · {row.department}</b>
          <small>{row.school} · {row.date ? longDate(row.date) : "date not set"} · Chairperson {row.chairName || "—"} · Member Secretary {row.secretaryName || "—"}</small>
        </div>
        <div className="doc-tool-actions">
          <StatusPill status="pending">{row.momStatusLabel}</StatusPill>
          <button className="btn btn-primary btn-small" onClick={() => openMinutesReview(row.workspaceId)}>
            Open completed form
          </button>
        </div>
      </div>)}</div>}
    </>;
  }

  // Every DAC and BOS meeting on record, filtered by committee, school, department,
  // academic year or document. This is the Academic Office's shelf of past forms.
  function archiveView() {
    if (!["academic_office", "system_admin"].includes(role)) {
      return <><SectionHeading eyebrow="Committee archive" title="Every DAC and BOS meeting on record"
        description="Approved request forms and completion forms, filtered by school and department." />
        <div className="empty-state"><h3>Academic Office access required</h3></div></>;
    }
    const filters = archive.filters || { committees: [], schools: [], academicYears: [], statuses: [] };
    const summary = archive.summary || { all: 0, DAC: 0, BOS: 0, withRequestForm: 0, withCompletionForm: 0 };
    const rows = archive.rows || [];
    const query = archive.query;
    const departments = (filters.schools || []).find(entry => entry.school === query.school)?.departments || [];
    const setQuery = patch => setArchive(current => ({ ...current, query: { ...current.query, ...patch } }));
    const chip = (label, value, key) => <button key={`${key}-${value || "all"}`}
      className={`archive-chip ${query[key] === value ? "active" : ""}`}
      onClick={() => loadArchive({ [key]: value })}>{label}</button>;
    return <>
      <SectionHeading eyebrow="Committee archive"
        title="Every DAC and BOS meeting on record"
        description="Filter the past meetings by committee, school, department and year, then open the meeting request form or the completion form (approved minutes)."
        actions={<span className="tag">{summary.all || 0} meetings</span>} />

      <div className="stat-grid">
        {[["All meetings", summary.all], ["DAC", summary.DAC], ["BOS", summary.BOS],
          ["Request forms", summary.withRequestForm], ["Completion forms", summary.withCompletionForm]]
          .map(([label, value]) => <div className="stat-card" key={label}>
            <span className="stat-label">{label}</span><strong>{value ?? 0}</strong></div>)}
      </div>

      <section className="panel panel-pad mt-16 archive-filters">
        <div className="panel-header"><div><h2>Filter the archive</h2>
          <p>Choose a committee, then narrow to a school, a department or a single year.</p></div>
          <button className="btn btn-outline btn-small" onClick={() => loadArchive({ committee: "", school: "", department: "", academicYear: "", docType: "", status: "", q: "", dateFrom: "", dateTo: "" })}>Clear</button></div>
        <div className="archive-chip-row">
          <span className="archive-chip-label">Committee</span>
          {chip("All", "", "committee")}
          {(filters.committees || []).map(entry => chip(entry.code, entry.code, "committee"))}
        </div>
        <div className="archive-selects">
          <label className="doc-tool-label">School
            <select className="doc-tool-input" aria-label="Filter by school" value={query.school}
              onChange={event => loadArchive({ school: event.target.value, department: "" })}>
              <option value="">All schools</option>
              {(filters.schools || []).map(entry => <option value={entry.school} key={entry.school}>{entry.school}</option>)}
            </select>
          </label>
          <label className="doc-tool-label">Department / branch
            <select className="doc-tool-input" aria-label="Filter by department" value={query.department}
              onChange={event => loadArchive({ department: event.target.value })}>
              <option value="">All departments</option>
              {departments.map(name => <option value={name} key={name}>{name}</option>)}
            </select>
          </label>
          <label className="doc-tool-label">Academic year
            <select className="doc-tool-input" aria-label="Filter by academic year" value={query.academicYear}
              onChange={event => loadArchive({ academicYear: event.target.value })}>
              <option value="">All years</option>
              {(filters.academicYears || []).map(year => <option value={year} key={year}>{year}</option>)}
            </select>
          </label>
          <label className="doc-tool-label">Form
            <select className="doc-tool-input" aria-label="Filter by form" value={query.docType}
              onChange={event => loadArchive({ docType: event.target.value })}>
              <option value="">Both forms</option>
              <option value="request">Meeting request form only</option>
              <option value="mom">Completion form (minutes) only</option>
              <option value="atr">Action Taken Report only</option>
            </select>
          </label>
          <label className="doc-tool-label">Search
            <input className="doc-tool-input" aria-label="Search the archive" placeholder="Department, chair, reference…"
              value={query.q} onChange={event => setQuery({ q: event.target.value })}
              onKeyDown={event => { if (event.key === "Enter") loadArchive({ q: event.target.value }); }} />
          </label>
          <label className="doc-tool-label">From date
            <input type="date" className="doc-tool-input" aria-label="Archive from date" value={query.dateFrom}
              onChange={event => setQuery({ dateFrom: event.target.value })} />
          </label>
          <label className="doc-tool-label">To date
            <input type="date" className="doc-tool-input" aria-label="Archive to date" value={query.dateTo}
              onChange={event => setQuery({ dateTo: event.target.value })} />
          </label>
          <button className="btn btn-primary btn-small" onClick={() => loadArchive({ q: query.q, dateFrom: query.dateFrom, dateTo: query.dateTo })}>Apply</button>
        </div>
      </section>

      {archive.loading && <p className="muted mt-16">Loading the archive…</p>}
      {!archive.loading && !rows.length && <div className="empty-state mt-16"><h3>No meeting matches these filters</h3>
        <p>Clear the filters, or pick another committee or school.</p></div>}
      {!!rows.length && <section className="panel panel-pad mt-16">
        <div className="panel-header"><div><h2>{rows.length} meeting{rows.length === 1 ? "" : "s"}</h2>
          <p>Newest first. Open a form to read it, or download the approved copy.</p></div></div>
        <div className="archive-table-wrap">
          <table className="report-table archive-table">
            <thead><tr><th>Meeting</th><th>School / department</th><th>Date</th><th>Chairperson</th>
              <th>Status</th><th>Forms</th></tr></thead>
            <tbody>{rows.map(row => <tr key={row.workspaceId}>
              <td><b>{row.meetingLabel}</b><br /><small>{row.academicYear} · {row.semester} semester<br />{row.reference}</small></td>
              <td>{row.school}<br /><small>{row.department}</small></td>
              <td>{row.date ? dmy(row.date) : "—"}<br /><small>{row.venue}</small></td>
              <td>{row.chairName || "—"}<br /><small>{row.secretaryName}</small></td>
              <td><StatusPill status={row.status} /><br /><small>{row.momStatusLabel}</small></td>
              <td className="archive-forms">
                <button className="btn btn-outline btn-small" onClick={() => openArchiveMeeting(row.workspaceId)}>View on screen</button>
                {row.requestForm ? <a className="btn btn-outline btn-small" href={row.requestForm.downloadUrl}>Request form ↓</a>
                  : <span className="archive-missing">Request form not archived</span>}
                {row.completionForm ? <a className="btn btn-outline btn-small" href={row.completionForm.downloadUrl}>Completion form ↓</a>
                  : <span className="archive-missing">Minutes not approved yet</span>}
              </td>
            </tr>)}</tbody>
          </table>
        </div>
      </section>}
    </>;
  }

  function notificationsView() {
    const items = notifications.items || [];
    return <><SectionHeading eyebrow="Notifications" title="What needs your attention" description="The same event that will be emailed from the conveyer's mailbox (Microsoft 365, configured last) appears here immediately." actions={notifications.unread ? <button className="btn btn-outline btn-small" onClick={async () => { await apiFetch("/api/notifications/read", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ all: true }) }); setNotifications(current => ({ items: current.items.map(item => ({ ...item, unread: false })), unread: 0 })); }}>Mark all read</button> : null} />
      {items.length ? <div className="notification-list">{items.map(item => <article className={`notification-row ${item.unread ? "unread" : ""}`} key={item.id}><div><b>{item.title}</b><p>{item.body}</p><small>{item.kindLabel} · {item.createdAt?.replace("T", " ").slice(0, 16)}{item.actor ? ` · from ${item.actor}` : ""}</small></div><div className="doc-tool-actions">{item.workspaceId && role === "faculty" && <button className="btn btn-outline btn-small" onClick={() => (mine.some(row => row.workspaceId === item.workspaceId) ? openWorkspace(item.workspaceId) : openChairRequest(item.workspaceId))}>Open request</button>}{item.unread && <span className="nav-count">1</span>}</div></article>)}</div>
        : <div className="empty-state"><h3>No notifications yet</h3><p>Invitations, approval requests, revision notes and report reminders appear here.</p></div>}
    </>;
  }

  // Full request view for the Chairperson: agenda wording, invitee roster, meeting
  // details and the approval trail, with the decision buttons at the end.
  const chairReviewPanel = chairReview ? (() => {
    const meeting = chairReview.state.meeting || {};
    const agendas = meeting.agendas || [];
    const members = meeting.members || [];
    const trail = [
      { label: "Submitted by the Member Secretary", value: `${meeting.secretaryName || "—"} · ${chairReview.state.submittedAt || "—"}` },
      { label: "Member Secretary signature", value: chairReview.state.secretarySignature ? `Recorded · v${chairReview.state.secretarySignature.version || "—"}` : "On file with the organizer" },
      { label: "Waiting on", value: `${meeting.chairName || "Chairperson"} — your signature` },
    ];
    return <div className="signature-backdrop chair-review-backdrop" role="dialog" aria-modal="true" aria-label="Request awaiting your signature">
      <div className="chair-review-panel">
        <header className="chair-review-head">
          <div>
            <div className="doc-tool-subheading">Request awaiting your signature</div>
            <h2>{meeting.school} · {meeting.department}</h2>
            <small className="muted">
              DAC-{String(Number(numberOnly(meeting.meetingNo)) || 0).padStart(2, "0")} · {longDate(meeting.date)} · {meeting.startTime}–{meeting.endTime} · {meeting.venue} · {meeting.mode}
            </small>
          </div>
          <button className="btn btn-outline btn-small" onClick={() => { setChairReview(null); setChairComment(""); }}>Close</button>
        </header>
        <div className="chair-review-body">
          <section className="chair-review-block">
            <h3>Agenda ({agendas.length})</h3>
            <ol className="chair-review-agenda">
              {agendas.map((item, index) => <li key={item.id || index}>
                <b>Agenda No: {String(index + 1).padStart(2, "0")}</b>
                <span>{item.title || item.text}</span>
                <small>{item.kind === "standard" ? "Academic Office common agenda" : "Meeting-specific proposal"}{item.rationale ? ` · ${item.rationale}` : ""}</small>
              </li>)}
            </ol>
          </section>
          <section className="chair-review-block">
            <h3>Proposed invitees ({members.length})</h3>
            <table className="chair-review-table">
              <thead><tr><th>Name</th><th>Designation</th><th>Role</th><th>Email</th></tr></thead>
              <tbody>
                {members.map((member, index) => <tr key={member.id || index}>
                  <td>{member.name}</td><td>{member.designation || "—"}</td>
                  <td>{member.role || "Member"}</td><td>{member.email}</td>
                </tr>)}
              </tbody>
            </table>
          </section>
          <section className="chair-review-block">
            <h3>Approval trail</h3>
            <div className="kv-list">{trail.map(row => <div className="kv" key={row.label}><span>{row.label}</span><b>{row.value}</b></div>)}</div>
            {meeting.previousMeetingNo && <p className="muted small">Previous meeting reference: {ordinal(meeting.previousMeetingNo)} DAC meeting held on {longDate(meeting.previousMeetingDate)}.</p>}
          </section>
        </div>
        <footer className="chair-review-foot">
          {!signature && <div className="notice warning chair-review-notice">
            <span className="notice-icon">!</span>
            <span>You have not recorded a signature yet. Approving will ask for it once, and the
              approval is then recorded automatically.</span>
          </div>}
          <label className="field chair-review-comment">
            <span>Note for the Member Secretary (required when returning for revision)</span>
            <textarea className="doc-tool-input doc-comment" value={chairComment}
                      onChange={event => setChairComment(event.target.value)}
                      placeholder="What should change before this request is approved?" />
          </label>
          <div className="doc-tool-actions">
            <button className="btn btn-primary" disabled={busy}
                    onClick={() => chairDecide(chairReview.workspaceId, "approved", chairComment)}>
              Sign &amp; approve
            </button>
            <button className="btn btn-outline" disabled={busy}
                    onClick={() => chairDecide(chairReview.workspaceId, "revision", chairComment)}>
              Return for revision
            </button>
          </div>
        </footer>
      </div>
    </div>;
  })() : null;

  const archiveViewerPanel = archiveViewer ? (() => {
    const viewer = archiveViewer;
    const state = viewer.state || {};
    const meeting = state.meeting || {};
    const row = viewer.row || {};
    return <div className="signature-backdrop archive-viewer-backdrop" role="dialog" aria-modal="true"
                aria-label="Archived meeting">
      <div className="chair-review-panel archive-viewer-panel">
        <div className="chair-review-head">
          <div>
            <div className="eyebrow">{row.committee} · archived meeting</div>
            <h2>{row.meetingLabel} — {row.department}</h2>
            <p className="muted">{row.school} · {row.academicYear} · {row.semester} semester ·
              {" "}{row.date ? dmy(row.date) : "date not recorded"} · reference {row.reference || "—"}</p>
          </div>
          <button className="btn btn-outline btn-small" onClick={() => setArchiveViewer(null)}>Close</button>
        </div>
        <div className="archive-viewer-body">
          <RequestDocument meeting={meeting} editable={false} signatures={viewer.signatures}
            catalog={catalog}
            onSchoolChange={() => {}} onDepartmentChange={() => {}} onMeetingChange={() => {}}
            onMemberChange={() => {}} onMemberRoleChange={() => {}} onRemoveMember={() => {}} onRemoveAgenda={() => {}} />
          {!!(viewer.momSignatures || []).length && <SignatureBlock className="archive-mom-signatures"
            title={`Signatures on the ${row.committee} minutes`} rows={viewer.momSignatures}
            legend="The completion form: the Member Secretary recorded the minutes, the Chairperson approved them, and the Academic Office gave the final approval." />}
        </div>
        <footer className="chair-review-foot">
          <span className="muted">{row.requestForm ? "The signed request form is archived." : "The request form is not archived for this meeting."}
            {" "}{row.completionForm ? "The approved completion form is archived." : "The minutes are not approved yet."}</span>
          <div className="doc-tool-actions">
            {row.requestForm && <a className="btn btn-outline" href={row.requestForm.downloadUrl}>Request form ↓</a>}
            {row.completionForm && <a className="btn btn-primary" href={row.completionForm.downloadUrl}>Completion form ↓</a>}
          </div>
        </footer>
      </div>
    </div>;
  })() : null;

  // Scheduling is a DAC office, not a general faculty right: only the Member Secretary of
  // a DAC may start its meeting request, and only one request may be open at a time. The
  // other office holders (and everyone else) keep full read access. Declared before the
  // view switch, because requestView() consults them.
  // Reports this account still has to act on — shown as a count beside the menu item.
  const atrDue = (atr.reports || []).filter(row =>
    (row.isOwner && row.window?.canFill && ["draft", "returned"].includes(row.status))
    || (row.isChair && row.status === "submitted")).length;
  const scheduleBlocked = role === "faculty" && capabilities ? !capabilities.canSchedule : false;
  const scheduleReason = capabilities?.reason
    || "Only a Member Secretary of a DAC can schedule that DAC's meeting.";

  let content;
  switch (view) {
    case "request": content = requestView(); break;
    case "review": content = reviewView(); break;
    case "mom": content = momView(); break;
    case "library": content = role === "academic_office" ? <AgendaLibrary bank={agendaBank} onAdd={addBankItem} onRemove={removeBankItem} onRestore={restoreBank} /> : <div className="empty-state"><h3>Academic Office permission required</h3></div>; break;
    case "directory": content = role === "system_admin" ? <UserDirectory currentUser={user} /> : <div className="empty-state"><h3>System Administrator permission required</h3></div>; break;
    case "outbox": content = outboxView(); break;
    case "security": content = securityView(); break;
    case "member": content = memberView(); break;
    case "vault": content = vaultView(); break;
    case "archive": content = archiveView(); break;
    case "minutes": content = minutesReviewView(); break;
    case "alerts": content = notificationsView(); break;
    case "atr": content = atrView(); break;
    case "calendar": content = calendarView(); break;
    default: content = overviewView();
  }
  const navItems = NAV[role] || NAV.faculty;

  return <>
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top" onClick={event => { event.preventDefault(); setView("overview"); }}><span className="brand-mark"><span /><span /><span /></span><span><strong>DAC Minutes</strong><small>Document-first workflow</small></span></a>
        <div className="side-label">WORKSPACE</div><nav className="nav-list" aria-label="Main navigation">{navItems.map(([key, label, icon]) => {
          // "Finish it before starting another" is advice about starting, not a lock on
          // the screen where you finish. The nav therefore always opens Meeting request;
          // the New meeting action is what gets blocked.
          const closed = false;
          return <button className={`nav-item ${view === key ? "active" : ""} ${closed ? "nav-item-closed" : ""}`} key={key}
            aria-disabled={closed || undefined}
            title={closed ? scheduleReason : undefined}
            onClick={() => { if (closed) { showToast(scheduleReason, true); return; } setView(key); }}>
            <span className="nav-icon">{icon}</span><span>{label}</span>{closed && <span className="nav-lock" aria-hidden="true">🔒</span>}{key === "review" && state.status === "pending" && <span className="nav-count">1</span>}{key === "alerts" && notifications.unread > 0 && <span className="nav-count">{notifications.unread}</span>}{key === "atr" && atrDue > 0 && <span className="nav-count">{atrDue}</span>}
          </button>;
        })}</nav>
        <div className="sidebar-bottom"><div className="side-status"><span className="status-dot" /><span><b>Secure session</b><small>Signed, role-based workflow</small></span></div><a className="docs-link" href="/README" target="_blank" rel="noreferrer">Project & security notes <span>↗</span></a></div>
      </aside>
      <main className="main-area" id="top">
        <header className="topbar"><div className="crumb"><span>University workspace</span><span className="crumb-sep">/</span><b>{VIEW_LABEL[view] || "Overview"}</b></div><div className="top-actions"><span className="environment-pill"><i /> SECURE SESSION</span><div className="signed-in-user"><span className="avatar">{(user.name || user.email).slice(0, 1).toUpperCase()}</span><span><b>{user.name}</b><small>{user.designation || ROLE_LABEL[role]} · {user.email}</small></span></div><button className="btn btn-outline btn-small" onClick={onLogout}>Sign out</button></div></header>
                <div className="view-root">{content}</div>
    {chairReviewPanel}
    {archiveViewerPanel}
      </main>
    </div>
    {(signatureRequired || signatureOpen) && <SignatureDialog required={signatureRequired && !signature}
      current={!!signature}
      onDone={record => { setSignature(record); setSignatureRequired(false); setSignatureOpen(false); showToast("Signature saved."); }}
      onSignOut={onLogout}
      onCancel={() => setSignatureOpen(false)} />}
    <div className="toast-region" aria-live="polite">{toast && <div className={`toast${toast.isError ? " error" : ""}`}>{toast.message}</div>}</div>
  </>;
}

function SignatureDialog({ onDone, onCancel, onSignOut, required, current }) {
  const canvasRef = useRef(null);
  const [mode, setMode] = useState("draw");
  const [upload, setUpload] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const drawing = useRef(false);

  function point(event) {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const source = event.touches ? event.touches[0] : event;
    return { x: (source.clientX - rect.left) * (canvas.width / rect.width), y: (source.clientY - rect.top) * (canvas.height / rect.height) };
  }
  function start(event) {
    event.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    drawing.current = true;
    const context = canvas.getContext("2d");
    const spot = point(event);
    context.beginPath(); context.moveTo(spot.x, spot.y);
  }
  function move(event) {
    if (!drawing.current) return;
    event.preventDefault();
    const canvas = canvasRef.current;
    const context = canvas.getContext("2d");
    const spot = point(event);
    context.lineWidth = 2.6; context.lineCap = "round"; context.strokeStyle = "#101828";
    context.lineTo(spot.x, spot.y); context.stroke();
  }
  function stop() { drawing.current = false; }
  function clearCanvas() {
    const canvas = canvasRef.current;
    if (canvas) canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  }
  function pickFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!/^image\/(png|jpe?g)$/.test(file.type)) { setError("Upload a PNG or JPEG image of your signature."); return; }
    const reader = new FileReader();
    reader.onload = () => { setUpload(String(reader.result || "")); setError(""); };
    reader.readAsDataURL(file);
  }
  async function save() {
    let image = upload;
    if (mode === "draw") {
      const canvas = canvasRef.current;
      const blank = canvas ? !canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data.some(value => value !== 0) : true;
      if (blank) { setError("Draw your signature in the box, or switch to uploading an image."); return; }
      image = canvas.toDataURL("image/png");
    }
    if (!image) { setError("Draw your signature or upload an image first."); return; }
    setBusy(true); setError("");
    try {
      const response = await apiFetch("/api/signature", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image, method: mode }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The signature could not be saved.");
      onDone(result.signature);
    } catch (problem) { setError(problem.message || "The signature could not be saved."); }
    finally { setBusy(false); }
  }

  return <div className="signature-backdrop signature-dialog" role="dialog" aria-modal="true" aria-label="Digital signature">
    <div className="signature-panel">
      <h2>{current ? "Replace your signature" : "Add your digital signature"}</h2>
      <p className="muted">{required
        ? "Before your first action in the DAC workspace, record the signature that will be stamped on the forms you sign — the meeting request, and later the minutes."
        : "This signature is stamped on every form you sign. Replacing it keeps the earlier version on record against documents already signed."}</p>
      <div className="signature-tabs">
        <button className={`btn btn-small ${mode === "draw" ? "btn-primary" : "btn-outline"}`} onClick={() => setMode("draw")}>Draw on screen</button>
        <button className={`btn btn-small ${mode === "upload" ? "btn-primary" : "btn-outline"}`} onClick={() => setMode("upload")}>Upload an image</button>
      </div>
      {mode === "draw" ? <>
        <canvas ref={canvasRef} width={720} height={220} className="signature-canvas"
                onMouseDown={start} onMouseMove={move} onMouseUp={stop} onMouseLeave={stop}
                onTouchStart={start} onTouchMove={move} onTouchEnd={stop} />
        <div className="doc-tool-actions"><button className="btn btn-outline btn-small" onClick={clearCanvas}>Clear</button></div>
      </> : <>
        <input type="file" accept="image/png,image/jpeg" className="doc-tool-input" onChange={pickFile} aria-label="Signature image" />
        {upload && <div className="signature-preview"><img src={upload} alt="Signature preview" /></div>}
        <small className="doc-tool-hint">PNG or JPEG, at least 120 × 40 px, up to 2 MB. A signature on plain white paper photographs well; the system trims the margin and prints it on the form.</small>
      </>}
      {error && <div className="notice warning mt-10"><span className="notice-icon">!</span><span>{error}</span></div>}
      <div className="notice info mt-10"><span className="notice-icon">i</span><span>Typing a name is not a signature. The image you record here is embedded in the PDF forms you sign, and its checksum is stored so a signed document can always be traced to it.</span></div>
      <div className="doc-tool-actions mt-16">
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save signature"}</button>
        {/* The signature is mandatory, but the account must still be able to leave:
            the dialog covers the header, so "Sign out" here is the only way out. */}
        {required && onSignOut && <button className="btn btn-outline" onClick={onSignOut}>Sign out instead</button>}
        {!required && <button className="btn btn-outline" onClick={onCancel}>Cancel</button>}
      </div>
    </div>
  </div>;
}

// Written out rather than built from the role name: the stylesheet integrity check reads
// class names from the source, and a template literal would hide these from it.
// A Dean chairs every department of their school, so the list is grouped per role:
// one line per office instead of one line per DAC.
function groupDacOffices(offices) {
  const order = ["Chairperson", "Member Secretary", "External Member"];
  const grouped = new Map();
  for (const office of offices || []) {
    const units = grouped.get(office.role) || [];
    if (!units.includes(office.unit)) units.push(office.unit);
    grouped.set(office.role, units);
  }
  return [...grouped.entries()]
    .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
    .map(([role, units]) => {
      // A Dean's list repeats "School of X / " on every line. When all the units sit in
      // one school, print the school once and then just the departments.
      const schools = new Set(units.map(unit => unit.split(" / ")[0]));
      if (units.length > 1 && schools.size === 1) {
        const school = [...schools][0];
        const rest = units.map(unit => unit.split(" / ").slice(1).join(" / ") || "school-level");
        return { role, units: rest, school };
      }
      return { role, units };
    });
}

const DAC_OFFICE_CLASS = {
  "Chairperson": "dac-office-chairperson",
  "Member Secretary": "dac-office-member-secretary",
  "External Member": "dac-office-external-member",
};

function UserDirectory({ currentUser }) {
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState(["system_admin", "academic_office", "faculty", "external_member"]);
  const [catalog, setCatalog] = useState({ schools: [] });
  const [edits, setEdits] = useState({});
  const [form, setForm] = useState({ name: "", email: "", role: "faculty", school: "Engineering", department: "Mechanical Engineering",
    designation: "", employeeCode: "", qualification: "", specialization: "", phone: "", office: "" });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [directoryQuery, setDirectoryQuery] = useState("");
  const [directorySchool, setDirectorySchool] = useState("");
  const [directoryRole, setDirectoryRole] = useState("");
  const schoolNames = catalog.schools.map(school => school.name);
  const departmentsFor = schoolNameValue => catalog.schools.find(school => school.name === schoolNameValue)?.departments || [];
  const formDepartments = departmentsFor(form.school);

  async function refresh() {
    setLoading(true); setError("");
    try {
      const response = await apiFetch("/api/admin/users");
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load the access directory.");
      setUsers(data.users || []); setRoles(data.roles || roles); setCatalog(data.catalog || { schools: [] });
      setForm(current => ({ ...current, school: current.school || data.catalog?.schools?.[0]?.name || "", department: current.department || data.catalog?.schools?.[0]?.departments?.[0]?.name || "" }));
    } catch (loadError) { setError(loadError.message || "Could not load the access directory."); }
    finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);
  function changeForm(field, value) {
    setForm(current => {
      if (field === "school") return { ...current, school: value, department: departmentsFor(value)[0]?.name || "" };
      if (field === "role" && value !== "faculty") return { ...current, role: value, school: "", department: "" };
      if (field === "role" && value === "faculty") {
        const school = current.school || schoolNames[0] || "";
        return { ...current, role: value, school, department: current.department || departmentsFor(school)[0]?.name || "" };
      }
      return { ...current, [field]: value };
    });
  }
  function editValue(user, key) {
    const saved = edits[user.id] || {};
    if (key in saved) return saved[key];
    if (key === "name") return user.name;
    if (key === "designation") return user.designation || "";
    if (key === "employeeCode") return user.employeeCode || "";
    if (key === "qualification") return user.qualification || "";
    if (key === "specialization") return user.specialization || "";
    if (key === "phone") return user.phone || "";
    if (key === "office") return user.office || "";
    if (key === "role") return user.role;
    if (key === "active") return user.active;
    if (key === "school") return user.school || "";
    if (key === "department") return user.department || "";
    return "";
  }
  function changeUser(user, key, value) {
    if (key === "role" && value === "faculty") {
      const school = editValue(user, "school") || schoolNames[0] || "";
      const department = editValue(user, "department") || departmentsFor(school)[0]?.name || "";
      setEdits(current => ({ ...current, [user.id]: { ...(current[user.id] || {}), role: value, school, department } }));
      return;
    }
    if (key === "role" && value !== "faculty") {
      setEdits(current => ({ ...current, [user.id]: { ...(current[user.id] || {}), role: value, school: "", department: "" } }));
      return;
    }
    setEdits(current => ({ ...current, [user.id]: { ...(current[user.id] || {}), [key]: value } }));
    if (key === "school") {
      const nextDepartment = departmentsFor(value)[0]?.name || "";
      setEdits(current => ({ ...current, [user.id]: { ...(current[user.id] || {}), school: value, department: nextDepartment } }));
    }
  }
  async function addUser(event) {
    event?.preventDefault?.(); setBusy(true); setError(""); setMessage("");
    try {
      const response = await apiFetch("/api/admin/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not provision the account.");
      setMessage(`${data.user.email} added to the active access directory.`);
      setForm(current => ({ ...current, name: "", email: "" })); await refresh();
    } catch (addError) { setError(addError.message || "Could not provision the account."); }
    finally { setBusy(false); }
  }
  async function saveUser(user) {
    const draft = { ...user, ...(edits[user.id] || {}) };
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await apiFetch(`/api/admin/users/${user.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: draft.name, role: draft.role, active: draft.active, school: draft.school || null, department: draft.department || null, designation: draft.designation || "", employeeCode: draft.employeeCode || "", qualification: draft.qualification || "", specialization: draft.specialization || "", phone: draft.phone || "", office: draft.office || "" }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not update this account.");
      setUsers(current => current.map(item => item.id === user.id ? data.user : item));
      setEdits(current => { const next = { ...current }; delete next[user.id]; return next; });
      setMessage(`Saved access settings for ${data.user.email}.`);
    } catch (saveError) { setError(saveError.message || "Could not update this account."); }
    finally { setBusy(false); }
  }
  const activeCount = users.filter(user => user.active).length;
  // R1's offices, as held by these accounts. Used for the counters and the filters so the
  // administrator sees exactly what the meeting form will offer.
  const officeOf = user => (user.dacOffices || []).map(office => office.role);
  const externalCount = users.filter(user => officeOf(user).includes("External Member")).length;
  const secretaryCount = users.filter(user => officeOf(user).includes("Member Secretary")).length;
  const chairCount = users.filter(user => user.chairpersonEligible || officeOf(user).includes("Chairperson")).length;
  const signedCount = users.filter(user => user.hasSignature).length;
  const visibleUsers = users.filter(user => {
    if (directorySchool && (user.school || "") !== directorySchool) return false;
    if (directoryRole === "chair" && !(user.chairpersonEligible || officeOf(user).includes("Chairperson"))) return false;
    if (directoryRole === "secretary" && !officeOf(user).includes("Member Secretary")) return false;
    if (directoryRole === "external" && !officeOf(user).includes("External Member")) return false;
    if (directoryRole === "unsigned" && user.hasSignature) return false;
    if (directoryRole === "inactive" && user.active) return false;
    if (["faculty", "academic_office", "system_admin"].includes(directoryRole) && user.role !== directoryRole) return false;
    const needle = directoryQuery.trim().toLowerCase();
    if (!needle) return true;
    return [user.name, user.email, user.designation, user.employeeCode, user.qualification,
            user.specialization, user.phone, user.office, user.school, user.department,
            (user.dacOffices || []).map(office => `${office.role} ${office.unit}`).join(" ")]
      .filter(Boolean).join(" ").toLowerCase().includes(needle);
  });
  // The same rows, as a file the department can print or mail — every detail is included.
  function downloadDirectoryCsv() {
    const header = ["Name", "Email", "Designation", "Staff ID", "Qualification", "Specialisation",
                    "Phone", "Office", "Application role", "School", "Department", "DAC office", "DAC",
                    "Signature on file", "Status"];
    const rows = visibleUsers.map(user => [
      user.name, user.email, user.designation || "", user.employeeCode || "", user.qualification || "",
      user.specialization || "", user.phone || "", user.office || "", ROLE_LABEL[user.role] || user.role,
      user.school || "", user.department || "",
      (user.dacOffices || []).map(office => office.role).join("; "),
      (user.dacOffices || []).map(office => office.unit).join("; "),
      user.hasSignature ? "Yes" : "No", user.active ? "Active" : "Inactive",
    ]);
    const escape = value => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const csv = [header, ...rows].map(row => row.map(escape).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "access-directory.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  return <>
    <SectionHeading eyebrow="System Administrator" title="Access directory" description="Every account on record with the details needed to set a meeting up — designation, staff ID, qualification, specialisation, contact, school, department and the DAC office each person holds. Accounts are permanent: they are re-created on every start and are never removed by an upgrade." actions={<button className="btn btn-outline" onClick={refresh} disabled={loading}>Refresh directory</button>} />
    <div className="notice info"><span className="notice-icon">i</span><span><b>Permanent roster.</b> These 81 accounts come from the college's R1 registry and are re-created on every application start (<code>INSERT OR IGNORE</code>) — no upgrade, restart or reset removes them. Sign-in is a one-time code, never a password.</span></div>
    <div className="stat-grid mt-16">
      <div className="stat-card"><span className="stat-label">Active accounts</span><strong>{activeCount}</strong><small>{users.length} on record · {users.length - activeCount} deactivated</small></div>
      <div className="stat-card"><span className="stat-label">Chairpersons</span><strong>{chairCount}</strong><small>Deans and Heads of Department who may chair</small></div>
      <div className="stat-card"><span className="stat-label">Member Secretaries</span><strong>{secretaryCount}</strong><small>Faculty who may schedule that DAC's meeting</small></div>
      <div className="stat-card"><span className="stat-label">External Members</span><strong>{externalCount}</strong><small>Nominated by R1 to observe a DAC</small></div>
      <div className="stat-card"><span className="stat-label">Signatures on file</span><strong>{signedCount}</strong><small>{users.length - signedCount} still to record one at first sign-in</small></div>
    </div>
    <div className="grid grid-2 mt-16"><section className="panel panel-pad"><div className="panel-header"><div><h2>Add account to allow-list</h2><p>No passwords are collected or stored.</p></div><span className="tag">Admin only</span></div>{/* Not a <form>: a sandboxed frame blocks native submission, so the button calls the
                handler directly. */}
            <div className="admin-user-form"
                 onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); addUser(); } }}><label className="field"><span>Full name</span><input required value={form.name} onChange={event => changeForm("name", event.target.value)} placeholder="Full name as printed on college records" /></label><label className="field"><span>Email address</span><input required type="email" value={form.email} onChange={event => changeForm("email", event.target.value)} placeholder="name@presidencyuniversity.in" /></label><label className="field"><span>Application role</span><select value={form.role} onChange={event => changeForm("role", event.target.value)}>{roles.map(role => <option key={role} value={role}>{ROLE_LABEL[role] || role}</option>)}</select></label>
      {form.role === "faculty" && <><label className="field"><span>School</span><select required value={form.school} onChange={event => changeForm("school", event.target.value)}>{schoolNames.map(school => <option key={school}>{school}</option>)}</select></label>{formDepartments.length > 0
        ? <label className="field"><span>Department</span><select required value={form.department} onChange={event => changeForm("department", event.target.value)}>{formDepartments.map(department => <option key={department.id}>{department.name}</option>)}</select></label>
        : <div className="field-hint">R1 gives this school no departments — it has one school-level DAC, so no department is recorded.</div>}</>}
      {form.role !== "external_member" && <><label className="field"><span>Designation</span><input required value={form.designation} onChange={event => changeForm("designation", event.target.value)} placeholder="Head of the Department, Civil Engineering" /></label><label className="field"><span>Staff ID (optional)</span><input value={form.employeeCode} onChange={event => changeForm("employeeCode", event.target.value)} placeholder="Staff ID issued by the college" /></label></>}
      <label className="field"><span>Qualification (optional)</span><input value={form.qualification} onChange={event => changeForm("qualification", event.target.value)} placeholder="Ph.D. (specialisation)" /></label>
      <label className="field"><span>Specialisation (optional)</span><input value={form.specialization} onChange={event => changeForm("specialization", event.target.value)} placeholder="Research / teaching specialisation" /></label>
      <label className="field"><span>Phone</span><input required value={form.phone} onChange={event => changeForm("phone", event.target.value)} placeholder="+91 …" /></label>
      <label className="field"><span>Office / cabin (optional)</span><input value={form.office} onChange={event => changeForm("office", event.target.value)} placeholder="Block and cabin" /></label>
      <button className="btn btn-primary mt-16" type="button" onClick={addUser} disabled={busy}>{busy ? "Saving…" : "Add to access directory →"}</button></div>
      <div className="notice info mt-16"><span className="notice-icon">i</span><span>The role determines permitted application sections. Faculty are scoped to the selected school and department. Chairperson is not a global account role: the scheduling faculty member is the organizer for that meeting only.</span></div>
    </section><section className="panel panel-pad"><div className="panel-header"><div><h2>Role permissions</h2><p>Server checks are applied to API routes, not just navigation.</p></div></div><div className="permission-row"><b>System Administrator</b><span>Provision, activate, deactivate and assign roles to users.</span></div><div className="permission-row"><b>Academic Office</b><span>Review and decide submitted meeting requests; maintain common agenda items.</span></div><div className="permission-row"><b>Faculty</b><span>Create requests within their provisioned school/department; edit only their own meeting MoM.</span></div><div className="permission-row"><b>External Member</b><span>Read-only access to an explicitly approved meeting that lists their email.</span></div><div className="admin-current-user">Signed in as <b>{currentUser.name}</b> · {currentUser.email}</div></section></div>
    {message && <div className="notice success mt-16"><span className="notice-icon">✓</span><span>{message}</span></div>}{error && <div className="notice error mt-16"><span className="notice-icon">!</span><span>{error}</span></div>}
    <section className="panel panel-pad mt-16"><div className="panel-header"><div><h2>College staff directory (R1)</h2><p>Every account on record, with the DAC office it holds. This is the working list for setting up a meeting: the Chairperson, the Member Secretary who may schedule, and the External Member who observes.</p></div><span className="tag">{visibleUsers.length} of {users.length}</span></div>
      <div className="directory-filters">
        <input className="roster-search directory-search" type="search" value={directoryQuery}
               onChange={event => setDirectoryQuery(event.target.value)}
               placeholder="Search name, email, designation, staff ID, school, department, DAC…" aria-label="Search the access directory" />
        <select value={directorySchool} onChange={event => setDirectorySchool(event.target.value)} aria-label="Filter by school">
          <option value="">All schools</option>
          {schoolNames.map(school => <option key={school} value={school}>{school}</option>)}
        </select>
        <select value={directoryRole} onChange={event => setDirectoryRole(event.target.value)} aria-label="Filter by role">
          <option value="">Everyone</option>
          <option value="chair">Chairpersons ({chairCount})</option>
          <option value="secretary">Member Secretaries ({secretaryCount})</option>
          <option value="external">External Members ({externalCount})</option>
          <option value="faculty">Faculty ({users.filter(u => u.role === "faculty").length})</option>
          <option value="academic_office">Academic Office</option>
          <option value="system_admin">Administrator</option>
          <option value="unsigned">Signature not recorded ({users.length - signedCount})</option>
          <option value="inactive">Deactivated</option>
        </select>
        <button className="btn btn-outline" onClick={downloadDirectoryCsv}>Download CSV</button>
        {(directoryQuery || directorySchool || directoryRole) && (
          <button className="btn-text" onClick={() => { setDirectoryQuery(""); setDirectorySchool(""); setDirectoryRole(""); }}>Clear</button>
        )}
      </div>
      {loading ? <p className="muted">Loading accounts…</p> : <div className="admin-table-wrap"><table className="admin-table directory-table"><thead><tr><th>Person / email</th><th>Profile</th><th>DAC office (R1)</th><th>Role</th><th>School</th><th>Department</th><th>Signature</th><th>Status</th><th>Actions</th></tr></thead><tbody>{visibleUsers.map(user => {
        const selectedRole = editValue(user, "role");
        const selectedSchool = editValue(user, "school");
        const rowDepartments = departmentsFor(selectedSchool);
        return <tr key={user.id}><td><b>{user.name}</b><small>{user.email}</small>{user.designation && <small className="admin-designation">{user.designation}</small>}
            {user.id === currentUser.id && <span className="tag">You</span>}</td>
          <td>{[user.employeeCode && `Staff ID ${user.employeeCode}`, user.qualification, user.specialization,
                user.phone, user.office].filter(Boolean).length > 0
              ? [user.employeeCode && `Staff ID ${user.employeeCode}`, user.qualification, user.specialization,
                 user.phone, user.office].filter(Boolean).map((line, index) => <small className="admin-profile" key={index}>{line}</small>)
              : <span className="muted">—</span>}</td>
          <td>{groupDacOffices(user.dacOffices).length > 0
              ? <div className="dac-office-list">{groupDacOffices(user.dacOffices).map(group => (
                  <small className={`dac-office ${DAC_OFFICE_CLASS[group.role] || ""}`} key={group.role}>
                    <b>{group.role}{group.units.length > 1 ? ` · ${group.units.length} DACs` : ""}</b>
                    {group.school && <span className="dac-office-school">{group.school}</span>}
                    <span>{group.units.join(" · ")}</span>
                  </small>))}</div>
              : <span className="muted">—</span>}</td>
          <td><select value={selectedRole} onChange={event => changeUser(user, "role", event.target.value)}>{roles.map(role => <option key={role} value={role}>{ROLE_LABEL[role] || role}</option>)}</select></td>
          <td>{selectedRole === "faculty" ? <select value={selectedSchool} onChange={event => changeUser(user, "school", event.target.value)}>{schoolNames.map(school => <option key={school}>{school}</option>)}</select> : <span className="muted">—</span>}</td>
          <td>{selectedRole !== "faculty" ? <span className="muted">—</span>
              : rowDepartments.length > 0
                ? <select value={editValue(user, "department")} onChange={event => changeUser(user, "department", event.target.value)}>{rowDepartments.map(department => <option key={department.id}>{department.name}</option>)}</select>
                : <span className="muted" title="R1 gives this school no departments — it has one school-level DAC">— school-level DAC</span>}</td>
          <td>{user.hasSignature
              ? <span className="signature-state signed">On file</span>
              : <span className="signature-state pending">Not recorded</span>}</td>
          <td><StatusPill status={user.active ? "approved" : "rejected"}>{user.active ? "Active" : "Inactive"}</StatusPill></td>
          <td><div className="admin-actions"><button className="btn btn-outline btn-small" onClick={() => saveUser(user)} disabled={busy}>Save</button><button className="btn-text" onClick={() => changeUser(user, "active", !editValue(user, "active"))}>{editValue(user, "active") ? "Deactivate" : "Activate"}</button></div></td></tr>;
      })}{visibleUsers.length === 0 && !loading && (
        <tr><td colSpan={9}><span className="muted">No account matches this filter.</span></td></tr>
      )}</tbody></table></div>}
    </section>
  </>;
}

function AgendaLibrary({ bank, onAdd, onRemove, onRestore }) {
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  return <><SectionHeading eyebrow="Academic Office" title="Common agenda library" description="Maintain recurring agenda options available to Chairpersons. Meeting-specific proposals are not added automatically." actions={<button className="btn btn-outline" onClick={onRestore}>Restore official list</button>} /><div className="grid grid-2"><section className="panel panel-pad"><div className="panel-header"><div><h2>Shared agenda items</h2><p>Published by the Academic Office</p></div><span className="tag">{bank.length} items</span></div><div className="bank-list">{bank.map((item, index) => <div className="bank-item" key={item.id}><span className="tag">{pad2(index + 1)}</span><span><b>{item.title}</b><small>{item.note}</small></span><button className="btn-text" onClick={() => onRemove(item.id)}>Remove</button></div>)}</div></section><section className="panel panel-pad"><div className="panel-header"><div><h2>Add a common agenda item</h2><p>Only Academic Office maintains this list.</p></div></div><label className="field"><span>Agenda title</span><input value={title} onChange={event => setTitle(event.target.value)} placeholder="Concise recurring agenda title" /></label><label className="field mt-10"><span>Category / note</span><input value={note} onChange={event => setNote(event.target.value)} placeholder="e.g. Academic review" /></label><button className="btn btn-primary mt-16" onClick={() => { onAdd(title, note); setTitle(""); setNote(""); }}>Add to common list</button><hr className="divider" /><div className="notice info"><span className="notice-icon">i</span><span>Promoting a meeting-specific item into the shared library is an explicit Office action.</span></div></section></div></>;
}
function SecurityCard({ icon, title, text, tag }) { return <article className="security-card"><div className="security-icon">{icon}</div><h3>{title}</h3><p>{text}</p><span className="tag tag-new mt-10">{tag}</span></article>; }

export default App;
