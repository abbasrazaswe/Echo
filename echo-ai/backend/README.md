# Echo backend — first checkpoint

This checkpoint runs a local HTTP server with a health endpoint. It does not
require API keys, a database, or transcript files.

## Setup (macOS/Linux)

From the repository root:

```sh
cd echo-ai/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The virtual environment keeps this project's Python packages separate from
other projects. Activate it again whenever you open a new terminal.

## Run

From `echo-ai/backend`, with the virtual environment active:

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
