"""Delegation — sub-agents with bounded authority.

Each sub-agent has its own restricted policy scope.  Attempts to act
outside the delegated boundary are deterministically BLOCKED,
demonstrating the "bounded delegation" concept from the spec.
"""

from __future__ import annotations

import logging
from typing import Optional

from models import (
    ActionProposal,
    ActionType,
    ExecutionResult,
    Platform,
    Policy,
    PolicyResult,
    Verdict,
)
from policy_engine import ArmorClaw

logger = logging.getLogger("clawsocial.delegation")


class SubAgent:
    """A sub-agent with restricted authority enforced by its own ArmorClaw."""

    def __init__(
        self,
        name: str,
        allowed_actions: list[ActionType],
        allowed_platforms: list[Platform] | None = None,
        can_publish: bool = False,
    ):
        self.name = name
        self.can_publish = can_publish

        # Build a scoped policy for this sub-agent
        all_actions = list(allowed_actions)
        forbidden = [
            a for a in ActionType
            if a not in all_actions
        ]

        self._policy = Policy(
            platform_restrictions=allowed_platforms or [Platform.INSTAGRAM],
            allowed_actions=all_actions,
            forbidden_actions=forbidden,
            blocked_words=["politics", "religion"],
            max_posts_per_day=0 if not can_publish else 3,
            max_replies_per_hour=20,
        )
        self._armor = ArmorClaw(policy=self._policy)
        logger.info(
            "Sub-agent '%s' created — allowed: %s, can_publish=%s",
            name,
            [a.value for a in all_actions],
            can_publish,
        )

    def validate(self, proposal: ActionProposal) -> PolicyResult:
        """Validate an action against this sub-agent's delegated authority."""
        result = self._armor.validate(proposal)
        if result.verdict == Verdict.BLOCK:
            result.reason = f"[{self.name}] {result.reason} — outside delegated authority"
        return result

    def record_execution(self, proposal: ActionProposal) -> None:
        """Record successful delegated action execution for rate-limit accounting."""
        self._armor.record_execution(proposal)


# ── Pre-built sub-agents ─────────────────────────────────────────────────

def create_content_agent() -> SubAgent:
    """Content Agent — can generate captions and hashtags, cannot publish."""
    return SubAgent(
        name="ContentAgent",
        allowed_actions=[
            ActionType.GENERATE_CAPTION,
            ActionType.SUGGEST_HASHTAGS,
        ],
        can_publish=False,
    )


def create_engagement_agent() -> SubAgent:
    """Engagement Agent — can read/reply comments, cannot publish posts."""
    return SubAgent(
        name="EngagementAgent",
        allowed_actions=[
            ActionType.READ_COMMENTS,
            ActionType.REPLY_COMMENT,
        ],
        can_publish=False,
    )


def create_moderation_agent() -> SubAgent:
    """Moderation Agent — can read, hide, and report comments."""
    return SubAgent(
        name="ModerationAgent",
        allowed_actions=[
            ActionType.READ_COMMENTS,
            ActionType.HIDE_COMMENT,
            ActionType.REPORT_COMMENT,
        ],
        can_publish=False,
    )
