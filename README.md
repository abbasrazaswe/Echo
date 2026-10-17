# Echo

Echo is a conversational AI project being built step by step. Its goal is to
answer questions using imported conversation history and apply a configurable
conversational style through retrieval-augmented generation (RAG).

**Current stage:** a working local backend that parses WhatsApp text exports,
stores conversations in SQLite, and supports message browsing, keyword search,
semantic retrieval, reviewable summaries and references, and JSON export.
The grounded chat endpoint is implemented with an OpenAI adapter; provider behavior
is tested with mocked HTTP responses. A live hosted-model evaluation and the
frontend are still pending.

## Progress

| Checkpoint | Status | What works |
| --- | --- | --- |
| Backend foundation | Complete | FastAPI server, health endpoint, interactive API docs, Python dependencies |
| Transcript parsing | Implemented and tested with fictional samples | Common WhatsApp text formats, explicit date order, multiline messages, Unicode, system notices, source lines, JSON export |
| Structured storage | Implemented and tested | Profiles, transactional imports, SQLite persistence, duplicate protection, pagination, keyword search, conversation export |
| Semantic retrieval | Implemented and smoke-evaluated | Local embeddings, bounded context chunks, persistent ChromaDB indexes, source-linked results, stale-index detection |
| Summaries and references | Implemented with local rules | Extractive segment summaries, participant labels, candidate topics/events, source inspection, correction and review |
| Grounded AI replies | Implemented; provider tested with mocks | Responses API adapter, bounded evidence/history, exact-quote citation checks, uncertainty and provider failure handling |
| Conversation continuity | Next | Persistent sessions, follow-ups, separate live memory |
| Style profiles | Planned | Configurable vocabulary, punctuation, and conversational patterns |
| Web interface | Planned | React chat, transcript browsing, memory inspection |
| Deployment readiness | Planned | Authentication, access controls, operational documentation |

The latest verified suite has **100 passing tests**, covering parsing, API
validation, profile isolation, persistence after restart, transaction rollback,
duplicate detection, search, and export fidelity. Retrieval tests also cover
chunk bounds, provenance, model changes, incomplete builds, and stale indexes.
Artifact tests cover source links, segment boundaries, profile isolation,
correction validation, revision conflicts, atomic generation, and review persistence.
Chat tests cover prompt boundaries, unsupported questions, quote/source validation,
profile isolation, provider retries, rate limits, refusals, and configuration loading.
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

- No passages above the threshold: return `insufficient_evidence` without a model call.
- Retrieved passages do not answer the question: the model can signal insufficient
  evidence, which produces a fixed uncertainty reply without citations.
- An answered reply must cite retrieved message IDs with exact quotes from the
  excerpts sent to the model. Invalid or missing citations return 502.
- Citation checks establish provenance, not that every generated claim follows
  logically from the quoted text. Retrieval and answer quality still need evaluation.

The question is limited to 220 characters to match the current retrieval inputs.
You may supply up to eight recent user/assistant turns, each up to 1,000 characters;
only the latest complete turns fitting 4,000 content characters are forwarded.
Recent turns are client-provided context, not historical evidence. Up to three
reviewed summary hints are included when all their source IDs occur in retrieval.
Unreviewed/rejected artifacts and people/event/topic candidates are not forwarded.

**External processing:** configured chat sends the question, bounded recent turns,
retrieved excerpts, speaker labels/timestamps, and applicable reviewed summary hints
to OpenAI. Requests use `store:false`; this is not a claim of zero data retention.
Source records and local vector indexes remain on your machine.

Provider timeouts, connection failures, and 5xx errors receive at most one retry.
Rate limits return 429 with `Retry-After`; exhausted timeouts return 504;
configuration/connectivity/provider outages return 503. Refusals return `refused`.
Chat is currently stateless: it does not save sessions, replies, or new memories.

**Verification:** provider requests/responses are mocked in tests. No live OpenAI
call has been made for this checkpoint. A successful mocked test is not evidence
of hosted-model access, output quality, or resistance to all prompt injections.

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
├── backend/
│   ├── app/
│   │   ├── main.py              # Application startup and health endpoint
│   │   ├── api.py               # Profiles, imports, browsing, and export
│   │   ├── artifact_api.py      # Artifact generation, inspection, and review
│   │   ├── artifacts.py         # Extractive summaries and reference rules
│   │   ├── chat.py              # Prompt context and citation validation
│   │   ├── llm.py               # Provider interface, OpenAI adapter, settings
│   │   ├── prompts/             # Grounding instructions
│   │   ├── database.py          # SQLAlchemy schema and SQLite connections
│   │   ├── retrieval.py         # Chunking, embeddings, and vector snapshots
│   │   └── parser/              # WhatsApp parser and command-line entry point
│   ├── tests/                   # Parser and storage/API tests, fictional fixture
│   ├── scripts/                 # Opt-in real-model retrieval evaluation
│   ├── data/profiles/            # Local database and private data; ignored by Git
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── README.md                # Detailed walkthrough and parser behavior
├── echo_project_handoff.md      # Design and development roadmap
└── README.md
```

## Current limits and next steps

- The grounded chat API is implemented with mocked provider coverage. **Next:
  persistent conversation sessions and separate live memory**. Hosted-model
  evaluation remains pending until credentials are configured locally.
- Semantic results rank similarity; scores are not evidence that an answer is
  true. `min_score` can suppress weak matches but cannot reliably detect every
  question without an answer. Validate retrieval on your own examples before RAG.
- The local model is primarily suitable for English. Urdu, Roman Urdu, and mixed
  language conversations need evaluation and may require a multilingual provider.
- Indexing is explicit and synchronous. New imports or an embedding-model change
  require rebuilding; a missing/stale index returns HTTP 409. Model or vector-store
  failures return 503. SQLite remains the source of truth.
- Import currently accepts transcript text in JSON, up to 2,000,000 characters.
  File upload and PDF parsing are not implemented.
- The parser supports common export layouts. Validate a small redacted real
  sample before importing a full history; locale-specific formats and pasted
  header-shaped text may need additional handling.
- Duplicate detection covers whole transcripts, ignoring BOM and newline-style
  differences. Partially overlapping exports are not deduplicated.
- This is a local development backend. Authentication is not implemented; keep
  it bound to `127.0.0.1` until access controls are added.
- Keep private transcripts, generated exports, databases, credentials, and virtual
  environments out of Git. Store private data under `backend/data/profiles/`,
  which is ignored by Git.

See the [backend walkthrough](backend/README.md) for step-by-step examples and
the [project handoff](echo_project_handoff.md) for the full planned architecture.
