import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError, errorText } from "./api";
import type { Conversation } from "./api";
import type { StyleRecord, StyleSettings, Evaluation } from "./reviewTypes";

const choices = {
  length: ["brief", "balanced", "detailed"],
  tone: ["neutral", "casual", "warm", "formal"],
  punctuation: ["standard", "light", "expressive"],
  emoji_usage: ["none", "occasional"],
  capitalization: ["standard", "mostly_lowercase"],
  language: ["match_user", "english", "urdu", "roman_urdu", "english_urdu_mix"],
} as const;
const labels = {
  length: "Reply length",
  tone: "Tone",
  punctuation: "Punctuation",
  emoji_usage: "Emoji use",
  capitalization: "Capitalization",
  language: "Language",
};
const human = (value: string) => value.replaceAll("_", " ");

export default function StylePanel({
  base,
  onBusy,
}: {
  base: string;
  onBusy: (busy: boolean) => void;
}) {
  const [record, setRecord] = useState<StyleRecord | null>(null);
  const [draft, setDraft] = useState<StyleSettings | null>(null);
  const [words, setWords] = useState("");
  const [speaker, setSpeaker] = useState("");
  const [scope, setScope] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [candidate, setCandidate] = useState("");
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);
  function accept(next: StyleRecord) {
    setRecord(next);
    setDraft(next.settings);
    setWords(next.settings.preferred_words.join(", "));
    setSpeaker(next.speaker ?? "");
    setScope(next.conversation_id ?? "");
    setEvaluation(null);
    setConflict(false);
  }
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api<StyleRecord>(`${base}/style`, undefined, "GET", controller.signal),
      api<Conversation[]>(
        `${base}/conversations`,
        undefined,
        "GET",
        controller.signal,
      ),
    ])
      .then(([next, rows]) => {
        if (!controller.signal.aborted) {
          accept(next);
          setConversations(rows);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [base]);
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
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!record || !draft || conflict || busy) return;
    await run(async () => {
      const preferred_words = words
        .split(",")
        .map((word) => word.trim())
        .filter(Boolean);
      if (
        preferred_words.length > 10 ||
        preferred_words.some((word) => word.length > 32)
      )
        throw new Error(
          "Use up to 10 individual words, each at most 32 characters.",
        );
      const next = await api<StyleRecord>(
        `${base}/style`,
        { revision: record.revision, settings: { ...draft, preferred_words } },
        "PATCH",
      );
      accept(next);
      setNotice(
        next.settings.enabled
          ? "Reviewed style saved and enabled for future model replies."
          : "Settings saved. Style is disabled.",
      );
    });
  }
  return (
    <>
      <p className="eyebrow">REVIEW HOW ECHO WRITES</p>
      <h2>Conversational style</h2>
      <p className="muted">
        Analyze one participant’s writing, then review the settings. Style
        changes presentation; original source quotes stay intact.
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
      {conflict && (
        <div className="notice">
          Your draft is kept. Another update changed the saved revision. Reload
          and review it before saving.
        </div>
      )}
      <button
        className="secondary full"
        disabled={busy || loading}
        onClick={() =>
          run(async () => {
            accept(await api<StyleRecord>(`${base}/style`));
            setNotice("Loaded saved settings. Local edits were discarded.");
          })
        }
      >
        Reload saved settings (discard draft)
      </button>
      {loading && <p role="status">Loading style…</p>}
      {record && draft && (
        <>
          <p className="muted small">
            Saved revision {record.revision} ·{" "}
            {record.settings.enabled ? "Enabled" : "Disabled"}
          </p>
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              if (busy || conflict) return;
              void run(async () => {
                const next = await api<StyleRecord>(`${base}/style/analyze`, {
                  revision: record.revision,
                  speaker: speaker.trim(),
                  ...(scope ? { conversation_id: scope } : {}),
                });
                // Analysis never replaces unsaved settings or enables style.
                setRecord(next);
                setEvaluation(null);
                setNotice(
                  "Analysis saved. Review the suggestions below; your settings draft is unchanged.",
                );
              });
            }}
          >
            <h3>1. Analyze a participant</h3>
            <label>
              Participant name
              <input
                required
                maxLength={200}
                placeholder="Exact speaker label, e.g. Sara"
                value={speaker}
                disabled={busy || conflict}
                onChange={(e) => setSpeaker(e.target.value)}
              />
            </label>
            <label>
              Analysis scope
              <select
                value={scope}
                disabled={busy || conflict}
                onChange={(e) => setScope(e.target.value)}
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
              disabled={
                busy || conflict || !speaker.trim() || !conversations.length
              }
            >
              Analyze writing
            </button>
          </form>
          {record.analysis_stale && (
            <div className="notice" role="status">
              Analysis is stale after imports. Analyze again to refresh the
              sample. Saved settings remain active.
            </div>
          )}
          {record.analysis && (
            <section className="analysis-summary" aria-label="Writing analysis">
              <h3>Sample: {record.speaker}</h3>
              <dl className="metrics">
                <div>
                  <dt>Messages</dt>
                  <dd>{record.analysis.metrics.message_count}</dd>
                </div>
                <div>
                  <dt>Mean words</dt>
                  <dd>{record.analysis.metrics.mean_words}</dd>
                </div>
                <div>
                  <dt>Emoji messages</dt>
                  <dd>
                    {Math.round(
                      record.analysis.metrics.emoji_message_rate * 100,
                    )}
                    %
                  </dd>
                </div>
              </dl>
              {record.analysis.sample_limited && (
                <p className="muted small">
                  Small sample (fewer than 20 usable messages). Suggestions may
                  be unreliable.
                </p>
              )}
              {record.analysis.sample_truncated && (
                <p className="muted small">
                  Analysis used a bounded sample, not the entire history.
                </p>
              )}
              <p className="muted small">
                Common words:{" "}
                {record.analysis.common_words
                  .map((item) => `${item.word} (${item.occurrences})`)
                  .join(", ") || "None"}
              </p>
              {!!record.analysis.common_phrases.length && (
                <details>
                  <summary>Repeated phrases and source IDs</summary>
                  {record.analysis.common_phrases.map((item) => (
                    <p className="small" key={item.phrase}>
                      {item.phrase} · {item.message_count} messages
                      <br />
                      <span className="source-id">
                        {item.source_message_ids.join(", ")}
                      </span>
                    </p>
                  ))}
                </details>
              )}
            </section>
          )}
          <form className="stack" onSubmit={save}>
            <h3>2. Review and save settings</h3>
            {record.suggested_settings && (
              <>
                <p className="muted small">
                  Suggested:{" "}
                  {Object.entries(record.suggested_settings)
                    .filter(([key]) => key !== "enabled")
                    .map(
                      ([key, value]) =>
                        `${human(key)}: ${Array.isArray(value) ? value.join(", ") || "none" : human(String(value))}`,
                    )
                    .join(" · ")}
                </p>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy || conflict}
                  onClick={() => {
                    const suggestion = record.suggested_settings!;
                    setDraft({ ...suggestion, enabled: draft.enabled });
                    setWords(suggestion.preferred_words.join(", "));
                    setNotice(
                      "Suggestions copied to the draft. Review and save to apply.",
                    );
                  }}
                >
                  Copy suggestions to draft
                </button>
              </>
            )}
            <label className="remember">
              <input
                type="checkbox"
                checked={draft.enabled}
                disabled={busy || conflict}
                onChange={(e) =>
                  setDraft({ ...draft, enabled: e.target.checked })
                }
              />
              Enable reviewed style for future replies
            </label>
            {(Object.keys(choices) as (keyof typeof choices)[]).map((key) => (
              <label key={key}>
                {labels[key]}
                <select
                  value={draft[key]}
                  disabled={busy || conflict}
                  onChange={(e) =>
                    setDraft({ ...draft, [key]: e.target.value })
                  }
                >
                  {choices[key].map((value) => (
                    <option key={value} value={value}>
                      {human(value)}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <label>
              Preferred words (comma separated)
              <input
                value={words}
                maxLength={340}
                disabled={busy || conflict}
                onChange={(e) => setWords(e.target.value)}
              />
            </label>
            <p className="muted small">
              Up to 10 individual words, not sentences or instructions.
            </p>
            <button className="primary" disabled={busy || conflict}>
              Save reviewed settings
            </button>
          </form>
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void run(async () => {
                setEvaluation(
                  await api<Evaluation>(`${base}/style/evaluate`, {
                    text: candidate.trim(),
                  }),
                );
              });
            }}
          >
            <h3>3. Check a sample reply locally</h3>
            <label>
              Sample reply
              <textarea
                required
                maxLength={4000}
                value={candidate}
                disabled={busy}
                onChange={(e) => {
                  setCandidate(e.target.value);
                  setEvaluation(null);
                }}
              />
            </label>
            <p className="muted small">
              Checks use the saved settings, not your unsaved draft. No model
              call or text storage.
            </p>
            <button className="secondary" disabled={busy || !candidate.trim()}>
              Check sample
            </button>
          </form>
          {evaluation && (
            <div className="analysis-summary" role="status">
              <h3>Checks · saved revision {evaluation.revision}</h3>
              {Object.entries(evaluation.checks).map(([key, passes]) => (
                <p className="small" key={key}>
                  {human(key)}: {passes ? "within setting" : "outside setting"}
                </p>
              ))}
              <p className="muted small">
                Preferred words present:{" "}
                {evaluation.preferred_words_present.join(", ") || "none"}. Not
                evaluated: {evaluation.not_evaluated.map(human).join(", ")}.
                These checks do not establish identity or factual accuracy.
              </p>
            </div>
          )}
        </>
      )}
    </>
  );
}
