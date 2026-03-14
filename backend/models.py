"""Pydantic models for the ClawSocial agent pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────

class Platform(str, Enum):
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    FACEBOOK = "facebook"
    LINKEDIN = "linkedin"


class ActionType(str, Enum):
    READ_COMMENTS = "read_comments"
    REPLY_COMMENT = "reply_comment"
    SCHEDULE_POST = "schedule_post"
    PUBLISH_POST = "publish_post"
    GENERATE_CAPTION = "generate_caption"
    SUGGEST_HASHTAGS = "suggest_hashtags"
    HIDE_COMMENT = "hide_comment"
    REPORT_COMMENT = "report_comment"
    DELETE_POST = "delete_post"
    SEND_DM = "send_dm"
    CHANGE_PROFILE = "change_profile"
    POST_TWEET = "post_tweet"


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    SPAM = "spam"
    ABUSIVE = "abusive"


# ── Intent ───────────────────────────────────────────────────────────────

class Intent(BaseModel):
    """Structured representation of a user instruction."""

    intent: str = Field(..., description="Task category, e.g. engagement_management")
    platform: Platform
    actions_allowed: list[ActionType] = Field(default_factory=list)
    content_generation: bool = False
    publish_allowed: bool = False
    time_scope: str = Field("today", description="Execution window")


# ── Policy ───────────────────────────────────────────────────────────────

class Policy(BaseModel):
    """Runtime constraints enforced by ArmorClaw."""

    platform_restrictions: list[Platform] = Field(
        default_factory=lambda: [Platform.INSTAGRAM],
        description="Platforms the agent is allowed to operate on",
    )
    blocked_words: list[str] = Field(
        default_factory=lambda: ["politics", "religion"],
    )
    max_posts_per_day: int = 3
    max_replies_per_hour: int = 20
    allowed_actions: list[ActionType] = Field(
        default_factory=lambda: [
            ActionType.READ_COMMENTS,
            ActionType.REPLY_COMMENT,
            ActionType.SCHEDULE_POST,
            ActionType.GENERATE_CAPTION,
            ActionType.SUGGEST_HASHTAGS,
        ],
    )
    forbidden_actions: list[ActionType] = Field(
        default_factory=lambda: [
            ActionType.DELETE_POST,
            ActionType.SEND_DM,
            ActionType.CHANGE_PROFILE,
        ],
    )


# ── Action Proposal ─────────────────────────────────────────────────────

class ActionProposal(BaseModel):
    """An action proposed by the reasoning layer."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    action_type: ActionType
    platform: Platform
    content: Optional[str] = None
    intent_token: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    reasoning: str = Field("", description="Why the engine chose this action")


# ── Policy Result ────────────────────────────────────────────────────────

class PolicyResult(BaseModel):
    """Outcome of ArmorClaw policy validation."""

    action_id: str
    verdict: Verdict
    reason: str = ""


# ── Execution Result ─────────────────────────────────────────────────────

class ExecutionResult(BaseModel):
    """Outcome of OpenClaw execution."""

    action_id: str
    success: bool
    detail: str = ""


# ── Action Log ───────────────────────────────────────────────────────────

class ActionLog(BaseModel):
    """Full audit trail entry for a single action."""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    intent: str = ""
    action_id: str = ""
    action_type: str = ""
    platform: str = ""
    content: Optional[str] = None
    verdict: Verdict = Verdict.ALLOW
    reason: str = ""
    executed: bool = False
    execution_detail: str = ""


# ── Task Request / Response ──────────────────────────────────────────────

class TaskRequest(BaseModel):
    """API request body for submitting a new task."""

    instruction: str = Field(..., description="Natural language instruction")


class TaskResult(BaseModel):
    """API response for a completed task."""

    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    instruction: str
    intent: Optional[Intent] = None
    proposals: list[ActionProposal] = Field(default_factory=list)
    policy_results: list[PolicyResult] = Field(default_factory=list)
    execution_results: list[ExecutionResult] = Field(default_factory=list)
    logs: list[ActionLog] = Field(default_factory=list)
    status: str = "completed"
