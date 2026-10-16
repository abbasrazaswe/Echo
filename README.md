# Echo

Echo is a conversational AI project being built step by step. Its goal is to
answer questions using imported conversation history and apply a configurable
conversational style through retrieval-augmented generation (RAG).

**Current stage:** a working local backend that parses WhatsApp text exports,
stores conversations in SQLite, and supports message browsing, keyword search,
and JSON export. AI-generated replies and the frontend are still planned.

## Progress

| Checkpoint | Status | What works |
| --- | --- | --- |
| Backend foundation | Complete | FastAPI server, health endpoint, interactive API docs, Python dependencies |
| Transcript parsing | Implemented and tested with fictional samples | Common WhatsApp text formats, explicit date order, multiline messages, Unicode, system notices, source lines, JSON export |
| Structured storage | Implemented and tested | Profiles, transactional imports, SQLite persistence, duplicate protection, pagination, keyword search, conversation export |
| Semantic retrieval | Next | Embeddings, context chunks, vector indexing, source-linked retrieval |
| Summaries and references | Planned | Conversation summaries and people, event, and topic references |
| Grounded AI replies | Planned | LLM integration using retrieved evidence and honest uncertainty |
| Conversation continuity | Planned | Session history, follow-ups, separate live memory |
| Style profiles | Planned | Configurable vocabulary, punctuation, and conversational patterns |
| Web interface | Planned | React chat, transcript browsing, memory inspection |
| Deployment readiness | Planned | Authentication, access controls, operational documentation |

The latest verified suite has **31 passing tests**, covering parsing, API
validation, profile isolation, persistence after restart, transaction rollback,
duplicate detection, search, and export fidelity. The import/search/export flow
has also been checked against the running HTTP server.

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

Stop the server with **Ctrl+C**. No AI API key is needed for the current features.
The application creates its SQLite database automatically at
`backend/data/profiles/echo.db`. Configuration currently uses that fixed local
path; the `.env` template is not loaded by the application yet.

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

The flow so far is:

```text
WhatsApp text → parser → validated messages → SQLite → browse/search/export
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

## Tests

From `backend`, with the virtual environment active:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use temporary databases and fictional transcripts.

## Repository structure

```text
Echo/
├── backend/
│   ├── app/
│   │   ├── main.py              # Application startup and health endpoint
│   │   ├── api.py               # Profiles, imports, browsing, and export
│   │   ├── database.py          # SQLAlchemy schema and SQLite connections
│   │   └── parser/              # WhatsApp parser and command-line entry point
│   ├── tests/                   # Parser and storage/API tests, fictional fixture
│   ├── data/profiles/            # Local database and private data; ignored by Git
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── README.md                # Detailed walkthrough and parser behavior
├── echo_project_handoff.md      # Design and development roadmap
└── README.md
```

## Current limits and next steps

- Search currently matches text substrings. **Next: semantic retrieval** to find
  relevant passages by meaning, while retaining links to original messages.
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
