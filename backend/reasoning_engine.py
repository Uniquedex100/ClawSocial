"""Reasoning Engine — generates the plan to be captured by ArmorIQ.

This generates a structured plan dictionary that format correctly for the 
ArmorIQ SDK (`client.capture_plan()`).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from models import ActionProposal, ActionType, Intent, Platform

logger = logging.getLogger("clawsocial.reasoning")


def _extract_comment_text(instruction: str) -> str:
    """Extract requested comment text from natural language instruction."""
    text = instruction.strip()

    # Handles variants like: saying looking good / saying "looking good"
    match = re.search(r"\bsaying\s+[\"']?(.+?)[\"']?$", text, flags=re.IGNORECASE)
    if match:
        comment = match.group(1).strip()
        if comment:
            return comment

    # Handles: comment ... 'looking good' / comment ... "looking good"
    quoted = re.search(r"[\"']([^\"']{1,140})[\"']", text)
    if quoted:
        return quoted.group(1).strip()

    return "Thanks!"


def _extract_twitter_account(instruction: str) -> str | None:
    """Extract a Twitter/X account handle from instructions like 'by @modi'."""
    # Prefer explicit handle mentions.
    handle_match = re.search(r"@([A-Za-z0-9_]{1,15})", instruction)
    if handle_match:
        return handle_match.group(1)

    return None


def _extract_twitter_source_query(instruction: str) -> str | None:
    """Extract a display-name/account query from phrases like 'by prime minister modi'."""
    text = instruction.strip()

    # If we have an explicit @handle, that is already the best query.
    handle = _extract_twitter_account(text)
    if handle:
        return handle

    by_match = re.search(
        r"\b(?:by|from)\s+(.+?)(?:\s+on\s+(?:twitter|x)|\s*$)",
        text,
        flags=re.IGNORECASE,
    )
    if not by_match:
        return None

    query = by_match.group(1).strip(" .,!?:;\"'")
    if not query:
        return None
    return query


def _extract_batch_count(instruction: str) -> int:
    match = re.search(r"\blatest\s+(\d{1,2})\s+tweets?\b", instruction, flags=re.IGNORECASE)
    if not match:
        return 1
    return max(1, min(int(match.group(1)), 10))


def _extract_schedule_time(instruction: str) -> str | None:
    """Extract HH:MM (24h) from 'at 9:30 pm' style text."""
    match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", instruction, flags=re.IGNORECASE)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = (match.group(3) or "").lower()

    if meridiem:
        if hour == 12:
            hour = 0
        if meridiem == "pm":
            hour += 12

    if hour > 23 or minute > 59:
        return None

    return f"{hour:02d}:{minute:02d}"


def _extract_scheduled_command(instruction: str) -> str | None:
    match = re.search(r"\bschedule\s+(.+?)\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", instruction, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def _infer_watchlist_action(text: str) -> str:
    if "repost" in text or "retweet" in text:
        return "repost"
    if "reply" in text or "comment" in text:
        return "reply"
    return "like"


def _build_twitter_latest_action_metadata(instruction: str, mode: str) -> dict:
    return {
        "mode": mode,
        "source_account": _extract_twitter_account(instruction),
        "source_query": _extract_twitter_source_query(instruction),
    }


def _build_scheduled_action_metadata(command_text: str) -> dict:
    text = command_text.lower()
    metadata = {
        "source_account": _extract_twitter_account(command_text),
        "source_query": _extract_twitter_source_query(command_text),
    }
    if "repost" in text or "retweet" in text:
        metadata["kind"] = "repost_latest_tweet"
    elif "reply" in text or "comment" in text:
        metadata["kind"] = "reply_latest_tweet"
        metadata["reply_text"] = _extract_comment_text(command_text)
    else:
        metadata["kind"] = "like_latest_tweet"
    metadata["batch_count"] = _extract_batch_count(command_text)
    return metadata


def generate_plan_for_armoriq(instruction: str) -> dict:
    """Generate the 'plan' dictionary expected by ArmorIQ capture_plan."""
    text = instruction.lower()
    steps = []

    if "watchlist" in text or "schedule" in text or "thread" in text:
        steps = [
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "open"}
            },
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "snapshot"}
            }
        ]
    elif "like" in text and "latest" in text and ("tweet" in text or "twitter" in text or "x.com" in text):
        steps = [
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "open"}
            },
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "snapshot"}
            },
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "click"}
            }
        ]
    elif "repost" in text and ("tweet" in text or "twitter" in text or "x.com" in text):
        steps = [
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "open"}
            },
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "snapshot"}
            },
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "click"}
            }
        ]
    elif "reply" in text or "comment" in text:
        steps = [
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "open"}
            },
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "snapshot"}
            },
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "type", "submit": True}
            }
        ]
    elif "post" in text or "tweet" in text or "publish" in text:
        steps = [
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "open"}
            }
        ]
    else:
        steps = [
            {
                "action": "openclaw",
                "tool": "browser",
                "inputs": {"command": "open"}
            }
        ]

    return {
        "goal": instruction,
        "steps": steps
    }


def build_action_proposals(intent: Intent, instruction: str) -> list[ActionProposal]:
    """Convert the logical intent into local ActionProposal objects for ArmorClaw execution."""
    text = instruction.lower()
    proposals = []

    if "run watchlist" in text:
        proposals.append(ActionProposal(
            action_type=ActionType.RUN_AUTOMATION,
            platform=Platform.TWITTER,
            metadata={"mode": "run_watchlist"},
            reasoning="Run watchlist automation rules now",
        ))
    elif "watchlist" in text and any(k in text for k in ["add", "remove", "list", "show"]):
        operation = "list"
        if "add" in text:
            operation = "add"
        elif "remove" in text or "delete" in text:
            operation = "remove"

        metadata = {
            "mode": "manage_watchlist",
            "operation": operation,
            "rule_action": _infer_watchlist_action(text),
            "source_account": _extract_twitter_account(instruction),
            "source_query": _extract_twitter_source_query(instruction),
            "reply_text": _extract_comment_text(instruction) if ("reply" in text or "comment" in text) else None,
        }
        proposals.append(ActionProposal(
            action_type=ActionType.MANAGE_WATCHLIST,
            platform=Platform.TWITTER,
            metadata=metadata,
            reasoning="Manage watchlist automation rules",
        ))
    elif "run scheduled" in text:
        proposals.append(ActionProposal(
            action_type=ActionType.RUN_AUTOMATION,
            platform=Platform.TWITTER,
            metadata={"mode": "run_scheduled_actions"},
            reasoning="Run due scheduled Twitter actions",
        ))
    elif text.startswith("schedule ") and ("twitter" in text or "tweet" in text or "x.com" in text):
        run_at = _extract_schedule_time(instruction)
        scheduled_command = _extract_scheduled_command(instruction)
        if run_at and scheduled_command:
            proposals.append(ActionProposal(
                action_type=ActionType.SCHEDULE_ACTION,
                platform=Platform.TWITTER,
                metadata={
                    "mode": "schedule_twitter_action",
                    "run_at": run_at,
                    "scheduled_command": scheduled_command,
                    "scheduled_action": _build_scheduled_action_metadata(scheduled_command),
                },
                reasoning="Schedule a Twitter action for later execution",
            ))
    elif "summarize" in text and "thread" in text and ("twitter" in text or "tweet" in text or "x.com" in text):
        proposals.append(ActionProposal(
            action_type=ActionType.SUMMARIZE_THREAD,
            platform=Platform.TWITTER,
            metadata={
                **_build_twitter_latest_action_metadata(instruction, "summarize_thread"),
                "max_items": 5,
            },
            reasoning="Summarize latest Twitter thread",
        ))
    elif "suggest" in text and "reply" in text and ("twitter" in text or "tweet" in text or "x.com" in text):
        proposals.append(ActionProposal(
            action_type=ActionType.SUGGEST_REPLY,
            platform=Platform.TWITTER,
            metadata={
                **_build_twitter_latest_action_metadata(instruction, "suggest_reply"),
                "max_items": 5,
                "suggestions": 3,
            },
            reasoning="Generate suggested replies for latest tweet/thread",
        ))
    elif "like" in text and "latest" in text and ("tweet" in text or "twitter" in text or "x.com" in text):
        batch_count = _extract_batch_count(instruction)
        source_account = _extract_twitter_account(instruction)
        source_query = _extract_twitter_source_query(instruction)
        proposals.append(ActionProposal(
            action_type=ActionType.LIKE_POST,
            platform=Platform.TWITTER,
            metadata={
                "mode": "like_latest_tweets_batch" if batch_count > 1 else "like_latest_tweet",
                "batch_count": batch_count,
                "source_account": source_account,
                "source_query": source_query,
            },
            reasoning="Like latest tweet(s) from a specific account",
        ))
    elif "repost" in text and ("tweet" in text or "twitter" in text or "x.com" in text):
        batch_count = _extract_batch_count(instruction)
        source_account = _extract_twitter_account(instruction)
        source_query = _extract_twitter_source_query(instruction)
        proposals.append(ActionProposal(
            action_type=ActionType.POST_TWEET,
            platform=Platform.TWITTER,
            metadata={
                "mode": "repost_latest_tweets_batch" if batch_count > 1 else "repost_latest_tweet",
                "batch_count": batch_count,
                "source_account": source_account,
                "source_query": source_query,
            },
            reasoning="Repost latest tweet(s) from a specific account",
        ))
    elif ("reply" in text or "comment" in text) and ("latest" in text and ("tweet" in text or "twitter" in text or "x.com" in text)):
        batch_count = _extract_batch_count(instruction)
        source_account = _extract_twitter_account(instruction)
        source_query = _extract_twitter_source_query(instruction)
        reply_text = _extract_comment_text(instruction)
        proposals.append(ActionProposal(
            action_type=ActionType.REPLY_COMMENT,
            platform=Platform.TWITTER,
            content=reply_text,
            metadata={
                "mode": "reply_latest_tweets_batch" if batch_count > 1 else "reply_latest_tweet",
                "batch_count": batch_count,
                "source_account": source_account,
                "source_query": source_query,
            },
            reasoning="Reply to the latest tweet from a specific account",
        ))
    elif "reply" in text or "comment" in text:
        comment_text = _extract_comment_text(instruction)
        target_first_post = "first post" in text

        proposals.append(ActionProposal(
            action_type=ActionType.READ_COMMENTS,
            platform=intent.platform,
            metadata={
                "target_scope": "feed",
                "post_selector": "first" if target_first_post else "auto",
            },
            reasoning="Read comments to reply"
        ))
        proposals.append(ActionProposal(
            action_type=ActionType.REPLY_COMMENT,
            platform=intent.platform,
            content=comment_text,
            metadata={
                "target_scope": "feed",
                "post_selector": "first" if target_first_post else "auto",
            },
            reasoning="Reply to comment"
        ))
    elif "post" in text or "tweet" in text or "publish" in text:
        action = ActionType.POST_TWEET if intent.platform.value == "twitter" else ActionType.PUBLISH_POST
        proposals.append(ActionProposal(
            action_type=action,
            platform=intent.platform,
            content="Check this out!",
            reasoning="Publish content"
        ))

    return proposals
