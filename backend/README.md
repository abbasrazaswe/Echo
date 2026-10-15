# Echo backend — first checkpoint

This checkpoint runs a local HTTP server with a health endpoint. It does not
require API keys, a database, or transcript files.

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
Stop the server with **Ctrl+C**. A request to `/` returns 404 because we have
only defined `/health` so far.

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
check an AI provider or database; those will be introduced in later checkpoints.

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

The parser is a command-line tool for this checkpoint; it is not connected to
the HTTP API or a database yet.

### Parser tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The tests exercise message boundaries, date ambiguity, Unicode, system notices,
invalid input, JSON export, and protection against overwriting source files.
