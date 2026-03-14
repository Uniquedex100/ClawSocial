# ClawSocial - Short Report

## 1. Problem Statement
Social media teams increasingly use autonomous systems for posting, engagement, moderation, and campaign workflows. The core risk is unsafe autonomy: an agent may perform unintended actions, publish on the wrong platform, violate policy, or exceed delegated authority.

ClawSocial addresses this by combining autonomous task handling with deterministic runtime policy enforcement so that every proposed action is either explicitly allowed or blocked before execution.

## 2. Proposed Solution
ClawSocial is an intent-safe autonomous social media agent built on OpenClaw automation with a policy-first enforcement layer (ArmorClaw). It separates reasoning from execution and validates every action proposal against user-defined constraints.

High-level flow:

1. User submits a natural-language instruction.
2. Intent and plan are generated.
3. Action proposals are evaluated by policy rules.
4. Allowed actions execute through OpenClaw.
5. Blocked actions are denied and logged with reason.

## 3. System Architecture

- Intent Layer: Converts natural-language instructions into structured intents.
- Reasoning Layer: Decomposes tasks into executable proposals.
- Policy Layer (ArmorClaw): Enforces platform, action, content, and rate constraints.
- Execution Layer (OpenClaw): Performs real browser automation for approved actions.
- Observability Layer: Audit logs, history, and run-time status for traceability.

## 4. Key Features Implemented

- Intent parsing from plain-language instructions.
- Policy-enforced autonomous execution with ALLOW/BLOCK verdicts.
- Deterministic blocking for unauthorized platform or action.
- Bounded delegation with scoped sub-agent authority.
- Action audit logging and export.
- Interactive dashboard with:
  - live pipeline stages,
  - policy editor and summary,
  - audit logs,
  - history and statistics,
  - chat-like result stream,
  - platform/account command targeting.

## 5. Advanced Capabilities

- Twitter/X common command flows:
  - like latest tweet,
  - repost latest tweet,
  - reply latest tweet.
- Batch actions with guardrails (`max_batch_actions`).
- Thread summarization and suggested reply generation.
- Scheduled actions and watchlist automation (demo-oriented).

## 6. Safety and Compliance Design

ClawSocial enforces safety at runtime, not only at prompt time. Each proposal is validated against active policy rules, including:

- Platform restrictions.
- Allowed/forbidden actions.
- Blocked word constraints.
- Rate and batch limits.
- Delegation boundaries.

If any rule fails, execution is blocked and the reason is logged.

## 7. Demonstration Scenarios

### A. Allowed Scenario
Instruction: Reply to comments on Instagram today.

Outcome: Intent is parsed, proposal is policy-approved, and execution proceeds via OpenClaw.

### B. Blocked Scenario
Instruction: Post this tweet on Twitter (when disallowed by policy).

Outcome: Policy returns BLOCK, execution is skipped, and violation reason appears in logs.

### C. Delegation Scenario
A scoped sub-agent attempts an action outside authority.

Outcome: Action is blocked due to delegated authority constraints.

## 8. Traceability and Evaluation Readiness

The system provides end-to-end evidence for judging:

- input instruction,
- inferred intent,
- generated proposals,
- policy verdicts,
- execution outcomes,
- timestamped audit records.

This supports explainability, safety verification, and reproducible demos.

## 9. Current Limitations

- Some automation features (for example, scheduled/watchlist state) are currently in-memory for demo speed.
- Browser interaction reliability can vary with platform UI changes.
- Full persistence and production hardening are future steps.

## 10. Conclusion

ClawSocial satisfies the hackathon objective by demonstrating autonomous social media execution with policy-aware control, deterministic blocking, and clear traceability. It combines practical automation with safety-first architecture, making it suitable for real-world social operations where control and accountability are mandatory.