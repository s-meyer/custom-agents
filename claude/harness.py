from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolUseBlock, query

from agent.contract import AgentReport, AgentTaskRequest
from agent.profiles import AgentProfile
from agent.harness.common import HarnessError, build_prompt, build_system_prompt
from agent.azure_auth import foundry_access_token, foundry_enabled, foundry_settings

logger = logging.getLogger(__name__)


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
    model = profile.model
    if foundry_enabled():
        endpoint, deployment, _ = foundry_settings()
        model = model or deployment
        os.environ.update(
            {
                "ANTHROPIC_BASE_URL": f"{endpoint}/anthropic",
                "ANTHROPIC_AUTH_TOKEN": foundry_access_token(),
                "ANTHROPIC_MODEL": profile.model or deployment,
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
        model or "sdk-default",
        cwd,
        request.permissions.sandbox,
        ",".join(tools),
    )
    final_text: str | None = None
    async for message in query(
        prompt=build_prompt(request, cwd, request.completion or profile.default_completion), options=options
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    logger.info("claude.tool.started tool=%s", block.name)
                elif isinstance(block, TextBlock):
                    logger.info("claude.assistant.message_received")
        elif isinstance(message, ResultMessage):
            logger.info(
                "claude.query.completed subtype=%s turns=%s cost_usd=%s",
                message.subtype,
                message.num_turns,
                message.total_cost_usd,
            )
            if message.is_error:
                raise HarnessError(message.result or f"Claude SDK finished with {message.subtype}")
            final_text = message.result

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
        return AgentReport.model_validate_json(raw.strip())
    except Exception as exc:
        raise HarnessError("Claude final response was not valid AgentReport JSON") from exc
