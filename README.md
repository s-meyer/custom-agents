# Agent Containers

This repository provides three separate agent containers. They share an execution contract, Git workflow, logs, and demo project.

| Directory | SDK | Runtime | Authentication |
| --- | --- | --- | --- |
| [`codex/`](codex/) | OpenAI Codex SDK | Python | Codex login, OpenAI API, or Azure AI Foundry |
| [`claude/`](claude/) | Claude Agent SDK | Python | Anthropic API or Azure AI Foundry |
| [`opencode/`](opencode/) | OpenCode SDK | TypeScript/Bun | Anthropic API or Azure AI Foundry |
| [`shared/`](shared/) | Contract and local runtime data | Python runner for Codex and Claude | — |
| [`demo/`](demo/) | Intentionally broken ARM32 C project | C | — |

## Setup

```sh
cp shared/.env.example shared/.env
make -C shared demo-repo
```

This creates `shared/work/demo-repo.git`, which each agent checks out as its starting repository.

## Codex SDK

To authenticate with a ChatGPT/Codex account, configure Codex to save credentials in a file:

```sh
mkdir -p "$HOME/.codex"
printf '\ncli_auth_credentials_store = "file"\n' >> "$HOME/.codex/config.toml"
codex login
test -s "$HOME/.codex/auth.json" && echo "Codex auth.json found"

export CODEX_HOST_HOME="$HOME/.codex"
make -C shared codex-image
docker compose -f codex/compose.yaml run --rm -T agent run \
  < demo/examples/request.fix-warnings.json
```

The authentication cache is mounted read-only and copied into the container's private `CODEX_HOME` at startup. Alternatively, set `OPENAI_API_KEY` in `shared/.env`.

## Claude Agent SDK

```sh
# Add ANTHROPIC_API_KEY=... to shared/.env
make -C shared claude-image
docker compose -f claude/compose.yaml run --rm -T claude-agent run \
  < demo/examples/request.fix-warnings.claude.json
```

## OpenCode SDK

The OpenCode container is TypeScript-native: it uses the official `@opencode/sdk` directly and does not include the shared Python runner.

```sh
# Add these values to shared/.env:
# ANTHROPIC_API_KEY=...
make -C shared opencode-image
docker compose -f opencode/compose.yaml run --rm -T opencode-agent run \
  < demo/examples/request.fix-warnings.opencode.json
```

OpenCode activity is visible line by line: `Agent tool (tool=read target=…/src/util.c)` reports each tool call, `Agent tool failed (… reason=permission.rejected)` reports denials and errors, and `Agent step finished (step=4 tokens_out=851 cost=$0.0135)` is a per-turn heartbeat with token and cost totals. `Agent run summary (steps=5 tools=11)` closes the run, and the same lines are recorded in the transcript artifact.

## Azure AI Foundry

All SDK containers can access Azure AI Foundry through a service principal. Add the following values to `shared/.env`:

```dotenv
AI_PROVIDER=azure-foundry
AZURE_AI_FOUNDRY_ENDPOINT=https://<resource-name>.services.ai.azure.com
AZURE_TENANT_ID=<tenant-id>
AZURE_CLIENT_ID=<service-principal-client-id>
AZURE_CLIENT_SECRET=<service-principal-secret>
AZURE_AI_FOUNDRY_TOKEN_SCOPE=https://ai.azure.com/.default
```

Use the Foundry resource base endpoint without `/openai/v1`, `/anthropic`, or a project path. The shared harness obtains a Microsoft Entra token for each task and passes it to the SDK. The service principal needs a Foundry role that permits model inference.

Codex uses the OpenAI Responses endpoint and Claude uses the Anthropic endpoint. For OpenCode, select the API shape exposed by the deployment:

```dotenv
# Claude deployment
AZURE_AI_FOUNDRY_API=anthropic

# OpenAI-compatible deployment
# AZURE_AI_FOUNDRY_API=openai
```

```sh
chmod 600 shared/.env
```

## Model selection

The task contract selects the model used by an agent. `model` is required; profiles cannot provide a fallback. With Azure AI Foundry, it identifies the deployment to invoke:

```json
"agent_profile": { "name": "code-fixer", "version": "1.0.0" },
"model": "your-model-or-deployment-name"
```

The included test contracts use `gpt-6-luna` for Codex and `claude-sonnet-5-5` for Claude. OpenCode uses its provider-qualified form, `anthropic/claude-sonnet-5-5`. With Azure AI Foundry, set `model` to the deployment name; it remains required.

## Permissions and outputs

Tasks carry `permissions.sandbox`:

| Value | Effect |
| --- | --- |
| `read_only` | Read and analyze files |
| `workspace_write` | Modify the workspace; default |
| `full_access` | SDK-specific unrestricted access |

With `workspace_write`, OpenCode permits reading, editing, `git status`, `git diff`, `git log`, `make`, and `arm-linux-gnueabihf-gcc`. Shell statements outside that list (for example `ls`, `cat`, or piped segments) are denied, and compound commands are checked statement by statement. Containers write a human-readable activity log to `stderr` by default; the result, transcript, and patch are written to `shared/out/<task-id>/<attempt>/`. Set `LOG_FORMAT=json` to retain machine-readable JSON logs for log collectors.

## Task limits

`limits.max_duration_s` is enforced as a hard deadline: the runner aborts the agent run and returns an `error` result when it expires. `limits.max_steps` and `limits.max_cost_usd` are validated by the contract but are not enforced by the current runners; agents are expected to budget themselves within the deadline.

## Mandatory completion checks

The shared runner, rather than an SDK-specific hook, enforces completion checks for every agent. A profile provides the default policy and a task can override it through the provider-neutral `completion` field:

```json
"completion": {
  "checks": [
    { "id": "clean", "argv": ["make", "clean"] },
    { "id": "build", "argv": ["make"], "timeout_s": 300, "fail_on_warning": true }
  ],
  "max_repair_attempts": 2
}
```

Checks run in order after every agent response. When a check fails, the runner returns its diagnostics to the agent and gives it another repair attempt. The runner never returns `succeeded` until every check exits successfully and every check configured with `fail_on_warning: true` has no `warning:` or `error:` output. Each check receives an argument array (`argv`) rather than a shell command string. Completion checks require `workspace_write` or `full_access` because builds commonly write outputs.

The activity log makes final verification explicit with a `Running mandatory final verification` line followed by an individual result for each check and a final warning/error total. The final result's `usage` object includes `completion_checks`, `completion_repair_attempts`, `completion_warnings`, and `completion_errors`; each command's full output is available as a completion-log artifact.

Claude activity identifies safe, high-level work such as `Claude: Reading src/util.c`, `Claude: Editing src/util.c`, or `Claude: Running a build (make)`. Command summaries are limited in length and redact credential assignments; prompts and source contents are not logged. The end of the run says whether Claude returned a valid task report; only a validated report can start the mandatory completion checks.

## Demonstrate a failed compiler run

The demo project deliberately has warnings and a compiler error. A separate compiler image demonstrates the failure without agent SDKs or model credentials:

```sh
docker build -f demo/Dockerfile -t codex-demo-compiler:dev demo
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$PWD/demo:/workspace" \
  -w /workspace \
  codex-demo-compiler:dev make
```

The command intentionally exits with a failure status and reports, among other issues, the problem in `demo/src/util.c`.

## Product and architecture documentation

Goals, requirements, and architecture decisions are versioned in [`docs/`](docs/): [PRD](docs/PRD.md), [requirements](docs/requirements.md), and [ADRs](docs/adr/).
