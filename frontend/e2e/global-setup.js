// Global setup: sign every actor in once, record any missing signatures, and build the
// five starting points the browser specs need. Written to e2e/.fixtures.json.
import fs from "node:fs";
import path from "node:path";
import { ACCOUNTS, signIn, ensureSignature } from "./support/api.js";
import { Cast, buildMeeting } from "./support/workflow.js";

const BASE_URL = process.env.DAC_BASE_URL || "http://127.0.0.1:8050";
const HERE = path.dirname(new URL(import.meta.url).pathname);
const AUTH_DIR = path.join(HERE, ".auth");
const FIXTURE_FILE = path.join(HERE, ".fixtures.json");

const STATE_NAMES = {
  [ACCOUNTS.momSecretary]: "mom-secretary",
  [ACCOUNTS.chairRequestSecretary]: "chair-request-secretary",
  [ACCOUNTS.officeSecretary]: "office-secretary",
  [ACCOUNTS.atrSecretary]: "atr-secretary",
  [ACCOUNTS.externalSecretary]: "external-secretary",
  [ACCOUNTS.chair]: "chair",
  [ACCOUNTS.chairSoe]: "chair-soe",
  [ACCOUNTS.office]: "office",
  [ACCOUNTS.admin]: "admin",
  [ACCOUNTS.externalAi]: "external-ai",
  [ACCOUNTS.externalEee]: "external-eee",
  [ACCOUNTS.externalCivil]: "external-civil",
};

export function statePath(name) {
  return path.join(AUTH_DIR, `${name}.json`);
}

function isoDate(offsetDays) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

/** Unit codes (SOE / CIV …) for the reference numbers, read from the app's own registry. */
async function unitCodes(cast) {
  const admin = await cast.person(ACCOUNTS.admin, { sign: false });
  const { body } = await admin.get("/api/dac/units");
  const map = new Map();
  for (const unit of body.units || []) {
    map.set(`${unit.school}::${unit.department || ""}`, unit.code || "");
  }
  return map;
}

function codesFor(codes, user) {
  const code = codes.get(`${user.school}::${user.department || ""}`) || "";
  if (code) return { schoolCode: code.slice(0, 3).toUpperCase(), departmentCode: code.toUpperCase() };
  const initials = (value, fallback) => {
    const words = String(value || "").replace(/^school of|^department of/gi, "").trim().split(/\s+/).filter(Boolean);
    return (words.slice(0, 3).map((word) => word[0]).join("") || fallback).toUpperCase();
  };
  return { schoolCode: initials(user.school, "SOE"), departmentCode: initials(user.department, "GEN") };
}

export default async function globalSetup() {
  // Iterating on a spec? DAC_E2E_REUSE=1 keeps the fixtures already built on the running
  // server instead of rebuilding them (a rebuild collides with the existing workspaces).
  if (process.env.DAC_E2E_REUSE === "1") {
    console.log("  reusing the fixtures already on the server (DAC_E2E_REUSE=1)");
    return;
  }
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  const health = await fetch(`${BASE_URL}/api/health`).catch(() => null);
  if (!health || !health.ok) throw new Error(`No server at ${BASE_URL} — start it first (bash tests/run_e2e.sh).`);
  const mode = await health.json();
  if (mode.mode !== "test") throw new Error(`Refusing to run: the server is in ${mode.mode} mode. E2E needs APP_ENV=test.`);

  const cast = new Cast(BASE_URL);
  const codes = await unitCodes(cast);

  // Every actor signs in once and keeps a saved session; the clock-drawing gate is
  // exercised properly in 01-signin.spec.js, so the rest reuses the session.
  const sessions = {};
  for (const email of Object.keys(STATE_NAMES)) {
    const session = await signIn(BASE_URL, email);
    await session.context.storageState({ path: statePath(STATE_NAMES[email]) });
    sessions[email] = session;
  }
  // Every signatory needs a signature on file: it is stamped on the forms they sign,
  // and the app refuses an approval without one.
  for (const email of Object.keys(STATE_NAMES)) {
    await ensureSignature(sessions[email]);
  }
  for (const email of Object.keys(STATE_NAMES)) cast.sessions[email] = sessions[email];

  const people = Object.fromEntries(Object.entries(sessions).map(([email, session]) => [email, session.user]));
  const codesOf = (email) => codesFor(codes, people[email]);

  const fixtures = {};

  // 1 · A request waiting for the Chairperson's signature.
  const chairQueueCodes = codesOf(ACCOUNTS.chairRequestSecretary);
  fixtures.chairQueue = await buildMeeting(cast, {
    label: "CHAIR", stopAt: "chair", secretaryEmail: ACCOUNTS.chairRequestSecretary,
    chairEmail: ACCOUNTS.chair, externalEmail: ACCOUNTS.externalAi,
    meetingNo: "1", academicYear: "2026-27", semester: "Odd", ...chairQueueCodes,
  });

  // 2 · A request the Chairperson has signed, waiting for the Academic Office.
  const officeQueueCodes = codesOf(ACCOUNTS.officeSecretary);
  fixtures.officeQueue = await buildMeeting(cast, {
    label: "OFFICE", stopAt: "office", secretaryEmail: ACCOUNTS.officeSecretary,
    chairEmail: ACCOUNTS.chair, externalEmail: ACCOUNTS.externalAi,
    meetingNo: "1", academicYear: "2027-28", semester: "Odd", ...officeQueueCodes,
  });

  // 3 · An approved meeting that has happened: the minutes are unlocked and empty, so a
  //     person can write the discussion and resolution in the browser.
  const momCodes = codesOf(ACCOUNTS.momSecretary);
  fixtures.momDraft = await buildMeeting(cast, {
    label: "MOM", stopAt: "unlocked", secretaryEmail: ACCOUNTS.momSecretary,
    chairEmail: ACCOUNTS.chair, externalEmail: ACCOUNTS.externalAi,
    meetingNo: "1", academicYear: "2028-29", semester: "Odd", ...momCodes,
  });

  // 4 · Minutes already signed by the Chairperson, with the External Member's report
  //     still outstanding — the Academic Office cannot approve until that report exists.
  const signedCodes = codesOf(ACCOUNTS.externalSecretary);
  fixtures.externalPending = await buildMeeting(cast, {
    label: "EXTERNAL", stopAt: "signed", secretaryEmail: ACCOUNTS.externalSecretary,
    chairEmail: ACCOUNTS.chairSoe, externalEmail: ACCOUNTS.externalCivil,
    meetingNo: "1", academicYear: "2026-27", semester: "Odd", ...signedCodes,
  });

  // 5 · A fully approved meeting whose action items are past their target dates: the
  //     Action Taken Report is open and ready to be filled. Its approved minutes also
  //     populate the document vault and the committee archive.
  const atrCodes = codesOf(ACCOUNTS.atrSecretary);
  const office = await cast.person(ACCOUNTS.office);
  const atrYear = { academicYear: "2026-27", semester: "Even" };
  await office.post("/api/atr/calendar", {
    entries: [
      { ...atrYear, committee: "DAC", meetingNo: 1, date: isoDate(-30) },
      { ...atrYear, committee: "DAC", meetingNo: 2, date: isoDate(60) },
    ],
  });
  fixtures.atrReady = await buildMeeting(cast, {
    label: "ATR", stopAt: "approved", secretaryEmail: ACCOUNTS.atrSecretary,
    chairEmail: ACCOUNTS.chairSoe, externalEmail: ACCOUNTS.externalEee,
    meetingNo: "1", ...atrYear, ...atrCodes,
    actionTargets: [isoDate(2), isoDate(5), isoDate(10)],
  });
  const atrSecretary = await cast.person(ACCOUNTS.atrSecretary);
  await atrSecretary.post("/api/testing/atr-clock", { workspaceId: fixtures.atrReady.workspaceId, daysAgo: 1 });

  // Only identifiers and starting statuses are written out — never credentials.
  const summary = {};
  for (const [name, fixture] of Object.entries(fixtures)) {
    summary[name] = {
      workspaceId: fixture.workspaceId,
      status: fixture.state?.status || "",
      department: fixture.state?.meeting?.department || "",
      school: fixture.state?.meeting?.school || "",
      meetingLabel: `${fixture.state?.committee || "DAC"}-${fixture.state?.meeting?.meetingNo || ""}`,
      secretaryName: fixture.secretary.user.name,
      secretary: fixture.secretary.user.email,
      chair: fixture.chair.user.email,
      external: fixture.external.user.email,
      momStatus: fixture.state?.momReview?.status || "",
    };
  }
  fs.writeFileSync(FIXTURE_FILE, JSON.stringify({ baseURL: BASE_URL, fixtures: summary }, null, 2));
  console.log("\n  E2E fixtures ready:");
  for (const [name, row] of Object.entries(summary)) {
    console.log(`    ${name.padEnd(16)} ${row.workspaceId}  status=${row.status}  minutes=${row.momStatus || "—"}`);
  }
  console.log("");
}
