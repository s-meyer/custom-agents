from __future__ import annotations

import logging
import os
from pathlib import Path

from openai_codex import AsyncCodex, Sandbox

from agent.contract import AgentReport, AgentTaskRequest
from agent.profiles import AgentProfile
from agent.azure_auth import foundry_access_token, foundry_enabled, foundry_settings
from agent.harness.common import HarnessError, build_prompt, parse_report_text

logger = logging.getLogger(__name__)


async def run(request: AgentTaskRequest, profile: AgentProfile, cwd: Path) -> AgentReport:
    if profile.harness != "codex-sdk":
        raise HarnessError(f"unsupported harness: {profile.harness}")
    sandbox = {
        "read_only": Sandbox.read_only,
        "workspace_write": Sandbox.workspace_write,
        "full_access": Sandbox.full_access,
    }[request.permissions.sandbox]
    provider_config = None
    model_provider = None
    model = request.model
    if foundry_enabled():
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
            "codex.thread.starting model=%s workspace=%s sandbox=%s",
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
        )
        logger.info("codex.thread.started")
        logger.info("codex.prompt.submitted")
        result = await thread.run(
            f"{profile.system_prompt_append}\n\n{build_prompt(request, cwd, request.completion or profile.default_completion)}"
        )
        logger.info("codex.response.received")
    return parse_report_text(result.final_response, source="Codex")
