from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolUseBlock, query

from agent.contract import AgentReport, AgentTaskRequest
from agent.profiles import AgentProfile
from agent.harness.common import HarnessError, build_prompt, build_system_prompt
from agent.azure_auth import foundry_access_token, foundry_enabled, foundry_settings

logger = logging.getLogger(__name__)


def _workspace_path(value: object, cwd: Path) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return str(Path(value).resolve().relative_to(cwd.resolve()))
    except ValueError:
        return Path(value).name or "external-path"


def _shell_activity(command: object) -> str:
    if not isinstance(command, str):
        return "shell"
    normalized = command.lstrip().lower()
    if normalized.startswith(("make", "ninja", "cmake")):
        return "build"
    if normalized.startswith(("arm-linux-gnueabihf-gcc", "gcc", "clang")):
        return "compile"
    if normalized.startswith("git "):
        return "git"
    if normalized.startswith(("ls", "find", "rg", "grep", "sed", "head", "tail", "cat")):
        return "inspect"
    return "shell"


def _command_summary(command: object) -> str:
    """Keep an activity log useful without allowing secrets into it."""
    if not isinstance(command, str):
        return "shell command"
    summary = " ".join(command.split())
    summary = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password|authorization)\s*=\s*(?:'[^']*'|\"[^\"]*\"|\S+)",
        r"\1=***",
        summary,
    )
    return summary[:160] + ("…" if len(summary) > 160 else "")


def _tool_activity(block: ToolUseBlock, cwd: Path) -> tuple[str, str]:
    tool_input = getattr(block, "input", {})
    if not isinstance(tool_input, dict):
        return block.name, ""
    if block.name == "Bash":
        command = tool_input.get("command")
        return _shell_activity(command), f" command={_command_summary(command)}"
    if block.name in {"Read", "Write", "Edit"}:
        path = _workspace_path(tool_input.get("file_path") or tool_input.get("path"), cwd)
        return block.name.lower(), f" file={path}" if path else ""
    if block.name in {"Glob", "Grep"}:
        path = _workspace_path(tool_input.get("path"), cwd)
        return block.name.lower(), f" path={path}" if path else ""
    return block.name.lower(), ""


def _tool_permissions(sandbox: str) -> tuple[list[str], str]:
    read_tools = ["Read", "Glob", "Grep"]
    edit_tools = ["Write", "Edit"]
    if sandbox == "read_only":
        return read_tools, "default"
    if sandbox == "workspace_write":
        return [*read_tools, *edit_tools, "Bash"], "acceptEdits"
    return [*read_tools, *edit_tools, "Bash"], "bypassPermissions"


async def run(request: AgentTaskRequest, profile: AgentProfile, cwd: Path) -> AgentReport:
    if profile.harness != "claude-code-sdk":
        raise HarnessError(f"unsupported harness: {profile.harness}")

    tools, permission_mode = _tool_permissions(request.permissions.sandbox)
    model = request.model
    if foundry_enabled():
        endpoint, _, _ = foundry_settings()
        os.environ.update(
            {
                "ANTHROPIC_BASE_URL": f"{endpoint}/anthropic",
                "ANTHROPIC_AUTH_TOKEN": foundry_access_token(),
                "ANTHROPIC_MODEL": model,
            }
        )
    options = ClaudeAgentOptions(
        cwd=str(cwd),
        model=model,
        system_prompt=build_system_prompt(profile),
        tools=tools,
        allowed_tools=tools,
        permission_mode=permission_mode,
        max_turns=request.limits.max_steps,
        max_budget_usd=request.limits.max_cost_usd,
        setting_sources=[],
    )
    logger.info(
        "claude.query.started model=%s workspace=%s sandbox=%s tools=%s",
        model,
        cwd,
        request.permissions.sandbox,
        ",".join(tools),
    )
    final_text: str | None = None
    tool_counts: dict[str, int] = {}
    async for message in query(
        prompt=build_prompt(request, cwd, request.completion or profile.default_completion), options=options
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    activity, details = _tool_activity(block, cwd)
                    tool_counts[activity] = tool_counts.get(activity, 0) + 1
                    logger.info("claude.tool.started tool=%s activity=%s%s", block.name, activity, details)
                elif isinstance(block, TextBlock):
                    logger.info("claude.assistant.message_received chars=%s", len(block.text))
        elif isinstance(message, ResultMessage):
            logger.info(
                "claude.query.completed subtype=%s turns=%s cost_usd=%s",
                message.subtype,
                message.num_turns,
                message.total_cost_usd,
            )
            if message.is_error:
                logger.error("claude.query.failed subtype=%s", message.subtype)
                raise HarnessError(message.result or f"Claude SDK finished with {message.subtype}")
            final_text = message.result

    logger.info(
        "claude.activity.summary tools=%s",
        ",".join(f"{activity}={count}" for activity, count in sorted(tool_counts.items())) or "none",
    )
    if not final_text:
        raise HarnessError("Claude SDK did not return a final result")
    raw = final_text.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    try:
        report = AgentReport.model_validate_json(raw.strip())
        logger.info("claude.report.validated source=final_text")
        return report
    except Exception as exc:
        start = raw.find("{")
        if start > 0:
            try:
                payload, _ = json.JSONDecoder().raw_decode(raw[start:])
                report = AgentReport.model_validate(payload)
                logger.info("claude.report.validated source=embedded_json")
                return report
            except (json.JSONDecodeError, ValueError):
                pass
        logger.error(
            "claude.report.invalid source=final_text chars=%s json_object=%s",
            len(raw),
            raw.startswith("{"),
        )
        raise HarnessError("Claude final response was not valid AgentReport JSON") from exc
