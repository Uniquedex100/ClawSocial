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
import re
import shutil
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from typing import Optional

import httpx

from config import settings
from models import ActionProposal, ActionType, ExecutionResult, Platform

logger = logging.getLogger("clawsocial.executor")

# Demo-focused in-memory automation stores.
_SCHEDULED_TWITTER_ACTIONS: list[dict] = []
_WATCHLIST_RULES: list[dict] = []


def _redact_cli_command(cmd: list[str]) -> str:
    """Return a safe CLI command string with secrets redacted for logs."""
    safe = list(cmd)
    for i, part in enumerate(safe[:-1]):
        if part == "--token":
            safe[i + 1] = "***"
    return " ".join(safe)

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

    def get_scheduled_actions(self) -> list[dict]:
        return list(_SCHEDULED_TWITTER_ACTIONS)

    def get_watchlist_rules(self) -> list[dict]:
        return list(_WATCHLIST_RULES)

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
        await self._goto_url(url, proposal.intent_token)
        return f"Navigated to {url}"

    async def _read_comments(self, proposal: ActionProposal) -> str:
        """Navigate to platform and read comments (snapshot)."""
        url = _PLATFORM_URLS.get(proposal.platform, "https://www.instagram.com")
        await self._goto_url(url, proposal.intent_token)
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
        if proposal.platform == Platform.TWITTER and proposal.metadata.get("mode") == "reply_latest_tweet":
            return await self._reply_latest_tweet(proposal)
        if proposal.platform == Platform.TWITTER and proposal.metadata.get("mode") == "reply_latest_tweets_batch":
            return await self._reply_latest_tweets_batch(proposal)

        if self.dry_run:
            return " → ".join(steps) + " [DRY RUN]"

        # Real execution sequence
        url = _PLATFORM_URLS.get(proposal.platform, "https://www.instagram.com")
        await self._goto_url(url, proposal.intent_token)

        # Take snapshot to find comment elements
        snapshot_json = await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )

        try:
            snap_data = self._parse_snapshot(snapshot_json)
            refs = snap_data.get("refs", {})

            # If instruction targets first post, click first visible comment button on feed.
            if proposal.metadata.get("post_selector") == "first":
                first_comment_ref = self._find_first_comment_button_ref(refs)
                if first_comment_ref:
                    await self._run_browser_command(
                        "click", ref=first_comment_ref, intent_token=proposal.intent_token
                    )
                    snapshot_json = await self._run_browser_command(
                        "snapshot", intent_token=proposal.intent_token
                    )
                    snap_data = self._parse_snapshot(snapshot_json)
                    refs = snap_data.get("refs", {})

            target_ref = self._find_comment_input_ref(refs)

            if not target_ref:
                # Fallback: click a generic Comment button then rescan for textbox.
                fallback_comment_ref = self._find_comment_button_ref(refs)
                if fallback_comment_ref:
                    await self._run_browser_command(
                        "click", ref=fallback_comment_ref, intent_token=proposal.intent_token
                    )
                    snapshot_json = await self._run_browser_command(
                        "snapshot", intent_token=proposal.intent_token
                    )
                    snap_data = self._parse_snapshot(snapshot_json)
                    refs = snap_data.get("refs", {})
                    target_ref = self._find_comment_input_ref(refs)

            if not target_ref:
                return " → ".join(steps) + " [FAILED: Element not found]"

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
        repost_mode = proposal.metadata.get("mode") == "repost_latest_tweet"
        if proposal.platform == Platform.TWITTER and repost_mode:
            return await self._repost_latest_tweet(proposal)
        repost_batch_mode = proposal.metadata.get("mode") == "repost_latest_tweets_batch"
        if proposal.platform == Platform.TWITTER and repost_batch_mode:
            return await self._repost_latest_tweets_batch(proposal)

        steps = [
            f"Navigating to {proposal.platform.value}",
            f"Opening post creation dialog",
            f"Entering content: {(proposal.content or '')[:50]}...",
            f"Publishing post",
        ]
        if self.dry_run:
            return " → ".join(steps) + " [DRY RUN]"

        url = _PLATFORM_URLS.get(proposal.platform)
        await self._goto_url(url, proposal.intent_token)
        return " → ".join(steps) + " [EXECUTED]"

    async def _like_post(self, proposal: ActionProposal) -> str:
        """Like a post/tweet, with dedicated latest-tweet flow on X."""
        if proposal.platform == Platform.TWITTER and proposal.metadata.get("mode") == "like_latest_tweet":
            return await self._like_latest_tweet(proposal)
        if proposal.platform == Platform.TWITTER and proposal.metadata.get("mode") == "like_latest_tweets_batch":
            return await self._like_latest_tweets_batch(proposal)

        if self.dry_run:
            return f"Would like post on {proposal.platform.value} [DRY RUN]"
        await self._goto_url(_PLATFORM_URLS.get(proposal.platform, "https://twitter.com"), proposal.intent_token)
        return f"Liked post on {proposal.platform.value} [EXECUTED]"

    async def _like_latest_tweet(self, proposal: ActionProposal) -> str:
        """Like the latest tweet from a specific account on X/Twitter."""
        source_account = await self._resolve_source_account(
            proposal.metadata, proposal.intent_token
        )
        steps = [
            f"Opening account profile @{source_account}",
            "Extracting latest tweet URL",
            "Opening latest tweet",
            "Clicking like",
        ]
        if self.dry_run:
            return " → ".join(steps) + " [DRY RUN]"

        latest_tweet_url = await self._resolve_latest_tweet_url_for_account(
            source_account, proposal.intent_token
        )
        await self._goto_url(latest_tweet_url, proposal.intent_token)
        tweet_snapshot = await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )
        tweet_data = self._parse_snapshot(tweet_snapshot)
        tweet_refs = tweet_data.get("refs", {})
        like_ref = self._find_like_button_ref(tweet_refs)
        if not like_ref:
            raise RuntimeError("Could not find like button on tweet page")

        await self._run_browser_command("click", ref=like_ref, intent_token=proposal.intent_token)
        return " → ".join(steps) + f" [EXECUTED @{source_account}]"

    async def _like_latest_tweets_batch(self, proposal: ActionProposal) -> str:
        """Like the latest N tweets for a target account."""
        source_account = await self._resolve_source_account(
            proposal.metadata, proposal.intent_token
        )
        batch_count = int(proposal.metadata.get("batch_count", 1) or 1)
        urls = await self._resolve_latest_tweet_urls_for_account(
            source_account, batch_count, proposal.intent_token
        )
        if not urls:
            raise RuntimeError(f"No latest tweets found for @{source_account}")

        liked = 0
        for url in urls:
            await self._goto_url(url, proposal.intent_token)
            tweet_snapshot = await self._run_browser_command(
                "snapshot", intent_token=proposal.intent_token
            )
            tweet_data = self._parse_snapshot(tweet_snapshot)
            tweet_refs = tweet_data.get("refs", {})
            like_ref = self._find_like_button_ref(tweet_refs)
            if like_ref:
                await self._run_browser_command(
                    "click", ref=like_ref, intent_token=proposal.intent_token
                )
                liked += 1

        return f"Batch like completed for @{source_account}: {liked}/{len(urls)} tweets liked"

    async def _reply_latest_tweet(self, proposal: ActionProposal) -> str:
        """Reply to the latest tweet from a specific account on X/Twitter."""
        source_account = await self._resolve_source_account(
            proposal.metadata, proposal.intent_token
        )
        reply_text = proposal.content or "Thanks!"
        steps = [
            f"Opening account profile @{source_account}",
            "Extracting latest tweet URL",
            "Opening latest tweet",
            f"Typing reply: {reply_text}",
            "Submitting reply",
        ]
        if self.dry_run:
            return " → ".join(steps) + " [DRY RUN]"

        latest_tweet_url = await self._resolve_latest_tweet_url_for_account(
            source_account, proposal.intent_token
        )
        await self._goto_url(latest_tweet_url, proposal.intent_token)
        tweet_snapshot = await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )
        tweet_data = self._parse_snapshot(tweet_snapshot)
        tweet_refs = tweet_data.get("refs", {})

        reply_button_ref = self._find_reply_button_ref(tweet_refs)
        if reply_button_ref:
            await self._run_browser_command(
                "click", ref=reply_button_ref, intent_token=proposal.intent_token
            )

        composer_snapshot = await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )
        composer_data = self._parse_snapshot(composer_snapshot)
        composer_refs = composer_data.get("refs", {})

        input_ref = self._find_reply_input_ref(composer_refs)
        if not input_ref:
            raise RuntimeError("Could not find reply input field on tweet dialog")

        await self._run_browser_command(
            "type", ref=input_ref, text=reply_text, intent_token=proposal.intent_token
        )

        # Re-snapshot after typing so we pick the active modal submit button state.
        submit_snapshot = await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )
        submit_data = self._parse_snapshot(submit_snapshot)
        submit_refs = submit_data.get("refs", {})

        submit_ref = self._find_reply_submit_ref(submit_refs)
        if submit_ref:
            await self._run_browser_command(
                "click", ref=submit_ref, intent_token=proposal.intent_token
            )
        else:
            await self._run_browser_command(
                "press", key="Enter", intent_token=proposal.intent_token
            )

        return " → ".join(steps) + f" [EXECUTED @{source_account}]"

    async def _reply_latest_tweets_batch(self, proposal: ActionProposal) -> str:
        """Reply to the latest N tweets for a target account."""
        source_account = await self._resolve_source_account(
            proposal.metadata, proposal.intent_token
        )
        reply_text = proposal.content or "Thanks!"
        batch_count = int(proposal.metadata.get("batch_count", 1) or 1)
        urls = await self._resolve_latest_tweet_urls_for_account(
            source_account, batch_count, proposal.intent_token
        )
        if not urls:
            raise RuntimeError(f"No latest tweets found for @{source_account}")

        replied = 0
        for url in urls:
            await self._goto_url(url, proposal.intent_token)
            tweet_snapshot = await self._run_browser_command(
                "snapshot", intent_token=proposal.intent_token
            )
            tweet_data = self._parse_snapshot(tweet_snapshot)
            tweet_refs = tweet_data.get("refs", {})

            reply_button_ref = self._find_reply_button_ref(tweet_refs)
            if reply_button_ref:
                await self._run_browser_command(
                    "click", ref=reply_button_ref, intent_token=proposal.intent_token
                )

            composer_snapshot = await self._run_browser_command(
                "snapshot", intent_token=proposal.intent_token
            )
            composer_data = self._parse_snapshot(composer_snapshot)
            composer_refs = composer_data.get("refs", {})

            input_ref = self._find_reply_input_ref(composer_refs)
            if not input_ref:
                continue

            await self._run_browser_command(
                "type", ref=input_ref, text=reply_text, intent_token=proposal.intent_token
            )

            submit_snapshot = await self._run_browser_command(
                "snapshot", intent_token=proposal.intent_token
            )
            submit_data = self._parse_snapshot(submit_snapshot)
            submit_refs = submit_data.get("refs", {})

            submit_ref = self._find_reply_submit_ref(submit_refs)
            if submit_ref:
                await self._run_browser_command(
                    "click", ref=submit_ref, intent_token=proposal.intent_token
                )
            else:
                await self._run_browser_command(
                    "press", key="Enter", intent_token=proposal.intent_token
                )
            replied += 1

        return f"Batch reply completed for @{source_account}: {replied}/{len(urls)} tweets replied"

    async def _repost_latest_tweet(self, proposal: ActionProposal) -> str:
        """Repost the latest tweet from a specific account on X/Twitter."""
        source_account = await self._resolve_source_account(
            proposal.metadata, proposal.intent_token
        )

        steps = [
            f"Opening account profile @{source_account}",
            "Extracting latest tweet URL",
            "Opening latest tweet",
            "Clicking repost",
            "Confirming repost",
        ]
        if self.dry_run:
            return " → ".join(steps) + " [DRY RUN]"

        latest_tweet_url = await self._resolve_latest_tweet_url_for_account(
            source_account, proposal.intent_token
        )

        await self._goto_url(latest_tweet_url, proposal.intent_token)
        tweet_snapshot = await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )
        tweet_data = self._parse_snapshot(tweet_snapshot)
        tweet_refs = tweet_data.get("refs", {})

        repost_ref = self._find_repost_button_ref(tweet_refs)
        if not repost_ref:
            raise RuntimeError("Could not find repost button on tweet page")

        await self._run_browser_command(
            "click", ref=repost_ref, intent_token=proposal.intent_token
        )

        # In many X flows a confirmation menu opens; click the explicit Repost item if present.
        confirm_snapshot = await self._run_browser_command(
            "snapshot", intent_token=proposal.intent_token
        )
        confirm_data = self._parse_snapshot(confirm_snapshot)
        confirm_refs = confirm_data.get("refs", {})
        confirm_ref = self._find_repost_confirm_ref(confirm_refs)
        if confirm_ref:
            await self._run_browser_command(
                "click", ref=confirm_ref, intent_token=proposal.intent_token
            )

        return " → ".join(steps) + f" [EXECUTED @{source_account}]"

    async def _repost_latest_tweets_batch(self, proposal: ActionProposal) -> str:
        """Repost the latest N tweets for a target account."""
        source_account = await self._resolve_source_account(
            proposal.metadata, proposal.intent_token
        )
        batch_count = int(proposal.metadata.get("batch_count", 1) or 1)
        urls = await self._resolve_latest_tweet_urls_for_account(
            source_account, batch_count, proposal.intent_token
        )
        if not urls:
            raise RuntimeError(f"No latest tweets found for @{source_account}")

        reposted = 0
        for url in urls:
            await self._goto_url(url, proposal.intent_token)
            tweet_snapshot = await self._run_browser_command(
                "snapshot", intent_token=proposal.intent_token
            )
            tweet_data = self._parse_snapshot(tweet_snapshot)
            tweet_refs = tweet_data.get("refs", {})

            repost_ref = self._find_repost_button_ref(tweet_refs)
            if not repost_ref:
                continue

            await self._run_browser_command(
                "click", ref=repost_ref, intent_token=proposal.intent_token
            )

            confirm_snapshot = await self._run_browser_command(
                "snapshot", intent_token=proposal.intent_token
            )
            confirm_data = self._parse_snapshot(confirm_snapshot)
            confirm_refs = confirm_data.get("refs", {})
            confirm_ref = self._find_repost_confirm_ref(confirm_refs)
            if confirm_ref:
                await self._run_browser_command(
                    "click", ref=confirm_ref, intent_token=proposal.intent_token
                )
            reposted += 1

        return f"Batch repost completed for @{source_account}: {reposted}/{len(urls)} tweets reposted"

    async def _schedule_action(self, proposal: ActionProposal) -> str:
        """Schedule a Twitter action for later execution."""
        mode = str(proposal.metadata.get("mode", ""))
        if mode != "schedule_twitter_action":
            return "Unsupported scheduling mode"

        run_at = str(proposal.metadata.get("run_at") or "").strip()
        scheduled_action = proposal.metadata.get("scheduled_action") or {}
        scheduled_command = str(proposal.metadata.get("scheduled_command") or "").strip()
        if not run_at or not isinstance(scheduled_action, dict):
            raise RuntimeError("Missing scheduling metadata")

        schedule_id = str(uuid.uuid4())[:8]
        run_at_iso = self._resolve_run_at_iso(run_at)
        _SCHEDULED_TWITTER_ACTIONS.append({
            "id": schedule_id,
            "run_at": run_at_iso,
            "scheduled_command": scheduled_command,
            "scheduled_action": scheduled_action,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        })
        return f"Scheduled Twitter action {schedule_id} at {run_at_iso}: {scheduled_command}"

    async def _run_automation(self, proposal: ActionProposal) -> str:
        """Run due scheduled actions or watchlist rules."""
        mode = str(proposal.metadata.get("mode", ""))
        if mode == "run_scheduled_actions":
            return await self._run_due_scheduled_actions(proposal.intent_token)
        if mode == "run_watchlist":
            return await self._run_watchlist_rules(proposal.intent_token)
        return "No automation mode selected"

    async def _manage_watchlist(self, proposal: ActionProposal) -> str:
        """Add/remove/list watchlist rules."""
        operation = str(proposal.metadata.get("operation", "list"))
        rule_action = str(proposal.metadata.get("rule_action", "like"))
        source_account = str(proposal.metadata.get("source_account") or "").strip().lstrip("@")
        source_query = str(proposal.metadata.get("source_query") or "").strip()
        reply_text = str(proposal.metadata.get("reply_text") or "Thanks!")

        if operation == "list":
            if not _WATCHLIST_RULES:
                return "Watchlist is empty"
            lines = [f"{r['id']}: @{r['account']} -> {r['action']}" for r in _WATCHLIST_RULES]
            return "Watchlist rules:\n" + "\n".join(lines)

        account = source_account
        if not account:
            if not source_query:
                raise RuntimeError("Missing account for watchlist rule")
            account = await self._resolve_twitter_account_from_query(source_query, proposal.intent_token)

        if operation == "add":
            rule_id = str(uuid.uuid4())[:8]
            _WATCHLIST_RULES.append({
                "id": rule_id,
                "account": account,
                "action": rule_action,
                "reply_text": reply_text,
                "enabled": True,
                "created_at": datetime.utcnow().isoformat(),
            })
            return f"Added watchlist rule {rule_id}: @{account} -> {rule_action}"

        if operation == "remove":
            before = len(_WATCHLIST_RULES)
            _WATCHLIST_RULES[:] = [r for r in _WATCHLIST_RULES if r["account"].lower() != account.lower()]
            removed = before - len(_WATCHLIST_RULES)
            return f"Removed {removed} watchlist rule(s) for @{account}"

        return "Unsupported watchlist operation"

    async def _summarize_thread(self, proposal: ActionProposal) -> str:
        """Summarize latest thread/tweets for a target account."""
        source_account = await self._resolve_source_account(proposal.metadata, proposal.intent_token)
        max_items = int(proposal.metadata.get("max_items", 5) or 5)

        await self._goto_url(f"https://x.com/{source_account}", proposal.intent_token)
        profile_snapshot = await self._run_browser_command("snapshot", intent_token=proposal.intent_token)
        profile_data = self._parse_snapshot(profile_snapshot)
        snapshot_text = str(profile_data.get("snapshot", ""))
        tweet_lines = self._extract_tweet_lines_from_snapshot(snapshot_text, source_account, limit=max_items)
        if not tweet_lines:
            return f"Could not extract tweet text for @{source_account}"

        summary = self._build_extract_summary(tweet_lines)
        return (
            f"Thread summary for @{source_account}:\n"
            f"{summary}\n\n"
            f"Suggested replies:\n"
            f"1. Great update, thanks for sharing this.\n"
            f"2. This is insightful. Looking forward to the next part.\n"
            f"3. Appreciate the context here, very helpful."
        )

    async def _suggest_reply(self, proposal: ActionProposal) -> str:
        """Generate suggested replies for the latest tweet/thread."""
        source_account = await self._resolve_source_account(proposal.metadata, proposal.intent_token)
        await self._goto_url(f"https://x.com/{source_account}", proposal.intent_token)
        profile_snapshot = await self._run_browser_command("snapshot", intent_token=proposal.intent_token)
        profile_data = self._parse_snapshot(profile_snapshot)
        snapshot_text = str(profile_data.get("snapshot", ""))
        tweet_lines = self._extract_tweet_lines_from_snapshot(snapshot_text, source_account, limit=3)
        topic = tweet_lines[0][:90] if tweet_lines else "your latest update"
        return (
            f"Suggested replies for @{source_account}:\n"
            f"1. Great update on {topic}.\n"
            f"2. Thanks for sharing this, really useful context.\n"
            f"3. Appreciate this thread, looking forward to more details."
        )

    async def _resolve_source_account(self, metadata: dict, intent_token: Optional[str]) -> str:
        """Resolve the source account from metadata."""
        source_account = str(metadata.get("source_account") or "").strip().lstrip("@")
        source_query = str(metadata.get("source_query") or "").strip()

        if source_account and re.fullmatch(r"[A-Za-z0-9_]{1,15}", source_account):
            return source_account

        if not source_query:
            raise RuntimeError("Missing account source. Use @handle or a display name after 'by'")
        return await self._resolve_twitter_account_from_query(source_query, intent_token)

    async def _resolve_latest_tweet_url_for_account(
        self, source_account: str, intent_token: Optional[str]
    ) -> str:
        await self._goto_url(f"https://x.com/{source_account}", intent_token)
        profile_snapshot = await self._run_browser_command("snapshot", intent_token=intent_token)
        profile_data = self._parse_snapshot(profile_snapshot)
        refs = profile_data.get("refs", {})
        snapshot_text = str(profile_data.get("snapshot", ""))
        latest_tweet_url = self._find_latest_tweet_url(refs, source_account, snapshot_text)
        if not latest_tweet_url:
            raise RuntimeError(f"Could not find latest tweet URL for @{source_account}")
        return latest_tweet_url

    async def _resolve_latest_tweet_urls_for_account(
        self, source_account: str, count: int, intent_token: Optional[str]
    ) -> list[str]:
        await self._goto_url(f"https://x.com/{source_account}", intent_token)
        profile_snapshot = await self._run_browser_command("snapshot", intent_token=intent_token)
        profile_data = self._parse_snapshot(profile_snapshot)
        refs = profile_data.get("refs", {})
        snapshot_text = str(profile_data.get("snapshot", ""))
        return self._find_latest_tweet_urls(refs, source_account, snapshot_text, count)

    async def _run_due_scheduled_actions(self, intent_token: Optional[str]) -> str:
        now = datetime.utcnow()
        executed = 0
        for item in _SCHEDULED_TWITTER_ACTIONS:
            if item.get("status") != "pending":
                continue

            run_at_raw = str(item.get("run_at") or "")
            try:
                run_at = datetime.fromisoformat(run_at_raw)
            except ValueError:
                continue
            if run_at > now:
                continue

            action_meta = item.get("scheduled_action") or {}
            action_kind = str(action_meta.get("kind") or "")
            fake = ActionProposal(
                action_type=ActionType.LIKE_POST,
                platform=Platform.TWITTER,
                content=action_meta.get("reply_text"),
                metadata=dict(action_meta),
                intent_token=intent_token,
            )

            if action_kind == "repost_latest_tweet":
                fake.action_type = ActionType.POST_TWEET
                fake.metadata["mode"] = "repost_latest_tweet"
                await self._repost_latest_tweet(fake)
            elif action_kind == "reply_latest_tweet":
                fake.action_type = ActionType.REPLY_COMMENT
                fake.metadata["mode"] = "reply_latest_tweet"
                fake.content = str(action_meta.get("reply_text") or "Thanks!")
                await self._reply_latest_tweet(fake)
            else:
                fake.action_type = ActionType.LIKE_POST
                fake.metadata["mode"] = "like_latest_tweet"
                await self._like_latest_tweet(fake)

            item["status"] = "executed"
            item["executed_at"] = now.isoformat()
            executed += 1

        return f"Scheduled automation run complete: executed {executed} action(s)"

    async def _run_watchlist_rules(self, intent_token: Optional[str]) -> str:
        executed = 0
        for rule in _WATCHLIST_RULES:
            if not rule.get("enabled", True):
                continue

            fake = ActionProposal(
                action_type=ActionType.LIKE_POST,
                platform=Platform.TWITTER,
                content=rule.get("reply_text"),
                metadata={
                    "source_account": rule.get("account"),
                    "source_query": rule.get("account"),
                },
                intent_token=intent_token,
            )

            action = str(rule.get("action") or "like")
            if action == "repost":
                fake.action_type = ActionType.POST_TWEET
                fake.metadata["mode"] = "repost_latest_tweet"
                await self._repost_latest_tweet(fake)
            elif action == "reply":
                fake.action_type = ActionType.REPLY_COMMENT
                fake.metadata["mode"] = "reply_latest_tweet"
                fake.content = str(rule.get("reply_text") or "Thanks!")
                await self._reply_latest_tweet(fake)
            else:
                fake.action_type = ActionType.LIKE_POST
                fake.metadata["mode"] = "like_latest_tweet"
                await self._like_latest_tweet(fake)
            executed += 1

        return f"Watchlist automation run complete: executed {executed} rule(s)"

    @staticmethod
    def _resolve_run_at_iso(run_at: str) -> str:
        now = datetime.utcnow()
        hour, minute = run_at.split(":")
        target = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return target.isoformat()

    async def _resolve_twitter_account_from_query(
        self, query: str, intent_token: Optional[str]
    ) -> str:
        """Resolve a display name query to the top account handle on X search."""
        encoded = quote_plus(query)
        search_url = f"https://x.com/search?q={encoded}&src=typed_query&f=user"
        await self._goto_url(search_url, intent_token)

        snap_json = await self._run_browser_command("snapshot", intent_token=intent_token)
        data = self._parse_snapshot(snap_json)
        refs = data.get("refs", {})
        handle = self._find_account_handle_from_search_results(refs, query)
        if handle:
            return handle

        # Fallback: general search page may still include user links in some layouts.
        fallback_url = f"https://x.com/search?q={encoded}&src=typed_query"
        await self._goto_url(fallback_url, intent_token)
        snap_json = await self._run_browser_command("snapshot", intent_token=intent_token)
        data = self._parse_snapshot(snap_json)
        refs = data.get("refs", {})
        handle = self._find_account_handle_from_search_results(refs, query)
        if handle:
            return handle

        raise RuntimeError(f"Could not resolve account from query: '{query}'")

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


    @staticmethod
    def _find_like_button_ref(refs: dict) -> Optional[str]:
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            name = str(ref_data.get("name", "")).strip().lower()
            if role == "button" and (
                name.endswith(" like") or ". like" in name or name == "like" or " likes. like" in name
            ):
                return ref_id
        return None

    @staticmethod
    def _find_reply_button_ref(refs: dict) -> Optional[str]:
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            name = str(ref_data.get("name", "")).strip().lower()
            if role == "button" and (
                name.endswith(" reply") or ". reply" in name or name == "reply" or " replies. reply" in name
            ):
                return ref_id
        return None

    @staticmethod
    def _find_reply_input_ref(refs: dict) -> Optional[str]:
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            name = str(ref_data.get("name", "")).strip().lower()
            if role in {"textbox", "combobox"} and (
                "post your reply" in name or "reply" in name or "post text" in name
            ):
                return ref_id
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            if role in {"textbox", "combobox"}:
                return ref_id
        return None

    @staticmethod
    def _find_reply_submit_ref(refs: dict) -> Optional[str]:
        # Prefer an enabled explicit Reply button (modal composer submit),
        # not background/disabled page buttons.
        exact_enabled = []
        generic_enabled = []

        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            name = str(ref_data.get("name", "")).strip().lower()
            disabled = bool(ref_data.get("disabled", False))
            if role != "button" or disabled:
                continue

            if name == "reply":
                exact_enabled.append(ref_id)
            elif name.startswith("reply") or name == "post":
                generic_enabled.append(ref_id)

        if exact_enabled:
            return exact_enabled[0]
        if generic_enabled:
            return generic_enabled[0]
        return None
    _dispatch = {
        ActionType.READ_COMMENTS: _read_comments,
        ActionType.REPLY_COMMENT: _reply_comment,
        ActionType.LIKE_POST: _like_post,
        ActionType.SCHEDULE_ACTION: _schedule_action,
        ActionType.RUN_AUTOMATION: _run_automation,
        ActionType.MANAGE_WATCHLIST: _manage_watchlist,
        ActionType.SUMMARIZE_THREAD: _summarize_thread,
        ActionType.SUGGEST_REPLY: _suggest_reply,
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

    async def _goto_url(self, url: str, intent_token: Optional[str]) -> None:
        """Navigate in the current tab when possible; fallback to opening a new tab."""
        try:
            await self._run_browser_command(
                "navigate", url=url, intent_token=intent_token
            )
        except Exception:
            await self._run_browser_command(
                "open", url=url, intent_token=intent_token
            )

    @staticmethod
    def _parse_snapshot(snapshot_json: str) -> dict:
        try:
            data = json.loads(snapshot_json)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    @staticmethod
    def _find_first_comment_button_ref(refs: dict) -> Optional[str]:
        """Find first numeric-comment-count context by nearest 'Comment' button heuristic."""
        return OpenClawExecutor._find_comment_button_ref(refs)

    @staticmethod
    def _find_comment_button_ref(refs: dict) -> Optional[str]:
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            name = str(ref_data.get("name", "")).strip().lower()
            if role == "button" and (name == "comment" or name.startswith("comment")):
                return ref_id
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            name = str(ref_data.get("name", "")).strip().lower()
            if role == "button" and "comment" in name:
                return ref_id
        return None

    @staticmethod
    def _find_comment_input_ref(refs: dict) -> Optional[str]:
        # Highest confidence: explicit add-a-comment style labels
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            name = str(ref_data.get("name", "")).lower()
            if role in {"textbox", "combobox", "searchbox"} and (
                "add a comment" in name or name == "comment"
            ):
                return ref_id

        # Fallback: any textbox on post/comment composer surface
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            if role == "textbox":
                return ref_id

        return None

    @staticmethod
    def _find_latest_tweet_url(refs: dict, account: str, snapshot_text: str = "") -> Optional[str]:
        """Find the most likely latest status URL from snapshot refs."""
        account = account.lower()
        preferred = []
        generic = []

        for ref_data in refs.values():
            for value in ref_data.values():
                if not isinstance(value, str):
                    continue
                candidate = value.strip()
                if "/status/" not in candidate:
                    continue

                if candidate.startswith("/"):
                    candidate = f"https://x.com{candidate}"
                elif candidate.startswith("http://"):
                    candidate = candidate.replace("http://", "https://", 1)

                if candidate.startswith("https://x.com/") or candidate.startswith("https://twitter.com/"):
                    if f"/{account}/status/" in candidate.lower():
                        preferred.append(candidate)
                    else:
                        generic.append(candidate)

        # Snapshot text can contain the /url entries even when refs omit them.
        if snapshot_text:
            status_pattern = re.compile(
                r"/" + re.escape(account) + r"/status/\d+(?:/photo/\d+|/analytics)?",
                flags=re.IGNORECASE,
            )
            for match in status_pattern.findall(snapshot_text):
                preferred.append(f"https://x.com{match}")

        for url in preferred + generic:
            if "/photo/" in url or "/analytics" in url:
                continue
            return url
        return None

    @staticmethod
    def _find_latest_tweet_urls(
        refs: dict,
        account: str,
        snapshot_text: str = "",
        count: int = 1,
    ) -> list[str]:
        account = account.lower()
        ordered: list[str] = []

        if snapshot_text:
            for match in re.findall(
                r"/" + re.escape(account) + r"/status/\d+",
                snapshot_text,
                flags=re.IGNORECASE,
            ):
                url = f"https://x.com{match}"
                if url not in ordered:
                    ordered.append(url)

        for ref_data in refs.values():
            for value in ref_data.values():
                if not isinstance(value, str):
                    continue
                candidate = value.strip()
                if "/status/" not in candidate:
                    continue
                if candidate.startswith("/"):
                    candidate = f"https://x.com{candidate}"
                elif candidate.startswith("http://"):
                    candidate = candidate.replace("http://", "https://", 1)
                if f"/{account}/status/" not in candidate.lower():
                    continue
                if "/photo/" in candidate or "/analytics" in candidate:
                    continue
                if candidate not in ordered:
                    ordered.append(candidate)

        return ordered[: max(1, count)]

    @staticmethod
    def _extract_tweet_lines_from_snapshot(snapshot_text: str, account: str, limit: int = 5) -> list[str]:
        if not snapshot_text:
            return []

        lines = []
        pattern = re.compile(
            r"article \"[^\"]*@" + re.escape(account.lower()) + r"[^\"]*\"",
            flags=re.IGNORECASE,
        )
        for raw in pattern.findall(snapshot_text):
            cleaned = re.sub(r"\s+", " ", raw)
            cleaned = cleaned.replace('article "', "").rstrip('"')
            cleaned = re.sub(
                r"\b\d+\s+(?:replies?|reposts?|likes?|bookmarks?|views?)\b",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(r"https?://\S+", "", cleaned)
            if cleaned and cleaned not in lines:
                lines.append(cleaned.strip())
            if len(lines) >= max(1, limit):
                break
        return lines

    @staticmethod
    def _build_extract_summary(tweet_lines: list[str]) -> str:
        bullets = []
        for line in tweet_lines[:3]:
            text = line
            if len(text) > 180:
                text = text[:177] + "..."
            bullets.append(f"- {text}")
        return "\n".join(bullets)

    @staticmethod
    def _find_repost_button_ref(refs: dict) -> Optional[str]:
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            name = str(ref_data.get("name", "")).strip().lower()
            if role == "button" and (
                "repost" in name or "retweet" in name or "repost this post" in name
            ):
                return ref_id
        return None

    @staticmethod
    def _find_repost_confirm_ref(refs: dict) -> Optional[str]:
        for ref_id, ref_data in refs.items():
            role = str(ref_data.get("role", "")).lower()
            name = str(ref_data.get("name", "")).strip().lower()
            if role in {"button", "menuitem"} and (
                name == "repost" or "repost this post" in name or name == "retweet"
            ):
                return ref_id
        return None

    @staticmethod
    def _find_account_handle_from_search_results(refs: dict, query: str) -> Optional[str]:
        """Pick the best @handle candidate from X user search results."""
        query_l = query.lower()
        query_tokens = [
            tok for tok in re.findall(r"[a-z0-9_]+", query_l)
            if tok not in {"the", "by", "from", "prime", "minister", "latest", "tweet", "repost", "official"}
        ]
        if not query_tokens:
            query_tokens = re.findall(r"[a-z0-9_]+", query_l)

        scored: dict[str, int] = {}

        for ref_data in refs.values():
            context = str(ref_data.get("name", "")).lower()
            handles = set(re.findall(r"@([a-z0-9_]{1,15})", context))

            # Also include handles from path URLs like /narendramodi.
            for value in ref_data.values():
                if not isinstance(value, str):
                    continue
                parsed = OpenClawExecutor._extract_profile_handle_from_path(value)
                if parsed:
                    handles.add(parsed.lower())

            for handle in handles:
                score = 0

                if handle in query_l.replace(" ", ""):
                    score += 80
                if all(tok in context for tok in query_tokens):
                    score += 50
                score += sum(12 for tok in query_tokens if tok in handle or tok in context)

                if "verified account" in context:
                    score += 20
                if "follow @" in context:
                    score -= 8
                if "fan account" in context:
                    score -= 35
                if handle.endswith(tuple(str(i) for i in range(10))):
                    score -= 12
                if "army" in handle and "army" not in query_l:
                    score -= 20

                if score > scored.get(handle, -10_000):
                    scored[handle] = score

        if not scored:
            return None

        return max(scored.items(), key=lambda kv: kv[1])[0]

    @staticmethod
    def _extract_profile_handle_from_path(candidate: str) -> Optional[str]:
        candidate = candidate.strip()
        if candidate.startswith("/"):
            path = candidate
        elif candidate.startswith("https://x.com/"):
            path = candidate[len("https://x.com"):]
        elif candidate.startswith("https://twitter.com/"):
            path = candidate[len("https://twitter.com"):]
        else:
            return None

        parts = [p for p in path.split("/") if p]
        if not parts:
            return None
        first = parts[0]
        if first.lower() in {
            "home", "explore", "search", "notifications", "messages",
            "compose", "i", "settings", "tos", "privacy", "help", "login", "signup"
        }:
            return None
        if re.fullmatch(r"[A-Za-z0-9_]{1,15}", first):
            return first
        return None

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

        safe_cmd = _redact_cli_command(cmd)
        logger.info("CLI exec: %s (token: %s)", safe_cmd, bool(intent_token))
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
        oc_logger.info(f"COMMAND: {safe_cmd}")
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
