import { OpenCode } from "@opencode/sdk"

type Input = {
  prompt: string
  cwd: string
  model: string
  sandbox: "read_only" | "workspace_write" | "full_access"
  azure_foundry?: {
    endpoint: string
    deployment: string
    access_token: string
    api: "openai" | "anthropic"
  }
}

function rulesFor(sandbox: Input["sandbox"]) {
  if (sandbox === "full_access") {
    return [{ action: "*", resource: "*", effect: "allow" }]
  }

  const rules = [
    { action: "*", resource: "*", effect: "deny" },
    { action: "external_directory", resource: "*", effect: "deny" },
    { action: "read", resource: "*", effect: "allow" },
    { action: "glob", resource: "*", effect: "allow" },
    { action: "grep", resource: "*", effect: "allow" },
  ]
  if (sandbox === "workspace_write") {
    rules.push(
      { action: "edit", resource: "*", effect: "allow" },
      { action: "shell", resource: "git status *", effect: "allow" },
      { action: "shell", resource: "git diff *", effect: "allow" },
      { action: "shell", resource: "git log *", effect: "allow" },
      { action: "shell", resource: "make *", effect: "allow" },
      { action: "shell", resource: "arm-linux-gnueabihf-gcc *", effect: "allow" },
    )
  }
  return rules
}

function textParts(value: any): string {
  if (!value) return ""
  const parts = Array.isArray(value) ? value : value.parts
  if (!Array.isArray(parts)) return ""
  return parts
    .filter((part: any) => part?.type === "text" && typeof part.text === "string")
    .map((part: any) => part.text)
    .join("\n")
}

async function main() {
  const input = JSON.parse(await Bun.stdin.text()) as Input
  const model = input.azure_foundry
    ? `azure_foundry/${input.azure_foundry.deployment}`
    : input.model

  process.env.OPENCODE_DISABLE_PROJECT_CONFIG = "1"
  process.env.OPENCODE_CONFIG_CONTENT = JSON.stringify({
    model,
    default_agent: "general",
    providers: input.azure_foundry
      ? {
          azure_foundry: {
            name: "Azure AI Foundry",
            package: input.azure_foundry.api === "anthropic"
              ? "@opencode/ai/providers/anthropic-compatible"
              : "@opencode/ai/providers/openai-compatible",
            settings: {
              baseURL: input.azure_foundry.api === "anthropic"
                ? `${input.azure_foundry.endpoint}/anthropic`
                : `${input.azure_foundry.endpoint}/openai/v1`,
            },
            headers: { Authorization: `Bearer ${input.azure_foundry.access_token}` },
            models: { [input.azure_foundry.deployment]: { name: input.azure_foundry.deployment } },
          },
        }
      : {
          anthropic: { settings: { apiKey: process.env.ANTHROPIC_API_KEY } },
        },
    permissions: rulesFor(input.sandbox),
  })

  const opencode = await OpenCode.create()
  try {
    const session = await opencode.sessions.create({
      location: { directory: input.cwd },
      title: "Contract agent task",
    })
    console.error(JSON.stringify({ event: "session.created", session_id: session.id, model }))
    await opencode.sessions.prompt({ sessionID: session.id, text: input.prompt })

    const response = await opencode.message.list({ sessionID: session.id })
    const messages: any[] = response.data ?? []
    const assistant = [...messages].reverse().find((message: any) => message?.info?.role === "assistant")
    const final = textParts(assistant) || textParts(assistant?.parts)
    if (!final) throw new Error("OpenCode session did not return an assistant text response")
    console.log(JSON.stringify({ final_response: final }))
  } finally {
    await opencode.close()
  }
}

main().catch((error) => {
  console.error(JSON.stringify({ event: "error", message: error instanceof Error ? error.message : String(error) }))
  process.exitCode = 1
})
