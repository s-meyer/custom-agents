from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

from agent.contract import (
    AgentTaskRequest,
    AgentTaskResult,
    ArtifactRef,
    CompletionCheck,
    CompletionPolicy,
    CriterionResult,
    Status,
)
from agent.git_ops import checkout, publish
from agent.harness.common import HarnessError
from agent.profiles import load_profile

logger = logging.getLogger(__name__)
WARNING_PATTERN = re.compile(r"\bwarning\s*:", re.IGNORECASE)
ERROR_PATTERN = re.compile(r"\berror\s*:", re.IGNORECASE)


@dataclass(frozen=True)
class CompletionCheckResult:
    check: CompletionCheck
    command: str
    output: str
    returncode: int | None
    timed_out: bool
    warning_count: int
    error_count: int

    @property
    def passed(self) -> bool:
        return (
            not self.timed_out
            and self.returncode == 0
            and self.error_count == 0
            and (not self.check.fail_on_warning or self.warning_count == 0)
        )


async def _log_agent_progress(task_id: str, harness: str, interval_s: int = 15) -> None:
    elapsed = 0
    while True:
        await asyncio.sleep(interval_s)
        elapsed += interval_s
        logger.info("agent.run.in_progress task_id=%s harness=%s elapsed_s=%s", task_id, harness, elapsed)


def _remaining_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


async def _run_agent_attempt(run_agent, request: AgentTaskRequest, profile, cwd: Path, deadline: float):
    progress = asyncio.create_task(_log_agent_progress(request.task_id, profile.harness))
    try:
        return await asyncio.wait_for(run_agent(request, profile, cwd), timeout=_remaining_time(deadline))
    finally:
        progress.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await progress


async def _run_completion_check(
    check: CompletionCheck, cwd: Path, deadline: float
) -> CompletionCheckResult:
    command = shlex.join(check.argv)
    timeout_s = min(float(check.timeout_s), _remaining_time(deadline))
    logger.info("completion.check.started id=%s command=%s timeout_s=%s", check.id, command, timeout_s)
    try:
        process = await asyncio.create_subprocess_exec(
            *check.argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        output = f"Could not start verification command: {type(exc).__name__}: {exc}\n"
        return CompletionCheckResult(check, command, output, None, False, 0, 1)
    try:
        output_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        timed_out = False
    except TimeoutError:
        process.terminate()
        with contextlib.suppress(ProcessLookupError):
            await process.wait()
        output_bytes = b""
        timed_out = True
    output = output_bytes.decode(errors="replace")
    result = CompletionCheckResult(
        check=check,
        command=command,
        output=output,
        returncode=process.returncode,
        timed_out=timed_out,
        warning_count=len(WARNING_PATTERN.findall(output)),
        error_count=len(ERROR_PATTERN.findall(output)),
    )
    logger.info(
        "completion.check.completed id=%s passed=%s returncode=%s warnings=%s errors=%s timed_out=%s",
        check.id,
        result.passed,
        result.returncode,
        result.warning_count,
        result.error_count,
        result.timed_out,
    )
    return result


async def _run_completion_policy(
    policy: CompletionPolicy, cwd: Path, deadline: float, output_dir: Path, pass_number: int
) -> tuple[list[CompletionCheckResult], list[ArtifactRef]]:
    checks: list[CompletionCheckResult] = []
    artifacts: list[ArtifactRef] = []
    for check in policy.checks:
        result = await _run_completion_check(check, cwd, deadline)
        checks.append(result)
        log_path = output_dir / f"completion-{pass_number}-{check.id}.log"
        log_path.write_text(
            f"$ {result.command}\n"
            f"exit_code={result.returncode} timed_out={result.timed_out} "
            f"warnings={result.warning_count} errors={result.error_count}\n\n"
            f"{result.output}"
        )
        artifacts.append(
            ArtifactRef(name=f"completion-{pass_number}-{check.id}", uri=log_path.as_uri(), media_type="text/plain")
        )
    return checks, artifacts


def _completion_feedback(checks: list[CompletionCheckResult]) -> str:
    failed = [check for check in checks if not check.passed]
    details = []
    for check in failed:
        output = check.output[-4000:] or "No command output was captured."
        details.append(
            f"Verification `{check.check.id}` failed: `{check.command}`; "
            f"exit_code={check.returncode}, warnings={check.warning_count}, errors={check.error_count}, "
            f"timed_out={check.timed_out}.\nOutput:\n{output}"
        )
    return "\n\n".join(details)


def _load_harness(harness: str):
    if harness == "codex-sdk":
        from codex_harness import run as run_agent
    elif harness == "claude-code-sdk":
        from claude_harness import run as run_agent
    elif harness == "opencode-sdk":
        from opencode_harness import run as run_agent
    else:
        raise HarnessError(f"unsupported harness: {harness}")
    return run_agent


async def run(request: AgentTaskRequest) -> AgentTaskResult:
    started = time.monotonic()
    work_root = Path(os.getenv("WORKSPACE_DIR", "/workspace"))
    out_root = Path(os.getenv("OUTPUT_DIR", "/output"))
    profile_root = Path(os.getenv("AGENT_PROFILES_DIR", "/app/profiles"))
    task_dir = work_root / request.task_id / str(request.attempt)
    output_dir = out_root / request.task_id / str(request.attempt)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = AgentTaskResult(
        contract_version=request.contract_version,
        task_id=request.task_id,
        attempt=request.attempt,
        status=Status.ERROR,
        summary="Task did not complete.",
        rationale="Runner did not receive a valid final report.",
    )
    transcript: dict[str, object] = {}
    logger.info("task.started task_id=%s attempt=%s", request.task_id, request.attempt)
    try:
        if request.session_mode != "new":
            result.status = Status.FAILED
            result.summary = "Resume sessions are not supported yet."
            result.rationale = "session_mode must be 'new' in this implementation."
            return result
        profile = load_profile(profile_root, request.agent_profile.name, request.agent_profile.version)
        logger.info(
            "profile.loaded task_id=%s profile=%s@%s harness=%s model=%s",
            request.task_id,
            request.agent_profile.name,
            request.agent_profile.version,
            profile.harness,
            profile.model or "sdk-default",
        )
        logger.info("permissions.applied task_id=%s sandbox=%s", request.task_id, request.permissions.sandbox)
        run_agent = _load_harness(profile.harness)
        logger.info("repository.checkout.started task_id=%s", request.task_id)
        await checkout(request.repository, request.base_branch, request.work_branch, task_dir)
        logger.info("repository.checkout.completed task_id=%s workspace=%s", request.task_id, task_dir)
        completion = request.completion or profile.default_completion
        deadline = started + request.limits.max_duration_s
        if request.permissions.sandbox == "read_only":
            raise HarnessError("Completion checks require workspace_write or full_access permissions")
        logger.info(
            "agent.run.started task_id=%s harness=%s timeout_s=%s completion_checks=%s",
            request.task_id,
            profile.harness,
            request.limits.max_duration_s,
            len(completion.checks),
        )
        attempt_request = request
        completion_attempt = 0
        completion_artifacts: list[ArtifactRef] = []
        completion_results: list[CompletionCheckResult] = []
        reports: list[dict[str, object]] = []
        while True:
            report = await _run_agent_attempt(run_agent, attempt_request, profile, task_dir, deadline)
            reports.append(report.model_dump(mode="json"))
            logger.info(
                "agent.run.completed task_id=%s harness=%s status=%s completion_attempt=%s",
                request.task_id,
                profile.harness,
                report.status,
                completion_attempt,
            )
            logger.info(
                "completion.final.started task_id=%s pass=%s checks=%s",
                request.task_id,
                completion_attempt + 1,
                len(completion.checks),
            )
            completion_results, artifacts = await _run_completion_policy(
                completion, task_dir, deadline, output_dir, completion_attempt + 1
            )
            completion_artifacts.extend(artifacts)
            warnings = sum(check.warning_count for check in completion_results)
            errors = sum(check.error_count for check in completion_results)
            passed = all(check.passed for check in completion_results)
            logger.info(
                "completion.final.completed task_id=%s pass=%s status=%s warnings=%s errors=%s",
                request.task_id,
                completion_attempt + 1,
                "passed" if passed else "failed",
                warnings,
                errors,
            )
            if passed:
                break
            if completion_attempt >= completion.max_repair_attempts:
                break
            completion_attempt += 1
            attempt_request = request.model_copy(
                update={
                    "objective": (
                        f"{request.objective}\n\nA mandatory final verification failed after your prior response. "
                        "Fix the current workspace, then return the required JSON report only after it passes.\n\n"
                        f"{_completion_feedback(completion_results)}"
                    )
                }
            )
            logger.info(
                "completion.repair.requested task_id=%s repair_attempt=%s",
                request.task_id,
                completion_attempt,
            )
        logger.info("agent.run.completed task_id=%s harness=%s status=%s", request.task_id, profile.harness, report.status)
        transcript["reports"] = reports
        transcript["completion"] = [
            {
                "id": check.check.id,
                "command": check.command,
                "returncode": check.returncode,
                "timed_out": check.timed_out,
                "warnings": check.warning_count,
                "errors": check.error_count,
                "passed": check.passed,
            }
            for check in completion_results
        ]
        result.status = Status(report.status)
        result.criteria_results = report.criteria_results
        result.summary = report.summary
        result.rationale = report.rationale
        result.open_questions = report.open_questions
        result.artifact_refs.extend(completion_artifacts)
        completion_warnings = sum(check.warning_count for check in completion_results)
        completion_errors = sum(check.error_count for check in completion_results)
        result.usage["completion_checks"] = len(completion_results)
        result.usage["completion_repair_attempts"] = completion_attempt
        result.usage["completion_warnings"] = completion_warnings
        result.usage["completion_errors"] = completion_errors
        for check in completion_results:
            result.criteria_results.append(
                CriterionResult(
                    id=f"completion-{check.check.id}",
                    met=check.passed,
                    evidence=(
                        f"{check.command}: exit_code={check.returncode}, timed_out={check.timed_out}, "
                        f"warnings={check.warning_count}, errors={check.error_count}."
                    ),
                )
            )
        known = {c.id for c in result.criteria_results}
        for criterion in request.acceptance_criteria:
            if criterion.id not in known:
                result.criteria_results.append(
                    {"id": criterion.id, "met": None, "evidence": "No result was provided for this criterion."}
                )
        if result.status == Status.SUCCEEDED:
            unmet = [c for c in result.criteria_results if c.met is not True]
            if unmet:
                result.status = Status.NEEDS_EXTERNAL_CHECK if any(c.met is None for c in unmet) else Status.FAILED
                result.rationale += " Runner changed status because not all criteria were met."
        failed_checks = [check for check in completion_results if not check.passed]
        if failed_checks:
            result.status = Status.FAILED
            result.summary = (
                "Mandatory completion checks failed "
                f"(warnings={completion_warnings}, errors={completion_errors})."
            )
            result.rationale = (
                "The runner rejected completion after "
                f"{completion_attempt} repair attempt(s). {_completion_feedback(failed_checks)}"
            )
        elif result.status == Status.SUCCEEDED:
            result.summary = (
                f"{result.summary} Final completion checks passed "
                f"(warnings={completion_warnings}, errors={completion_errors})."
            )
        if result.status != Status.ERROR:
            logger.info("repository.publish.started task_id=%s branch=%s", request.task_id, request.work_branch)
            commit, patch = await publish(task_dir, request.work_branch, request.base_branch)
            result.commit_hash = commit
            patch_path = output_dir / "changes.patch"
            patch_path.write_text(patch)
            result.artifact_refs.append(ArtifactRef(name="patch", uri=patch_path.as_uri(), media_type="text/x-diff"))
            logger.info("repository.publish.completed task_id=%s commit=%s", request.task_id, commit)
    except TimeoutError:
        result.status = Status.ABORTED
        result.summary = "Task reached max_duration_s."
        result.rationale = "The runner cancelled the SDK call at the configured time limit."
        logger.warning("task.timed_out task_id=%s timeout_s=%s", request.task_id, request.limits.max_duration_s)
    except Exception as exc:
        result.status = Status.ERROR
        result.summary = "Technical error while running the task."
        result.rationale = f"{type(exc).__name__}: {exc}"
        logger.exception("task.failed task_id=%s error_type=%s", request.task_id, type(exc).__name__)
        if isinstance(exc, HarnessError):
            transcript["harness_error"] = str(exc)
    finally:
        result.usage["duration_s"] = round(time.monotonic() - started, 2)
        logger.info(
            "task.finished task_id=%s attempt=%s status=%s duration_s=%s",
            request.task_id,
            request.attempt,
            result.status.value,
            result.usage["duration_s"],
        )
        transcript_path = output_dir / "transcript.jsonl"
        transcript_path.write_text(json.dumps(transcript, ensure_ascii=False) + "\n")
        result_path = output_dir / "result.json"
        result_path.write_text(result.model_dump_json(indent=2) + "\n")
        result.artifact_refs.append(ArtifactRef(name="transcript", uri=transcript_path.as_uri(), media_type="application/jsonl"))
        result.artifact_refs.append(ArtifactRef(name="result", uri=result_path.as_uri(), media_type="application/json"))
        result_path.write_text(result.model_dump_json(indent=2) + "\n")
    return result
