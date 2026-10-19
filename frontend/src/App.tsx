import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, errorText } from "./api";
import type { Profile } from "./api";
import Workspace from "./Workspace";

export default function App() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api<Profile[]>("/profiles", undefined, "GET", controller.signal)
      .then((rows) => {
        setProfiles(rows);
        const previous = localStorage.getItem("echo.profile");
        setSelected(
          rows.find((row) => row.id === previous)?.id ?? rows[0]?.id ?? "",
        );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);
  async function createProfile(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const profile = await api<Profile>("/profiles", { name: name.trim() });
      setProfiles([...profiles, profile]);
      choose(profile.id);
      setName("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  function choose(id: string) {
    setSelected(id);
    localStorage.setItem("echo.profile", id);
  }
  return (
    <div className="app">
      <aside className="rail">
        <a className="brand" href="/" aria-label="Echo home">
          <span className="brand-icon">◖</span> echo
          <span className="brand-dot">.</span>
        </a>
        <p className="eyebrow">CONVERSATION WORKSPACE</p>
        <label className="rail-label" htmlFor="profile">
          Your profile
        </label>
        <select
          id="profile"
          value={selected}
          disabled={busy || loading || !profiles.length}
          onChange={(e) => choose(e.target.value)}
        >
          {!profiles.length && <option value="">No profiles yet</option>}
          {profiles.map((profile) => (
            <option key={profile.id} value={profile.id}>
              {profile.name}
            </option>
          ))}
        </select>
        <form onSubmit={createProfile} className="profile-form">
          <label htmlFor="profile-name">Create a profile</label>
          <div className="inline">
            <input
              id="profile-name"
              placeholder="Profile name"
              maxLength={100}
              value={name}
              disabled={busy || loading}
              onChange={(e) => setName(e.target.value)}
            />
            <button
              disabled={busy || loading || !name.trim()}
              aria-label="Create profile"
            >
              +
            </button>
          </div>
        </form>
        <div className="rail-note">
          <span className="status-dot" /> Local workspace
          <p>
            History gives context.
            <br />
            You decide what to remember.
          </p>
        </div>
        <a
          className="docs-link"
          href="http://127.0.0.1:8001/docs"
          target="_blank"
          rel="noreferrer"
        >
          Explore the API ↗
        </a>
      </aside>
      <main>
        {error && (
          <div className="notice error" role="alert">
            {error}{" "}
            <button onClick={() => window.location.reload()}>Reload</button>
          </div>
        )}
        {loading ? (
          <p className="empty" role="status">
            Opening your workspace…
          </p>
        ) : selected ? (
          <Workspace
            key={selected}
            profile={profiles.find((p) => p.id === selected)!}
            onBusy={setBusy}
          />
        ) : (
          <div className="welcome">
            <p className="eyebrow">A PLACE FOR YOUR CONVERSATIONS</p>
            <h1>
              Keep the context.
              <br />
              Continue the conversation.
            </h1>
            <p>
              Create your first profile in the sidebar, then import a WhatsApp
              text export or start by saving a new memory.
            </p>
            <div className="steps">
              <span>01 · Create a profile</span>
              <span>02 · Bring your history</span>
              <span>03 · Ask with context</span>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
