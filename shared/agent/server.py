from __future__ import annotations

import asyncio
import json
import os

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent.contract import AgentTaskRequest, AgentTaskResult, Status
from agent.runner import run

_lock = asyncio.Lock()


async def readiness(_: Request) -> JSONResponse:
    return JSONResponse({"ready": True})


async def invocation(request: Request) -> JSONResponse:
    if _lock.locked():
        return JSONResponse({"error": "agent is busy"}, status_code=409)
    try:
        payload = await request.json()
        task = AgentTaskRequest.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        result = AgentTaskResult(
            task_id=None,
            attempt=None,
            status=Status.FAILED,
            summary="Invalid task request.",
            rationale=str(exc),
        )
        return JSONResponse(result.model_dump(mode="json"))
    async with _lock:
        result = await run(task)
    return JSONResponse(result.model_dump(mode="json"))


app = Starlette(routes=[Route("/readiness", readiness), Route("/invocations", invocation, methods=["POST"])])
