import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

// A render-time exception must never leave a blank page behind: the operator sees
// what broke and can copy the detail, and the app keeps working for everyone else.
class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error("DAC Minutes Studio failed to render:", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const detail = String((this.state.error && (this.state.error.stack || this.state.error.message)) || this.state.error);
    return (
      <div style={{ maxWidth: 720, margin: "12vh auto", padding: "0 20px", fontFamily: "system-ui, sans-serif", color: "#172b45" }}>
        <div style={{ border: "1px solid #e2c9c9", background: "#fdf5f5", borderRadius: 14, padding: "26px 28px" }}>
          <div style={{ fontSize: 11, letterSpacing: ".14em", textTransform: "uppercase", color: "#8c3b3b", fontWeight: 700 }}>
            Interface error
          </div>
          <h1 style={{ fontSize: 24, margin: "8px 0 10px" }}>This screen could not be drawn.</h1>
          <p style={{ margin: "0 0 14px", color: "#3c4a5b", lineHeight: 1.55 }}>
            The application is running, but the browser stopped while rendering the interface. Reload to
            try again; if it keeps happening, send the detail below to the administrator.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{ background: "#172b45", color: "#fff", border: 0, borderRadius: 8, padding: "10px 16px", fontWeight: 600, cursor: "pointer" }}
          >
            Reload the page
          </button>
          <pre style={{ marginTop: 18, maxHeight: 220, overflow: "auto", background: "#fff", border: "1px solid #e8dede", borderRadius: 8, padding: 12, fontSize: 12, whiteSpace: "pre-wrap" }}>
            {detail}
          </pre>
        </div>
      </div>
    );
  }
}

const container = document.getElementById("root");

if (!container) {
  document.body.innerHTML = "<p style=\"font-family:system-ui;padding:32px\">The page shell is missing its root element.</p>";
} else {
  createRoot(container).render(
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  );
}
