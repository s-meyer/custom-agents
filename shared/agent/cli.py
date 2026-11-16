from __future__ import annotations

import asyncio
import json
import logging
import os
import re
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


def _value(message: str, name: str, default: str = "") -> str:
    match = re.search(rf"\b{re.escape(name)}=([^\s]+)", message)
    return match.group(1) if match else default


class _HumanActivityFormatter(logging.Formatter):
    """Render safe, concise progress for an interactive terminal."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        event = message.split(maxsplit=1)[0]
        detail = self._describe(event, message)
        timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
        return f"[{timestamp}] {detail}"

    @staticmethod
    def _describe(event: str, message: str) -> str:
        if event == "task.started":
            return f"Starting task {_value(message, 'task_id')} (attempt {_value(message, 'attempt')})"
        if event == "profile.loaded":
            return (
                f"Using {_value(message, 'profile')} with {_value(message, 'harness')} "
                f"(model: {_value(message, 'model')})"
            )
        if event == "permissions.applied":
            return f"Permissions: {_value(message, 'sandbox')}"
        if event == "repository.checkout.started":
            return "Checking out the repository"
        if event == "repository.checkout.completed":
            return "Repository checkout complete"
        if event == "repository.publish.started":
            return f"Publishing changes to {_value(message, 'branch')}"
        if event == "repository.publish.completed":
            return f"Changes published (commit {_value(message, 'commit')[:12]})"
        if event == "agent.run.started":
            return f"Agent is starting ({_value(message, 'harness')}; {_value(message, 'completion_checks')} final checks)"
        if event == "agent.run.in_progress":
            return f"Agent is still working ({_value(message, 'elapsed_s')}s elapsed)"
        if event == "claude.query.started":
            return f"Claude is starting (model: {_value(message, 'model')})"
        if event == "claude.tool.started":
            activity = _value(message, "activity")
            location = _value(message, "file") or _value(message, "path")
            command = message.partition("command=")[2]
            labels = {
                "read": "Reading",
                "edit": "Editing",
                "write": "Writing",
                "glob": "Finding files in",
                "grep": "Searching",
                "inspect": "Inspecting the workspace",
                "build": "Running a build",
                "compile": "Compiling",
                "git": "Checking Git state",
                "shell": "Running a shell task",
                "structuredoutput": "Preparing the final task report",
            }
            action = labels.get(activity, f"Using {activity or 'a tool'}")
            if command:
                return f"Claude: {action} ({command})"
            return f"Claude: {action}{f' {location}' if location else ''}"
        if event == "claude.assistant.message_received":
            return "Claude is reasoning"
        if event == "claude.activity.summary":
            return f"Claude activity complete ({message.partition('tools=')[2]})"
        if event == "claude.report.validated":
            return "Claude returned a valid task report; starting final verification"
        if event == "claude.report.invalid":
            return "Claude returned an invalid task report; final verification cannot start"
        if event == "claude.query.completed":
            return f"Claude finished its response ({_value(message, 'turns')} turns)"
        if event == "agent.run.completed":
            return f"Agent phase complete (reported: {_value(message, 'status')})"
        if event == "completion.final.started":
            return f"Running mandatory final verification (pass {_value(message, 'pass')}; {_value(message, 'checks')} checks)"
        if event == "completion.check.started":
            command = message.partition("command=")[2].partition(" timeout_s=")[0]
            return f"Verification started: {_value(message, 'id')} ({command})"
        if event == "completion.check.completed":
            status = "passed" if _value(message, "passed") == "True" else "failed"
            return (
                f"Verification {status}: {_value(message, 'id')} "
                f"(warnings: {_value(message, 'warnings')}, errors: {_value(message, 'errors')})"
            )
        if event == "completion.final.completed":
            return (
                f"Final verification {_value(message, 'status')} "
                f"(warnings: {_value(message, 'warnings')}, errors: {_value(message, 'errors')})"
            )
        if event == "completion.repair.requested":
            return f"Asking the agent to fix verification failures (repair {_value(message, 'repair_attempt')})"
        if event == "task.timed_out":
            return f"Task timed out after {_value(message, 'timeout_s')}s"
        if event == "task.failed":
            return f"Task failed ({_value(message, 'error_type')}); see the result artifact for details"
        if event == "task.finished":
            return f"Task finished: {_value(message, 'status')} ({_value(message, 'duration_s')}s)"
        if record.levelno >= logging.ERROR:
            return f"Error: {message}"
        if record.levelno >= logging.WARNING:
            return f"Warning: {message}"
        return message


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    log_format = os.getenv("LOG_FORMAT", "human").lower()
    handler.setFormatter(_JsonFormatter() if log_format == "json" else _HumanActivityFormatter())
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
