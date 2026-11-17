.PHONY: out-dir repo-check image codex-image claude-image opencode-image demo-repo schemas run run-claude run-opencode serve smoke
image: codex-image

codex-image:
	docker compose -f ../codex/compose.yaml build

claude-image:
	docker compose -f ../claude/compose.yaml build

opencode-image:
	docker compose -f ../opencode/compose.yaml build

# Pre-create the bind-mount target as the host user; otherwise Docker creates it as root
# and the container's non-root user (uid 10001) cannot write results.
out-dir:
	mkdir -p out && { chmod a+rwx out 2>/dev/null || true; }

# The container (uid 10001) pushes the work branch back, so the bare repo must be writable for it.
demo-repo:
	python3 scripts/make_demo_repo.py
	chmod -R a+rwX work

# Fail fast instead of letting Docker create an empty root-owned mount directory.
repo-check:
	@test -f work/demo-repo.git/HEAD || { echo "work/demo-repo.git is missing or empty; run 'make -C shared demo-repo' first" >&2; exit 1; }

schemas:
	mkdir -p contract
	python -c 'from agent.contract import AgentTaskRequest,AgentTaskResult; import json; from pathlib import Path; Path("contract/agent-task-request.schema.json").write_text(json.dumps(AgentTaskRequest.model_json_schema(),indent=2)+"\n"); Path("contract/agent-task-result.schema.json").write_text(json.dumps(AgentTaskResult.model_json_schema(),indent=2)+"\n")'

run: out-dir repo-check
	docker compose -f ../codex/compose.yaml run --rm -T agent run

run-claude: out-dir repo-check
	docker compose -f ../claude/compose.yaml run --rm -T claude-agent run

run-opencode: out-dir repo-check
	docker compose -f ../opencode/compose.yaml run --rm -T opencode-agent run

serve: out-dir repo-check
	docker compose -f ../codex/compose.yaml run --rm -p 8088:8088 -e AGENT_MODE=serve agent

smoke:
	docker compose -f ../codex/compose.yaml run --rm agent smoke
