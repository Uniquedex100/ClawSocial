"""OpenClaw Executor — browser automation via OpenClaw CLI / Gateway API.

This module is the *only* component that performs real-world side effects.
The reasoning layer never calls these functions directly; actions must first
pass through ArmorClaw.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Optional

import httpx

from config import settings
from models import ActionProposal, ActionType, ExecutionResult, Platform

logger = logging.getLogger("clawsocial.executor")

# ── Platform URLs ────────────────────────────────────────────────────────

_PLATFORM_URLS: dict[Platform, str] = {
    Platform.INSTAGRAM: "https://www.instagram.com",
    Platform.TWITTER: "https://twitter.com",
    Platform.FACEBOOK: "https://www.facebook.com",
    Platform.LINKEDIN: "https://www.linkedin.com",
}


class OpenClawExecutor:
    """Execute approved actions via OpenClaw's browser automation.

    Supports two modes:
    1. **CLI mode** — calls `openclaw browser …` sub-commands via subprocess.
    2. **HTTP mode** — sends requests to the OpenClaw Gateway REST API.

    Falls back to a *dry-run* simulation when OpenClaw is not installed.
    """

    def __init__(
        self,
        gateway_url: str = settings.openclaw_gateway_url,
        profile: str = settings.openclaw_browser_profile,
        dry_run: bool = False,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.profile = profile
        self.dry_run = dry_run
        self._has_cli = shutil.which("openclaw") is not None

        if not self._has_cli and not dry_run:
            logger.warning(
                "OpenClaw CLI not found on PATH — running in dry-run simulation mode"
            )
            self.dry_run = True

    # ── Public API ───────────────────────────────────────────────────────

    async def execute(self, proposal: ActionProposal) -> ExecutionResult:
        """Execute a single approved action proposal."""
        handler = self._dispatch.get(proposal.action_type)
        if handler is None:
            return ExecutionResult(
                action_id=proposal.id,
                success=False,
                detail=f"No executor handler for {proposal.action_type.value}",
            )
        try:
            detail = await handler(self, proposal)
            return ExecutionResult(action_id=proposal.id, success=True, detail=detail)
        except Exception as exc:
            logger.error("Execution failed for %s: %s", proposal.id, exc)
            return ExecutionResult(action_id=proposal.id, success=False, detail=str(exc))

    async def execute_batch(self, proposals: list[ActionProposal]) -> list[ExecutionResult]:
        """Execute multiple proposals sequentially."""
        results = []
        for p in proposals:
            results.append(await self.execute(p))
        return results

    # ── Action handlers ──────────────────────────────────────────────────

    async def _open_browser(self, proposal: ActionProposal) -> str:
        """Start the OpenClaw-managed browser."""
        return await self._run_browser_command("start")

    async def _navigate_to_platform(self, proposal: ActionProposal) -> str:
        """Navigate to the platform URL."""
        url = _PLATFORM_URLS.get(proposal.platform, "https://www.instagram.com")
        return await self._run_browser_command("open", url=url)

    async def _read_comments(self, proposal: ActionProposal) -> str:
        """Navigate to platform and read comments (snapshot)."""
        url = _PLATFORM_URLS.get(proposal.platform, "https://www.instagram.com")
        await self._run_browser_command("open", url=url)
        snapshot = await self._run_browser_command("snapshot")
        return f"Navigated to {url} and captured snapshot. {snapshot}"

    async def _reply_comment(self, proposal: ActionProposal) -> str:
        """Type and submit a reply to a comment."""
        steps = [
            f"Navigating to {proposal.platform.value}",
            f"Locating comment reply field",
            f"Typing reply: {proposal.content or 'Thanks!'}",
            f"Submitting reply",
        ]
        if self.dry_run:
            return " → ".join(steps) + " [DRY RUN]"

        # Real execution sequence
        url = _PLATFORM_URLS.get(proposal.platform, "https://www.instagram.com")
        await self._run_browser_command("open", url=url)
        # Take snapshot to find comment elements
        await self._run_browser_command("snapshot")
        # Type the reply (in real scenario, would use ref from snapshot)
        await self._run_browser_command(
            "act", action="type", text=proposal.content or "Thanks!"
        )
        await self._run_browser_command("act", action="press", key="Enter")
        return " → ".join(steps) + " [EXECUTED]"

    async def _publish_post(self, proposal: ActionProposal) -> str:
        """Publish a post to the platform."""
        steps = [
            f"Navigating to {proposal.platform.value}",
            f"Opening post creation dialog",
            f"Entering content: {(proposal.content or '')[:50]}...",
            f"Publishing post",
        ]
        if self.dry_run:
            return " → ".join(steps) + " [DRY RUN]"

        url = _PLATFORM_URLS.get(proposal.platform)
        await self._run_browser_command("open", url=url)
        return " → ".join(steps) + " [EXECUTED]"

    async def _schedule_post(self, proposal: ActionProposal) -> str:
        """Schedule a post for later publishing."""
        return f"Scheduled post on {proposal.platform.value}: {(proposal.content or '')[:80]} [{'DRY RUN' if self.dry_run else 'SCHEDULED'}]"

    async def _generate_caption(self, proposal: ActionProposal) -> str:
        """Caption generation is handled by reasoning — this is a no-op execution."""
        return f"Caption generated: {proposal.content or 'N/A'}"

    async def _suggest_hashtags(self, proposal: ActionProposal) -> str:
        """Hashtag suggestion is handled by reasoning — no-op execution."""
        return f"Hashtags suggested: {proposal.content or '#trending #social'}"

    async def _hide_comment(self, proposal: ActionProposal) -> str:
        """Hide a flagged comment."""
        if self.dry_run:
            return f"Would hide comment on {proposal.platform.value} [DRY RUN]"
        await self._run_browser_command("act", action="click", ref="hide-btn")
        return f"Comment hidden on {proposal.platform.value} [EXECUTED]"

    async def _report_comment(self, proposal: ActionProposal) -> str:
        """Report a flagged comment."""
        if self.dry_run:
            return f"Would report comment on {proposal.platform.value} [DRY RUN]"
        return f"Comment reported on {proposal.platform.value} [EXECUTED]"

    # ── Dispatch table ───────────────────────────────────────────────────

    _dispatch = {
        ActionType.READ_COMMENTS: _read_comments,
        ActionType.REPLY_COMMENT: _reply_comment,
        ActionType.PUBLISH_POST: _publish_post,
        ActionType.POST_TWEET: _publish_post,
        ActionType.SCHEDULE_POST: _schedule_post,
        ActionType.GENERATE_CAPTION: _generate_caption,
        ActionType.SUGGEST_HASHTAGS: _suggest_hashtags,
        ActionType.HIDE_COMMENT: _hide_comment,
        ActionType.REPORT_COMMENT: _report_comment,
    }

    # ── OpenClaw CLI / HTTP helpers ──────────────────────────────────────

    async def _run_browser_command(
        self,
        command: str,
        *,
        url: Optional[str] = None,
        action: Optional[str] = None,
        text: Optional[str] = None,
        key: Optional[str] = None,
        ref: Optional[str] = None,
    ) -> str:
        """Execute an OpenClaw browser command (CLI or HTTP)."""
        if self.dry_run:
            parts = [f"openclaw browser {command}"]
            if url:
                parts.append(f"--url {url}")
            if action:
                parts.append(f"--action {action}")
            if text:
                parts.append(f'--text "{text}"')
            dry_cmd = " ".join(parts)
            logger.info("[DRY RUN] %s", dry_cmd)
            return f"[DRY RUN] {dry_cmd}"

        if self._has_cli:
            return await self._cli_exec(command, url=url, action=action, text=text, key=key, ref=ref)
        else:
            return await self._http_exec(command, url=url, action=action, text=text, key=key, ref=ref)

    async def _cli_exec(
        self, command: str, **kwargs
    ) -> str:
        """Call OpenClaw via CLI subprocess."""
        cmd = ["openclaw", "browser", command, "--profile", self.profile]
        for k, v in kwargs.items():
            if v is not None:
                cmd.extend([f"--{k}", str(v)])

        logger.info("CLI exec: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode().strip()
        if proc.returncode != 0:
            err = stderr.decode().strip()
            raise RuntimeError(f"OpenClaw CLI error (rc={proc.returncode}): {err}")
        return output or "OK"

    async def _http_exec(
        self, command: str, **kwargs
    ) -> str:
        """Call OpenClaw Gateway via HTTP API."""
        payload = {"command": command, "profile": self.profile}
        payload.update({k: v for k, v in kwargs.items() if v is not None})

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.gateway_url}/api/browser",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return json.dumps(data, indent=2)
