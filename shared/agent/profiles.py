from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from agent.contract import CompletionPolicy


class AgentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    harness: str
    sandbox: str = "workspace_write"
    system_prompt_append: str
    limits_mapping: dict[str, str]
    default_completion: CompletionPolicy


def load_profile(root: Path, name: str, version: str) -> AgentProfile:
    path = root / name / f"{version}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"unknown agent profile {name}@{version}")
    return AgentProfile.model_validate(yaml.safe_load(path.read_text()))
