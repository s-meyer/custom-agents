from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from agent.azure_auth import foundry_access_token, foundry_enabled, foundry_settings
from agent.contract import AgentReport, AgentTaskRequest
from agent.harness.common import HarnessError, build_prompt
from agent.profiles import AgentProfile

logger = logging.getLogger(__name__)
RUNNER = Path("/app/opencode-sdk-runner.ts")


async def run(request: AgentTaskRequest, profile: AgentProfile, cwd: Path) -> AgentReport:
    if profile.harness != "opencode-sdk":
        raise HarnessError(f"unsupported harness: {profile.harness}")

    payload = {
        "prompt": (
            f"{profile.system_prompt_append}\n\n"
            f"{build_prompt(request, cwd, request.completion or profile.default_completion)}"
        ),
        "cwd": str(cwd),
        "model": request.model or profile.model,
        "sandbox": request.permissions.sandbox,
    }
    if foundry_enabled():
        endpoint, deployment, _ = foundry_settings()
        api = os.getenv("AZURE_AI_FOUNDRY_API", "openai").strip().lower()
        if api not in {"openai", "anthropic"}:
            raise HarnessError("AZURE_AI_FOUNDRY_API must be 'openai' or 'anthropic'")
        payload["azure_foundry"] = {
            "endpoint": endpoint,
            "deployment": request.model or deployment,
            "access_token": foundry_access_token(),
            "api": api,
        }
    proc = await asyncio.create_subprocess_exec(
        "bun",
        "run",
        str(RUNNER),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await proc.communicate(json.dumps(payload).encode())
    except asyncio.CancelledError:
        proc.terminate()
        await proc.wait()
        raise

    for line in stderr.decode(errors="replace").splitlines():
        if line.strip():
            logger.info("opencode.sdk %s", line)
    if proc.returncode:
        raise HarnessError(stderr.decode(errors="replace").strip() or "OpenCode SDK process failed")
    try:
        response = json.loads(stdout)
        return AgentReport.model_validate_json(response["final_response"])
    except Exception as exc:
        raise HarnessError("OpenCode final response was not valid AgentReport JSON") from exc
