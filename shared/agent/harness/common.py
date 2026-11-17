from __future__ import annotations

import json
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
