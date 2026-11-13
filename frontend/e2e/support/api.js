// API helpers for the end-to-end suite.
//
// The suite proves the *interface*. Seeding a meeting to the state a screen needs is
// done over the product's own HTTP API — the same endpoints the interface calls — so a
// test starts where the person would find themselves, without clicking through an hour
// of setup first. Nothing here writes to the database directly.
import { request } from "@playwright/test";
import zlib from "node:zlib";

export const ACCOUNTS = {
  // One organizer per journey, so each account's "current workspace" is unambiguous.
  momSecretary: "poonam.nilesh@presidencyuniversity.in",
  chairRequestSecretary: "swetha.rajagopal@presidencyuniversity.in",
  officeSecretary: "thabassumkhan@presidencyuniversity.in",
  atrSecretary: "gayatri.mtl@presidencyuniversity.in",
  externalSecretary: "ajay@presidencyuniversity.in",
  chair: "shakkeera.l@presidencyuniversity.in",
  chairSoe: "deansoe@presidencyuniversity.in",
  office: "academic.office@presidencyuniversity.in",
  admin: "admin@presidencyuniversity.in",
  externalAi: "sekar.ramalingam@presidencyuniversity.in",
  externalEee: "pradeepkumar@presidencyuniversity.in",
  externalCivil: "chandrasekar.v@presidencyuniversity.in",
};

// --------------------------------------------------------------------- tiny PNG writer
const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buffer) {
  let c = 0xffffffff;
  for (const byte of buffer) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const typed = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typed));
  return Buffer.concat([length, typed, crc]);
}

/** A legible 240x80 signature stroke as a PNG data URL, distinct per account. */
export function signatureDataUrl(seed = "") {
  const width = 240;
  const height = 80;
  const offset = [...seed].reduce((sum, character) => sum + character.charCodeAt(0), 0) % 18;
  const rows = [];
  for (let y = 0; y < height; y += 1) {
    const row = Buffer.alloc(1 + width * 3, 255); // filter byte + white pixels
    row[0] = 0;
    const set = (x) => {
      if (x < 0 || x >= width) return;
      const at = 1 + x * 3;
      row[at] = 16; row[at + 1] = 24; row[at + 2] = 40;
    };
    // A slanted stroke and a baseline rule — different for every account.
    const stroke = 20 + offset + Math.round((y / height) * 120);
    for (let thickness = 0; thickness < 3; thickness += 1) set(stroke + thickness);
    if (y === height - 14) for (let x = 15; x < width - 20 - offset; x += 1) set(x);
    rows.push(row);
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // bit depth
  header[9] = 2; // truecolour
  const png = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", zlib.deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
  return `data:image/png;base64,${png.toString("base64")}`;
}

// --------------------------------------------------------------------- sessions
export class Session {
  constructor(context, email, csrf, user) {
    this.context = context;
    this.email = email;
    this.csrf = csrf;
    this.user = user;
  }

  async call(method, path, payload, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (this.csrf && method !== "GET") headers["X-CSRF-Token"] = this.csrf;
    const response = await this.context.fetch(path, {
      method,
      headers,
      data: payload === undefined ? undefined : JSON.stringify(payload),
    });
    const status = response.status();
    const text = await response.text();
    let body = {};
    try { body = text ? JSON.parse(text) : {}; } catch { body = { raw: text }; }
    return { status, body, text, headers: response.headers() };
  }

  /** Fetch a binary document (PDF) and return its bytes. */
  async raw(path) {
    const response = await this.context.fetch(path, { method: "GET" });
    const buffer = await response.body();
    return { status: response.status(), bytes: buffer, headers: response.headers() };
  }

  get(path) { return this.call("GET", path); }
  post(path, payload) { return this.call("POST", path, payload ?? {}); }

  /** POST that answers with a binary body. */
  async postRaw(path, payload) {
    const response = await this.context.fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(this.csrf ? { "X-CSRF-Token": this.csrf } : {}) },
      data: JSON.stringify(payload ?? {}),
    });
    return { status: response.status(), bytes: await response.body(), headers: response.headers() };
  }
}

/** Sign in over the API against a throwaway server that echoes the one-time code. */
export async function signIn(baseURL, email, { statePath } = {}) {
  const context = await request.newContext({ baseURL, ignoreHTTPSErrors: true });
  const requested = await context.post("/api/auth/request-code", { data: { email } });
  if (!requested.ok()) throw new Error(`request-code ${email}: ${requested.status()} ${await requested.text()}`);
  const { devCode } = await requested.json();
  const verified = await context.post("/api/auth/verify-code", { data: { email, code: devCode } });
  if (!verified.ok()) throw new Error(`verify-code ${email}: ${verified.status()} ${await verified.text()}`);
  const body = await verified.json();
  const session = new Session(context, email, body.csrfToken, body.user);
  if (statePath) await context.storageState({ path: statePath });
  return session;
}

/** Register a signature if the account has none — the app's own first-login gate. */
export async function ensureSignature(session) {
  const existing = await session.get("/api/signature/me");
  if (existing.status === 200 && existing.body?.signature?.image) return false;
  const posted = await session.post("/api/signature", { image: signatureDataUrl(session.email), method: "upload" });
  if (posted.status !== 200 && posted.status !== 409) {
    throw new Error(`signature ${session.email}: ${posted.status} ${posted.text}`);
  }
  return true;
}

/** A signed-in session rebuilt from a saved storage state (for cross-checks in specs). */
export async function sessionFromState(baseURL, statePath) {
  const context = await request.newContext({ baseURL, ignoreHTTPSErrors: true, storageState: statePath });
  const me = await context.get("/api/auth/me");
  if (!me.ok()) throw new Error(`saved session for ${statePath} is no longer valid: ${me.status()}`);
  const body = await me.json();
  return new Session(context, body.user.email, body.csrfToken, body.user);
}
