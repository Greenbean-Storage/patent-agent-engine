from __future__ import annotations

from fastapi import FastAPI
from venezia_logging import get_logger, setup_logging

# AWS Secrets Manager — inject env vars before config is read
from . import secrets  # noqa: F401
from .router import router

setup_logging()
log = get_logger()

app = FastAPI(title="Memory Manager", version="2.0.0")
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
