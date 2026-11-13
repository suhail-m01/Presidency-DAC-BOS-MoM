// Where the saved sessions and the fixture manifest live.
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname);
export const E2E_DIR = path.resolve(HERE, "..");
export const AUTH_DIR = path.join(E2E_DIR, ".auth");
export const FIXTURE_FILE = path.join(E2E_DIR, ".fixtures.json");

export function statePath(name) {
  return path.join(AUTH_DIR, `${name}.json`);
}
