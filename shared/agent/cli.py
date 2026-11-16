from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from agent.contract import AgentTaskRequest, AgentTaskResult, Status
from agent.runner import run


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


def _invalid_result(message: str) -> AgentTaskResult:
    return AgentTaskResult(
        task_id=None,
        attempt=None,
        status=Status.FAILED,
        summary="Invalid task request.",
        rationale=message,
    )


def _load_request(source: str | None) -> AgentTaskRequest:
    raw = Path(source).read_text() if source else sys.stdin.read()
    return AgentTaskRequest.model_validate_json(raw)


def main() -> None:
    _configure_logging()
    args = sys.argv[1:]
    mode = args.pop(0) if args and args[0] in {"run", "serve", "smoke"} else os.getenv("AGENT_MODE", "run")
    if mode == "serve":
        import uvicorn
        uvicorn.run("agent.server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8088")))
        return
    if mode == "smoke":
        if os.getenv("AI_PROVIDER", "").strip().lower() == "azure-foundry":
            from agent.azure_auth import foundry_access_token

            foundry_access_token()
            print("Azure AI Foundry service-principal credentials are valid")
            return
        if os.getenv("AGENT_HARNESS") == "claude-code-sdk":
            import claude_agent_sdk  # noqa: F401

            configured = bool(os.getenv("ANTHROPIC_API_KEY"))
            if not configured:
                print("Claude auth missing: set ANTHROPIC_API_KEY", file=sys.stderr)
                raise SystemExit(1)
            print(f"Claude Agent SDK available; API key present={configured}")
            return
        if os.getenv("AGENT_HARNESS") == "opencode-sdk":
            configured = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENCODE_API_KEY"))
            if not configured:
                print("OpenCode auth missing: set ANTHROPIC_API_KEY or OPENCODE_API_KEY", file=sys.stderr)
                raise SystemExit(1)
            print(f"OpenCode SDK available; provider key present={configured}")
            return
        from openai_codex import AsyncCodex
        auth_home = Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex")))
        configured = bool(os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_ACCESS_TOKEN")) or (auth_home / "auth.json").is_file()
        if not configured:
            print("Codex auth missing: provide a CODEX_HOME auth cache or OPENAI_API_KEY", file=sys.stderr)
            raise SystemExit(1)
        print(f"Codex SDK available; CODEX_HOME={auth_home}; auth cache present={configured}")
        return
    if mode != "run":
        raise SystemExit(f"unknown mode: {mode}")
    if len(args) > 1:
        raise SystemExit("usage: python -m agent run [request.json]")
    try:
        request = _load_request(args[0] if args else None)
    except (ValidationError, ValueError) as exc:
        print(_invalid_result(str(exc)).model_dump_json())
        return
    result = asyncio.run(run(request))
    print(result.model_dump_json())
    if result.status == Status.ERROR:
        raise SystemExit(1)
