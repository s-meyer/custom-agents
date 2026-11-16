.PHONY: image codex-image claude-image opencode-image demo-repo schemas run run-claude run-opencode serve smoke
image: codex-image

codex-image:
	docker compose -f ../codex/compose.yaml build

claude-image:
	docker compose -f ../claude/compose.yaml build

opencode-image:
	docker compose -f ../opencode/compose.yaml build

demo-repo:
	python3 scripts/make_demo_repo.py

schemas:
	mkdir -p contract
	python -c 'from agent.contract import AgentTaskRequest,AgentTaskResult; import json; from pathlib import Path; Path("contract/agent-task-request.schema.json").write_text(json.dumps(AgentTaskRequest.model_json_schema(),indent=2)+"\n"); Path("contract/agent-task-result.schema.json").write_text(json.dumps(AgentTaskResult.model_json_schema(),indent=2)+"\n")'

run:
	docker compose -f ../codex/compose.yaml run --rm -T agent run

run-claude:
	docker compose -f ../claude/compose.yaml run --rm -T claude-agent run

run-opencode:
	docker compose -f ../opencode/compose.yaml run --rm -T opencode-agent run

serve:
	docker compose -f ../codex/compose.yaml run --rm -p 8088:8088 -e AGENT_MODE=serve agent

smoke:
	docker compose -f ../codex/compose.yaml run --rm agent smoke
