# Echo backend — development walkthrough

Echo runs a local HTTP server, parses WhatsApp exports, stores imported
messages in SQLite, and retrieves passages by meaning with local embeddings.
It also generates reviewable extractive summaries and reference candidates.
These features run locally without an API key. The sixth checkpoint adds
provider-backed grounded chat, which requires local configuration for real replies.
The seventh adds persistent sessions and explicit live memory. Saving memories and
browsing sessions work locally; provider-generated follow-up replies still require configuration.
The eighth adds local style analysis and reviewed presentation settings for replies.

## Setup (macOS/Linux)

From the repository root:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The virtual environment keeps this project's Python packages separate from
other projects. Activate it again whenever you open a new terminal.

## Run

From `backend`, with the virtual environment active:

```sh
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Open <http://127.0.0.1:8001/health>. The response should be:

```json
{"status": "ok"}
```

Open <http://127.0.0.1:8001/docs> to explore and call the endpoint interactively.
Stop the server with **Ctrl+C**. A request to `/` returns 404 because no root
page is defined; use `/health` or `/docs`.

We use port 8001 because another local process was already using 8000 during
setup. If 8001 is occupied, choose another port and update the browser URL.

## Understand the code

- `app/__init__.py` marks `app` as a Python package.
- `app/main.py` creates the FastAPI application and defines its first route.
- `@app.get("/health")` connects an HTTP GET request at `/health` to `health()`.
- `health()` returns a Python dictionary, which FastAPI serializes as JSON.
- `dict[str, str]` describes the return value's key and value types.
- `async def` defines a coroutine that FastAPI can await when handling a request.
- `app.main:app` tells Uvicorn to load the `app` object from `app/main.py`.
- `--reload` restarts the development server when Python files change.
- `127.0.0.1` makes the server accessible only on this computer.

The health response confirms that the server can handle a request. It does not
query the database or check an AI provider. Database storage is covered in the
third checkpoint below; the sixth checkpoint covers the separate chat provider.

## Second checkpoint: WhatsApp transcript parsing

From `backend`, activate the virtual environment and run the fictional sample:

```sh
source .venv/bin/activate
python -m app.parser tests/fixtures/whatsapp_sample.txt --date-order day-first --output data/profiles/default/processed/sample.json
```

Open the output JSON to inspect four records: a system notice and three messages.
Sara's two-line message remains one record. The output folder is excluded from
Git because real imports and derived files may contain private conversations.
The parser refuses to overwrite an existing output; choose a fresh output path
when running again.

For your own export, put the `.txt` file in
`data/profiles/default/raw/` and replace the sample path in the command.
Use `--date-order month-first` for exports where `04/05/2026` means April 5.
Use `day-first` where it means May 4. Two-digit years use Python's convention:
00–68 mean 2000–2068, and 69–99 mean 1969–1999.

Supported headers include:

```text
14/10/2026, 09:01 - Ali: Hello
[14/10/2026, 9:01:00 PM] Ali: Hello
```

The parser supports 12- and 24-hour time, optional seconds, two- or four-digit
years, and slash, dot, or hyphen date separators. It preserves file order,
Unicode text, multiline content, media placeholders, and timestamped notices.
Each record contains the original text block and source line numbers for review.
Line endings are normalized to newlines. Timestamps have no timezone because the
export does not provide one.

Unreadable headers, invalid dates, and nonblank text before the first message
produce errors with line numbers. An arbitrary continuation line is retained as
message text. A pasted line that looks exactly like an export header is ambiguous
and will begin a new record. Sender detection uses the first `: ` separator;
names containing that separator and system notices containing it need review.
These are common-format rules, not a guarantee for every WhatsApp locale.
We should validate a redacted real sample before importing your full history.

The parser can run independently from the terminal. The third checkpoint also
uses it when importing transcript text through the HTTP API.

### Parser tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The tests exercise message boundaries, date ambiguity, Unicode, system notices,
invalid input, JSON export, and protection against overwriting source files.

## Third checkpoint: persistent conversations

Install the updated requirements and restart the server before trying these
endpoints. The SQLite file is created automatically at
`backend/data/profiles/echo.db`, independent of the launch directory. This
checkpoint uses that fixed local path. Startup now loads LLM configuration from
`backend/.env`; database and embedding paths remain fixed.
One database holds all profiles, with queries scoped to the selected profile.
The database and imported data are excluded from Git.

### Try it in the interactive docs

1. Open <http://127.0.0.1:8001/docs>.
2. Expand `POST /profiles`, click **Try it out**, and submit
   `{"name": "Learning profile"}`. Copy the returned `id`.
3. Expand `POST /profiles/{profile_id}/imports`. Paste the profile ID into the
   path field and submit this body:

   ```json
   {
     "title": "Python discussion",
     "date_order": "day-first",
     "transcript": "14/10/2026, 09:01 - Ali: Shall we study Python?\n14/10/2026, 09:02 - Sara: Yes, let's start with functions."
   }
   ```

4. Use `GET /profiles/{profile_id}/messages` with that profile ID. Set `q` to
   `functions` to find Sara's message. Leave optional fields unset for all messages.
5. Repeat the import: HTTP **409** means it was already saved. No duplicates
   are added. Restart the server and browse again to confirm the data persists.
6. Use the conversation `id` returned by the import to call
   `GET /profiles/{profile_id}/conversations/{conversation_id}/export`.
   It returns all records as JSON, including stable message IDs and source text.

### What the database does

- A **profile** groups a dataset. Profile names need not be unique; IDs are unique.
- A **conversation** represents one import, with its title, date order, source
  fingerprint, message count, and time range.
- A **message** stores the parsed fields plus a stable ID and conversation ID.
- A **transaction** commits the conversation and all its messages together;
  any failure rolls the import back.
- A **unique constraint** prevents the same source fingerprint from being
  imported twice into a profile, including under concurrent requests.

Duplicate detection ignores BOM and newline-style differences. It detects
repeated whole transcripts, not partially overlapping exports. Changing the
date-order selection does not bypass duplicate detection; there is no correction
or deletion API yet. Source messages have no edit endpoint.

`GET /profiles` lists profiles, and `GET /profiles/{profile_id}/conversations`
lists their imports. Message browsing supports `limit` (1–200), `offset`, an
optional `conversation_id`, and `q` for literal substring search in message text.
SQLite's default case-insensitive matching handles ASCII letters; this is not
semantic or multilingual case-folded search. Within each conversation, messages
are returned in original export order. Export returns a full conversation and
is intended for small local datasets at this stage.

Invalid input returns HTTP 422; missing profiles/conversations return 404.
Import accepts transcript text in JSON, up to 2,000,000 characters. File upload,
authentication, and remote deployment are later work. Keep the server bound to
`127.0.0.1` until access controls are added. Historical imports remain separate
from live chat memory stored in separate tables by the seventh checkpoint.

Run `python -m pytest -q` for the parser and API/storage checks, including
restart persistence, profile isolation, rollback, duplicates, and export fidelity.

## Fourth checkpoint: semantic retrieval

Keyword search matches characters in a message. Semantic retrieval turns both
passages and questions into **embeddings** (numeric vectors), then ranks nearby
vectors in ChromaDB. It returns historical passages, not a generated AI reply.

Install the updated `requirements.txt` and restart the server. In `/docs`:

1. Import one or more conversations into a profile.
2. Run `POST /profiles/{profile_id}/memories/index` for that profile.
3. Run `GET /profiles/{profile_id}/memories/search` with a question in `q`, such
   as `What are our plans for learning to code?` for the Python sample.
4. Inspect each hit's `text`, `score`, `messages`, and `spans`. A span points
   to a message ID and zero-based, end-exclusive character offsets in its text.
   Original source line numbers remain available in the returned messages.

Search accepts `q` (1–220 characters, nonblank), `limit` (1–20, default 5), and
`min_score` (0–1, default 0.2). Score is cosine similarity clipped to 0–1;
it is not a probability or factual confidence. A stricter threshold may remove
weak results, including relevant ones. Semantic search does not replace checking
the retrieved text before making historical claims.

### Index and model lifecycle

- SQLite messages remain authoritative. Embedding vectors are stored separately
  in `backend/data/profiles/chroma/`, with a snapshot pointer in SQLite.
- Each chunk groups up to three nearby messages within one conversation and is
  bounded to 220 characters, including speaker labels. Long messages split into
  adjacent segments with source offsets. System notices and recognised media-only
  placeholders are excluded; media contents are not understood.
- The embedding interface allows another provider later. This version uses
  Chroma's ONNX `all-MiniLM-L6-v2` model with short inputs and batches of 32.
  It is primarily an English model; multilingual retrieval quality is unverified.
- The first nonempty index build downloads the model archive (about 79 MB).
  Files are cached at `backend/data/profiles/models/all-MiniLM-L6-v2/`.
  No transcript text is sent to an embedding API. Chroma telemetry is disabled.
- The model and Chroma client load only when needed. Normal imports, keyword
  search, and health checks work without downloading a model.
- Index builds are explicit and synchronous. A complete new snapshot is published
  only after all embedding batches are saved. A failed build leaves the previous
  snapshot selected; partial vector data is cleaned up on a best-effort basis.
- Every rebuild reads the source records again. Adding an import makes the index
  stale. Missing/stale indexes or changed embedding models return 409 until rebuilt.
  A failure to load the model or vector store returns 503, with details in server logs.
- An empty or system-only profile can be indexed and returns no hits without a
  model download. Profile IDs scope index contents and returned source records.
- Successful older snapshots are retained so concurrent readers can finish.
  Automatic cache pruning is not implemented; repeated rebuilds consume disk.
  The index is derived data and can be rebuilt from SQLite. Do not delete the
  source database when clearing vector/model caches.

If a slow connection interrupts the model download, indexing returns 503. Retry
after checking connectivity; the model archive is checksum-verified by Chroma.
Keep this service on localhost: authentication and background indexing jobs are
not part of this checkpoint.

### Verify real-model ranking

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m scripts.evaluate_retrieval
```

The default test suite uses fake embeddings to test retrieval mechanics without
network access. The separate evaluation uses the real model, fictional restaurant,
airport, and programming conversations, and three paraphrased questions. It uses
a temporary database while retaining the local model cache. Passing those three
cases is a smoke check; representative conversation/language evaluation remains
necessary before relying on retrieval for generated answers.

## Fifth checkpoint: summaries and structured references

These features use local deterministic rules and require no model download.
They create derived artifacts in a new SQLite table, leaving imported records
and the semantic index unchanged. The table is added automatically at startup;
existing profiles and conversations are retained.

### Try generation and review

1. In `/docs`, choose an existing profile or import this fictional transcript:

   ```json
   {
     "title": "Study plans",
     "date_order": "day-first",
     "transcript": "14/10/2026, 09:01 - Ali: Shall we study Python tomorrow?\n14/10/2026, 09:02 - Sara: Yes, Python practice sounds useful.\n14/10/2026, 09:03 - Ali: Our meeting is tomorrow at the library."
   }
   ```

2. Run `POST /profiles/{profile_id}/artifacts/generate`. Optionally set
   `conversation_id` to process only that import. The result reports `created`,
   `refreshed`, and `preserved` counts.
3. Run `GET /profiles/{profile_id}/artifacts`. Filter by `kind` (`summary`,
   `person`, `event`, `topic`) or review `status`. Pagination uses `limit` (1–200)
   and `offset` (0 or greater).
4. Inspect an artifact using `GET /profiles/{profile_id}/artifacts/{artifact_id}`.
   `sources` contains the current citations' full messages and source line numbers;
   `generated_sources` contains the original generated citations' messages.
5. PATCH that artifact with its latest revision, for example:

   ```json
   {"revision": 1, "status": "corrected", "content": "Plans to study Python and meet at the library."}
   ```

6. Generate again. The correction, its ID, and its reviewed status are preserved.
   Pending artifacts are refreshed; new conversations receive new artifacts.

### What is generated

- **Summaries:** divide the original ordered records into groups of 20, exclude
  system notices, blank messages and recognised media-only placeholders, and
  choose up to three distinct message texts using recurring vocabulary. Selected
  excerpts appear in original order. At most 500 characters from each message
  are quoted, with explicit markers for omitted text. This can omit important
  details; it is a compact extract, not a comprehensive or abstractive summary.
- **People:** speaker labels from the export, including source message IDs.
  A label is not a verified real-world identity. Mentions of new people inside
  message bodies are not resolved or automatically linked to participants.
- **Topics:** up to five candidate keywords per conversation, ranked by the
  number of messages using a term after English stopword filtering.
- **Events:** messages containing English cues such as meeting, appointment,
  exam, flight or trip. The excerpt includes the matched cue. A mention may
  describe a proposal, denial, past event or hypothetical situation; no event
  occurrence or calendar date is inferred.

The method is labelled `extractive-rules-v1`. These rules are inspectable and
reproducible; language-specific extraction and model-written summaries remain
future work. System-only conversations produce no artifacts.

### Review rules and provenance

All generated artifacts begin `pending`. References carry `uncertain=true`,
whereas summary excerpts carry `uncertain=false` because their text is extracted
directly; this does not establish that claims made by the speaker are true.
Uncertainty describes the generation method and stays unchanged after review.

Use `confirmed` or `rejected` without supplying edits. Use `corrected` with
`content`, `source_message_ids`, or both. Corrected citations must be nonempty
and belong to the artifact's conversation. IDs from another conversation or
profile are rejected with 422. Source links validate provenance membership;
the server cannot prove that a human-written correction is supported by them.

Each PATCH requires the current `revision`, increments it on success, and returns
409 for a stale edit. Regeneration also increments revisions on refreshed pending
records. Reviewed records, including rejected ones, are protected from automatic
regeneration. Original generated content and source IDs remain available alongside
the latest correction. Intermediate edit history is not stored.

Generation is synchronous and transactional. Failures roll back the generated
batch. Missing profiles/artifacts return 404. The endpoints inherit the existing
localhost-only development setup and have no authentication yet.

These artifacts are review data and are not automatically embedded. The sixth
checkpoint uses eligible reviewed summaries as hints alongside retrieved messages.
Run
`python -m pytest -q` to verify generation, evidence inspection, correction,
review persistence, conflict handling, and transaction rollback.

## Sixth checkpoint: LLM integration and RAG

The flow is question → semantic retrieval → bounded prompt → model reply →
source validation. `app/llm.py` defines the provider interface and an OpenAI
Responses API adapter. `app/chat.py` selects prompt context and validates citations.
`app/prompts/grounded_chat.txt` contains the grounding and uncertainty instructions.

### Configure and ask a question

Edit `backend/.env` using `.env.example` as a guide. Set `OPENAI_API_KEY` and
`LLM_MODEL` locally; do not put credentials in a request body or commit them.
The selected model must support Responses API Structured Outputs and be available
to your API project. No default model is selected. Restart after configuration
changes. Process environment variables override file values; file loading does
not mutate the process environment.

Optional settings are `LLM_PROVIDER=openai`, `LLM_TIMEOUT_SECONDS=20` (1–60),
and `LLM_MAX_OUTPUT_TOKENS=1600` (256–4096). These settings are validated at
startup; invalid values must be corrected before the app can start. Missing keys
do not prevent startup or local features, but provider-backed answers return 503.
Database and embedding paths are still fixed; legacy `DATABASE_URL` and
`EMBEDDING_MODEL` variables are not read.

After importing and indexing a profile, open `/docs` and submit `POST /chat`:

```json
{
  "profile_id": "your-profile-id",
  "message": "What were our plans for learning to code?",
  "recent_turns": [],
  "min_score": 0.3
}
```

The current request requires a nonblank question of 1–220 characters. It retrieves
at most five passages. `min_score` is a similarity cutoff between 0 and 1, not a
confidence threshold. Missing/stale indexes return 409; nonexistent profiles
return 404. Build/rebuild the profile's index through the existing index endpoint.

### Context and evidence boundaries

- Only selected source spans are sent as historical evidence, with message IDs,
  speaker labels and timestamps. Full messages may be returned in debug `context`,
  but hidden text outside those spans cannot validate a model citation.
- `recent_turns` accepts up to eight turns with roles `user` or `assistant`, each
  containing 1–1,000 characters. The latest complete turns fitting a 4,000-character
  content budget are retained. `history_trimmed` reports whether older turns were
  omitted. Client-supplied history is not an authenticated historical record.
- Up to three confirmed/corrected summary hints are included, each capped at 600
  characters, only when all citation IDs occur in retrieved sources. Pending and
  rejected artifacts and person/topic/event candidates are excluded. Hints are
  labelled derived context, not independent proof.
- Instructions tell the model to treat retrieved material, speaker labels,
  summary hints, and recent turns as untrusted data; distinguish claims from
  events; avoid impersonation and invented quotations; and acknowledge missing
  or conflicting evidence. This is not a guarantee against prompt injection.

An answered response includes exact-quote `citations`, retrieved `context`, used
`summary_ids`, provider `model`, and `status=answered`. The server rejects replies
with missing citations, unknown message IDs, or quotes outside the supplied
excerpts. Citation lists are deduplicated. This verifies provenance only, not
semantic entailment or completeness of every historical claim.

For stateless requests, empty retrieval returns a fixed uncertainty statement
without contacting the provider (`model=null`). Session requests can additionally
use live memory as described below. The model may also signal insufficient
evidence after reading the passages. In either case status is
`insufficient_evidence` and citations are empty. Model refusals return `refused`.
Malformed JSON, incomplete responses, schema violations and citation failures
return 502 without exposing an unvalidated generated answer.

### Provider behavior and privacy

Chat uses HTTPS requests to OpenAI with Structured Outputs and `store:false`.
The provider receives the question, selected excerpts and source metadata,
bounded recent turns and eligible summary hints. The API key is sent only as an
authorization header; Echo does not log credentials or raw upstream errors.
`store:false` does not establish zero retention; provider policies still apply.
Imports, artifact generation, and embeddings continue to run locally.

Timeouts, connection failures and upstream 5xx responses have at most one retry
with a 0.25-second delay. Rate limits are forwarded as 429 with a bounded numeric
`Retry-After` value (or 30 seconds when unavailable), without an immediate retry.
Exhausted timeouts return 504; connectivity, access/configuration and provider
outages return 503. Other rejected requests return 502 with sanitized messages.
Requests are synchronous and there is no streaming yet.

Requests without session fields remain stateless. The seventh checkpoint below
adds stored turns, topic tracking, optional follow-ups and explicit live memory.
The eighth checkpoint below adds reviewed style settings without changing evidence rules.

### Verification for this checkpoint

Run `python -m pytest -q`. Tests use real local SQLite/ChromaDB with deterministic
test embeddings and mocked OpenAI HTTP responses. They exercise prompt assembly,
schema payloads, recent-turn bounds, reviewed hints, citation provenance,
unsupported questions, profile isolation, failures, refusals and retry behavior.
No live OpenAI call has been made for this checkpoint, as requested. Real model
access, latency, answer quality and grounding behavior still require evaluation
using a locally configured key and representative, appropriately chosen examples.

The request schema follows the official [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Seventh checkpoint: persistent conversations and live memory

Three new SQLite tables hold `ChatSession`, `ChatTurn`, and `LiveMemory` records.
Startup adds these tables without modifying imported messages. Historical
retrieval and artifact generation still read the original transcript tables;
chat turns and live memories are not added to the historical vector index.

### Start and continue a session

Create a session with `POST /profiles/{profile_id}/sessions` and a JSON body such
as `{"title":"Learning chat"}`. The returned session has `revision=0` and
`turn_count=0`. Supply `session_id` and `session_revision` together on `/chat`:

```json
{
  "profile_id": "your-profile-id",
  "session_id": "your-session-id",
  "session_revision": 0,
  "message": "What were our Python plans?",
  "allow_follow_up": true
}
```

Use the returned revision on the next exchange. Session requests reject nonempty
`recent_turns` because the server loads its own history. With no session fields,
the existing stateless contract still works. Creating a session does not require
a model key. Import-based replies still need a current historical index; a session
with no imported conversations can use its live memory without building an index.

Every accepted session exchange stores one user turn and one assistant turn,
including response status, historical/live citations, model name, and an optional
follow-up question. Uncertainty replies, refusals and memory acknowledgements are
also saved. Provider errors, invalid citations and stale-index errors save nothing.
Saving both turns, new memories, topic state and the revision is one transaction.

The session revision prevents stale and concurrent writes. A conflict returns
409 without inserting a partial exchange. If another request wins while a model
call is in progress, the losing generated reply is discarded; provider usage may
already have occurred. After a lost network response, inspect the saved turns
before retrying with a new revision to avoid repeating an accepted message.

`GET /profiles/{profile_id}/sessions` supports `limit` and `offset`.
`GET /profiles/{profile_id}/sessions/{session_id}` returns the current revision,
topic and turn count. `/turns` under that session returns ordered, paginated
turns (`limit` 1–200, `offset` 0 or greater). IDs are scoped to the profile.

### Stored history, topic hints and follow-ups

Prompt history uses the last eight stored turns. Each is capped at 1,000 content
characters for the prompt; only the newest complete capped turns fitting 4,000
characters are forwarded. Full turn text remains stored. `history_trimmed` reports
omission or truncation. The generated follow-up question is stored separately
and appended to its assistant turn when preparing history, within that same cap.

The topic is an English-stopword-filtered keyword label (up to 120 characters)
from the latest substantive message. Its original query is retained internally.
Recognised short English continuations (`Tell me more?`, `Why?`, `Continue`,
`What about that?`, and a few similar forms) combine that query with the new
message, bounded to 220 characters. `retrieval_query` exposes the query used.
This does not resolve arbitrary pronouns, languages, or complex topic changes.

The model returns an optional `follow_up_question` field. The server suppresses
it if the caller sets `allow_follow_up=false`, if a question was asked too recently,
or if its normalized text repeats one of the last ten session follow-ups, recent
assistant text, or the current user message. At least two accepted exchanges must
intervene between follow-up questions. Questions are not returned after uncertainty,
refusals or memory acknowledgements. Prompt instructions require relevant questions
without invented premises; relevance and semantic duplicate detection are not
programmatically verified. The cooldown applies to persisted session exchanges.

### Save and recall live information

Live memories are explicit user statements. Send a dedicated request such as:

```json
{
  "profile_id": "your-profile-id",
  "session_id": "your-session-id",
  "session_revision": 0,
  "message": "For this demo, I am learning Python.",
  "remember": ["For this demo, I am learning Python."]
}
```

Replace the revision with the session's current value. Each entry must be a
nonblank exact excerpt from `message`, up to 220 characters. At most three entries
are accepted; duplicates within the request are removed. A session is required.
The request returns `status=memory_saved`, `saved_memory_ids`, and the new revision.
It is acknowledged locally without retrieval or a provider call, even with no
imports or model key. It is a save action; ask any accompanying question separately.

Each memory links to its originating user turn. Assistant text is not automatically
promoted into facts. The same assertion may be saved again in another turn, keeping
its separate provenance. There is no automatic extraction, merge, conflict
resolution, or general cross-session history sharing.

Recall uses up to the 20 newest active memories across the same profile, fitting
4,000 content characters. Session history itself stays session-specific. The prompt
labels memories `source=live`, with source turn and session IDs, and treats them as
unverified user statements. For a live-only claim the model must use
`live_citations=[{"memory_id":"...","quote":"exact excerpt"}]`, while imported
claims use the existing `citations` array with historical message IDs. Mixed replies
can use both arrays. Unknown IDs, mismatched quotes and live IDs passed off as
historical citations are rejected with 502. This verifies source membership, not
whether a generated claim follows logically from it or is true.

The response's `live_memory_context` shows the memories supplied to the model.
Older memories remain stored but may not be included by this recency policy.
There is no semantic live-memory index yet. If both retrieved historical evidence
and selected live memory are empty, return uncertainty without a provider call.
Current-message assertions and old chat replies alone do not qualify as evidence.

Browse `GET /profiles/{profile_id}/live-memories` with `active`, `limit`, and
`offset` filters. PATCH `/profiles/{profile_id}/live-memories/{memory_id}` with
`{"active":false}` to retract, or `true` to reactivate. Content is immutable through
this endpoint; save a replacement explicitly and retract the old entry. Retraction
excludes a memory from future live evidence but does not erase original turns,
past replies or citations. If a cited memory is retracted during generation, the
reply is rejected with 409 and no new turns are committed.

Configured model requests now also send selected live memories, stored recent
turns, and topic/follow-up hints to the external provider. Explicit memory saves
remain local. Source data stays excluded from Git. Authentication, data deletion
and deployment hardening remain future work; keep using localhost.

### Verification

Run `python -m pytest -q`. Session tests cover persistence, topic-aware retrieval,
history/memory budgets, follow-up cooldowns, profile and session isolation,
memory provenance/retraction, stale and concurrent requests, and rollback.
The older stateless chat tests remain in the suite. LLM behavior continues to use
mocks; no hosted-model evaluation has been run, and real multi-turn conversational
quality remains unverified. Style controls are covered in the eighth checkpoint below.

## Eighth checkpoint: configurable writing style

Style analysis measures text patterns, not personality or identity. The application
keeps three distinct things: measured source statistics, suggested settings, and
the settings you actually review/enable. Only the latter can reach the model prompt.
There is one current style configuration per profile, shared across its sessions.
Creating a separate profile allows a separate configuration.

### Analyze, review and enable

1. Read `GET /profiles/{profile_id}/style`. Without a saved record, revision is 0,
   settings are neutral and disabled, and analysis is null. GET does not create data.
2. Run `POST /profiles/{profile_id}/style/analyze`:

   ```json
   {"revision": 0, "speaker": "Ali"}
   ```

   Use an exact speaker label from the profile's messages. An optional
   `conversation_id` restricts the scope to one import. The current revision is
   required; the example assumes a new profile style.
3. Inspect `analysis.metrics`, `common_words`, `common_phrases`, `common_emojis`,
   source IDs, sample flags, and `suggested_settings`. This saves a new revision
   but does not enable style or replace existing reviewed settings.
4. PATCH `/profiles/{profile_id}/style` with the current revision and chosen fields:

   ```json
   {
     "revision": 1,
     "settings": {
       "enabled": true,
       "length": "brief",
       "tone": "warm",
       "emoji_usage": "occasional",
       "preferred_words": ["haan", "python"]
     }
   }
   ```

5. Submit a normal stateless or session `/chat` request. Answered model replies
   return a `style` snapshot of the revision/settings requested. This does not
   certify that the model followed them. Fixed local responses return `style=null`.

PATCH merges only supplied settings. Empty/null fields, unknown keys, unsupported
values, and sentence-like preferred words return 422. A stale revision returns
409. Manual settings can be saved without analyzing any transcript. New analyses
refresh only statistics/suggestions, preserving active settings and their enabled
state. A different analyzed speaker does not automatically replace active settings.

### Available controls

| Setting | Values |
| --- | --- |
| `enabled` | `false` by default; explicit enable/disable |
| `length` | `brief`, `balanced`, `detailed` |
| `tone` | `neutral`, `casual`, `warm`, `formal` |
| `punctuation` | `standard`, `light`, `expressive` |
| `emoji_usage` | `none`, `occasional` |
| `capitalization` | `standard`, `mostly_lowercase` |
| `language` | `match_user`, `english`, `urdu`, `roman_urdu`, `english_urdu_mix` |
| `preferred_words` | At most ten individual words, each at most 32 characters |

Preferred words allow letters and internal apostrophes/hyphens, not sentences,
digits, emoji or arbitrary instruction text. They are optional diction hints;
the model must not invent a fact or force a topic to use one. Language is a manual
choice; the analyzer always suggests `match_user`. Tone stays neutral in suggestions
because the rules do not establish a speaker's emotional intent.

### What the analyzer measures

The method is `writing-patterns-v1`. It samples up to 1,000 records for the selected
speaker, ordered by conversation start time/ID and source sequence. System notices,
blank text and recognised media-only placeholders are excluded. Each usable text
is capped at 1,000 characters; the combined text budget is 100,000 characters.
`sample_truncated` reports omitted/truncated records or text, and `sample_limited`
flags fewer than 20 usable messages. Statistics reflect that bounded sample.

- Length is measured using whitespace-delimited word units and characters.
- Terminal punctuation measures the final non-whitespace character. A message
  ending in an emoji after punctuation may not count as terminally punctuated.
- Common words use case-folded letter tokens and English stopword filtering;
  `occurrences` counts tokens. Phrases are normalized two/three-word sequences
  found in at least two messages. Their `message_count` is document frequency,
  with up to three example source message IDs each. They are not exact quotations.
- Emoji detection uses broad Unicode ranges and counts codepoints approximately.
  Joined sequences, modifiers, flags and text symbols are not grapheme-aware;
  ASCII emoticons are not counted as emoji.
- Script buckets distinguish ASCII Latin letters, Arabic-script alphabetic
  characters, both, or neither. Digits/punctuation alone do not establish Arabic
  script. This cannot distinguish Urdu from Arabic or English from Roman Urdu.
- Lowercase rate considers only messages containing cased characters. Uncased
  scripts do not imply a lowercase preference.

Suggestions use transparent thresholds: median words ≤10 suggests brief, ≥30
suggests detailed; otherwise balanced. Terminal punctuation below 30% suggests
light punctuation. Emoji in at least 10% of messages suggests occasional emoji.
At least five sampled messages and ≥75% lowercase cased messages suggest mostly
lowercase. Repeated common words become optional vocabulary suggestions. These
are starting points for review, not validated linguistic classifications.

`analysis_stale` compares the analyzed scope's imported-conversation fingerprint
with the current source set. Profile-wide analyses can become stale after any new
import; conversation-scoped analyses remain tied to that conversation. Staleness
does not silently disable or replace reviewed preferences. Reanalyze with the
latest revision to refresh the sample.

### Separation from evidence and turn history

The prompt receives only validated enabled settings under `presentation_style`.
It does not receive raw analysis, source phrases, or the analyzed speaker's name
as style material. Existing retrieved messages can still contain those details
independently as evidence. Style changes neither retrieval queries nor source
selection, citation checks, live-memory labels, or follow-up cooldowns. No output
post-processing rewrites facts or citation quotes to force a style.

Source messages, embeddings and artifacts remain unchanged. Generated text stays
new assistant dialogue; no style option claims it is an authentic message from
the selected speaker. Uncertainty/refusal/save acknowledgements remain neutral.

Two additive SQLite tables hold `ProfileStyle` and `TurnStyle`. For an answered
session reply with active style, the exact requested settings/revision are saved
with the assistant turn in the same transaction as the exchange. `/turns` includes
this snapshot, so later settings changes do not relabel past replies. User turns,
old turns, and fixed acknowledgements have `style=null`.

### Local evaluation

Use `POST /profiles/{profile_id}/style/evaluate` with a candidate reply:

```json
{"text": "haan, python practice sounds good 🙂"}
```

The result returns observed metrics, source baseline metrics when available,
staleness, preferred-word presence, and simple checks against saved settings.
These checks run even when settings are disabled, allowing local inspection:
brief ≤40 whitespace word units; balanced ≤120; detailed ≥40. Emoji budgets are
zero codepoints for none or at most two for occasional. Mostly-lowercase checks
require all cased text to be lowercase; names and exact quotes may trigger a flag.
Do not change authentic quotes just to pass a diagnostic.

The endpoint does not call a model, save the candidate text, gate chat replies,
or score tone, language identity, semantic similarity or factual grounding.
Comparing a full generated reply with short source messages has obvious length
differences; treat the numbers as inspection aids, not a likeness score.

Run `python -m pytest -q` for analysis/scoping, revisions, settings review,
staleness, bounds, prompt/evidence separation and immutable turn snapshots. Actual
hosted-model style quality remains untested because generation still uses mocks.
## Ninth checkpoint — browser workspace

The React/Vite/TypeScript workspace now lives in `../frontend`. Start this backend
on `127.0.0.1:8001`, then run `npm ci` and `npm run dev` from that directory.
Open <http://127.0.0.1:5173/>. Vite proxies the existing `/profiles`, `/chat`, and
`/health` routes; API contracts and server-side credential handling are unchanged.

The interface creates/selects profiles and persistent sessions, displays stored
turns and citation quotes, reads WhatsApp `.txt` exports into the existing JSON
import endpoint, builds the index explicitly, browses/searches original messages,
and retracts/restores explicit live memory. A missing key produces a visible error
and preserves the chat draft. Revision conflicts reload stored turns before retry.
Saving an explicit memory continues to work without a provider or index.

The first frontend checkpoint had 8 mocked-network regression tests and passes the TypeScript/build
check. The backend suite remains at 146 passing tests. Real local browser checks
covered sessions, explicit memory, persistence, browsing/search, and indexing;
no hosted model request was made. The native upload chooser could not be automated;
file reading/submission is tested in the component suite and imports separately
through HTTP. See [frontend learning guide](../frontend/README.md).

## Tenth checkpoint — style and artifact review in the browser

The **Style** tab analyzes an exact participant label in a selected scope, shows
bounded/stale sample information, and keeps suggestions separate from the editable
settings. Copying suggestions never enables an inactive style. Saving reviewed
settings sends the current revision; sample checks use the saved revision and make
no provider call. Manual configuration works without analysis or imports.

The **Review** tab generates summaries/references, filters/paginates records,
shows current and original generated evidence, and supports confirm, reject,
content correction, and same-conversation source-ID corrections. Unsaved edits
block confirm/reject until saved as a correction or explicitly discarded.
Regeneration preserves reviewed records. Existing API contracts are unchanged.

Both panels retain drafts on validation errors and revision conflicts. A conflict
blocks further writes until an explicit reload discards local edits and loads the
latest database revision. No automatic retry is made. Switching panels discards
unsaved drafts; navigation/profile switches are locked during review writes.

Verification: **146 backend tests and 18 frontend tests pass**, plus TypeScript
validation and the production build. Direct HTTP smoke checks with fictional data
verified style analysis, explicit enablement, local checks, artifact sources,
correction, stale writes, and reviewed-record preservation. The browser tool's URL
security policy blocked visual QA for these panels. Hosted-model behavior remains
mocked; no hosted model request was made.

Next is quality and deployment readiness: authentication/access controls, structured
logging, backups/deletion procedures, and reproducible deployment. Keep both
development servers on loopback until those controls exist.
