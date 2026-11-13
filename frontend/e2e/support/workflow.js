// Meeting journeys, built over the product's own API.
//
// A browser test should start at the moment a person takes over — the request waiting
// for the Chairperson, the minutes unlocked after the meeting, an Action Taken Report
// whose deadline has passed. Getting there by clicking would test the setup, not the
// screen. So each fixture below walks the real chain (save → submit → chair → office →
// clock → minutes → report) and stops exactly where the browser spec begins.
import { signIn, ensureSignature, ACCOUNTS } from "./api.js";

/**
 * The meeting document as the request screen builds it: both committees need the first
 * two agenda items to be the previous minutes and the Action Taken Report.
 */
export function meetingFixture(workspaceId, { committee, organizer, chair, external, extraMember, meetingNo, academicYear, semester, schoolCode, departmentCode }) {
  return {
    id: workspaceId,
    committee,
    meetingNo,
    academicYear,
    semester,
    school: organizer.school,
    department: organizer.department || "",
    schoolCode,
    departmentCode,
    previousMeetingNo: "1",
    previousMeetingDate: "2026-06-12",
    date: "2026-11-12",
    startTime: "10:30",
    endTime: "12:30",
    venue: "Board Room",
    mode: "Offline",
    onlineLink: "",
    chairName: chair.name,
    chairEmail: chair.email,
    secretaryName: organizer.name,
    secretaryEmail: organizer.email,
    attendanceConfirmed: false,
    agendas: [
      { id: "std-mom", kind: "standard", title: "Approval of the previous minutes", rationale: "" },
      { id: "std-atr", kind: "standard", title: "Action Taken Report of the previous meeting", rationale: "" },
      { id: "std-curriculum", kind: "standard", title: "Curriculum and course outcome review", rationale: "" },
    ],
    members: [
      { id: "m-chair", name: chair.name, designation: chair.designation || "Professor", role: "Chairperson", email: chair.email, external: false, present: false },
      { id: "m-sec", name: organizer.name, designation: "Member Secretary", role: "Member Secretary", email: organizer.email, external: false, present: false },
      ...(extraMember ? [{ id: "m-1", name: extraMember.name, designation: extraMember.designation || "Professor", role: "Member", email: extraMember.email, external: false, present: false }] : []),
      { id: "m-ext", name: external.name, designation: external.designation || "External", role: "External Member", email: external.email, external: true, present: false },
    ],
  };
}

export function blankState(workspaceId, meeting) {
  return {
    status: "draft", workspaceId, committee: meeting.committee, meeting,
    agendaBank: [], momItems: [], additionalDiscussions: [], photos: [],
    actionItems: [], aiReport: null, outbox: [], audit: [], pdfGenerated: false,
  };
}

export function fillMinutes(state, { actionTargets }) {
  function relevantText(title, kind) {
    const low = title.toLowerCase();
    if (low.includes("mom") || low.includes("previous minutes") || low.includes("approval of the mom")) {
      return kind === "discussion"
        ? `The committee reviewed and discussed the MoM of the 1st Departmental Academic Committee meeting held on 12.06.2026 for "${title}". The Chairperson confirmed quorum with 5 members present, the Member Secretary read the previous minutes dated 12 June 2026 circulated on 10 November 2026, noted the correction on agenda numbering suggested by the Chairperson, verified attendance of the External Member, and deliberated on the approval of the minutes for record and continuation of pending curriculum matters.`
        : `Resolved to approve the MoM of the 1st Departmental Academic Committee meeting held on 12.06.2026 for "${title}" as circulated, incorporating the correction on agenda numbering noted in the discussion and confirming the record for the next DAC meeting.`;
    }
    if (low.includes("atr") || low.includes("action taken")) {
      return kind === "discussion"
        ? `The Member Secretary presented the Action Taken Report (ATR) on decisions from the 1st DAC meeting held on 12.06.2026 for "${title}" for consideration and approval, including the status of curriculum revision completed for 3 courses, course plan approvals for the upcoming semester, and the pending action on audit course offerings. Members reviewed the ATR document circulated as Annexure 02, noted that the audit course list is pending student interest confirmation, and deliberated on the approval of the ATR and the follow-up required for the pending actions.`
        : `Resolved to approve the Action Taken Report (ATR) of the 1st DAC meeting held on 12.06.2026 for "${title}" as presented and to carry the pending actions on audit course offerings noted in the discussion to the next meeting for follow-up by the Member Secretary.`;
    }
    if (low.includes("curriculum") || low.includes("course outcome") || low.includes("outcome review")) {
      return kind === "discussion"
        ? `The committee discussed the curriculum structure for the upcoming semester and the attainment of course outcomes for "${title}". Members reviewed the CO-PO mapping data and attainment analysis for the last semester for Data Structures and Cloud Computing, noted attainment below 60 percent for CO2 in Data Structures and Cloud Computing, and deliberated on corrective measures including tutorial sessions for Data Structures and revised assessment rubrics for Cloud Computing.`
        : `Resolved to approve the curriculum structure and course outcome measures for "${title}" as discussed, and to implement tutorial sessions for Data Structures and revised assessment rubrics for Cloud Computing as corrective measures deliberated.`;
    }
    return kind === "discussion"
      ? `The committee discussed "${title}" — ${low}. Members reviewed the supporting documents for ${low}, noted the presentation on ${low} and deliberated on the action required for ${low}.`
      : `Resolved to approve ${low} as discussed.`;
  }
  const items = (state.momItems || []).map((item, index) => {
    const title = item.title || `Agenda ${index + 1}`;
    return {
      ...item,
      discussion: relevantText(title, "discussion"),
      resolution: relevantText(title, "resolution"),
    };
  });
  const first = items[0] || { agendaNo: 1, resolution: "" };
  return {
    ...state,
    momItems: items,
    actionItems: actionTargets.map((targetDate, index) => ({
      id: `act-${index + 1}`,
      agendaNo: String(first.agendaNo || 1),
      text: `Action item ${index + 1}: circulate the approved minutes and confirm the correction with the department.`,
      owner: "Member Secretary",
      targetDate,
      sourceResolution: first.resolution || "",
    })),
  };
}

export class Cast {
  constructor(baseURL) {
    this.baseURL = baseURL;
    this.sessions = {};
  }

  async person(email, { sign = true } = {}) {
    if (!this.sessions[email]) {
      const session = await signIn(this.baseURL, email);
      if (sign) await ensureSignature(session);
      this.sessions[email] = session;
    }
    return this.sessions[email];
  }

  async organizer(email) {
    const session = await this.person(email);
    return { session, user: session.user };
  }
}

async function must(promise, label) {
  const result = await promise;
  if (result.status !== 200) throw new Error(`${label}: HTTP ${result.status} ${JSON.stringify(result.body).slice(0, 240)}`);
  return result.body;
}

/**
 * A meeting carried as far as ``stopAt``:
 *
 *   "chair"     the request is waiting for the Chairperson's signature
 *   "office"    the Chairperson signed; the Academic Office queue holds it
 *   "minutes"   approved, the meeting has happened, minutes are unlocked and written
 *   "signed"    minutes are with the Chairperson for signature
 *   "external"  the Chairperson signed the minutes; the external report is pending
 *   "approved"  everything approved and archived (the ATR can then be opened)
 */
export async function buildMeeting(cast, options) {
  const {
    label, committee = "DAC", stopAt = "approved",
    secretaryEmail, chairEmail, externalEmail, meetingNo = "1",
    academicYear = "2026-27", semester = "Even", schoolCode = "SOE", departmentCode = "CIV",
    extraMemberEmail = "", actionTargets = [],
  } = options;

  const workspaceId = `${committee}-E2E-${label}`;
  const secretary = await cast.person(secretaryEmail);
  const chair = await cast.person(chairEmail);
  const office = await cast.person(ACCOUNTS.office);
  const external = await cast.person(externalEmail);
  const extra = extraMemberEmail ? await cast.person(extraMemberEmail) : null;

  const people = [chair.user, secretary.user, ...(extra ? [extra.user] : []), external.user];
  const meeting = meetingFixture(workspaceId, {
    committee, organizer: secretary.user, chair: chair.user, external: external.user,
    extraMember: extra?.user, meetingNo, academicYear, semester, schoolCode, departmentCode,
  });
  let state = blankState(workspaceId, meeting);

  await must(secretary.post("/api/workspace/save", { workspaceId, state }), `${label}: save draft`);
  state = (await must(secretary.post("/api/workspace/submit", { workspaceId, state }), `${label}: submit request`)).state;
  if (stopAt === "chair") return { workspaceId, state, secretary, chair, office, external, people };

  state = (await must(chair.post("/api/workspace/chair-decision", { workspaceId, decision: "approved", comment: "" }),
    `${label}: chair approves request`)).state;
  if (stopAt === "office") return { workspaceId, state, secretary, chair, office, external, people };

  state = (await must(office.post("/api/workspace/decision", { workspaceId, decision: "approved", comment: "" }),
    `${label}: office approves request`)).state;

  state = (await must(secretary.post("/api/testing/advance-clock", { workspaceId }), `${label}: clock`)).state;
  if (stopAt === "unlocked") {
    // The MoM blocks appear when the meeting is completed; leave them empty so the
    // browser spec can write the discussion and the resolution itself.
    await must(secretary.post("/api/workspace/save", { workspaceId, state }), `${label}: save unlocked minutes`);
    return { workspaceId, state, secretary, chair, office, external, people };
  }
  state = fillMinutes(state, { actionTargets });
  await must(secretary.post("/api/workspace/save", { workspaceId, state }), `${label}: save minutes`);
  state = (await must(secretary.post("/api/workspace/mom/submit", { workspaceId }), `${label}: submit minutes`)).state;
  if (stopAt === "minutes") return { workspaceId, state, secretary, chair, office, external, people };

  state = (await must(chair.post("/api/workspace/mom/chair-decision", { workspaceId, decision: "approved", comment: "" }),
    `${label}: chair signs minutes`)).state;
  if (stopAt === "signed") return { workspaceId, state, secretary, chair, office, external, people };

  // The External Member's report is the Academic Office's gate.
  const draft = await must(external.get(`/api/external-report/${workspaceId}`), `${label}: external draft`);
  const payload = draft.draft || {};
  for (const row of payload.agenda || []) {
    row.response = "yes";
    row.remarks = "Verified with the department.";
  }
  payload.declaration = "The observations above are recorded to the best of my knowledge.";
  await must(external.post(`/api/external-report/${workspaceId}`, { payload, submit: true }), `${label}: external report`);
  if (stopAt === "external") {
    const fresh = await must(external.get(`/api/external-report/${workspaceId}`), `${label}: external state`);
    return { workspaceId, state, secretary, chair, office, external, people, externalReport: fresh };
  }

  state = (await must(office.post("/api/workspace/mom/office-decision", { workspaceId, decision: "approved", comment: "" }),
    `${label}: office approves minutes`)).state;
  return { workspaceId, state, secretary, chair, office, external, people };
}
