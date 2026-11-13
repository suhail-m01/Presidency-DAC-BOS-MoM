import { useEffect, useMemo, useState } from "react";

async function apiFetch(url, options = {}) {
  return fetch(url, { ...options, credentials: "same-origin" });
}

const ROLE_TABS = [
  ["faculty", "Faculty"],
  ["chair", "Chairpersons"],
  ["office", "Academic Office"],
  ["external", "External Members"],
  ["admin", "Administrator"],
];

function roleLabel(person) {
  if (person.role === "system_admin") return "System Administrator";
  if (person.role === "academic_office") return "Academic Office";
  if (person.externalMember) return "Faculty · External Member";
  return person.chairpersonEligible ? "Faculty · Chairperson eligible" : "Faculty";
}

// The directory stores "School of Engineering"; a bare "Engineering" is also possible.
// Adding the prefix unconditionally printed "School of School of …".
function schoolLabel(school) {
  const text = String(school || "").trim();
  if (!text) return "";
  return /^school of\b/i.test(text) ? text : `School of ${text}`;
}

export default function LoginScreen({ onAuthenticated }) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const [delivery, setDelivery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [requested, setRequested] = useState(false);
  const [roster, setRoster] = useState([]);
  const [rosterCounts, setRosterCounts] = useState(null);
  const [rosterTab, setRosterTab] = useState("faculty");
  const [rosterQuery, setRosterQuery] = useState("");
  const [devCode, setDevCode] = useState("");
  const [devCodeReason, setDevCodeReason] = useState("");
  const [showDirectory, setShowDirectory] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/directory/roster")
      .then(response => (response.ok ? response.json() : null))
      .then(data => {
        if (cancelled || !data) return;
        setRoster(data.accounts || []);
        setRosterCounts(data.counts || null);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // The person whose row was clicked. Showing name, department and position here means
  // the sign-in screen answers "who am I signing in as?" before a code is ever requested.
  const picked = useMemo(() => (
    roster.find(person => String(person.email || "").toLowerCase() === email.trim().toLowerCase()) || null
  ), [roster, email]);

  const visibleRoster = useMemo(() => {
    const needle = rosterQuery.trim().toLowerCase();
    return roster.filter(person => {
      const tabMatch =
        rosterTab === "chair" ? person.chairpersonEligible
        : rosterTab === "office" ? person.role === "academic_office"
        : rosterTab === "external" ? person.externalMember
        : rosterTab === "admin" ? person.role === "system_admin"
        : person.role === "faculty";
      if (!tabMatch) return false;
      if (!needle) return true;
      return [person.name, person.email, person.designation, person.school, person.department,
              person.employeeCode, person.specialization, person.qualification]
        .filter(Boolean).join(" ").toLowerCase().includes(needle);
    });
  }, [roster, rosterTab, rosterQuery]);

  function pickAccount(account) {
    setEmail(account);
    setRequested(false);
    setCode("");
    setMessage("");
    setDelivery("");
    setDevCode("");
    setDevCodeReason("");
    setError("");
  }

  async function requestCode(event) {
    event?.preventDefault();
    setBusy(true); setError(""); setMessage(""); setDelivery("");
    try {
      const response = await apiFetch("/api/auth/request-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not request a sign-in code.");
      setRequested(true);
      setMessage(data.message || "Check your inbox for a sign-in code.");
      setDelivery(data.delivery || "");
      // While no mail transport is configured the server hands the code back so it can
      // be read on screen — no trip to the terminal, no copy-paste.
      setDevCode(data.devCode || "");
      setDevCodeReason(data.devCodeReason || "");
      if (data.devCode) setCode(data.devCode);
    } catch (requestError) {
      setError(requestError.message || "The sign-in code request failed.");
    } finally {
      setBusy(false);
    }
  }

  async function verifyCode(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const response = await apiFetch("/api/auth/verify-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Sign-in failed.");
      onAuthenticated(data);
    } catch (authError) {
      setError(authError.message || "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-screen">
      <section className="login-brand-panel" aria-label="Presidency University campus">
        <img src="/ams-campus.webp" srcSet="/ams-campus.webp 1x, /ams-campus.jpg 1x" alt="Presidency University" className="login-campus-img" loading="eager" />
      </section>

      <section className="login-form-panel" id="signin">
        <div className="login-card">
          <div className="eyebrow">Welcome</div>
          <h2>Sign in for DAC & BOS Module</h2>
          <p className="login-subtitle">
            Use an email address that has been activated by the System Administrator.
          </p>

          {picked && (
            <div className="login-identity">
              <span className="login-identity-avatar" aria-hidden="true">
                {(picked.name || picked.email || "?").trim().slice(0, 1).toUpperCase()}
              </span>
              <div className="login-identity-body">
                <b className="login-identity-name">{picked.name}</b>
                <span className="login-identity-role">{picked.designation || roleLabel(picked)}</span>
                <span className="login-identity-meta">
                  {[picked.department, schoolLabel(picked.school), picked.employeeCode]
                    .filter(Boolean).join(" · ") || "College office"}
                </span>
                <span className="login-identity-tags">
                  <em>{roleLabel(picked)}</em>
                  {picked.chairpersonEligible && <em>Chairperson eligible</em>}
                  {picked.externalMember && <em>External Member</em>}
                  {picked.hasSignature
                    ? <em className="ok">Signature on file</em>
                    : <em className="warn">Signature to be recorded</em>}
                </span>
              </div>
              <button type="button" className="btn-text login-identity-clear"
                      onClick={() => { setEmail(""); setRequested(false); setCode(""); setMessage("");
                                       setDelivery(""); setDevCode(""); setDevCodeReason(""); setError(""); }}>
                Change
              </button>
            </div>
          )}

          {!requested ? (
            <form onSubmit={requestCode}>
              <label className="field"><span>College faculty email</span>
                <input autoComplete="email" type="email" required value={email}
                       onChange={event => setEmail(event.target.value.trimStart())}
                       placeholder="name@college.edu" />
              </label>
              <button className="btn btn-primary login-submit" type="submit" disabled={busy}>
                {busy ? "Requesting…" : "Email me a sign-in code →"}
              </button>
            </form>
          ) : (
            <form onSubmit={verifyCode}>
              <div className="login-address">Code requested for <b>{email}</b>
                <button className="btn-text" type="button"
                        onClick={() => { setRequested(false); setCode(""); setMessage(""); setDelivery(""); setDevCode(""); setDevCodeReason(""); }}>
                  Change
                </button>
              </div>
              {devCode && (
                <div className="otp-box" role="status" aria-label="Sign-in code shown on screen">
                  <div className="otp-box-head">
                    <span>Your sign-in code</span>
                    <b>Shown here because no mail server is configured yet</b>
                  </div>
                  <div className="otp-digits">{devCode.split("").map((digit, index) => <span key={`${digit}-${index}`}>{digit}</span>)}</div>
                  <div className="otp-box-foot">
                    <span>{devCodeReason || "Configure Microsoft 365 or SMTP and the code is emailed only."}</span>
                    <button type="button" className="btn-text" onClick={() => setCode(devCode)}>Use this code</button>
                  </div>
                </div>
              )}
              <label className="field"><span>Six-digit sign-in code</span>
                <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
                       onChange={event => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                       placeholder="000000" required />
              </label>
              <button className="btn btn-primary login-submit" type="submit"
                      disabled={busy || code.length !== 6}>
                {busy ? "Verifying…" : "Verify and continue →"}
              </button>
            </form>
          )}

          {message && (
            <div className="login-message">
              {message}
              {delivery === "console" && !devCode && (
                <div className="login-hint">Look in the terminal window running <code>python app.py</code>.</div>
              )}
            </div>
          )}
          {error && <div className="notice error login-error"><span className="notice-icon">!</span><span>{error}</span></div>}

          <div className="login-social-group">
            <div className="login-social-divider"><span>or continue with</span></div>
            <button type="button" className="login-social-btn" onClick={()=>{ setError(""); setMessage("Google federation can be enabled by the System Administrator (Microsoft 365 / Entra ID). Contact your administrator to enable SSO."); }}>
              <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.18 3.31v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.09Z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23Z"/><path fill="#FBBC05" d="M5.84 14.09A6.96 6.96 0 0 1 5.48 12c0-.72.13-1.42.36-2.09V7.07H2.18A11 11 0 0 0 1 12c0 1.78.42 3.45 1.18 4.93l3.66-2.84Z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53Z"/></svg>
              Sign in with Google
            </button>
            <button type="button" className="login-social-btn login-social-btn--microsoft" onClick={()=>{ setError(""); setMessage("Microsoft federation can be enabled by the System Administrator (Microsoft 365 / Entra ID). Contact your administrator to enable SSO."); }}>
              <span className="ams-ms" aria-hidden="true"><span style={{background:"#f25022"}}></span><span style={{background:"#7fba00"}}></span><span style={{background:"#00a4ef"}}></span><span style={{background:"#ffb900"}}></span></span>
              Sign in with Microsoft
            </button>
          </div>


          <div className="roster-panel" style={{marginTop: showDirectory ? "16px" : "10px"}}>
            <button type="button" onClick={()=>setShowDirectory(v=>!v)} style={{width:"100%", background:"none", border:0, padding:"8px 0 6px", color:"#187b74", fontSize:"11px", fontWeight:700, cursor:"pointer", textAlign:"center", textDecoration:"underline", textUnderlineOffset:"3px"}}>
              {showDirectory ? "Hide college directory ▲" : "Browse college directory — pick an account to fill User Name ▼"}
            </button>
            {showDirectory && (
            <>
            <div className="mini-label">
              College access directory
              {rosterCounts ? ` · ${rosterCounts.total} accounts · ${rosterCounts.faculty} faculty · ` +
                             `${rosterCounts.chairpersonEligible} chairperson-eligible · ` +
                             `${rosterCounts.externalMember} external members` : ""}
            </div>
            <input className="roster-search" type="search" value={rosterQuery}
                   onChange={event => setRosterQuery(event.target.value)}
                   placeholder="Search by name, email, department, staff ID…" />
            <div className="roster-tabs">
              {ROLE_TABS.map(([key, label]) => (
                <button type="button" key={key} onClick={() => setRosterTab(key)}
                        className={rosterTab === key ? "btn btn-primary btn-xs" : "btn btn-outline btn-xs"}>
                  {label}
                </button>
              ))}
            </div>
            <div className="roster-list">
              {visibleRoster.map(person => (
                <button type="button" className="roster-item" key={person.email}
                        onClick={() => pickAccount(person.email)}>
                  <span className="roster-avatar" aria-hidden="true">
                    {(person.name || person.email || "?").slice(0, 1).toUpperCase()}
                  </span>
                  <span className="roster-body">
                    <span className="roster-name">{person.name}</span>
                    {person.designation && <span className="roster-designation">{person.designation}</span>}
                    <b className="roster-email">{person.email}</b>
                    <small className="roster-meta">
                      {[roleLabel(person), schoolLabel(person.school),
                        person.department || "", person.employeeCode || ""]
                        .filter(Boolean).join(" · ")}
                    </small>
                    {person.externalMember && (person.externalFor || []).length > 0 && (
                      <small className="roster-meta roster-external">
                        External Member of {person.externalFor.join(", ")}
                      </small>
                    )}
                  </span>
                  <span className={person.hasSignature ? "roster-badge signed" : "roster-badge"}>
                    {person.hasSignature ? "Signature on file" : "No signature"}
                  </span>
                </button>
              ))}
              {roster.length === 0 && <small className="muted">Loading the directory…</small>}
              {roster.length > 0 && visibleRoster.length === 0 && (
                <small className="muted">No account matches “{rosterQuery}”.</small>
              )}
            </div>
            </>
            )}
          </div>
        </div>
        <div className="login-footnote">
          If your account is not active, ask the System Administrator to add and activate it in the
          access directory.
        </div>
      </section>
    </main>
  );
}
