"""Agent Orchestrator — ties all layers into the ClawSocial pipeline.

Pipeline:
    user instruction
        → IntentParser (Gemini)
        → ReasoningEngine (Gemini)
        → [ActionProposals]
        → ArmorClaw (PolicyEngine)
        → OpenClaw Executor
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from delegation import SubAgent
from intent_parser import capture_intent_armoriq
from logger import log_action, log_intent
from models import (
    ExecutionResult,
    TaskResult,
    Verdict,
)
from openclaw_executor import OpenClawExecutor
from policy_engine import ArmorClaw
from reasoning_engine import build_action_proposals, generate_plan_for_armoriq

logger = logging.getLogger("clawsocial.agent")


class ClawSocialAgent:
    """Main orchestrator for the ClawSocial pipeline."""

    def __init__(
        self,
        policy_engine: Optional[ArmorClaw] = None,
        executor: Optional[OpenClawExecutor] = None,
        use_llm: bool = True,
        dry_run: bool = False,
    ):
        self.policy_engine = policy_engine or ArmorClaw()
        self.executor = executor or OpenClawExecutor(dry_run=dry_run)
        self.use_llm = use_llm and bool(settings.llm_api_key)

    async def _build_intent_and_proposals(self, instruction: str):
        """Create intent, capture an intent token, and build local action proposals."""
        plan_dict = generate_plan_for_armoriq(instruction)
        intent, intent_token = await capture_intent_armoriq(instruction, plan_dict)
        proposals = build_action_proposals(intent, instruction)
        for proposal in proposals:
            proposal.intent_token = intent_token
        return intent, proposals

    async def run(self, instruction: str) -> TaskResult:
        """Execute the full pipeline from a natural-language instruction."""

        result = TaskResult(instruction=instruction)

        # ── 1 & 2. Intent Capture + Reasoning (via ArmorIQ SDK) ──────────
        logger.info("━━━ Pipeline start: %s", instruction)
        
        intent, proposals = await self._build_intent_and_proposals(instruction)

        result.intent = intent
        log_intent(intent)
        result.proposals = proposals
        logger.info("ArmorIQ Plan captured. Generated %d action proposals", len(proposals))

        # ── 3. Policy enforcement (Local ArmorClaw) ───────────────────────
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

        # ── 1 & 2. Intent capture + decomposition ───────────────────────
        intent, proposals = await self._build_intent_and_proposals(instruction)
        result.intent = intent
        log_intent(intent)
        result.proposals = proposals

        # ── 3. Sub-agent policy enforcement ──────────────────────────────
        policy_results = [subagent.validate(p) for p in proposals]
        result.policy_results = policy_results

        # ── 4. Execute approved ──────────────────────────────────────────
        for proposal, pr in zip(proposals, policy_results):
            exec_result: Optional[ExecutionResult] = None
            if pr.verdict == Verdict.ALLOW:
                exec_result = await self.executor.execute(proposal)
                if exec_result.success:
                    subagent.record_execution(proposal)
                result.execution_results.append(exec_result)

            entry = log_action(intent, proposal, pr, exec_result)
            result.logs.append(entry)

        return result
