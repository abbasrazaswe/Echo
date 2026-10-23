import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, allPages, errorText } from "./api";
import type { Memory, Message, Conversation, Page } from "./api";

export default function Tools({
  tab,
  base,
}: {
  tab: "history" | "memory" | "import";
  base: string;
}) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [dateOrder, setDateOrder] = useState("day-first");
  const [format, setFormat] = useState("whatsapp");
  const [speakers, setSpeakers] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const task =
      tab === "memory"
        ? allPages<Memory>(`${base}/live-memories`, controller.signal).then(
            setMemories,
          )
        : tab === "history"
          ? api<Page<Message>>(
              `${base}/messages?limit=30&offset=${offset}${search ? `&q=${encodeURIComponent(search)}` : ""}`,
              undefined,
              "GET",
              controller.signal,
            ).then((page) => {
              setMessages(page.items);
              setTotal(page.total);
            })
          : api<Conversation[]>(
              `${base}/conversations`,
              undefined,
              "GET",
              controller.signal,
            ).then(setConversations);
    task
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [tab, base, search, offset]);
  async function mutate(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await task();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function importFile(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    await mutate(async () => {
      // Avoid reading very large files into browser memory before server validation.
      if (file.size > 8_000_000)
        throw new Error(
          "Choose a text export under 8 MB (up to 2,000,000 characters).",
        );
      const transcript = await file.text();
      if (transcript.length > 2_000_000)
        throw new Error(
          "The export exceeds 2,000,000 characters. Split it into smaller exports.",
        );
      await api(`${base}/imports`, {
        title: title.trim(),
        ...(format === "whatsapp"
          ? { date_order: dateOrder }
          : {
              transcript_format: "speaker-labelled",
              speakers: speakers
                .split(/\r?\n/)
                .map((label) => label.trim())
                .filter(Boolean),
            }),
        transcript,
      });
      setConversations(await api<Conversation[]>(`${base}/conversations`));
      setNotice(
        "Transcript imported. Build the search index before asking about it.",
      );
    });
  }
  return (
    <>
      <p className="eyebrow">
        {tab === "import"
          ? "BRING YOUR HISTORY"
          : tab === "memory"
            ? "EXPLICITLY REMEMBERED"
            : "ORIGINAL CONVERSATIONS"}
      </p>
      <h2>
        {tab === "import"
          ? "Import a transcript"
          : tab === "memory"
            ? "Live memory"
            : "Browse the transcript"}
      </h2>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      {loading && <p role="status">Loading…</p>}
      {tab === "import" ? (
        <>
          <p className="muted">
            Choose a WhatsApp export or an undated transcript with standalone
            participant labels. Undated imports preserve file order; dates stay
            unknown.
          </p>
          <form className="stack" onSubmit={importFile}>
            <label>
              Transcript format
              <select
                value={format}
                disabled={busy}
                onChange={(e) => setFormat(e.target.value)}
              >
                <option value="whatsapp">WhatsApp export (dated)</option>
                <option value="speaker-labelled">
                  Speaker-labelled text (undated)
                </option>
              </select>
            </label>
            <label>
              Transcript title
              <input
                required
                maxLength={200}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={busy}
              />
            </label>
            <label>
              Transcript text file
              <input
                required
                type="file"
                accept=".txt,text/plain"
                disabled={busy}
                onChange={(e) => {
                  const selected = e.target.files?.[0] ?? null;
                  setFile(selected);
                  if (!title && selected)
                    setTitle(
                      selected.name.replace(/\.txt$/i, "").slice(0, 200),
                    );
                }}
              />
            </label>
            {format === "whatsapp" ? (
              <label>
                Date order
                <select
                  value={dateOrder}
                  onChange={(e) => setDateOrder(e.target.value)}
                  disabled={busy}
                >
                  <option value="day-first">Day first · 14/10/2026</option>
                  <option value="month-first">Month first · 10/14/2026</option>
                </select>
              </label>
            ) : (
              <>
                <label>
                  Participant labels (one per line, without colons)
                  <textarea
                    required
                    value={speakers}
                    disabled={busy}
                    onChange={(e) => setSpeakers(e.target.value)}
                  />
                </label>
                <p className="muted small">
                  Example: a line containing Sara: starts Sara’s message. Enter
                  every exact participant label above. Only those standalone
                  labels split messages; other lines remain message text. A
                  matching label inside a message is inherently ambiguous.
                </p>
              </>
            )}
            <button
              className="primary"
              disabled={
                busy ||
                !file ||
                !title.trim() ||
                (format !== "whatsapp" && !speakers.trim())
              }
            >
              {busy ? "Working…" : "Import transcript"}
            </button>
          </form>
          <div className="divider" />
          <h3>Make history searchable</h3>
          <p className="muted">
            Build again after each import. The first build downloads a local
            embedding model (~79 MB).
          </p>
          <button
            className="secondary full"
            disabled={busy || loading || !conversations.length}
            onClick={() =>
              mutate(async () => {
                const result = await api<{ chunks: number }>(
                  `${base}/memories/index`,
                  {},
                );
                setNotice(
                  `Search index ready: ${result.chunks} ${result.chunks === 1 ? "chunk" : "chunks"}.`,
                );
              })
            }
          >
            Build search index
          </button>
          <h3>Imported conversations</h3>
          {conversations.map((row) => (
            <div className="conversation-item" key={row.id}>
              <strong>{row.title}</strong>
              <span>{row.message_count} messages</span>
            </div>
          ))}
          {!loading && !conversations.length && (
            <p className="muted">No imports yet.</p>
          )}
        </>
      ) : tab === "memory" ? (
        <>
          <p className="muted">
            These are statements you chose to save. They are available across
            this profile’s chats. Retraction stops future use as evidence;
            earlier turns remain.
          </p>
          {!loading && !memories.length && (
            <div className="empty-card">
              No saved memories yet.
              <br />
              Use “Save this message as live memory” in chat.
            </div>
          )}
          {memories.map((memory) => (
            <article
              className={`memory-card ${memory.active ? "" : "retracted"}`}
              key={memory.id}
            >
              <span className="badge">
                {memory.active ? "Active · live" : "Retracted"}
              </span>
              <p>{memory.content}</p>
              <button
                className="source-link"
                disabled={busy}
                onClick={() =>
                  mutate(async () => {
                    const updated = await api<Memory>(
                      `${base}/live-memories/${memory.id}`,
                      { active: !memory.active },
                      "PATCH",
                    );
                    setMemories((rows) =>
                      rows.map((row) =>
                        row.id === updated.id ? updated : row,
                      ),
                    );
                  })
                }
              >
                {memory.active ? "Retract memory" : "Restore memory"}
              </button>
            </article>
          ))}
        </>
      ) : (
        <>
          <form
            className="search-form"
            onSubmit={(event) => {
              event.preventDefault();
              setOffset(0);
              setSearch(query.trim());
            }}
          >
            <label className="sr-only" htmlFor="search">
              Search transcript
            </label>
            <input
              id="search"
              placeholder="Search original words…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button className="secondary" disabled={loading}>
              Search
            </button>
          </form>
          <p className="muted small">
            {total} matching messages · keyword search
          </p>
          {messages.map((row) => (
            <article className="transcript-message" key={row.id}>
              <div className="message-heading">
                <strong>{row.speaker ?? "System notice"}</strong>
                <time>
                  {row.timestamp
                    ? new Date(row.timestamp).toLocaleDateString()
                    : "Date unknown"}
                </time>
              </div>
              <p>{row.text}</p>
              <span className="muted small">
                Source lines {row.source_line_start}–{row.source_line_end}
              </span>
            </article>
          ))}
          {!loading && !messages.length && (
            <div className="empty-card">No messages found.</div>
          )}
          <div className="pagination">
            <button
              className="secondary"
              disabled={loading || offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 30))}
            >
              Previous
            </button>
            <button
              className="secondary"
              disabled={loading || offset + 30 >= total}
              onClick={() => setOffset(offset + 30)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </>
  );
}
