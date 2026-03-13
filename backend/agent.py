"""Agent Orchestrator — ties all layers into the ClawSocial pipeline.

Pipeline:
    user instruction
        → IntentParser
        → ReasoningEngine
        → [ActionProposals]
        → ArmorClaw (PolicyEngine)
        → OpenClaw Executor
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from delegation import SubAgent
from intent_parser import parse_intent_keywords
from logger import log_action, log_intent
from models import (
    ActionLog,
    ActionProposal,
    ExecutionResult,
    Intent,
    PolicyResult,
    TaskResult,
    Verdict,
)
from openclaw_executor import OpenClawExecutor
from policy_engine import ArmorClaw
from reasoning_engine import decompose_task

logger = logging.getLogger("clawsocial.agent")


class ClawSocialAgent:
    """Main orchestrator for the ClawSocial pipeline."""

    def __init__(
        self,
        policy_engine: Optional[ArmorClaw] = None,
        executor: Optional[OpenClawExecutor] = None,
        dry_run: bool = True,
    ):
        self.policy_engine = policy_engine or ArmorClaw()
        self.executor = executor or OpenClawExecutor(dry_run=dry_run)

    async def run(self, instruction: str) -> TaskResult:
        """Execute the full pipeline from a natural-language instruction."""

        result = TaskResult(instruction=instruction)

        # ── 1. Parse intent ──────────────────────────────────────────────
        logger.info("━━━ Pipeline start: %s", instruction)
        intent = parse_intent_keywords(instruction)
        result.intent = intent
        log_intent(intent)

        # ── 2. Decompose into actions ────────────────────────────────────
        proposals = decompose_task(intent)
        result.proposals = proposals
        logger.info("Reasoning produced %d action proposals", len(proposals))

        # ── 3. Policy enforcement (ArmorClaw) ────────────────────────────
        policy_results = self.policy_engine.validate_batch(proposals)
        result.policy_results = policy_results

        # ── 4. Execute approved actions ──────────────────────────────────
        for proposal, pr in zip(proposals, policy_results):
            exec_result: Optional[ExecutionResult] = None

            if pr.verdict == Verdict.ALLOW:
                exec_result = await self.executor.execute(proposal)
                self.policy_engine.record_execution(proposal)
                result.execution_results.append(exec_result)

            # ── 5. Log everything ────────────────────────────────────────
            entry = log_action(intent, proposal, pr, exec_result)
            result.logs.append(entry)

        logger.info("━━━ Pipeline complete: %s", result.task_id)
        return result

    async def run_with_subagent(
        self, instruction: str, subagent: SubAgent
    ) -> TaskResult:
        """Execute the pipeline using a sub-agent's restricted policy."""

        result = TaskResult(instruction=instruction)

        # ── 1. Parse ─────────────────────────────────────────────────────
        intent = parse_intent_keywords(instruction)
        result.intent = intent
        log_intent(intent)

        # ── 2. Decompose ─────────────────────────────────────────────────
        proposals = decompose_task(intent)
        result.proposals = proposals

        # ── 3. Sub-agent policy enforcement ──────────────────────────────
        policy_results = [subagent.validate(p) for p in proposals]
        result.policy_results = policy_results

        # ── 4. Execute approved ──────────────────────────────────────────
        for proposal, pr in zip(proposals, policy_results):
            exec_result: Optional[ExecutionResult] = None
            if pr.verdict == Verdict.ALLOW:
                exec_result = await self.executor.execute(proposal)
                result.execution_results.append(exec_result)

            entry = log_action(intent, proposal, pr, exec_result)
            result.logs.append(entry)

        return result
