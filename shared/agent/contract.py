from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentProfileRef(StrictModel):
    name: str
    version: str


class ArtifactRef(StrictModel):
    name: str
    uri: str
    media_type: str | None = None


class AcceptanceCriterion(StrictModel):
    id: str
    description: str


class Limits(StrictModel):
    max_duration_s: int = Field(gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_steps: int | None = Field(default=None, gt=0)


class JobPermissions(StrictModel):
    sandbox: Literal["read_only", "workspace_write", "full_access"] = "workspace_write"


class CompletionCheck(StrictModel):
    id: str = Field(min_length=1)
    argv: list[str] = Field(min_length=1)
    timeout_s: int = Field(default=300, gt=0)
    fail_on_warning: bool = True


class CompletionPolicy(StrictModel):
    checks: list[CompletionCheck] = Field(min_length=1)
    max_repair_attempts: int = Field(default=2, ge=0)


class TraceContext(StrictModel):
    traceparent: str
    tracestate: str | None = None


class AgentTaskRequest(StrictModel):
    contract_version: str = "1.0.0"
    task_id: str
    attempt: int = Field(ge=1)
    agent_profile: AgentProfileRef
    model: str | None = Field(default=None, min_length=1)
    objective: str
    repository: str
    base_branch: str
    work_branch: str
    artifact_refs: list[ArtifactRef]
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    limits: Limits
    permissions: JobPermissions = Field(default_factory=JobPermissions)
    completion: CompletionPolicy | None = None
    session_mode: Literal["new", "resume"]
    trace_context: TraceContext


class Status(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_HUMAN = "needs_human"
    NEEDS_EXTERNAL_CHECK = "needs_external_check"
    ABORTED = "aborted"
    ERROR = "error"


class CriterionResult(StrictModel):
    id: str
    met: bool | None
    evidence: str


class AgentTaskResult(StrictModel):
    contract_version: str | None = "1.0.0"
    task_id: str | None
    attempt: int | None
    status: Status
    commit_hash: str | None = None
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    summary: str
    rationale: str
    open_questions: list[str] = Field(default_factory=list)
    usage: dict[str, int | float | None] = Field(default_factory=dict)


class AgentReport(StrictModel):
    status: Literal["succeeded", "failed", "needs_human", "needs_external_check"]
    criteria_results: list[CriterionResult]
    summary: str
    rationale: str
    open_questions: list[str]
