# Echo backend — development walkthrough

Echo runs a local HTTP server, parses WhatsApp exports, stores imported
messages in SQLite, and retrieves passages by meaning with local embeddings.
It also generates reviewable extractive summaries and reference candidates.
No AI API keys are needed for these checkpoints.

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
third checkpoint below; AI integration is planned for a later milestone.

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
checkpoint uses that fixed local path; `.env` configuration is not loaded yet.
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
from future live chat memory; live memory is not implemented yet.

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

These artifacts are review data. They are not automatically embedded or passed
to an LLM; that integration belongs to a later checkpoint. Run
`python -m pytest -q` to verify generation, evidence inspection, correction,
review persistence, conflict handling, and transaction rollback.
