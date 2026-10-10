"""Tree Loss Receipt - FastAPI backend (scaffold)."""
from fastapi import FastAPI

app = FastAPI(
    title="Tree Loss Receipt API",
    version="0.1.0",
    description="Local-first API that quantifies urban tree-loss impacts as ranges.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
