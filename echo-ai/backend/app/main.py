from fastapi import FastAPI


app = FastAPI(title="Echo API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    """Confirm that the API is running and can handle requests."""
    return {"status": "ok"}
