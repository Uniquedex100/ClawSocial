.PHONY: install dev run test lint format clean openclaw-start openclaw-restart openclaw-stop openclaw-status openclaw-logs

# Install the project and dev dependencies
install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

# Run the FastAPI backend & serve the Frontend UI in development mode
dev:
	cd backend && ../.venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run the full application (Backend API + Frontend UI) normally
run:
	cd backend && ../.venv/bin/python main.py

# Run tests
test:
	.venv/bin/pytest

# Run linter
lint:
	.venv/bin/ruff check .

# Format code
format:
	.venv/bin/ruff format .

# Clean cache files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Start OpenClaw Gateway service
openclaw-start:
	systemctl --user start openclaw-gateway.service

# Restart OpenClaw Gateway service
openclaw-restart:
	systemctl --user restart openclaw-gateway.service

# Stop OpenClaw Gateway service
openclaw-stop:
	systemctl --user stop openclaw-gateway.service

# View OpenClaw Gateway service status
openclaw-status:
	systemctl --user status openclaw-gateway.service

# Tail OpenClaw Gateway logs to see all interactions, thoughts, and received requests
openclaw-logs:
	@set -a; . backend/.env && set +a && node "$$OPENCLAW_CLI_PATH" logs --follow --token "$$OPENCLAW_GATEWAY_TOKEN"
