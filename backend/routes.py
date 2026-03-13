"""FastAPI route handlers for ClawSocial."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent import ClawSocialAgent
from delegation import (
    create_content_agent,
    create_engagement_agent,
    create_moderation_agent,
)
from logger import clear_logs, export_logs_json, get_logs
from models import ActionLog, Policy, TaskRequest, TaskResult
from policy_engine import ArmorClaw

router = APIRouter()

# ── Shared state ─────────────────────────────────────────────────────────

_policy_engine = ArmorClaw()
_agent = ClawSocialAgent(policy_engine=_policy_engine, dry_run=True)


# ── Task endpoints ───────────────────────────────────────────────────────


@router.post("/task", response_model=TaskResult, tags=["Tasks"])
async def submit_task(req: TaskRequest):
    """Submit a natural-language instruction for the agent to handle."""
    result = await _agent.run(req.instruction)
    return result


# ── Demo endpoints ───────────────────────────────────────────────────────


@router.post("/demo/allowed", response_model=TaskResult, tags=["Demo"])
async def demo_allowed():
    """Demo: allowed action — 'Reply to comments on Instagram.'"""
    result = await _agent.run("Reply to comments on Instagram today.")
    return result


@router.post("/demo/blocked", response_model=TaskResult, tags=["Demo"])
async def demo_blocked():
    """Demo: blocked action — 'Post this tweet.'"""
    result = await _agent.run("Post this tweet on Twitter.")
    return result


@router.post("/demo/delegation", response_model=TaskResult, tags=["Demo"])
async def demo_delegation():
    """Demo: bounded delegation — engagement agent tries to publish a post."""
    engagement = create_engagement_agent()
    result = await _agent.run_with_subagent(
        "Publish a new post on Instagram.",
        subagent=engagement,
    )
    return result


# ── Policy endpoints ─────────────────────────────────────────────────────


@router.get("/policy", response_model=Policy, tags=["Policy"])
async def get_policy():
    """View the current active policy."""
    return _policy_engine.policy


@router.put("/policy", response_model=Policy, tags=["Policy"])
async def update_policy(policy: Policy):
    """Update the active policy at runtime."""
    _policy_engine.update_policy(policy)
    return _policy_engine.policy


# ── Log endpoints ────────────────────────────────────────────────────────


@router.get("/logs", response_model=list[ActionLog], tags=["Logs"])
async def list_logs():
    """Retrieve all action logs."""
    return get_logs()


@router.get("/logs/export", tags=["Logs"])
async def export_logs():
    """Export all logs as JSON."""
    from fastapi.responses import JSONResponse
    import json

    return JSONResponse(content=json.loads(export_logs_json()))


@router.delete("/logs", tags=["Logs"])
async def delete_logs():
    """Clear all stored logs."""
    clear_logs()
    return {"status": "cleared"}
