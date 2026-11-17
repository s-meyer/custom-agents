from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from agent.contract import AgentReport, AgentTaskRequest, CompletionPolicy
from agent.profiles import AgentProfile


class HarnessError(RuntimeError):
    pass


def build_prompt(request: AgentTaskRequest, cwd: Path, completion: CompletionPolicy) -> str:
    criteria = "\n".join(f"- {c.id}: {c.description}" for c in request.acceptance_criteria)
    artifacts = "\n".join(f"- {a.name}: {a.uri}" for a in request.artifact_refs) or "none"
    checks = "\n".join(
        f"- {check.id}: `{shlex.join(check.argv)}`; timeout={check.timeout_s}s; "
        f"fail_on_warning={check.fail_on_warning}"
        for check in completion.checks
    )
    schema = json.dumps(AgentReport.model_json_schema(), indent=2)
    return f"""Objective: {request.objective}
Requested model: {request.model}
Repository is checked out at {cwd} on branch {request.work_branch} (based on {request.base_branch}).
Acceptance criteria:
{criteria}
Input artifacts:
{artifacts}
Mandatory completion checks:
{checks}

Run every completion check before your final response. A successful response requires
every check to pass. The runner independently repeats these checks and returns any
failure to you for repair.

Return exactly one JSON object matching this schema, without markdown fences:
{schema}
"""


def build_system_prompt(profile: AgentProfile) -> str:
    return profile.system_prompt_append


def parse_report_text(text: str, source: str) -> AgentReport:
    """Parse an AgentReport from free-form agent output.

    Accepts a bare JSON object, one wrapped in a markdown code fence, or one
    preceded by prose. Raises HarnessError naming `source` when nothing validates.
    """
    raw = _strip_code_fence(text.strip())
    try:
        return AgentReport.model_validate_json(raw)
    except ValueError as exc:
        error = exc
    start = raw.find("{")
    if start != -1:
        try:
            payload, _ = json.JSONDecoder().raw_decode(raw[start:])
            return AgentReport.model_validate(payload)
        except ValueError:
            pass
    raise HarnessError(f"{source} final response was not valid AgentReport JSON") from error


def _strip_code_fence(raw: str) -> str:
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```")
        raw = raw.removesuffix("```")
    return raw.strip()


SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\s*=\s*(?:'[^']*'|\"[^\"]*\"|\S+)"
)
MAX_COMMAND_SUMMARY = 160


def command_summary(command: object) -> str:
    """One-line, secret-masked, length-capped rendering of a shell command for logs."""
    if not isinstance(command, str):
        return "shell command"
    summary = SECRET_ASSIGNMENT.sub(r"\1=***", " ".join(command.split()))
    if len(summary) > MAX_COMMAND_SUMMARY:
        return summary[:MAX_COMMAND_SUMMARY] + "…"
    return summary


def workspace_path(value: object, cwd: Path) -> str | None:
    """Workspace-relative path for logs; paths outside the workspace are reduced to their name."""
    if not isinstance(value, str) or not value:
        return None
    workspace = cwd.resolve()
    path = (workspace / value).resolve()  # absolute values replace the workspace prefix
    if path.is_relative_to(workspace):
        return str(path.relative_to(workspace))
    return path.name or "external-path"
