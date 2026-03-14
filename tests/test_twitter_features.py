# pyright: reportMissingImports=false

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from models import ActionType, Intent, Platform
from reasoning_engine import build_action_proposals


def _twitter_intent() -> Intent:
    return Intent(
        intent="engagement_management",
        platform=Platform.TWITTER,
        actions_allowed=[],
        content_generation=True,
        publish_allowed=True,
        time_scope="today",
    )


def test_like_latest_batch_maps_to_like_post_batch_mode():
    proposals = build_action_proposals(
        _twitter_intent(),
        "like latest 3 tweets by @narendramodi",
    )

    assert len(proposals) == 1
    assert proposals[0].action_type == ActionType.LIKE_POST
    assert proposals[0].metadata.get("mode") == "like_latest_tweets_batch"
    assert proposals[0].metadata.get("batch_count") == 3


def test_schedule_twitter_action_maps_to_schedule_action():
    proposals = build_action_proposals(
        _twitter_intent(),
        "schedule repost latest tweet by @narendramodi at 9:30 pm",
    )

    assert len(proposals) == 1
    assert proposals[0].action_type == ActionType.SCHEDULE_ACTION
    assert proposals[0].metadata.get("mode") == "schedule_twitter_action"
    assert proposals[0].metadata.get("run_at") == "21:30"


def test_watchlist_add_maps_to_manage_watchlist():
    proposals = build_action_proposals(
        _twitter_intent(),
        "add @narendramodi to watchlist for repost",
    )

    assert len(proposals) == 1
    assert proposals[0].action_type == ActionType.MANAGE_WATCHLIST
    assert proposals[0].metadata.get("operation") == "add"
    assert proposals[0].metadata.get("rule_action") == "repost"


def test_thread_summary_maps_to_summarize_thread():
    proposals = build_action_proposals(
        _twitter_intent(),
        "summarize latest thread by @narendramodi on twitter",
    )

    assert len(proposals) == 1
    assert proposals[0].action_type == ActionType.SUMMARIZE_THREAD
