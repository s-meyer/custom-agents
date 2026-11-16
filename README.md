# Agent Containers

This repository provides three separate agent containers. They share an execution contract, Git workflow, logs, and demo project.

| Directory | SDK | Authentication |
| --- | --- | --- |
| [`codex/`](codex/) | OpenAI Codex SDK | Codex login, OpenAI API, or Azure AI Foundry |
| [`claude/`](claude/) | Claude Agent SDK | Anthropic API or Azure AI Foundry |
| [`opencode/`](opencode/) | OpenCode SDK | Anthropic API or Azure AI Foundry |
| [`shared/`](shared/) | Shared runner, contract, and local runtime data | — |
| [`demo/`](demo/) | Intentionally broken ARM32 C project | — |

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

```sh
# Add these values to shared/.env:
# ANTHROPIC_API_KEY=...
# OPENCODE_MODEL=anthropic/claude-sonnet-5-5
make -C shared opencode-image
docker compose -f opencode/compose.yaml run --rm -T opencode-agent run \
  < demo/examples/request.fix-warnings.opencode.json
```

## Azure AI Foundry

All SDK containers can access Azure AI Foundry through a service principal. Add the following values to `shared/.env`:

```dotenv
AI_PROVIDER=azure-foundry
AZURE_AI_FOUNDRY_ENDPOINT=https://<resource-name>.services.ai.azure.com
AZURE_AI_FOUNDRY_DEPLOYMENT=<deployment-name>
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

## Permissions and outputs

Tasks carry `permissions.sandbox`:

| Value | Effect |
| --- | --- |
| `read_only` | Read and analyze files |
| `workspace_write` | Modify the workspace; default |
| `full_access` | SDK-specific unrestricted access |

With `workspace_write`, OpenCode permits reading, editing, `make`, and `arm-linux-gnueabihf-gcc`. Containers write JSON logs to `stderr`; the result, transcript, and patch are written to `shared/out/<task-id>/<attempt>/`.

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
