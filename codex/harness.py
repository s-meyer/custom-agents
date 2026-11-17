from __future__ import annotations

import logging
import os
import re
import shlex
from collections import Counter
from pathlib import Path

from openai_codex import ApprovalMode, AsyncCodex, Sandbox
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    CommandExecutionThreadItem,
    ErrorNotification,
    FileChangeThreadItem,
    ItemCompletedNotification,
    ItemStartedNotification,
    McpToolCallThreadItem,
    MessagePhase,
    ReasoningThreadItem,
    ThreadTokenUsageUpdatedNotification,
    TurnCompletedNotification,
    TurnStatus,
    TurnPlanUpdatedNotification,
    WebSearchThreadItem,
)

from agent.contract import AgentReport, AgentTaskRequest
from agent.profiles import AgentProfile
from agent.azure_auth import (
    foundry_access_token,
    foundry_enabled,
    foundry_settings,
    gateway_access_token,
    gateway_base_url,
    gateway_enabled,
)
from agent.harness.common import (
    HarnessError,
    build_prompt,
    command_summary,
    parse_report_text,
    workspace_path,
)

logger = logging.getLogger(__name__)

# Optional reasoning summaries ("auto", "concise", "detailed"); unset keeps the Codex default.
REASONING_SUMMARY_ENV = "CODEX_REASONING_SUMMARY"
MAX_TEXT_LOG = 240
FAILED_OUTPUT_LINES = 3
PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$", re.MULTILINE)

# "container": the Docker container is the isolation boundary, so Codex runs commands
# without its own bwrap sandbox (which cannot create user namespaces under Docker's
# default seccomp profile). Unset: map the contract sandbox to Codex's sandbox modes.
SANDBOX_BOUNDARY_ENV = "CODEX_SANDBOX_BOUNDARY"
CONTRACT_SANDBOXES = {
    "read_only": Sandbox.read_only,
    "workspace_write": Sandbox.workspace_write,
    "full_access": Sandbox.full_access,
}


async def run(request: AgentTaskRequest, profile: AgentProfile, cwd: Path) -> AgentReport:
    if profile.harness != "codex-sdk":
        raise HarnessError(f"unsupported harness: {profile.harness}")
    sandbox = _select_sandbox(request.permissions.sandbox)
    provider_config = None
    model_provider = None
    model = request.model
    if gateway_enabled():
        provider_config = {
            "model_providers": {
                "azure_gateway": {
                    "name": "Azure AI Gateway",
                    "base_url": gateway_base_url(),
                    "env_key": "AZURE_GATEWAY_ACCESS_TOKEN",
                    "wire_api": "responses",
                }
            }
        }
        os.environ["AZURE_GATEWAY_ACCESS_TOKEN"] = gateway_access_token()
        model_provider = "azure_gateway"
    elif foundry_enabled():
        endpoint, _ = foundry_settings()
        token = foundry_access_token()
        provider_config = {
            "model_providers": {
                "azure_foundry": {
                    "name": "Azure AI Foundry",
                    "base_url": f"{endpoint}/openai/v1",
                    "env_key": "AZURE_AI_FOUNDRY_ACCESS_TOKEN",
                    "wire_api": "responses",
                }
            }
        }
        os.environ["AZURE_AI_FOUNDRY_ACCESS_TOKEN"] = token
        model_provider = "azure_foundry"
    async with AsyncCodex() as codex:
        logger.info(
            "codex.query.started model=%s workspace=%s sandbox=%s",
            model,
            cwd,
            request.permissions.sandbox,
        )
        thread = await codex.thread_start(
            cwd=str(cwd),
            model=model,
            model_provider=model_provider,
            config=provider_config,
            sandbox=sandbox,
            # Headless run: nobody can approve escalations, so never ask.
            approval_mode=ApprovalMode.deny_all,
        )
        prompt = (
            f"{profile.system_prompt_append}\n\n"
            f"{build_prompt(request, cwd, request.completion or profile.default_completion)}"
        )
        summary = os.getenv(REASONING_SUMMARY_ENV, "").strip().lower() or None
        turn = await thread.turn(prompt, summary=summary)
        final_response = await _consume_turn(turn, cwd)
    if not final_response:
        logger.error("codex.query.failed reason=no_final_response")
        raise HarnessError("Codex did not return a final response")
    try:
        report = parse_report_text(final_response, source="Codex")
    except HarnessError:
        logger.error("codex.report.invalid")
        raise
    logger.info("codex.report.validated source=final_text")
    return report


def _select_sandbox(contract_sandbox: str) -> Sandbox:
    if os.getenv(SANDBOX_BOUNDARY_ENV, "").strip().lower() != "container":
        return CONTRACT_SANDBOXES[contract_sandbox]
    if contract_sandbox == "read_only":
        logger.warning(
            "codex.sandbox.not_enforced contract=read_only boundary=container "
            "reason=shell commands can write inside the container"
        )
    logger.info("codex.sandbox.selected contract=%s codex=full_access boundary=container", contract_sandbox)
    return Sandbox.full_access


# --- turn event loop ---------------------------------------------------------


async def _consume_turn(turn, cwd: Path) -> str | None:
    """Stream one turn, logging each step, and return the final assistant message."""
    activity_counts: Counter[str] = Counter()
    messages: list[AgentMessageThreadItem] = []
    usage = None
    completed: TurnCompletedNotification | None = None

    async for event in turn.stream():
        payload = event.payload
        if isinstance(payload, ItemStartedNotification) and payload.turn_id == turn.id:
            _log_item_started(_unwrap(payload.item), cwd, activity_counts)
        elif isinstance(payload, ItemCompletedNotification) and payload.turn_id == turn.id:
            item = _unwrap(payload.item)
            if isinstance(item, AgentMessageThreadItem):
                messages.append(item)
            _log_item_completed(item, cwd)
        elif isinstance(payload, TurnPlanUpdatedNotification) and payload.turn_id == turn.id:
            _log_plan(payload)
        elif isinstance(payload, ThreadTokenUsageUpdatedNotification) and payload.turn_id == turn.id:
            usage = payload.token_usage.total
        elif isinstance(payload, ErrorNotification) and payload.turn_id == turn.id:
            logger.warning(
                "codex.turn.error will_retry=%s message=%s", payload.will_retry, _one_line(payload.error.message)
            )
        elif isinstance(payload, TurnCompletedNotification) and payload.turn.id == turn.id:
            completed = payload

    logger.info(
        "codex.activity.summary tools=%s",
        ",".join(f"{name}={count}" for name, count in sorted(activity_counts.items())) or "none",
    )
    if completed is None:
        raise HarnessError("Codex turn ended without a completion event")
    result = completed.turn
    logger.info(
        "codex.turn.completed status=%s duration_ms=%s input_tokens=%s output_tokens=%s",
        result.status.value,
        result.duration_ms,
        usage.input_tokens if usage else "unknown",
        usage.output_tokens if usage else "unknown",
    )
    if result.status == TurnStatus.failed:
        logger.error("codex.query.failed status=%s", result.status.value)
        raise HarnessError(result.error.message if result.error else "Codex turn failed")

    for item in reversed(messages):
        if item.phase == MessagePhase.final_answer:
            return item.text
    return messages[-1].text if messages else None


def _unwrap(item):
    return item.root if hasattr(item, "root") else item


# --- activity logging --------------------------------------------------------
# Free-text fields (command, query, text, output) always come last so the human
# formatter can take everything after "<field>=".

SHELL_ACTIVITIES: list[tuple[tuple[str, ...], str]] = [
    (("make", "ninja", "cmake"), "build"),
    (("arm-linux-gnueabihf-gcc", "gcc", "clang"), "compile"),
    (("git ",), "git"),
    (("ls", "find", "rg", "grep", "sed", "head", "tail", "cat"), "inspect"),
]


def _log_item_started(item, cwd: Path, activity_counts: Counter[str]) -> None:
    if isinstance(item, CommandExecutionThreadItem):
        activity, details = _describe_command(item, cwd)
        activity_counts[activity] += 1
        logger.info("codex.tool.started tool=shell activity=%s%s", activity, details)
    elif isinstance(item, FileChangeThreadItem):
        activity_counts["edit"] += 1
    elif isinstance(item, McpToolCallThreadItem):
        activity_counts["mcp"] += 1
        logger.info("codex.tool.started tool=%s.%s activity=mcp", item.server, item.tool)
    elif isinstance(item, WebSearchThreadItem):
        activity_counts["web_search"] += 1
        logger.info("codex.tool.started tool=web_search activity=web_search")
    elif isinstance(item, ReasoningThreadItem):
        logger.debug("codex.reasoning.started")


def _log_item_completed(item, cwd: Path) -> None:
    if isinstance(item, AgentMessageThreadItem):
        if item.phase == MessagePhase.commentary:
            logger.info("codex.assistant.commentary text=%s", _one_line(item.text))
        else:
            logger.info("codex.assistant.message_received chars=%s", len(item.text))
    elif isinstance(item, ReasoningThreadItem):
        for summary in item.summary or []:
            if summary.strip():
                logger.info("codex.reasoning.summary text=%s", _one_line(summary))
    elif isinstance(item, FileChangeThreadItem):
        status = getattr(item.status, "value", item.status)
        for change in item.changes:
            kind = getattr(_unwrap(change.kind), "type", "update")
            added, removed = _diff_stats(change.diff, kind)
            logger.info(
                "codex.file.changed kind=%s status=%s added=%s removed=%s file=%s",
                kind,
                status,
                added,
                removed,
                workspace_path(change.path, cwd) or "?",
            )
    elif isinstance(item, CommandExecutionThreadItem):
        if item.exit_code in (None, 0):
            logger.debug(
                "codex.tool.completed exit_code=%s duration_ms=%s", item.exit_code, item.duration_ms
            )
            return
        logger.warning(
            "codex.tool.failed activity=%s exit_code=%s duration_ms=%s output=%s",
            _shell_activity(item.command),
            item.exit_code,
            item.duration_ms,
            _output_tail(item.aggregated_output),
        )


def _log_plan(payload: TurnPlanUpdatedNotification) -> None:
    steps = payload.plan
    done = sum(1 for step in steps if getattr(step.status, "value", step.status) == "completed")
    current = next(
        (step.step for step in steps if getattr(step.status, "value", step.status) == "in_progress"), ""
    )
    logger.info(
        "codex.plan.updated completed=%s total=%s text=%s", done, len(steps), _one_line(current) or "-"
    )


def _describe_command(item: CommandExecutionThreadItem, cwd: Path) -> tuple[str, str]:
    """Classify a shell command, preferring Codex's own parsed actions (read/search/list)."""
    actions = [_unwrap(action) for action in item.command_actions or []]
    kinds = {getattr(action, "type", "unknown") for action in actions}
    if actions and kinds == {"read"}:
        files = ",".join(dict.fromkeys(workspace_path(a.path, cwd) or "?" for a in actions))
        return "read", f" file={files}"
    if actions and kinds == {"search"}:
        action = actions[0]
        path = workspace_path(action.path, cwd) if action.path else None
        return "search", f" path={path or '.'} query={_one_line(action.query or '')}"
    if actions and kinds == {"listFiles"}:
        path = workspace_path(actions[0].path, cwd) if actions[0].path else None
        return "list", f" path={path or '.'}"
    command = _inner_command(item.command)
    if command.lstrip().startswith("apply_patch"):
        files = ",".join(
            dict.fromkeys(workspace_path(path.strip(), cwd) or "?" for _, path in PATCH_FILE.findall(command))
        )
        return "edit", f" file={files or '?'}"
    return _shell_activity(command), f" command={command_summary(command)}"


def _diff_stats(diff: str, kind: str) -> tuple[int, int]:
    lines = diff.splitlines()
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    if not added and not removed and lines:  # add/delete payloads may be raw file content
        if kind == "add":
            added = len(lines)
        elif kind == "delete":
            removed = len(lines)
    return added, removed


def _output_tail(output: str | None) -> str:
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if not lines:
        return "-"
    return command_summary(" | ".join(lines[-FAILED_OUTPUT_LINES:]))


def _one_line(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= MAX_TEXT_LOG else flat[:MAX_TEXT_LOG] + "…"


def _inner_command(command: str) -> str:
    """Strip the `bash -lc '<script>'` wrapper Codex puts around shell commands."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    if len(parts) == 3 and parts[0].rsplit("/", 1)[-1] in {"bash", "sh", "zsh"} and parts[1] in {"-c", "-lc"}:
        return parts[2]
    return command


def _shell_activity(command: object) -> str:
    if not isinstance(command, str):
        return "shell"
    normalized = _inner_command(command).lstrip().lower()
    for prefixes, activity in SHELL_ACTIVITIES:
        if normalized.startswith(prefixes):
            return activity
    return "shell"
