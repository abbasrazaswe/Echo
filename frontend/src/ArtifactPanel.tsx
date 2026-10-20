import { useEffect, useState } from "react";
import { api, ApiError, errorText } from "./api";
import type { Conversation, Message, Page } from "./api";
import type {
  Artifact,
  ArtifactDetail,
  ArtifactKind,
  ArtifactStatus,
} from "./reviewTypes";

function Sources({ title, messages }: { title: string; messages: Message[] }) {
  return (
    <details open>
      <summary>
        {title} ({messages.length})
      </summary>
      {messages.map((message) => (
        <article className="transcript-message" key={message.id}>
          <strong>{message.speaker ?? "System"}</strong>
          <p>{message.text}</p>
          <p className="muted small">
            Source lines {message.source_line_start}–{message.source_line_end}
          </p>
          <p className="source-id">{message.id}</p>
        </article>
      ))}
      {!messages.length && <p className="muted">No linked messages.</p>}
    </details>
  );
}

export default function ArtifactPanel({
  base,
  onBusy,
}: {
  base: string;
  onBusy: (busy: boolean) => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [scope, setScope] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Artifact>>({ items: [], total: 0 });
  const [detail, setDetail] = useState<ArtifactDetail | null>(null);
  const [content, setContent] = useState("");
  const [sourceIds, setSourceIds] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty =
    !!detail &&
    (content !== detail.content ||
      sourceIds.split(/\s+/).filter(Boolean).join("\n") !==
        detail.source_message_ids.join("\n"));
  const path = `${base}/artifacts?limit=20&offset=${offset}${scope ? `&conversation_id=${encodeURIComponent(scope)}` : ""}${kind ? `&kind=${kind}` : ""}${status ? `&status=${status}` : ""}`;
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);
  useEffect(() => {
    const controller = new AbortController();
    api<Conversation[]>(
      `${base}/conversations`,
      undefined,
      "GET",
      controller.signal,
    )
      .then((rows) => {
        if (!controller.signal.aborted) setConversations(rows);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorText(e));
      });
    return () => controller.abort();
  }, [base]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setDetail(null);
    setPage({ items: [], total: 0 });
    setConflict(false);
    api<Page<Artifact>>(path, undefined, "GET", controller.signal)
      .then((rows) => {
        if (!controller.signal.aborted) setPage(rows);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path]);
  function accept(next: ArtifactDetail) {
    setDetail(next);
    setContent(next.content);
    setSourceIds(next.source_message_ids.join("\n"));
    setConflict(false);
  }
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await task();
    } catch (e) {
      setError(errorText(e));
      if (e instanceof ApiError && e.status === 409) setConflict(true);
    } finally {
      setBusy(false);
    }
  }
  async function review(nextStatus: Exclude<ArtifactStatus, "pending">) {
    if (!detail || busy || conflict) return;
    await run(async () => {
      const ids = [...new Set(sourceIds.split(/\s+/).filter(Boolean))];
      if (
        nextStatus === "corrected" &&
        (!content.trim() || !ids.length || ids.length > 100)
      )
        throw new Error(
          "A correction needs content and 1–100 source message IDs.",
        );
      const next = await api<ArtifactDetail>(
        `${base}/artifacts/${detail.id}`,
        {
          revision: detail.revision,
          status: nextStatus,
          ...(nextStatus === "corrected"
            ? { content: content.trim(), source_message_ids: ids }
            : {}),
        },
        "PATCH",
      );
      accept(next);
      setNotice(
        `Review saved: ${next.status}. Original transcript messages were not edited.`,
      );
      setPage(await api<Page<Artifact>>(path));
    });
  }
  return (
    <>
      <p className="eyebrow">REVIEW DERIVED RECORDS</p>
      <h2>Summaries & references</h2>
      <p className="muted">
        Local rules extract excerpts, participant labels, topics, and candidate
        events. Inspect the linked messages before reviewing. These records are
        not new historical facts.
      </p>
      {error && (
        <div role="alert" className="notice error">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="notice">
          {notice}
        </div>
      )}
      <div className="stack">
        <label>
          Conversation scope
          <select
            value={scope}
            disabled={busy || loading}
            onChange={(e) => {
              setScope(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All imported conversations</option>
            {conversations.map((row) => (
              <option key={row.id} value={row.id}>
                {row.title}
              </option>
            ))}
          </select>
        </label>
        <button
          className="secondary"
          disabled={busy || loading || !conversations.length}
          onClick={() =>
            run(async () => {
              const result = await api<{
                created: number;
                refreshed: number;
                preserved: number;
              }>(
                `${base}/artifacts/generate${scope ? `?conversation_id=${encodeURIComponent(scope)}` : ""}`,
                {},
              );
              setDetail(null);
              setConflict(false);
              setNotice(
                `Generation complete: ${result.created} created, ${result.refreshed} refreshed, ${result.preserved} reviewed records preserved.`,
              );
              setPage(await api<Page<Artifact>>(path));
            })
          }
        >
          Generate summaries & references
        </button>
      </div>
      <p className="muted small">
        Generation refreshes pending records and preserves reviewed records. No
        model call.
      </p>
      <div className="review-filters">
        <label>
          Record kind
          <select
            value={kind}
            disabled={busy || loading}
            onChange={(e) => {
              setKind(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All kinds</option>
            {(
              ["summary", "person", "event", "topic"] satisfies ArtifactKind[]
            ).map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Review status
          <select
            value={status}
            disabled={busy || loading}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All statuses</option>
            {(
              [
                "pending",
                "confirmed",
                "corrected",
                "rejected",
              ] satisfies ArtifactStatus[]
            ).map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
      </div>
      {loading ? (
        <p role="status">Loading records…</p>
      ) : (
        <>
          <p className="muted small">{page.total} records</p>
          {!page.items.length && (
            <div className="empty-card">
              No records in this view. Import a transcript and generate
              candidates, or change the filters.
            </div>
          )}
          <div className="artifact-list">
            {page.items.map((item) => (
              <button
                className={`artifact-choice ${detail?.id === item.id ? "selected" : ""}`}
                key={item.id}
                disabled={busy}
                aria-pressed={detail?.id === item.id}
                onClick={() =>
                  run(async () =>
                    accept(
                      await api<ArtifactDetail>(`${base}/artifacts/${item.id}`),
                    ),
                  )
                }
              >
                <span className="badge">
                  {item.kind} · {item.status}
                </span>
                <span>
                  {item.content.length > 160
                    ? `${item.content.slice(0, 160)}…`
                    : item.content}
                </span>
                {item.uncertain && (
                  <span className="muted small">Uncertain candidate</span>
                )}
              </button>
            ))}
          </div>
          <div className="pagination">
            <button
              className="secondary"
              disabled={busy || !offset}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Previous records
            </button>
            <button
              className="secondary"
              disabled={busy || offset + 20 >= page.total}
              onClick={() => setOffset(offset + 20)}
            >
              Next records
            </button>
          </div>
        </>
      )}
      {detail && (
        <section className="artifact-detail" aria-label="Selected record">
          <h3>Review {detail.kind}</h3>
          <p className="muted small">
            {detail.status} · revision {detail.revision} · {detail.method}
          </p>
          {detail.uncertain && (
            <div className="notice">
              Uncertain candidate. Confirm only what its sources support.
            </div>
          )}
          {conflict && (
            <div className="notice">
              This record changed elsewhere. Your edits are kept. Reload its
              latest revision before reviewing again.
            </div>
          )}
          <button
            className="secondary full"
            disabled={busy}
            onClick={() =>
              run(async () => {
                accept(
                  await api<ArtifactDetail>(`${base}/artifacts/${detail.id}`),
                );
                setNotice("Latest record loaded. Local edits were discarded.");
              })
            }
          >
            Reload latest record (discard edits)
          </button>
          <Sources
            title="Current linked source messages"
            messages={detail.sources}
          />
          <details>
            <summary>Original generated record</summary>
            <p className="turn-content">{detail.generated_content}</p>
            <Sources
              title="Original generated source messages"
              messages={detail.generated_sources}
            />
          </details>
          <div className="stack">
            <label>
              Reviewed content
              <textarea
                value={content}
                maxLength={10000}
                disabled={busy || conflict}
                onChange={(e) => setContent(e.target.value)}
              />
            </label>
            <label>
              Source message IDs (one per line)
              <textarea
                value={sourceIds}
                disabled={busy || conflict}
                onChange={(e) => setSourceIds(e.target.value)}
              />
            </label>
            <p className="muted small">
              Corrections use 1–100 original message IDs from this same
              conversation. The API validates their scope.
            </p>
            <button
              className="primary"
              disabled={
                busy || conflict || !content.trim() || !sourceIds.trim()
              }
              onClick={() => review("corrected")}
            >
              Save correction
            </button>
            <p className="muted small">
              Save your correction or reload the saved record before confirming
              or rejecting.
            </p>
            <div className="review-actions">
              <button
                className="secondary"
                disabled={busy || conflict || dirty}
                onClick={() => review("confirmed")}
              >
                Confirm saved record
              </button>
              <button
                className="secondary"
                disabled={busy || conflict || dirty}
                onClick={() => review("rejected")}
              >
                Reject saved record
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  );
}
