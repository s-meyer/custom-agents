"""Claude Agent SDK harness: runs one AgentTaskRequest and returns an AgentReport."""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionMode,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)
from pydantic import ValidationError

from agent.azure_auth import foundry_access_token, foundry_enabled, foundry_settings
from agent.contract import AgentReport, AgentTaskRequest
from agent.harness.common import HarnessError, build_prompt, build_system_prompt, parse_report_text
from agent.profiles import AgentProfile

logger = logging.getLogger(__name__)

HARNESS_NAME = "claude-code-sdk"

READ_TOOLS = ["Read", "Glob", "Grep"]
WRITE_TOOLS = ["Write", "Edit", "Bash"]

# Contract sandbox level -> (available tools, permission mode).
SANDBOX_POLICIES: dict[str, tuple[list[str], PermissionMode]] = {
    "read_only": (READ_TOOLS, "default"),
    "workspace_write": ([*READ_TOOLS, *WRITE_TOOLS], "acceptEdits"),
    "full_access": ([*READ_TOOLS, *WRITE_TOOLS], "bypassPermissions"),
}

# First matching command prefix wins.
SHELL_ACTIVITIES: list[tuple[tuple[str, ...], str]] = [
    (("make", "ninja", "cmake"), "build"),
    (("arm-linux-gnueabihf-gcc", "gcc", "clang"), "compile"),
    (("git ",), "git"),
    (("ls", "find", "rg", "grep", "sed", "head", "tail", "cat"), "inspect"),
]

SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\s*=\s*(?:'[^']*'|\"[^\"]*\"|\S+)"
)
MAX_COMMAND_SUMMARY = 160


async def run(request: AgentTaskRequest, profile: AgentProfile, cwd: Path) -> AgentReport:
    if profile.harness != HARNESS_NAME:
        raise HarnessError(f"unsupported harness: {profile.harness}")

    options = _build_options(request, profile, cwd)
    prompt = build_prompt(request, cwd, request.completion or profile.default_completion)
    logger.info(
        "claude.query.started model=%s workspace=%s sandbox=%s tools=%s",
        options.model,
        cwd,
        request.permissions.sandbox,
        ",".join(options.tools or []),
    )
    result = await _run_query(prompt, options, cwd)
    return _report_from_result(result)


# --- configuration -----------------------------------------------------------


def _build_options(request: AgentTaskRequest, profile: AgentProfile, cwd: Path) -> ClaudeAgentOptions:
    tools, permission_mode = SANDBOX_POLICIES[request.permissions.sandbox]
    return ClaudeAgentOptions(
        cwd=str(cwd),
        model=request.model,
        # Keep Claude Code's own system prompt (tool usage, git hygiene) and add the profile's rules.
        system_prompt={"type": "preset", "preset": "claude_code", "append": build_system_prompt(profile)},
        tools=tools,
        allowed_tools=tools,
        permission_mode=permission_mode,
        max_turns=request.limits.max_steps,
        max_budget_usd=request.limits.max_cost_usd,
        # The CLI validates the final answer against this schema and returns it as structured_output.
        output_format={"type": "json_schema", "schema": AgentReport.model_json_schema()},
        # Passed to the CLI subprocess only; this process's environment stays untouched.
        env=_provider_env(request.model),
        # Ignore user/project settings and CLAUDE.md so every run is reproducible.
        setting_sources=[],
    )


def _provider_env(model: str) -> dict[str, str]:
    if not foundry_enabled():
        return {}
    endpoint, _ = foundry_settings()
    return {
        "ANTHROPIC_BASE_URL": f"{endpoint}/anthropic",
        "ANTHROPIC_AUTH_TOKEN": foundry_access_token(),
        "ANTHROPIC_MODEL": model,
    }


# --- query loop --------------------------------------------------------------


async def _run_query(prompt: str, options: ClaudeAgentOptions, cwd: Path) -> ResultMessage:
    result: ResultMessage | None = None
    activity_counts: Counter[str] = Counter()

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            _log_assistant_message(message, cwd, activity_counts)
        elif isinstance(message, ResultMessage):
            result = message

    logger.info(
        "claude.activity.summary tools=%s",
        ",".join(f"{name}={count}" for name, count in sorted(activity_counts.items())) or "none",
    )
    if result is None:
        raise HarnessError("Claude SDK did not return a final result")

    logger.info(
        "claude.query.completed subtype=%s turns=%s cost_usd=%s permission_denials=%s",
        result.subtype,
        result.num_turns,
        result.total_cost_usd,
        len(result.permission_denials or []),
    )
    if result.is_error:
        logger.error("claude.query.failed subtype=%s", result.subtype)
        raise HarnessError(result.result or f"Claude SDK finished with {result.subtype}")
    return result


def _log_assistant_message(message: AssistantMessage, cwd: Path, activity_counts: Counter[str]) -> None:
    for block in message.content:
        if isinstance(block, ToolUseBlock):
            activity, details = _describe_tool_use(block, cwd)
            activity_counts[activity] += 1
            logger.info("claude.tool.started tool=%s activity=%s%s", block.name, activity, details)
        elif isinstance(block, TextBlock):
            logger.info("claude.assistant.message_received chars=%s", len(block.text))


def _report_from_result(result: ResultMessage) -> AgentReport:
    if result.structured_output is not None:
        try:
            report = AgentReport.model_validate(result.structured_output)
        except ValidationError as exc:
            raise HarnessError("Claude structured output was not a valid AgentReport") from exc
        logger.info("claude.report.validated source=structured_output")
        return report

    # Fallback for CLI versions that ignore output_format.
    if not result.result:
        raise HarnessError("Claude SDK did not return a final result")
    report = parse_report_text(result.result, source="Claude")
    logger.info("claude.report.validated source=final_text")
    return report


# --- activity logging --------------------------------------------------------


def _describe_tool_use(block: ToolUseBlock, cwd: Path) -> tuple[str, str]:
    """Return (activity, log details) for a tool call, without leaking secrets or absolute paths."""
    tool_input = block.input if isinstance(block.input, dict) else {}
    match block.name:
        case "Bash":
            command = tool_input.get("command")
            return _shell_activity(command), f" command={_command_summary(command)}"
        case "Read" | "Write" | "Edit":
            path = _workspace_path(tool_input.get("file_path") or tool_input.get("path"), cwd)
            return block.name.lower(), f" file={path}" if path else ""
        case "Glob" | "Grep":
            path = _workspace_path(tool_input.get("path"), cwd)
            return block.name.lower(), f" path={path}" if path else ""
        case _:
            return block.name.lower(), ""


def _shell_activity(command: object) -> str:
    if not isinstance(command, str):
        return "shell"
    normalized = command.lstrip().lower()
    for prefixes, activity in SHELL_ACTIVITIES:
        if normalized.startswith(prefixes):
            return activity
    return "shell"


def _command_summary(command: object) -> str:
    if not isinstance(command, str):
        return "shell command"
    summary = SECRET_ASSIGNMENT.sub(r"\1=***", " ".join(command.split()))
    if len(summary) > MAX_COMMAND_SUMMARY:
        return summary[:MAX_COMMAND_SUMMARY] + "…"
    return summary


def _workspace_path(value: object, cwd: Path) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    workspace = cwd.resolve()
    path = (workspace / value).resolve()  # absolute values replace the workspace prefix
    if path.is_relative_to(workspace):
        return str(path.relative_to(workspace))
    return path.name or "external-path"
