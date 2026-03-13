"""ClawSocial — FastAPI application entry point."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import settings
from logger import setup_logging
from routes import router

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    setup_logging(level=settings.log_level, log_file=settings.log_file)
    yield


app = FastAPI(
    title="ClawSocial",
    description=(
        "Intent-Safe Autonomous Social Media Agent powered by OpenClaw. "
        "Autonomous execution with runtime policy enforcement (ArmorClaw)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

# ── Serve frontend static files ─────────────────────────────────────────

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def root():
    """Serve the frontend dashboard."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {
        "name": "ClawSocial",
        "version": "0.1.0",
        "description": "Intent-Safe Autonomous Social Media Agent",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
