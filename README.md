## Echo


Echo is a conversational AI project being built step by step. Its goal is to
answer questions using imported conversation history and apply a configurable
conversational style through retrieval-augmented generation (RAG).

**Current stage:** a local React workspace connected to a working FastAPI backend.
The backend parses WhatsApp exports and explicit undated speaker-labelled text,
stores conversations in SQLite, and supports message browsing, keyword search,
semantic retrieval, reviewable summaries and references, and JSON export.
Chat sessions now persist turns, track a simple topic, and keep explicitly saved
live memory separate from imported history.
Each profile can also analyze a speaker's writing patterns and apply reviewed
presentation settings to model replies.
The grounded chat endpoint is implemented with an OpenAI adapter; provider behavior
is tested with mocked HTTP responses. The frontend supports profile selection,
saved chat sessions, transcript file import and browsing, explicit indexing,
citation inspection, live-memory review, style settings, and source-backed
summary/reference review. A live hosted-model evaluation
remains pending.

## Progress

| Checkpoint | Status | What works |
| --- | --- | --- |
| Backend foundation | Complete | FastAPI server, health endpoint, interactive API docs, Python dependencies |
| Transcript parsing | Implemented and tested | Dated WhatsApp exports and explicit undated speaker labels, multiline text, Unicode, source lines, JSON export |
| Structured storage | Implemented and tested | Profiles, transactional imports, SQLite persistence, duplicate protection, pagination, keyword search, conversation export |
| Semantic retrieval | Implemented and smoke-evaluated | Local embeddings, bounded context chunks, persistent ChromaDB indexes, source-linked results, stale-index detection |
| Summaries and references | Implemented with local rules | Extractive segment summaries, participant labels, candidate topics/events, source inspection, correction and review |
| Grounded AI replies | Implemented; provider tested with mocks | Responses API adapter, bounded evidence/history, exact-quote citation checks, uncertainty and provider failure handling |
| Conversation continuity | Implemented; model behavior mocked | Persistent sessions/turns, topic-aware short follow-ups, question cooldown, explicit live memory and retraction |
| Style profiles | Implemented; generation mocked | Speaker-scoped statistics, reviewed settings, prompt integration, turn snapshots, local diagnostics |
| Web interface | Implemented locally | React/Vite/TypeScript, persistent chat, .txt import, indexing, transcript search, source quotes, live-memory retraction, style and artifact review |
| Quality and deployment readiness | In progress | Private request metadata, error references, GitHub Actions checks; authentication and backup/deletion tooling pending |

The latest verified suites have **173 backend tests and 21 frontend tests passing**.
The frontend suite covers explicit saves, source display, retraction, provider
errors, conflict refresh, file-to-JSON import, browsing queries, and API errors/paging.
Undated tests cover explicit boundaries, unknown dates, empty source messages,
provenance, legacy database migration/backup/rollback, export, retrieval, artifacts,
style, mocked chat, and CLI export.
Review-panel tests cover explicit style enablement, suggestion/draft separation,
local diagnostics, stale analysis, scoped generation, linked evidence, corrections,
confirm/reject payloads, revision conflicts, validation failures, and unsaved-edit guards.
The backend suite covers parsing, API
validation, profile isolation, persistence after restart, transaction rollback,
duplicate detection, search, and export fidelity. Retrieval tests also cover
chunk bounds, provenance, model changes, incomplete builds, and stale indexes.
Artifact tests cover source links, segment boundaries, profile isolation,
correction validation, revision conflicts, atomic generation, and review persistence.
Chat tests cover prompt boundaries, unsupported questions, quote/source validation,
profile isolation, provider retries, rate limits, refusals, and configuration loading.
Session tests cover restart persistence, concurrent writes, history/memory budgets,
follow-up cooldowns, explicit memory provenance, retraction, and atomic saves.
Style tests cover source scoping, bounded analysis, configuration revisions,
stale samples, prompt/evidence separation and stored style snapshots.
The import/search/export flow has also been checked against the running HTTP server.

## Run locally

Development currently uses Python 3.12 on macOS. From the repository root:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

- [Health endpoint](http://127.0.0.1:8001/health) returns `{"status":"ok"}`.
- [Interactive API docs](http://127.0.0.1:8001/docs) let you create profiles,
  import transcripts, browse messages, and export conversations.

Stop the server with **Ctrl+C**. Imports, search, and artifact review need no API key.
Model-generated chat replies require local OpenAI configuration; see below.
The application creates its SQLite database automatically at
`backend/data/profiles/echo.db`. Configuration currently uses that fixed local
path. Startup loads the LLM settings from `backend/.env`; process environment
variables take precedence. Database and embedding paths remain fixed.
Semantic retrieval uses a local `all-MiniLM-L6-v2` ONNX embedding model and
ChromaDB. The first nonempty index build downloads the model (about 79 MB);
subsequent builds and searches can run offline with the cached files. Message
text is embedded locally. Chroma's anonymized telemetry is disabled. Chat sends
selected context to OpenAI when configured.

## Open the web interface

Keep the backend running on port **8001**. In a second terminal, from the
repository root (Node.js 22.12+; tested with Node 24):

```sh
cd frontend
npm ci
npm run dev
```

Open [Echo workspace](http://127.0.0.1:5173/). Vite forwards API requests to
FastAPI on the same browser origin. This is a local development setup; it is
not a published deployment. The backend still serves its API docs on port 8001.

1. Create or select a profile, then click **New chat**.
2. Try a statement such as “I prefer studying in the evening”, select
   **Save this message as live memory**, and save it. This uses no model key.
3. Open **Memory** to inspect, retract, or restore the saved statement. Reload
   the page to see that the selected profile, session, and stored turns return.
4. Choose **Import transcript**, select the transcript format and `.txt` file,
   then set the date order for WhatsApp or exact participant labels for undated
   text. Import and click **Build search index** after every new import.
5. Open **Transcript** to browse the original messages and search their words.
6. Ask a question in chat. Hosted model replies require server configuration;
   errors preserve your draft. Use **Inspect sources** below a cited reply to
   read the quoted evidence and distinguish historical messages from live memory.

Only profile/session IDs are saved in localStorage. Transcripts, turns, and
memories remain in backend storage; no API key belongs in the frontend.
The UI displays saved source quotes and identifiers, rather than full surrounding
source records. The **Style** and **Review** tabs expose the existing style and
artifact APIs; the API docs remain available for full endpoint inspection.

```sh
cd frontend
npm test          # 21 UI/API-client regression tests; mocked network responses
npm run build     # TypeScript checks and production assets in frontend/dist
npm run preview   # Local build preview, still needs backend on port 8001
```

Browser checks verified real profile/session creation, local memory save and
retraction, restoration after reload, transcript browsing/search, and index rebuild.
The fictional transcript was imported through HTTP; file selection/import behavior
is covered by the component test. The automated browser file chooser timed out,
so a full native file-picker round trip is not claimed. Mobile (390 px) and wide
(1440 px) layouts were checked for horizontal overflow. No hosted model was called.

### Import speaker-labelled text without dates

In **Import**, choose **Speaker-labelled text (undated)**. Choose your `.txt` file
and enter every participant label exactly as it appears, one per line **without
its trailing colon**. For example, enter `Sara` and `Ali` for this fictional file:

```text
Sara:
Shall we study Python?
A checklist:
Practice functions

Ali:
Good idea.
```

Only standalone lines matching the configured labels plus `:` begin a message;
`A checklist:` stays inside Sara's text. Inline `Sara: message` is not this format.
Matching participant-label lines inside message content are inherently ambiguous;
review the imported messages before indexing. Empty source messages are retained
and skipped by retrieval/style analysis. File order, raw records, and source lines
are preserved. Timestamps and raw timestamps are `null`, shown as **Date unknown**.
No dates or elapsed times are inferred, including in model context.

API imports use `transcript_format: "speaker-labelled"`, `speakers: ["Sara", "Ali"]`,
and no `date_order`. Existing WhatsApp requests remain valid with `date_order` and
an omitted format. Duplicate detection still covers the whole normalized file in
one profile; selecting different labels does not create a second copy.

On first startup with an older SQLite database, Echo creates a local
`backend/data/profiles/echo.pre-undated-<id>.db` backup, then upgrades the schema
transactionally. Historical records, constraints, indexes, and triggers are
preserved; failure rolls back the upgrade. Backups contain private data and remain
under the same Git-ignored directory. Fresh databases need no migration backup.

### Review style and derived records

- **Style:** enter a participant's exact transcript label and choose the analysis
  scope. Analysis saves measured patterns and suggestions, leaving your settings
  draft unchanged. Copy suggestions into the draft if useful, review the controls,
  explicitly select enablement, and click **Save reviewed settings**. Manual settings
  also work without analysis. The local sample checker uses the saved revision,
  not the unsaved draft; it does not assess tone, identity, or factual accuracy.
- **Review:** choose a conversation scope and generate summaries/references using
  local rules. Filter by record kind or status, open a record, and inspect current
  linked source messages alongside the original generated content/evidence. Confirm
  or reject the saved record, or edit content/source IDs and save a correction.
  Corrections preserve original transcript messages and original generated records.
  Confirm/reject are disabled while edits are unsaved.
- **Conflicts:** both panels submit the revision they loaded. A 409 keeps the local
  edits and blocks another write until you deliberately reload the latest saved
  record. Reload buttons explicitly discard local edits; writes are never retried
  automatically. Switching panels discards their unsaved drafts too.

These panels use no hosted model calls. Direct HTTP checks with a fictional
transcript verified analysis, explicit style enablement, sample diagnostics,
revision conflicts, source inspection, corrections, and preservation on regeneration.
Automated visual checks for this checkpoint remain pending: the browser tool's
URL security policy blocked access to the local page. Component tests and the
TypeScript/build check pass; no replacement browser path was used.

For a learning guide to the React components, see [frontend/README.md](frontend/README.md).

## Request references and automated checks

Echo now adds an `X-Request-ID` response header. If an API request fails, the web
interface displays that reference beside its error. Use it to find the matching
JSON request log in the backend terminal. The log includes the method, route
**template**, status, duration, and outcome; it excludes request/response bodies,
queries, raw URLs, client-supplied request IDs, headers, client addresses, and
profile/session IDs. Default Uvicorn access logging is disabled at application
startup because it would otherwise include raw URLs. Unexpected errors return a
generic JSON response; Uvicorn exception details and retrieval errors are redacted.
Third-party/custom process logging is outside this request-log contract.

The [Checks workflow](https://github.com/abbasrazaswe/Echo/actions/workflows/checks.yml)
runs on pushes to `main`, pull requests, and manual dispatch. Separate jobs run
Python 3.12 tests plus `pip check`, and Node 24 `npm ci`, UI tests, TypeScript, and
the production build. Actions are pinned to commit hashes; workflow permissions
are read-only. Tests use fictional input/mocked providers without credentials or
hosted-model evaluation. CI does not deploy, upload private data, or run the
opt-in real embedding evaluation. Repository branch-protection settings are not
changed by adding a workflow.

See [backend/README.md](backend/README.md#request-logging-and-ci--api-090) for
log fields, privacy limits, and how to reproduce a failed CI check locally.

## Try the current workflow

1. In the interactive docs, call `POST /profiles` with
   `{"name":"Learning profile"}` and copy the returned ID.
2. Call `POST /profiles/{profile_id}/imports` using that ID and this JSON body:

   ```json
   {
     "title": "Python discussion",
     "date_order": "day-first",
     "transcript": "14/10/2026, 09:01 - Ali: Shall we study Python?\n14/10/2026, 09:02 - Sara: Yes, let's start with functions."
   }
   ```

3. Call `GET /profiles/{profile_id}/messages`. Set `q` to `functions` to find
   Sara's message, or leave it unset to browse all messages.
4. Repeat the import to see duplicate protection: HTTP **409**, with no extra
   messages saved.
5. Use the returned conversation ID with the export endpoint to inspect all
   records, including stable IDs and source text.
6. Call `POST /profiles/{profile_id}/memories/index` to build the semantic index.
   The first build may take longer while the model downloads.
7. Call `GET /profiles/{profile_id}/memories/search` with `q` set to
   `What are our plans for learning to code?`. Results contain ranked passages,
   similarity scores, source messages, and character spans. Rebuild the index
   after importing more conversations.
8. Call `POST /profiles/{profile_id}/artifacts/generate`, then
   `GET /profiles/{profile_id}/artifacts` with `kind=summary` to see extractive
   summaries. Use `kind=person`, `event`, or `topic` to inspect reference candidates.
9. Copy an artifact ID into `GET /profiles/{profile_id}/artifacts/{artifact_id}`
   to inspect the source messages. Use PATCH on the same path to confirm,
   correct, or reject it. See the review example below.
10. After configuring the model, use `POST /chat` with the profile ID and a question
    to generate a reply with validated source quotes.

## Grounded chat

Create or edit `backend/.env` using [the configuration template](backend/.env.example):

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-local-key
LLM_MODEL=your-available-model
LLM_TIMEOUT_SECONDS=20
LLM_MAX_OUTPUT_TOKENS=1600
```

Choose a model available to your API project that supports the Responses API and
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
The model is explicitly configured; Echo does not select one automatically.
Restart the server after changing settings. Never commit the real `.env` file.

Import conversations and build the selected profile's semantic index, then use:

```json
{
  "profile_id": "your-profile-id",
  "message": "What were our plans for learning to code?",
  "recent_turns": [],
  "min_score": 0.3
}
```

`POST /chat` retrieves up to five passages and returns `answer`, `status`,
`citations`, the retrieved `context`, any reviewed `summary_ids` used as hints,
`history_trimmed`, and the provider `model`. Inspect the source messages and
character spans in `context` to assess the evidence.
Session requests additionally return `session_id`, `session_revision`, `topic`,
`retrieval_query`, `follow_up_question`, `live_citations`, `live_memory_context`,
and `saved_memory_ids`. Live citations point to new user statements, not imports.

- No passages above the threshold and no selected live memories: return
  `insufficient_evidence` without a model call.
- Retrieved passages do not answer the question: the model can signal insufficient
  evidence, which produces a fixed uncertainty reply without citations.
- An answered reply must cite retrieved historical message IDs or selected live
  memory IDs with exact quotes from supplied evidence. Invalid or missing
  citations return 502. The two source types use separate citation arrays.
- Citation checks establish provenance, not that every generated claim follows
  logically from the quoted text. Retrieval and answer quality still need evaluation.

The question is limited to 220 characters to match the current retrieval inputs.
You may supply up to eight recent user/assistant turns, each up to 1,000 characters;
only the latest complete turns fitting 4,000 content characters are forwarded.
For stateless requests, recent turns are client-provided context, not historical
evidence. Session requests load their history from storage instead. Up to three
reviewed summary hints are included when all their source IDs occur in retrieval.
Unreviewed/rejected artifacts and people/event/topic candidates are not forwarded.

**External processing:** configured chat sends the question, bounded recent turns,
retrieved excerpts, speaker labels/timestamps, and applicable reviewed summary hints
to OpenAI. Session chat also includes selected active live memories and topic/follow-up
context. Requests use `store:false`; this is not a claim of zero data retention.
Source records and local vector indexes remain on your machine.

Provider timeouts, connection failures, and 5xx errors receive at most one retry.
Rate limits return 429 with `Retry-After`; exhausted timeouts return 504;
configuration/connectivity/provider outages return 503. Refusals return `refused`.
Omitting session fields keeps requests stateless. Session-backed requests save
validated exchanges; explicit memory saves can be acknowledged without a model.

**Verification:** provider requests/responses are mocked in tests. No live OpenAI
call has been made for this checkpoint. A successful mocked test is not evidence
of hosted-model access, output quality, or resistance to all prompt injections.

## Persistent sessions and live memory

1. Create a session with `POST /profiles/{profile_id}/sessions` and body
   `{"title":"Learning chat"}`. Copy its `id` and initial `revision` (0).
2. Include both fields in `/chat` requests:

   ```json
   {
     "profile_id": "your-profile-id",
     "session_id": "your-session-id",
     "session_revision": 0,
     "message": "What were our Python plans?"
   }
   ```

3. Use the returned `session_revision` for the next request. History is loaded
   automatically; do not also supply `recent_turns`.
4. Browse saved exchanges with
   `GET /profiles/{profile_id}/sessions/{session_id}/turns`. Session state and turns
   survive restarts. A stale revision returns 409; reload the session and check
   its saved turns before retrying a request whose response was lost.

To save a new user statement explicitly, send a separate memory request:

```json
{
  "profile_id": "your-profile-id",
  "session_id": "your-session-id",
  "session_revision": 0,
  "message": "For this demo, I am learning Python.",
  "remember": ["For this demo, I am learning Python."]
}
```

Replace the revision with the current value. Each `remember` entry must be an exact
excerpt from the current message (up to three entries). The request saves a
user/assistant pair and returns `memory_saved` locally, without retrieval or a
provider call. If you also have a question, ask it in the next request.

Active live memories are shared across sessions **within the same profile**;
turn history remains session-specific. They carry `source=live` and a
`source_turn_id` linking to the user statement. Assistant-generated text is never
automatically saved as a fact. Recalled statements use a separate `live_citations`
array with memory IDs and exact quotes. They are user assertions, not verified
truth or evidence of an imported historical event.

Browse `/profiles/{profile_id}/live-memories` and PATCH an item's path with
`{"active":false}` to exclude it from future live evidence, or `true` to reactivate.
Retraction does not erase the saved turn, historical replies, or their citations.
The prompt uses at most the 20 newest active profile memories fitting 4,000 content
characters. Older facts are still stored; semantic live-memory search is later work.

The topic is a simple keyword label from the latest substantive user message.
Recognised English continuations such as `Tell me more?` reuse its retrieval
query; this is a heuristic, not general reference resolution. Follow-up questions
are a separate response field: they are optional, suppressed after uncertainty,
refusals and memory acknowledgements, and rate limited to allow at least two
intervening session exchanges. Normalized duplicates of the last ten follow-ups
or recent assistant text are suppressed. Set `allow_follow_up=false` to disable.
Actual question relevance and multi-turn language quality remain unverified with
a live model.

## Configurable conversational style

Style controls presentation. Evidence and citations still come from the separate
historical/live-memory paths. Analysis runs locally and is **disabled by default**;
it does not enable or overwrite your reviewed settings.

1. Read `GET /profiles/{profile_id}/style` to obtain the current revision (0 before
   any style has been saved).
2. Run `POST /profiles/{profile_id}/style/analyze` using a speaker label copied
   from imported messages:

   ```json
   {"revision": 0, "speaker": "Ali"}
   ```

3. Inspect `analysis`, `suggested_settings`, and the source message IDs. The
   measurements include length, terminal punctuation, common words and normalized
   repeated phrases, approximate emoji usage, lowercase habits, and script mixing.
4. Review settings, then PATCH `/profiles/{profile_id}/style` using the new revision:

   ```json
   {
     "revision": 1,
     "settings": {
       "enabled": true,
       "length": "brief",
       "tone": "casual",
       "emoji_usage": "occasional"
     }
   }
   ```

5. Chat normally. An answered model reply reports the requested `style` revision
   and settings; session turns retain that snapshot for inspection. To disable,
   PATCH `{"revision":2,"settings":{"enabled":false}}` using the latest revision.

Other controls include punctuation, capitalization, language, and optional preferred
words. Values are bounded enums or individual words; there is no free-form persona
instruction field. Settings apply across the selected profile's sessions. They can
also be configured manually before analysis. PATCH changes only supplied fields;
stale revisions return 409.

Analysis samples at most 1,000 matching speaker records, 1,000 text characters per
usable message, and 100,000 total text characters. Sample limitations/truncation
are reported. Fewer than 20 usable messages are flagged as a limited sample.
Latin/Arabic-script mixing is a rough script measure: it does not identify Urdu,
Arabic, Roman Urdu, personality, or relationships. Unicode emoji counts are
approximate, and phrases are normalized word sequences rather than authentic quotes.
New imports in the analyzed scope mark analysis stale; your reviewed settings remain.

`POST /profiles/{profile_id}/style/evaluate` with
`{"text":"python practice sounds good 🙂"}` compares the supplied text's broad
metrics with the analyzed baseline and saved settings. It checks simple length,
emoji and lowercase bands and reports preferred-word presence. It makes no model
call, does not change the profile, and does not score tone, language identity,
semantic similarity, or factual grounding.

Only enabled, reviewed settings reach the generation prompt. Raw style samples,
statistics, phrases and the analyzed speaker's name are not forwarded as style
context. Optional vocabulary is a diction hint, not evidence or permission to add
facts. Citation quotes are never rewritten for style. Fixed uncertainty, refusal
and memory-save messages remain neutral. Style similarity of actual hosted-model
replies is still unverified; tests use mocked generation and synthetic comparisons.

## Summaries and reference review

This checkpoint needs no API key or model download. It uses **extractive
summaries**: up to three informative original-message excerpts from each segment
of 20 imported records, in source order. Excerpts are capped at 500 text characters
and labelled when truncated. They are selected examples, not a complete account
of everything discussed or an AI-written paraphrase.

People candidates are participant labels from the export. Topic candidates use
frequent non-stopword terms; event candidates use English event words such as
`meeting`, `flight`, and `appointment`. These rules may miss or misclassify
references, especially in other languages. They do not infer real identities,
event dates, whether plans happened, or relationships between people.

Every artifact includes source message IDs and starts with review status `pending`.
Reference candidates also carry `uncertain=true`. That flag describes the original
rule-based extraction; review status separately records your decision. Inspect
the supporting messages before reviewing a candidate.

To correct an artifact, PATCH its path with the latest `revision`:

```json
{
  "revision": 1,
  "status": "corrected",
  "content": "The conversation discusses plans to study Python."
}
```

Use `{"revision":1,"status":"confirmed"}` or
`{"revision":1,"status":"rejected"}` for decisions without changing fields.
A correction may also provide `source_message_ids`; all must belong to the same
conversation. The server returns the updated revision. An outdated revision
returns HTTP 409 so you can reload before editing again.

Original generated text and citations remain available alongside the latest
reviewed version. Regeneration refreshes pending records and preserves confirmed,
corrected, and rejected records. It never changes imported messages. Full edit
history, automatic entity resolution, and AI-written summaries are later work.
Reviewed summaries can now be supplied to chat as hints alongside source evidence.

The flow so far is:

```text
WhatsApp text → parser → validated messages → SQLite → browse/search/export
                                               ↓
                                      chunks → embeddings → ChromaDB
                                                               ↓
                                 question → embedding → ranked source passages
                                                                  ↓
                                      bounded prompt → LLM → citation validation → reply
```

For standalone parsing, run this from `backend` with the virtual environment active:

```sh
python -m app.parser tests/fixtures/whatsapp_sample.txt \
  --date-order day-first \
  --output data/profiles/default/processed/sample.json
```

The fixture is fictional. Choose a new output filename if one already exists;
the parser refuses to overwrite files.

## API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Confirm the server responds |
| POST / GET | `/profiles` | Create or list profiles |
| POST | `/profiles/{profile_id}/imports` | Parse and save transcript text from JSON |
| GET | `/profiles/{profile_id}/conversations` | List imported conversations |
| GET | `/profiles/{profile_id}/messages` | Browse or search using `q`, `conversation_id`, `limit`, and `offset` |
| GET | `/profiles/{profile_id}/conversations/{conversation_id}/export` | Export a conversation as JSON |
| POST | `/profiles/{profile_id}/memories/index` | Build or rebuild the profile's semantic index |
| GET | `/profiles/{profile_id}/memories/search` | Search by meaning using `q`, `limit`, and `min_score` |
| POST | `/profiles/{profile_id}/artifacts/generate` | Generate summaries/references, optionally scoped by `conversation_id` |
| GET | `/profiles/{profile_id}/artifacts` | Browse using `kind`, `status`, `conversation_id`, `limit`, and `offset` |
| GET / PATCH | `/profiles/{profile_id}/artifacts/{artifact_id}` | Inspect evidence or review/correct an artifact |
| POST | `/chat` | Generate a reply using retrieved source passages and optional recent turns |
| POST / GET | `/profiles/{profile_id}/sessions` | Create or list persistent chat sessions |
| GET | `/profiles/{profile_id}/sessions/{session_id}` | Read revision, topic, and turn count |
| GET | `/profiles/{profile_id}/sessions/{session_id}/turns` | Browse saved turns with pagination |
| GET | `/profiles/{profile_id}/live-memories` | Browse user-stated memories, optionally filtered by `active` |
| PATCH | `/profiles/{profile_id}/live-memories/{memory_id}` | Retract or reactivate a live memory |
| GET / PATCH | `/profiles/{profile_id}/style` | Inspect or update reviewed style settings using revisions |
| POST | `/profiles/{profile_id}/style/analyze` | Measure a selected speaker, optionally scoped by `conversation_id` |
| POST | `/profiles/{profile_id}/style/evaluate` | Compare supplied text with saved settings and baseline metrics |

## Tests

From `backend`, with the virtual environment active:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use temporary databases and fictional transcripts.
Provider tests use mocked HTTP responses and fictional credentials; they make no
OpenAI calls. No live provider key is required to run the suite.
Automated retrieval tests use deterministic test embeddings and real ChromaDB;
they do not download a model. To evaluate the actual local embedding model on
three fictional paraphrase queries, run this separately from `backend`:

```sh
python -m scripts.evaluate_retrieval
```

The evaluation checks whether each expected source ranks first. It may download
the model on first use. This is a small smoke evaluation, not a representative
benchmark for your conversations or languages.

Latest real-model result: **3/3 expected sources ranked first**, with cosine
similarities of 0.385 (evening meal → restaurant/pasta), 0.428 (airport travel →
taxi/flight), and 0.468 (learning to code → Python/programming). These values
illustrate retrieval ranking, not confidence in a historical answer.

## Repository structure

```text
Echo/
├── .github/workflows/checks.yml # Backend/frontend CI checks
├── backend/
│   ├── app/
│   │   ├── main.py              # Application startup and health endpoint
│   │   ├── api.py               # Profiles, imports, browsing, and export
│   │   ├── artifact_api.py      # Artifact generation, inspection, and review
│   │   ├── artifacts.py         # Extractive summaries and reference rules
│   │   ├── chat.py              # Prompt context and citation validation
│   │   ├── llm.py               # Provider interface, OpenAI adapter, settings
│   │   ├── sessions.py          # Persistent turns, live memory, topic/revision handling
│   │   ├── style.py             # Writing statistics, settings, and local comparison
│   │   ├── prompts/             # Grounding instructions
│   │   ├── database.py          # SQLAlchemy schema and SQLite connections
│   │   ├── migrations.py        # Backed-up SQLite upgrade for unknown dates
│   │   ├── observability.py     # Private request metadata and error references
│   │   ├── retrieval.py         # Chunking, embeddings, and vector snapshots
│   │   └── parser/              # WhatsApp parser and command-line entry point
│   ├── tests/                   # Parser and storage/API tests, fictional fixture
│   ├── scripts/                 # Opt-in real-model retrieval evaluation
│   ├── data/profiles/            # Local database and private data; ignored by Git
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── README.md                # Detailed walkthrough and parser behavior
├── frontend/
│   ├── src/App.tsx              # Profile selection and creation
│   ├── src/Workspace.tsx        # Sessions, chat, and source quotes
│   ├── src/Tools.tsx            # File import, transcript browsing, live memory
│   ├── src/StylePanel.tsx       # Analysis, reviewed settings, local diagnostics
│   ├── src/ArtifactPanel.tsx    # Source inspection, generation, record review
│   ├── src/reviewTypes.ts       # Typed style/artifact API contracts
│   ├── src/api.ts               # Typed requests, errors, and pagination
│   ├── src/styles.css           # Responsive workspace styling
│   ├── src/*.test.*             # UI and API-client regression tests
│   ├── vite.config.ts          # Local API proxy and test setup
│   └── README.md               # Frontend setup and learning guide
├── echo_project_handoff.md      # Design and development roadmap
└── README.md
```

## Current limits and next steps

- The React workspace now includes style and derived-record review panels.
  **Next: authentication/access controls and backup/deletion tooling**,
  followed by deployment configuration. Request logging and automated CI checks
  are implemented; public/remote deployment is still pending.
  Hosted-model evaluation remains pending until credentials are configured locally.
- Semantic results rank similarity; scores are not evidence that an answer is
  true. `min_score` can suppress weak matches but cannot reliably detect every
  question without an answer. Validate retrieval on your own examples before RAG.
- The local model is primarily suitable for English. Urdu, Roman Urdu, and mixed
  language conversations need evaluation and may require a multilingual provider.
- Indexing is explicit and synchronous. New imports or an embedding-model change
  require rebuilding; a missing/stale index returns HTTP 409. Model or vector-store
  failures return 503. SQLite remains the source of truth.
- The web interface reads `.txt` exports and submits transcript text as JSON,
  up to 2,000,000 characters (client file cap: 8 MB). Multipart upload and PDF
  parsing are not implemented.
- The parsers support common WhatsApp layouts and explicit undated labels. Validate a small redacted real
  sample before importing a full history; locale-specific formats and pasted
  header-shaped text may need additional handling.
- Duplicate detection covers whole transcripts, ignoring BOM and newline-style
  differences. Partially overlapping exports are not deduplicated.
- This is a local development app. Authentication is not implemented; keep
  it bound to `127.0.0.1` until access controls are added.
- Keep private transcripts, generated exports, databases, credentials, and virtual
  environments out of Git. Store private data under `backend/data/profiles/`,
  which is ignored by Git.

See the [backend walkthrough](backend/README.md) for step-by-step examples and
the [project handoff](echo_project_handoff.md) for the full planned architecture.
