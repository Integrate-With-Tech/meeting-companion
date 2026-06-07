"use client";

import Image from "next/image";
import { type FormEvent, useState } from "react";

const notes = [
  {
    title: "Executive revenue review",
    date: "Jun 6, 2026",
    source: "Teams native transcript",
    status: "Completed",
    upload: "SharePoint uploaded",
    locked: "Sign in to open notes",
  },
  {
    title: "Partner implementation sync",
    date: "Jun 5, 2026",
    source: "Uploaded transcript",
    status: "Processing",
    upload: "Pending",
    locked: "Sign in to view transcript",
  },
  {
    title: "Security rollout planning",
    date: "Jun 4, 2026",
    source: "Uploaded media",
    status: "Completed",
    upload: "SharePoint uploaded",
    locked: "Sign in to download exports",
  },
];

const readiness = [
  ["Graph permissions", "Ready"],
  ["Transcript access", "Ready"],
  ["SharePoint folder", "Ready"],
  ["OpenAI connectivity", "Ready"],
  ["Supabase connection", "Ready"],
  ["Webhook status", "Review"],
];

const timeline = [
  "Connect Microsoft account",
  "Invite Korieo Companion to Teams",
  "Capture native transcript or upload prior transcript",
  "Generate AI agenda, decisions, and action items",
  "Download Markdown/JSON or open SharePoint notes",
];

export default function Home() {
  const [authMode, setAuthMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [signedInEmail, setSignedInEmail] = useState("");
  const [supabaseUserId, setSupabaseUserId] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  const signedIn = Boolean(signedInEmail);
  const lockLabel = signedIn ? "Signed in" : "Locked until sign-in";

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedEmail = email.trim();
    if (!normalizedEmail || password.length < 8) {
      return;
    }
    setAuthError("");
    setActionMessage("");
    setAuthLoading(true);

    try {
      const response = await fetch("/api/auth/supabase", {
        body: JSON.stringify({
          displayName,
          email: normalizedEmail,
          mode: authMode,
          password,
        }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });
      const result = (await response.json()) as {
        error?: string;
        user?: {
          id: string;
          email?: string;
          displayName?: string;
        };
      };

      if (!response.ok || !result.user) {
        throw new Error(result.error || "Authentication failed.");
      }

      setSupabaseUserId(result.user.id);
      setSignedInEmail(result.user.email || normalizedEmail);
      setDisplayName(result.user.displayName || displayName);
      setActionMessage(
        authMode === "signup"
          ? "Account created in Supabase. Korieo Companion app controls are now available."
          : "Authenticated with Supabase. Korieo Companion app controls are now available."
      );
    } catch (error) {
      setAuthError(
        error instanceof Error ? error.message : "Authentication failed."
      );
    } finally {
      setAuthLoading(false);
    }
  }

  return (
    <main>
      <section className="hero-band">
        <nav className="topbar" aria-label="Primary navigation">
          <a className="brand" href="#workspace" aria-label="Korieo Companion">
            <Image
              className="brand-logo"
              src="/korieo-logo.svg"
              alt=""
              aria-hidden="true"
              width={38}
              height={38}
            />
            <span>Korieo Companion</span>
          </a>
          <div className="nav-links">
            <a href="#showcase">Showcase</a>
            <a href="#workflow">Workflow</a>
            <a href="#security">Security</a>
          </div>
          <a className="icon-button" href="#signin" aria-label="Sign in">
            <span aria-hidden="true">{"->"}</span>
          </a>
        </nav>

        <div className="hero-grid" id="workspace">
          <div className="hero-copy">
            <p className="eyebrow">Korieo Companion showcase</p>
            <h1>AI meeting notes for Microsoft Teams, gated by sign-in.</h1>
            <p className="lede">
              Explore how Korieo Companion connects Teams transcripts,
              uploaded prior-meeting files, Whisper transcription, AI
              summarization, and SharePoint delivery. Product actions unlock
              only after the user signs in.
            </p>
            <div className="hero-actions">
              <a className="primary-action" href="#signin">
                Sign in or sign up
              </a>
              <a className="secondary-action" href="#showcase">
                View showcase
              </a>
            </div>
          </div>

          <div className="product-visual" aria-label="Meeting notes preview">
            <div className="visual-header">
              <span>Product preview</span>
              <strong>Signed-in workspace</strong>
            </div>
            <div className="visual-panel">
              <div className="meeting-row active">
                <span className="status-dot" />
                <div>
                  <strong>Executive revenue review</strong>
                  <small>Native Teams transcript ingested</small>
                </div>
                <span className="row-state">Preview only</span>
              </div>
              <div className="visual-transcript">
                <span>00:12:08</span>
                <p>
                  Dana: Confirm renewal owners and capture risks before Friday.
                </p>
              </div>
              <div className="summary-columns">
                <div>
                  <span>Decisions</span>
                  <strong>3</strong>
                </div>
                <div>
                  <span>Action items</span>
                  <strong>7</strong>
                </div>
                <div>
                  <span>Artifacts</span>
                  <strong>4</strong>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="section-band account-band" id="signin">
        <div className="section-shell account-grid">
          <div>
            <p className="eyebrow">Sign-in gate</p>
            <h2>App functions stay unavailable until identity is confirmed.</h2>
            <p>
              The existing service records sign-in audit events, user profiles,
              and Microsoft connection rows so notes access can stay scoped to
              the signed-in owner or tenant admin.
            </p>
          </div>
          <form
            className="signin-panel"
            id="showcase"
            onSubmit={handleAuthSubmit}
          >
            <span className={signedIn ? "success-pill" : "lock-pill"}>
              {signedIn ? "Authenticated" : "Authentication required"}
            </span>
            {signedIn ? (
              <>
                <div className="account-status">
                  <strong>{displayName.trim() || signedInEmail}</strong>
                  <span>{signedInEmail}</span>
                  <small>Supabase user: {supabaseUserId}</small>
                </div>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => {
                    setSignedInEmail("");
                    setSupabaseUserId("");
                    setPassword("");
                    setActionMessage("Signed out. App controls are locked.");
                  }}
                >
                  Sign out
                </button>
              </>
            ) : (
              <>
                <div className="auth-mode-row" aria-label="Authentication mode">
                  <button
                    type="button"
                    className={authMode === "signin" ? "mode-active" : ""}
                    onClick={() => setAuthMode("signin")}
                  >
                    Existing account
                  </button>
                  <button
                    type="button"
                    className={authMode === "signup" ? "mode-active" : ""}
                    onClick={() => setAuthMode("signup")}
                  >
                    New account
                  </button>
                </div>
                {authMode === "signup" ? (
                  <label>
                    Full name
                    <input
                      type="text"
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                      placeholder="Alex Morgan"
                    />
                  </label>
                ) : null}
                <label>
                  Work email
                  <input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="name@company.com"
                    required
                  />
                </label>
                <label>
                  Password
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="At least 8 characters"
                    minLength={8}
                    required
                  />
                </label>
                <label>
                  Product access
                  <input
                    type="text"
                    value="Korieo bot, uploads, notes, transcripts"
                    readOnly
                  />
                </label>
                <button type="submit" disabled={authLoading}>
                  {authLoading
                    ? "Connecting..."
                    : authMode === "signup"
                      ? "Create account"
                      : "Sign in"}
                </button>
              </>
            )}
            {authError ? (
              <p className="auth-error" role="alert">
                {authError}
              </p>
            ) : null}
            <p className="form-note">
              Microsoft Teams access is connected after authentication.
            </p>
          </form>
        </div>
      </section>

      <section className="section-band" id="workflow">
        <div className="section-shell two-column">
          <div className={`workflow-panel ${signedIn ? "" : "locked-panel"}`}>
            <div className="panel-heading">
              <p className="eyebrow">Meeting bot preview</p>
              <h2>Signed-in users can invite Korieo Companion to Teams.</h2>
            </div>
            <div className="invite-box">
              <span className={signedIn ? "success-pill" : "lock-pill"}>
                {lockLabel}
              </span>
              <label>
                Teams meeting link
                <input
                  type="text"
                  value="https://teams.microsoft.com/l/meetup-join/..."
                  readOnly
                  disabled={!signedIn}
                />
              </label>
              <label>
                Capture mode
                <select defaultValue="native" disabled={!signedIn}>
                  <option value="native">Native Teams transcript first</option>
                  <option value="bot">Visible bot fallback if enabled</option>
                </select>
              </label>
              <button
                type="button"
                disabled={!signedIn}
                onClick={() =>
                  setActionMessage(
                    "Bot invitation staged for the Teams meeting preview."
                  )
                }
              >
                Invite bot
              </button>
            </div>
          </div>
          <div className="audit-list">
            {timeline.map((item, index) => (
              <div className="audit-row" key={item}>
                <span>{index + 1}</span>
                <p>{item}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section-band upload-band" id="upload">
        <div className="section-shell upload-grid">
          <div>
            <p className="eyebrow">Prior meetings preview</p>
            <h2>Transcript uploads are shown here, but require sign-in.</h2>
            <p>
              Uploaded transcripts become source artifacts for the same notes
              generation path used by Teams-native artifacts. Uploaded media is
              routed through the existing Whisper pipeline before notes are
              produced.
            </p>
          </div>
          <div className={`upload-panel ${signedIn ? "" : "locked-panel"}`}>
            <label className="drop-zone">
              <input
                type="file"
                accept=".txt,.vtt,.srt,.md,.json"
                disabled={!signedIn}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) {
                    setActionMessage(
                      `${file.name} selected for transcript upload preview.`
                    );
                  }
                }}
              />
              <strong>
                {signedIn
                  ? "Choose a transcript file"
                  : "Sign in to upload a transcript"}
              </strong>
              <span>Preview supports Teams VTT, plain transcript, SRT, Markdown</span>
            </label>
            <div className="processing-rail">
              <span>Parse speakers</span>
              <span>Generate notes</span>
              <span>Track SharePoint upload</span>
            </div>
          </div>
        </div>
      </section>

      <section className="section-band" id="notes">
        <div className="section-shell">
          <div className="section-title-row">
            <div>
              <p className="eyebrow">Notes history preview</p>
              <h2>Meeting notes and transcripts are private after sign-in.</h2>
            </div>
            <div className="filter-pills" aria-label="Available filters">
              <span>Date</span>
              <span>Organizer</span>
              <span>Status</span>
              <span>Source</span>
              <span>Upload</span>
            </div>
          </div>

          <div className="notes-grid">
            {notes.map((note) => (
              <article className="note-card" key={note.title}>
                <div className="note-topline">
                  <span>{note.date}</span>
                  <strong>{note.status}</strong>
                </div>
                <h3>{note.title}</h3>
                <p>{note.source}</p>
                <div className="note-actions">
                  <button
                    type="button"
                    disabled={!signedIn}
                    onClick={() =>
                      setActionMessage(`${note.title} notes opened in preview.`)
                    }
                  >
                    Open notes
                  </button>
                  <button
                    type="button"
                    disabled={!signedIn}
                    onClick={() =>
                      setActionMessage(`${note.title} transcript opened in preview.`)
                    }
                  >
                    Transcript
                  </button>
                  <button
                    type="button"
                    disabled={!signedIn}
                    onClick={() =>
                      setActionMessage(`${note.title} JSON export prepared.`)
                    }
                  >
                    Download JSON
                  </button>
                </div>
                <small>
                  {note.upload} - {signedIn ? "Available" : note.locked}
                </small>
              </article>
            ))}
          </div>
          {actionMessage ? (
            <div className="action-message" role="status">
              {actionMessage}
            </div>
          ) : null}
        </div>
      </section>

      <section className="section-band readiness-band" id="security">
        <div className="section-shell readiness-grid">
          <div>
            <p className="eyebrow">Admin readiness preview</p>
            <h2>Operational setup is visible only to authenticated admins.</h2>
            <p>
              The documented readiness checklist covers Graph permissions,
              transcript access, SharePoint folder access, OpenAI connectivity,
              Supabase, and webhook status.
            </p>
          </div>
          <div className="readiness-table">
            {readiness.map(([name, state]) => (
              <div className="readiness-row" key={name}>
                <span>{name}</span>
                <strong className={state === "Ready" ? "ready" : "review"}>
                  {state}
                </strong>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
