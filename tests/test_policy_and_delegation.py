# pyright: reportMissingImports=false

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from delegation import create_engagement_agent
from models import ActionProposal, ActionType, Platform, Policy, Verdict
from policy_engine import ArmorClaw


def test_blocks_unauthorized_platform():
    engine = ArmorClaw(
        policy=Policy(
            platform_restrictions=[Platform.INSTAGRAM],
            allowed_actions=[ActionType.REPLY_COMMENT],
            forbidden_actions=[],
        )
    )
    proposal = ActionProposal(
        action_type=ActionType.REPLY_COMMENT,
        platform=Platform.TWITTER,
        content="Thanks!",
    )

    result = engine.validate(proposal)

    assert result.verdict == Verdict.BLOCK
    assert "Unauthorized platform" in result.reason


def test_blocks_forbidden_action():
    engine = ArmorClaw(
        policy=Policy(
            platform_restrictions=[Platform.INSTAGRAM],
            allowed_actions=[ActionType.REPLY_COMMENT],
            forbidden_actions=[ActionType.SEND_DM],
        )
    )
    proposal = ActionProposal(
        action_type=ActionType.SEND_DM,
        platform=Platform.INSTAGRAM,
        content="hello",
    )

    result = engine.validate(proposal)

    assert result.verdict == Verdict.BLOCK
    assert "Forbidden action" in result.reason


def test_blocks_blocked_word_content():
    engine = ArmorClaw(
        policy=Policy(
            platform_restrictions=[Platform.INSTAGRAM],
            allowed_actions=[ActionType.REPLY_COMMENT],
            forbidden_actions=[],
            blocked_words=["politics"],
        )
    )
    proposal = ActionProposal(
        action_type=ActionType.REPLY_COMMENT,
        platform=Platform.INSTAGRAM,
        content="Let us talk politics now",
    )

    result = engine.validate(proposal)

    assert result.verdict == Verdict.BLOCK
    assert "blocked word" in result.reason.lower()


def test_allows_valid_action():
    engine = ArmorClaw(
        policy=Policy(
            platform_restrictions=[Platform.INSTAGRAM],
            allowed_actions=[ActionType.REPLY_COMMENT],
            forbidden_actions=[],
            blocked_words=[],
        )
    )
    proposal = ActionProposal(
        action_type=ActionType.REPLY_COMMENT,
        platform=Platform.INSTAGRAM,
        content="Thanks for watching!",
    )

    result = engine.validate(proposal)

    assert result.verdict == Verdict.ALLOW


def test_blocks_after_reply_rate_limit_reached():
    engine = ArmorClaw(
        policy=Policy(
            platform_restrictions=[Platform.INSTAGRAM],
            allowed_actions=[ActionType.REPLY_COMMENT],
            forbidden_actions=[],
            blocked_words=[],
            max_replies_per_hour=1,
        )
    )
    first = ActionProposal(
        action_type=ActionType.REPLY_COMMENT,
        platform=Platform.INSTAGRAM,
        content="First reply",
    )
    second = ActionProposal(
        action_type=ActionType.REPLY_COMMENT,
        platform=Platform.INSTAGRAM,
        content="Second reply",
    )

    first_result = engine.validate(first)
    assert first_result.verdict == Verdict.ALLOW
    engine.record_execution(first)

    second_result = engine.validate(second)
    assert second_result.verdict == Verdict.BLOCK
    assert "Rate limit exceeded" in second_result.reason


def test_delegation_blocks_out_of_scope_publish():
    engagement = create_engagement_agent()
    proposal = ActionProposal(
        action_type=ActionType.PUBLISH_POST,
        platform=Platform.INSTAGRAM,
        content="New launch today!",
    )

    result = engagement.validate(proposal)

    assert result.verdict == Verdict.BLOCK
    assert "outside delegated authority" in result.reason
