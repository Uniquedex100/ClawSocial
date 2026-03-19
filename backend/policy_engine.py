"""ArmorClaw — Policy Enforcement Engine.

Every action proposed by the reasoning layer must pass through ArmorClaw
before it reaches the OpenClaw executor. This module implements
deterministic blocking of unauthorized behaviour.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from models import ActionProposal, ActionType, Platform, Policy, PolicyResult, Verdict

logger = logging.getLogger("clawsocial.policy")


class ArmorClaw:
    """Runtime policy enforcement engine."""

    def __init__(self, policy: Optional[Policy] = None, policy_file: Optional[str] = None):
        if policy is not None:
            self.policy = policy
        elif policy_file and Path(policy_file).exists():
            self.policy = self._load_policy(policy_file)
        else:
            self.policy = Policy()  

        # Rate-limit counters
        self._posts_today: int = 0
        self._replies_this_hour: int = 0
        self._day_start: datetime = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        self._hour_start: datetime = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

        logger.info(
            "ArmorClaw initialised — allowed platforms: %s, allowed actions: %s",
            [p.value for p in self.policy.platform_restrictions],
            [a.value for a in self.policy.allowed_actions],
        )

    # ── Public API ───────────────────────────────────────────────────────

    def validate(self, proposal: ActionProposal) -> PolicyResult:
        """Validate a single action proposal against the active policy.

        Returns a PolicyResult with verdict ALLOW or BLOCK.
        """
        # 1. Platform check
        if proposal.platform not in self.policy.platform_restrictions:
            return self._block(
                proposal,
                f"Unauthorized platform: {proposal.platform.value}. "
                f"Allowed: {[p.value for p in self.policy.platform_restrictions]}",
            )

        # 2. Forbidden action check
        if proposal.action_type in self.policy.forbidden_actions:
            return self._block(
                proposal,
                f"Forbidden action: {proposal.action_type.value}",
            )

        # 3. Allowed action check
        if proposal.action_type not in self.policy.allowed_actions:
            return self._block(
                proposal,
                f"Action not in allowed list: {proposal.action_type.value}",
            )

        # 4. Content / blocked words check
        if proposal.content:
            for word in self.policy.blocked_words:
                if self._contains_blocked_word_variant(proposal.content, word):
                    return self._block(
                        proposal,
                        f"Content contains blocked word: '{word}'",
                    )

        # 5. Rate limit checks
        self._refresh_counters()

        # 5a. Batch guardrail checks
        batch_count = int(proposal.metadata.get("batch_count", 1) or 1)
        if batch_count > self.policy.max_batch_actions:
            return self._block(
                proposal,
                f"Batch guardrail exceeded: {batch_count}/{self.policy.max_batch_actions} actions in one request",
            )

        if proposal.action_type in (ActionType.PUBLISH_POST, ActionType.POST_TWEET, ActionType.SCHEDULE_POST):
            if self._posts_today >= self.policy.max_posts_per_day:
                return self._block(
                    proposal,
                    f"Rate limit exceeded: {self._posts_today}/{self.policy.max_posts_per_day} posts today",
                )

        if proposal.action_type == ActionType.REPLY_COMMENT:
            if self._replies_this_hour >= self.policy.max_replies_per_hour:
                return self._block(
                    proposal,
                    f"Rate limit exceeded: {self._replies_this_hour}/{self.policy.max_replies_per_hour} replies this hour",
                )

        # All checks passed
        return self._allow(proposal)

    def validate_batch(self, proposals: list[ActionProposal]) -> list[PolicyResult]:
        """Validate a list of proposals, returning results in order."""
        return [self.validate(p) for p in proposals]

    def record_execution(self, proposal: ActionProposal) -> None:
        """Update rate-limit counters after a successful execution."""
        if proposal.action_type in (ActionType.PUBLISH_POST, ActionType.POST_TWEET, ActionType.SCHEDULE_POST):
            self._posts_today += 1
        if proposal.action_type == ActionType.REPLY_COMMENT:
            self._replies_this_hour += 1

    def update_policy(self, policy: Policy) -> None:
        """Hot-swap the active policy."""
        self.policy = policy
        logger.info("Policy updated at runtime")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _allow(self, proposal: ActionProposal) -> PolicyResult:
        logger.info("[ALLOW] %s on %s", proposal.action_type.value, proposal.platform.value)
        return PolicyResult(action_id=proposal.id, verdict=Verdict.ALLOW, reason="Policy checks passed")

    def _block(self, proposal: ActionProposal, reason: str) -> PolicyResult:
        logger.warning("[BLOCK] %s on %s — %s", proposal.action_type.value, proposal.platform.value, reason)
        return PolicyResult(action_id=proposal.id, verdict=Verdict.BLOCK, reason=reason)

    def _refresh_counters(self) -> None:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        hour_start = now.replace(minute=0, second=0, microsecond=0)

        if day_start > self._day_start:
            self._posts_today = 0
            self._day_start = day_start

        if hour_start > self._hour_start:
            self._replies_this_hour = 0
            self._hour_start = hour_start

    @staticmethod
    def _contains_blocked_word_variant(content: str, blocked_word: str) -> bool:
        """Match blocked words with light variant handling.

        Examples:
        - politics -> blocks politics, political
        - religion -> blocks religion, religions
        """
        text = str(content or "").lower()
        blocked = str(blocked_word or "").strip().lower()
        if not blocked:
            return False

        # Keep exact substring behavior for compatibility.
        if blocked in text:
            return True

        # Add a lightweight stem check for nearby variants.
        stem = blocked[:-1] if blocked.endswith("s") and len(blocked) > 3 else blocked
        pattern = rf"\b{re.escape(stem)}[a-z]*\b"
        return re.search(pattern, text) is not None

    @staticmethod
    def _load_policy(path: str) -> Policy:
        with open(path) as f:
            return Policy(**json.load(f))
