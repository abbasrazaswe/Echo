import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, allPages, allSessions, ApiError, errorText } from "./api";
import type { Profile, Session, Turn, Citation } from "./api";
import Tools from "./Tools";

export default function Workspace({
  profile,
  onBusy,
}: {
  profile: Profile;
  onBusy: (busy: boolean) => void;
}) {
  const base = `/profiles/${profile.id}`;
  const [sessions, setSessions] = useState<Session[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [remember, setRemember] = useState(false);
  const [tab, setTab] = useState<"sources" | "history" | "memory" | "import">(
    "sources",
  );
  const [citations, setCitations] = useState<Citation[]>([]);
  const [refresh, setRefresh] = useState(0);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    onBusy(busy || loading);
    return () => onBusy(false);
  }, [busy, loading, onBusy]);
  useEffect(() => {
    const controller = new AbortController();
    allSessions(`${base}/sessions`, controller.signal)
      .then((rows) => {
        setSessions(rows);
        const previous = localStorage.getItem(`echo.session.${profile.id}`);
        const initial =
          rows.find((row) => row.id === previous) ?? rows.at(-1) ?? null;
        setSession(initial);
        if (!initial) setLoading(false);
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setError(errorText(e));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [base, profile.id]);
  const sessionId = session?.id;
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    setLoading(true);
    setTurns([]);
    setCitations([]);
    setError("");
    setMessage("");
    setRemember(false);
    Promise.all([
      api<Session>(
        `${base}/sessions/${sessionId}`,
        undefined,
        "GET",
        controller.signal,
      ),
      allPages<Turn>(`${base}/sessions/${sessionId}/turns`, controller.signal),
    ])
      .then(([latest, rows]) => {
        setSession(latest);
        setTurns(rows);
        localStorage.setItem(`echo.session.${profile.id}`, sessionId);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [base, sessionId, profile.id]);
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [turns.length]);
  async function newSession() {
    setBusy(true);
    setError("");
    try {
      const next = await api<Session>(`${base}/sessions`, {
        title: `Chat ${sessions.length + 1}`,
      });
      setSessions([...sessions, next]);
      setSession(next);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function reloadSession() {
    const [latest, rows] = await Promise.all([
      api<Session>(`${base}/sessions/${sessionId}`),
      allPages<Turn>(`${base}/sessions/${sessionId}/turns`),
    ]);
    setSession(latest);
    setTurns(rows);
    setSessions((previous) =>
      previous.map((row) => (row.id === latest.id ? latest : row)),
    );
  }
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!session || !message.trim() || busy || loading) return;
    setBusy(true);
    setError("");
    let accepted = false;
    try {
      await api("/chat", {
        profile_id: profile.id,
        session_id: session.id,
        session_revision: session.revision,
        message: message.trim(),
        remember: remember ? [message.trim()] : [],
        allow_follow_up: true,
      });
      accepted = true;
      setMessage("");
      setRemember(false);
      setRefresh((value) => value + 1);
      await reloadSession();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        try {
          await reloadSession();
        } catch {
          /* Keep the original conflict visible. */
        }
      }
      setError(
        accepted
          ? "Your message was saved, but the view could not refresh. Reload this page before sending another message."
          : `${errorText(e)}${e instanceof ApiError && e.status === 409 ? " Review the refreshed conversation before trying again." : ""}`,
      );
      if (accepted) setLoading(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <header className="workspace-header">
        <div>
          <p className="eyebrow">YOUR WORKSPACE / {profile.name}</p>
          <h1>Conversations, with context.</h1>
        </div>
        <button className="secondary" onClick={() => setTab("import")}>
          ↥ Import transcript
        </button>
      </header>
      <div className="workspace-grid">
        <section className="chat-panel" aria-label="Chat">
          <div className="chat-toolbar">
            <label className="sr-only" htmlFor="session">
              Conversation
            </label>
            <select
              id="session"
              disabled={busy || loading || !sessions.length}
              value={sessionId ?? ""}
              onChange={(e) =>
                setSession(sessions.find((row) => row.id === e.target.value)!)
              }
            >
              {!sessions.length && (
                <option value="">No conversations yet</option>
              )}
              {sessions.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.title}
                </option>
              ))}
            </select>
            <button
              className="secondary"
              disabled={busy || loading}
              onClick={newSession}
            >
              + New chat
            </button>
          </div>
          <div
            className="turn-list"
            aria-live="polite"
            aria-busy={loading || busy}
          >
            {loading ? (
              <p className="empty">Loading conversation…</p>
            ) : !turns.length ? (
              <div className="chat-welcome">
                <span className="echo-mark">◖</span>
                <h2>A little history goes a long way.</h2>
                <p>
                  {session
                    ? "Ask about your imported conversations, or explicitly save something you want Echo to remember."
                    : "Start a new chat to ask questions and save memories."}
                </p>
                <div className="hint">
                  Try saving “I prefer studying in the evening” as a live
                  memory. This works without a model key.
                </div>
              </div>
            ) : (
              turns.map((turn) => (
                <article key={turn.id} className={`turn ${turn.role}`}>
                  <p className="speaker">
                    {turn.role === "user" ? "YOU" : "ECHO"}
                    {turn.status === "memory_saved" && " · MEMORY SAVED"}
                  </p>
                  <div className="turn-content">{turn.content}</div>
                  {turn.follow_up_question && (
                    <p className="follow-up">{turn.follow_up_question}</p>
                  )}
                  {(turn.citations.length > 0 ||
                    turn.live_citations.length > 0) && (
                    <button
                      className="source-link"
                      onClick={() => {
                        setCitations([
                          ...turn.citations,
                          ...turn.live_citations,
                        ]);
                        setTab("sources");
                      }}
                    >
                      Inspect{" "}
                      {turn.citations.length + turn.live_citations.length}{" "}
                      source(s) ↗
                    </button>
                  )}
                </article>
              ))
            )}
            {busy && (
              <p className="working" role="status">
                Working…
              </p>
            )}
            <div ref={bottom} />
          </div>
          {error && (
            <div className="notice error" role="alert">
              {error}
            </div>
          )}
          <form className="composer" onSubmit={send}>
            <label className="sr-only" htmlFor="message">
              Message
            </label>
            <textarea
              id="message"
              placeholder={
                session
                  ? "Ask a question about your conversations…"
                  : "Create a new chat to begin…"
              }
              maxLength={220}
              value={message}
              disabled={!session || busy || loading}
              onChange={(e) => setMessage(e.target.value)}
            />
            <div className="composer-bottom">
              <label className="remember">
                <input
                  type="checkbox"
                  checked={remember}
                  disabled={!session || busy || loading}
                  onChange={(e) => setRemember(e.target.checked)}
                />{" "}
                Save this message as live memory
              </label>
              <span className="count">{message.length}/220</span>
              <button
                className="primary"
                disabled={!session || busy || loading || !message.trim()}
              >
                {remember ? "Save memory" : "Send"} ↑
              </button>
            </div>
            <p className="composer-note">
              {remember
                ? "Saves your exact words locally. No model request is made."
                : "When configured, questions and selected context are sent to OpenAI. Replies can be wrong; inspect their sources."}
            </p>
          </form>
        </section>
        <aside className="inspector">
          <nav className="tabs" aria-label="Workspace tools">
            {(["sources", "history", "memory", "import"] as const).map(
              (item) => (
                <button
                  key={item}
                  aria-pressed={tab === item}
                  className={tab === item ? "active" : ""}
                  onClick={() => setTab(item)}
                >
                  {item === "history"
                    ? "Transcript"
                    : item[0].toUpperCase() + item.slice(1)}
                </button>
              ),
            )}
          </nav>
          <div className="inspector-body">
            {tab === "sources" ? (
              <>
                <p className="eyebrow">FOLLOW THE EVIDENCE</p>
                <h2>Where a reply comes from</h2>
                <p className="muted">
                  Select “Inspect sources” below a reply to see its quoted
                  evidence. Imported history and live memories stay distinct.
                </p>
                {citations.length ? (
                  citations.map((citation, index) => (
                    <div className="evidence" key={index}>
                      <span className="badge">
                        {citation.message_id
                          ? "Imported message"
                          : "Live memory"}
                      </span>
                      <blockquote>{citation.quote}</blockquote>
                      <p className="source-id">
                        {citation.message_id ?? citation.memory_id}
                      </p>
                      <p className="muted small">
                        Quoted at reply time. A live memory may since have been
                        retracted.
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="empty-card">
                    No reply selected yet.
                    <br />
                    Your sources will appear here.
                  </div>
                )}
              </>
            ) : (
              <Tools key={`${tab}-${refresh}`} tab={tab} base={base} />
            )}
          </div>
        </aside>
      </div>
    </>
  );
}
