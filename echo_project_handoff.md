# Echo — Technical Project Handoff

## 1. Project Overview

**Echo** is a modular, memory-grounded conversational AI application. It imports conversation transcripts, converts them into structured records, indexes relevant content, and uses retrieved context to generate coherent responses.

The system is designed to support:
- Transcript ingestion and parsing
- Structured message storage
- Semantic search over historical conversations
- Retrieval-augmented generation (RAG)
- Conversation and topic summaries
- People, events, and topic references
- A configurable conversational style profile
- Follow-up questions and continuity across turns
- Separate historical and newly created conversation memories
- A web-based chat interface

The initial implementation should prioritize a small, testable end-to-end workflow over implementing every planned module immediately.

## 2. Core Design Principles

1. **Modularity:** Each component has a clear responsibility.
2. **Grounded responses:** Historical claims should be based on retrieved transcript evidence.
3. **Separation of concerns:** Original transcript data, derived summaries, vector indexes, and live chat memory are stored separately.
4. **Incremental development:** Build and test one milestone at a time.
5. **Configurable profiles:** Keep transcript data and derived artifacts associated with a profile rather than hardcoding one dataset into application logic.
6. **Privacy:** Keep credentials and private transcripts out of version control.
7. **Honest uncertainty:** If the transcript does not support an answer, the system should acknowledge that instead of inventing a historical detail.
8. **Distinct memory sources:** Preserve the difference between imported historical data and information introduced during new chats.

## 3. Recommended Technology Stack

### Backend
- Python
- FastAPI
- Pydantic for request and response validation
- SQLAlchemy for database access

### Data storage
- SQLite for structured records during the initial version
- ChromaDB for vector search
- JSON for portable intermediate exports and derived artifacts

### AI and retrieval
- An LLM API for response generation
- An embedding model for semantic retrieval
- Optional reranking after basic retrieval works
- Retrieval-augmented generation (RAG) rather than training a foundation model from scratch

### Transcript processing
- PyMuPDF for PDF text extraction
- Format-specific parsers for exported chat formats
- Python utilities for normalization, validation, and JSON export

### Frontend
- React with Vite
- TypeScript
- Tailwind CSS, if desired

### Development tools
- Git and GitHub
- Python virtual environment
- `.env` for local secrets
- `.env.example` for documenting required configuration
- Pytest for automated tests

Use API-hosted models initially to avoid requiring a high-memory local machine. Keep the model provider behind a service interface so it can be changed later.

## 4. Folder Structure

```text
echo-ai/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── parser/
│   │   ├── database/
│   │   ├── models/
│   │   ├── memory/
│   │   ├── personality/
│   │   ├── engine/
│   │   ├── services/
│   │   ├── prompts/
│   │   └── utils/
│   ├── data/
│   │   └── profiles/
│   │       └── default/
│   │           ├── raw/
│   │           ├── processed/
│   │           ├── exports/
│   │           ├── chroma/
│   │           └── database/
│   ├── cache/
│   ├── logs/
│   ├── tests/
│   ├── .venv/                 # Local only; do not commit
│   ├── .env                   # Local secrets; do not commit
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── public/
│   └── src/
│       ├── assets/
│       ├── components/
│       ├── pages/
│       ├── layouts/
│       ├── hooks/
│       ├── services/
│       ├── store/
│       ├── types/
│       ├── utils/
│       └── styles/
├── docs/
├── scripts/
├── .github/
│   ├── workflows/
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE/
├── .gitignore
└── README.md
```

This is a target structure, not a requirement to create every directory immediately. Add modules when the corresponding milestone needs them. Empty directories are not tracked by Git unless they contain files.

## 5. Text Architecture

### Ingestion and indexing pipeline

```text
Transcript file
      |
      v
Format-specific parser
      |
      v
Text normalization and validation
      |
      v
Structured message records
      |
      +------------------------------+
      |                              |
      v                              v
SQLite storage                 JSON export
      |
      v
Chunking and context grouping
      |
      v
Embedding generation
      |
      v
ChromaDB vector index
```

### Query and response pipeline

```text
User message
      |
      v
API validation
      |
      v
Conversation state and recent turns
      |
      v
Retrieve relevant historical passages
      |
      v
Optional reranking and context selection
      |
      v
Prompt assembly
      |
      v
LLM response generation
      |
      v
Response validation
      |
      +------------------------------+
      |                              |
      v                              v
Return reply                  Save live conversation
                                     |
                                     v
                              Optional live-memory update
```

### Memory layers

- **Historical memory:** Imported transcript messages and derived historical summaries. Treat source records as read-only after ingestion, except through an explicit re-import or correction workflow.
- **Semantic index:** Embeddings and metadata used to retrieve relevant passages. This can be rebuilt from the source records.
- **Conversation state:** Recent turns and the active topic for the current chat.
- **Live memory:** New facts explicitly introduced in chats after import. Keep this separate from historical data and label its origin.
- **Derived artifacts:** Summaries, topic groupings, entity references, and style statistics. These should be reproducible where practical.

## 6. Initial Data Model

Start with a small schema and extend it when requirements become concrete.

### Message
- `id`
- `profile_id`
- `conversation_id`
- `speaker`
- `text`
- `timestamp` (nullable)
- `source_page` (nullable)
- `sequence_number`
- `source_type` (for example, imported transcript)

### Conversation
- `id`
- `profile_id`
- `title` (nullable)
- `started_at` (nullable)
- `ended_at` (nullable)
- `summary` (nullable)

### Profile
- `id`
- `name`
- `created_at`
- `source_description` (optional)

### Memory record
- `id`
- `profile_id`
- `memory_type`
- `content`
- `source` (historical or live)
- `source_message_ids` or another provenance reference
- `created_at`

Do not store embedding vectors in ordinary message rows if the vector database is responsible for indexing them. Keep stable IDs so vector results can point back to source messages.

## 7. Response-Grounding Rules

The response generator should receive:
- The current user message
- A bounded amount of recent chat history
- Relevant retrieved transcript passages
- Applicable conversation summaries
- The selected profile's style configuration
- Clear instructions to distinguish evidence from inference

Recommended behavior:
- Use exact historical details only when supported by retrieved records.
- Do not present hypothetical generated dialogue as an authentic historical quotation.
- When retrieval is weak or contradictory, state uncertainty or ask a clarifying question.
- Keep citations or internal source IDs available for debugging and memory inspection.
- Avoid loading the entire transcript into every prompt; retrieve a small, relevant context window.

## 8. Follow-up and Conversation Continuity

The conversation engine should keep interaction natural without asking a question after every response.

A response may:
- Answer directly and stop
- Ask a relevant follow-up
- Refer to an earlier detail
- Continue a topic
- Suggest a related topic when appropriate

The follow-up decision should consider:
- Whether the user introduced something that invites a question
- Whether a relevant question was recently asked
- The active topic
- Recent conversation turns
- Patterns in the selected profile's historical dialogue, when available

Avoid repetitive questions and do not invent shared events. Store recent conversation state separately from imported historical messages.

## 9. API Outline

Initial endpoints can remain minimal:

- `GET /health` — health check
- `POST /profiles` — create a profile
- `GET /profiles` — list profiles
- `POST /profiles/{profile_id}/imports` — register or ingest a transcript
- `GET /profiles/{profile_id}/messages` — browse imported messages with pagination
- `POST /chat` — generate a reply using a selected profile and conversation session
- `GET /profiles/{profile_id}/memories/search?q=...` — search relevant historical records

Protect endpoints before exposing the application beyond localhost. Add authentication, request limits, and access controls before deployment.

## 10. Development Roadmap

### Milestone 1 — Repository and environment
- [ ] Confirm the repository structure
- [ ] Add `.gitignore`
- [ ] Create and activate a Python virtual environment
- [ ] Add `requirements.txt`
- [ ] Add `.env.example`
- [ ] Create a minimal FastAPI app
- [ ] Verify the health endpoint
- [ ] Commit the working baseline

**Exit criterion:** The backend starts locally and the health endpoint returns a successful response.

### Milestone 2 — Transcript parsing
- [ ] Identify the transcript format and its message delimiters
- [ ] Extract text from the source document
- [ ] Parse speaker names and timestamps where available
- [ ] Preserve message order
- [ ] Handle multiline messages and extraction artifacts
- [ ] Export normalized records to JSON
- [ ] Add parser tests using small representative samples

**Exit criterion:** A sample transcript is converted into ordered, validated message records without silently dropping content.

### Milestone 3 — Structured persistence
- [ ] Define SQLAlchemy models
- [ ] Initialize SQLite
- [ ] Import parsed messages transactionally
- [ ] Prevent accidental duplicate imports
- [ ] Add pagination and basic message search
- [ ] Test database operations

**Exit criterion:** Parsed records can be imported, queried, and re-exported consistently.

### Milestone 4 — Semantic retrieval
- [ ] Define an embedding interface
- [ ] Split long conversations into useful retrieval chunks
- [ ] Preserve message IDs and speaker metadata
- [ ] Generate embeddings in batches
- [ ] Index chunks in ChromaDB
- [ ] Retrieve relevant passages for sample queries
- [ ] Evaluate retrieval quality against known transcript examples

**Exit criterion:** Queries retrieve relevant passages with traceable source records.

### Milestone 5 — Summaries and structured references
- [ ] Generate summaries for conversation segments
- [ ] Extract candidate people, events, and topics
- [ ] Link extracted references to source messages
- [ ] Keep uncertain extractions marked as uncertain
- [ ] Provide a way to inspect and correct derived records

**Exit criterion:** Summaries and references can be traced back to the transcript.

### Milestone 6 — LLM integration and RAG
- [ ] Implement a provider-independent LLM service interface
- [ ] Load credentials from environment variables
- [ ] Assemble prompts from retrieved context and recent turns
- [ ] Generate grounded responses
- [ ] Handle API failures, timeouts, and rate limits
- [ ] Test cases where the transcript contains no answer

**Exit criterion:** The system answers transcript-based questions using relevant context and acknowledges missing evidence.

### Milestone 7 — Conversational continuity
- [ ] Maintain a session identifier
- [ ] Store recent turns
- [ ] Track the current topic
- [ ] Add adaptive follow-up question behavior
- [ ] Avoid duplicate or repetitive questions
- [ ] Separate live memory from imported history

**Exit criterion:** Multi-turn chats remain coherent, and newly introduced facts are not misrepresented as historical events.

### Milestone 8 — Style profile
- [ ] Calculate common vocabulary and phrases
- [ ] Analyze message length and punctuation patterns
- [ ] Measure language-mixing and emoji usage where relevant
- [ ] Create a configurable style profile
- [ ] Evaluate generated responses against the source's broad patterns
- [ ] Keep factual retrieval separate from style generation

**Exit criterion:** The application can apply a configurable conversational style without confusing generated content with transcript evidence.

### Milestone 9 — Frontend
- [ ] Initialize React, Vite, and TypeScript
- [ ] Build the chat interface
- [ ] Add loading, error, and empty states
- [ ] Connect the frontend to the FastAPI backend
- [ ] Add transcript search and memory inspection
- [ ] Display source context where useful

**Exit criterion:** A user can chat with a selected profile and inspect the memories used to answer.

### Milestone 10 — Quality and deployment readiness
- [ ] Add automated tests for parsing, retrieval, and APIs
- [ ] Add structured logging
- [ ] Validate uploads and file sizes
- [ ] Ensure secrets and private data are excluded from Git
- [ ] Document installation and configuration
- [ ] Add authentication and access controls before remote deployment
- [ ] Document backups and data deletion

**Exit criterion:** The app is reproducible locally, tested on representative cases, and has documented security and operational limitations.

## 11. Environment Configuration

Keep real secrets in a local `.env` file and exclude it from Git. Commit only a template such as:

```env
LLM_API_KEY=
LLM_MODEL=
EMBEDDING_PROVIDER=
EMBEDDING_MODEL=
DATABASE_URL=sqlite:///./data/profiles/default/database/echo.db
CHROMA_PATH=./data/profiles/default/chroma
```

Use the environment-variable names consistently in application code. Do not commit API keys, private transcripts, local databases, vector indexes, logs, or virtual environments.

## 12. Practical Build Order

Do not create every subsystem before it is needed. Build the smallest end-to-end slice first:

1. Start FastAPI.
2. Parse a small sample transcript.
3. Validate and store messages in SQLite.
4. Retrieve messages by keyword.
5. Add embeddings and semantic retrieval.
6. Connect an LLM to the retrieved context.
7. Add session history and follow-up behavior.
8. Add style analysis and the frontend.

This order provides working checkpoints and makes errors easier to isolate.

## 13. Definition of Done for the First Usable Version

The first usable version is complete when a user can:
1. Import a supported transcript.
2. Review and search the extracted messages.
3. Ask a question about the transcript.
4. Receive a response grounded in relevant source passages.
5. Continue a multi-turn conversation with relevant follow-up questions.
6. Inspect the context used for a response.
7. Keep new chat memories separate from the imported historical record.

The priority is reliable parsing and retrieval first; advanced agents, knowledge graphs, and deployment can follow after the core flow works.
