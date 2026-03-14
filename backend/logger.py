"""Structured action logger — full traceability for every pipeline step."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from models import (
    ActionLog,
    ActionProposal,
    ExecutionResult,
    Intent,
    PolicyResult,
    Verdict,
)

# ── Module-level setup ───────────────────────────────────────────────────

_log_store: list[ActionLog] = []
_logger = logging.getLogger("clawsocial")


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """Configure root logger for the application."""
    fmt = logging.Formatter(
        "[%(asctime)s] %(name)s %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    _logger.addHandler(handler)
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        _logger.addHandler(fh)


# ── Logging helpers ──────────────────────────────────────────────────────

def log_intent(intent: Intent) -> None:
    """Log a parsed intent."""
    _logger.info(
        "[INTENT] %s | platform=%s | actions=%s",
        intent.intent,
        intent.platform.value,
        [a.value for a in intent.actions_allowed],
    )


def log_action(
    intent: Intent,
    proposal: ActionProposal,
    policy_result: PolicyResult,
    execution_result: Optional[ExecutionResult] = None,
) -> ActionLog:
    """Create and store a full audit-trail entry."""
    entry = ActionLog(
        timestamp=datetime.now(UTC),
        intent=intent.intent,
        action_id=proposal.id,
        action_type=proposal.action_type.value,
        platform=proposal.platform.value,
        content=proposal.content,
        verdict=policy_result.verdict,
        reason=policy_result.reason,
        executed=execution_result.success if execution_result else False,
        execution_detail=execution_result.detail if execution_result else "",
    )
    _log_store.append(entry)

    tag = "EXECUTED" if entry.executed else ("BLOCKED" if entry.verdict == Verdict.BLOCK else "SKIPPED")
    _logger.info(
        "[%s] action=%s platform=%s | %s",
        tag,
        entry.action_type,
        entry.platform,
        entry.reason or entry.execution_detail,
    )
    return entry


def get_logs() -> list[ActionLog]:
    """Return all stored log entries."""
    return list(_log_store)


def clear_logs() -> None:
    """Clear stored logs."""
    _log_store.clear()


def export_logs_json() -> str:
    """Export all logs as a JSON string."""
    return json.dumps(
        [entry.model_dump(mode="json") for entry in _log_store],
        indent=2,
        default=str,
    )
