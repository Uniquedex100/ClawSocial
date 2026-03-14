"""Reasoning Engine — generates the plan to be captured by ArmorIQ.

This generates a structured plan dictionary that format correctly for the 
ArmorIQ SDK (`client.capture_plan()`).
"""

from __future__ import annotations

import logging

from models import ActionProposal, ActionType, Intent

logger = logging.getLogger("clawsocial.reasoning")


def generate_plan_for_armoriq(instruction: str) -> dict:
    """Generate the 'plan' dictionary expected by ArmorIQ capture_plan."""
    text = instruction.lower()
    steps = []

    if "reply" in text or "comment" in text:
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

    if "reply" in text or "comment" in text:
        proposals.append(ActionProposal(
            action_type=ActionType.READ_COMMENTS,
            platform=intent.platform,
            reasoning="Read comments to reply"
        ))
        proposals.append(ActionProposal(
            action_type=ActionType.REPLY_COMMENT,
            platform=intent.platform,
            content="Thanks!",
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
