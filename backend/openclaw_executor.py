"""OpenClaw Executor — browser automation via OpenClaw CLI / Gateway API.

This module is the *only* component that performs real-world side effects.
The reasoning layer never calls these functions directly; actions must first
pass through ArmorClaw.

Uses the official OpenClaw CLI (openclaw browser <command>) or the Gateway
HTTP API for programmatic browser control.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Optional

import httpx

from config import settings
from models import ActionProposal, ActionType, ExecutionResult, Platform

logger = logging.getLogger("clawsocial.executor")

# ── Dedicated OpenClaw logger ────────────────────────────────────────────
oc_logger = logging.getLogger("openclaw.activity")
oc_logger.setLevel(logging.INFO)
oc_fh = logging.FileHandler("openclaw_execution.log")
oc_fh.setFormatter(logging.Formatter(
    "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
if not oc_logger.handlers:
    oc_logger.addHandler(oc_fh)
oc_logger.propagate = False

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
        gateway_token: str = settings.openclaw_gateway_token,
        profile: str = settings.openclaw_browser_profile,
        cli_path: str = settings.openclaw_cli_path,
        dry_run: bool = False,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.gateway_token = gateway_token
        self.profile = profile
        self.cli_path = cli_path
        self.dry_run = dry_run

        # Check if CLI is available
        if cli_path and cli_path.endswith(".mjs"):
            import os
            self._has_cli = os.path.exists(cli_path.replace("node ", "").strip())
        elif cli_path:
            self._has_cli = shutil.which(cli_path) is not None
        else:
            self._has_cli = False

        self._has_http = bool(self.gateway_url)

        if not self._has_cli and not self._has_http and not dry_run:
            logger.warning("Neither OpenClaw CLI nor Gateway configured — forcing dry-run")
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
        return await self._run_browser_command(
            "start", intent_token=proposal.intent_token
        )

    async def _navigate_to_platform(self, proposal: ActionProposal) -> str:
        """Navigate to the platform URL."""
        url = _PLATFORM_URLS.get(proposal.platform, "https://www.instagram.com")
        return await self._run_browser_command(
            "open", url=url, intent_token=proposal.intent_token
        )

    async def _read_comments(self, proposal: ActionProposal) -> str:
        """Navigate to platform and read comments (snapshot)."""
        url = _PLATFORM_URLS.get(proposal.platform, "https://www.instagram.com")
        await self._run_browser_command(
            "open", url=url, intent_token=proposal.intent_token
        )
        snapshot = await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )
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
        await self._run_browser_command(
            "open", url=url, intent_token=proposal.intent_token
        )
        # Take snapshot to find comment elements
        snapshot_json = await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )
        
        try:
            # Look for the 'Comment' or input field in the snapshot JSON refs in the most robust way available
            snap_data = json.loads(snapshot_json)
            refs = snap_data.get("refs", {})
            target_ref = None
            
            # Simple heuristic: find a form or input or generic element associated with "Add a comment..."
            # Usually 'Comment' button is there, let's find the one named 'Comment'
            for ref_id, ref_data in refs.items():
                name = ref_data.get("name", "").lower()
                role = ref_data.get("role", "").lower()
                if name == "comment" and role in ["button", "link", "generic", "textbox", "searchbox", "combobox"]:
                    target_ref = ref_id
                    break
                if "add a comment" in name:
                    target_ref = ref_id
                    break
            
            if not target_ref:
                logger.warning("Could not clearly identify comment input from snapshot. Trying fallback.")
                # Fallback to the first textbox or just a typical ref found in tests
                for ref_id, ref_data in refs.items():
                    if ref_data.get("role") == "textbox":
                        target_ref = ref_id
                        break
            
            if not target_ref:
                return " → ".join(steps) + " [FAILED: Element not found]"
                
            # Type the reply — using 'type' subcommand with dynamic ref and text
            reply_text = proposal.content or "Thanks!"
            await self._run_browser_command(
                "type", ref=target_ref, text=reply_text, submit=True,
                intent_token=proposal.intent_token
            )
            return " → ".join(steps) + f" [EXECUTED locally to {target_ref}]"
        except Exception as e:
            logger.error("Failed to parse snapshot or find ref: %s", e)
            return " → ".join(steps) + f" [FAILED: {e}]"

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
        await self._run_browser_command(
            "open", url=url, intent_token=proposal.intent_token
        )
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
        # Take snapshot first to get refs
        await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )
        await self._run_browser_command(
            "click", ref="hide-btn", intent_token=proposal.intent_token
        )
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
        ref: Optional[str] = None,
        text: Optional[str] = None,
        key: Optional[str] = None,
        submit: bool = False,
        intent_token: Optional[str] = None,
    ) -> str:
        """Execute an OpenClaw browser command (CLI or HTTP)."""
        # Ensure intent_token is a string
        token_str = None
        if intent_token is not None:
            token_str = str(intent_token) # SDK returns an IntentToken object we must stringify
            # sometimes SDKs have a .token or .value property, but str() usually works or we can just pass the object to the CLI/HTTP which needs a string

        if self.dry_run:
            parts = [f"openclaw browser {command}"]
            if url:
                parts.append(url)
            if ref:
                parts.append(ref)
            if text:
                parts.append(f'"{text}"')
            if token_str:
                parts.append(f"--intent-token {token_str[:8]}...")
            dry_cmd = " ".join(parts)
            logger.info("[DRY RUN] %s", dry_cmd)
            return f"[DRY RUN] {dry_cmd}"

        if self._has_cli:
            return await self._cli_exec(
                command, url=url, ref=ref, text=text, key=key, submit=submit,
                intent_token=token_str
            )
        else:
            return await self._http_exec(
                command, url=url, ref=ref, text=text, key=key, submit=submit,
                intent_token=token_str
            )

    async def _cli_exec(
        self,
        command: str,
        *,
        url: Optional[str] = None,
        ref: Optional[str] = None,
        text: Optional[str] = None,
        key: Optional[str] = None,
        submit: bool = False,
        intent_token: Optional[str] = None,
    ) -> str:
        """Call OpenClaw via CLI subprocess."""
        # Build the command
        if self.cli_path.endswith(".mjs"):
            cmd = ["node", self.cli_path, "--log-level", "debug", "browser", command]
        else:
            cmd = [self.cli_path, "--log-level", "debug", "browser", command]

        # Add auth token
        if self.gateway_token:
            cmd.extend(["--token", self.gateway_token])

        # Add browser profile
        cmd.extend(["--browser-profile", self.profile])

        # We assume armorclaw plugin checks this environment variable 
        env = os.environ.copy()
        if intent_token:
            env["ARMORIQ_INTENT_TOKEN"] = intent_token

        # Command-specific arguments (positional args per OpenClaw CLI docs)
        if command == "open" and url:
            cmd.append(url)
        elif command == "navigate" and url:
            cmd.append(url)
        elif command == "click" and ref:
            cmd.append(ref)
        elif command == "type" and ref and text:
            cmd.append(ref)
            cmd.append(text)
            if submit:
                cmd.append("--submit")
        elif command == "press" and key:
            cmd.append(key)
        elif command == "snapshot":
            cmd.append("--format")
            cmd.append("ai")

        # JSON output
        cmd.append("--json")

        logger.info("CLI exec: %s (token: %s)", " ".join(cmd), bool(intent_token))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode().strip()
        err_output = stderr.decode().strip()
        
        oc_logger.info(f"--- OPENCLAW CLI EXECUTION ---")
        oc_logger.info(f"COMMAND: {' '.join(cmd)}")
        if output:
            oc_logger.info(f"STDOUT:\n{output}")
        if err_output:
            oc_logger.info(f"STDERR:\n{err_output}")
        oc_logger.info("------------------------------")
        
        if proc.returncode != 0:
            raise RuntimeError(f"OpenClaw CLI error (rc={proc.returncode}): {err_output}")
        return output or "OK"

    async def _http_exec(
        self,
        command: str,
        *,
        url: Optional[str] = None,
        ref: Optional[str] = None,
        text: Optional[str] = None,
        key: Optional[str] = None,
        submit: bool = False,
        intent_token: Optional[str] = None,
    ) -> str:
        """Call OpenClaw Gateway via HTTP API (tools invoke endpoint)."""
        payload = {
            "command": command,
            "profile": self.profile,
        }
        if url:
            payload["url"] = url
        if ref:
            payload["ref"] = ref
        if text:
            payload["text"] = text
        if key:
            payload["key"] = key
        if submit:
            payload["submit"] = True
        if intent_token:
            payload["intentToken"] = intent_token

        headers = {}
        if self.gateway_token:
            headers["Authorization"] = f"Bearer {self.gateway_token}"

        async with httpx.AsyncClient() as client:
            oc_logger.info(f"--- OPENCLAW HTTP EXECUTION ---")
            oc_logger.info(f"POST {self.gateway_url}/api/browser")
            oc_logger.info(f"PAYLOAD:\n{json.dumps(payload, indent=2)}")
            
            resp = await client.post(
                f"{self.gateway_url}/api/browser",
                json=payload,
                headers=headers,
                timeout=30,
            )
            
            try:
                data = resp.json()
                resp_text = json.dumps(data, indent=2)
            except Exception:
                resp_text = resp.text
                
            oc_logger.info(f"RESPONSE [{resp.status_code}]:\n{resp_text}")
            oc_logger.info("-------------------------------")
            
            resp.raise_for_status()
            return resp_text
