# ClawSocial — Intent-Safe Autonomous Social Media Agent

An **OpenClaw-based** autonomous social media management agent with runtime intent enforcement (**ArmorClaw**). The system ensures autonomous actions always remain within user-defined constraints.

## Architecture

```
User Instruction
      │
  Intent Parser      ← NL → structured intent
      │
  Reasoning Engine   ← LLM task decomposition
      │
  Action Proposals
      │
  ArmorClaw          ← Policy enforcement (ALLOW / BLOCK)
      │
      ├── ALLOW ──→  OpenClaw Executor (browser automation)
      │
      └── BLOCK ──→  Violation Logger
```

## Quick Start

```bash
# 1. Install dependencies
pip install -e .

# 2. Copy env template
cp .env.example .env
# Edit .env with your API keys

# 3. Run the server
python main.py
# or: uvicorn main:app --reload

# 4. Open API docs
# http://localhost:8000/docs
```

## Demo Endpoints

| Endpoint | Description |
|---|---|
| `POST /api/demo/allowed` | Reply to Instagram comments (ALLOWED) |
| `POST /api/demo/blocked` | Post a tweet (BLOCKED - unauthorized platform) |
| `POST /api/demo/delegation` | Engagement agent tries to publish (BLOCKED - outside authority) |
| `POST /api/task` | Submit any instruction |
| `GET /api/policy` | View current policy |
| `GET /api/logs` | View action audit trail |

## Technology Stack

- **Core**: Python, OpenClaw
- **AI**: LLM (GPT / Claude), keyword-based fallback
- **Backend**: FastAPI, Pydantic
- **Execution**: OpenClaw browser automation (CLI / HTTP / dry-run)

## Key Features

- **Intent Parsing** — NL instructions → structured intents
- **Policy Enforcement** — platform, content, action, and rate-limit checks
- **Deterministic Blocking** — unauthorized actions never reach execution
- **Structured Logging** — full audit trail for every action
- **Bounded Delegation** — sub-agents with restricted authority
