import { ClientSecretCredential } from "@azure/identity"
import { OpenCode } from "@opencode/sdk"
import { parse as parseYaml } from "yaml"

type Status = "succeeded" | "failed" | "needs_human" | "needs_external_check" | "aborted" | "error"
type ArtifactRef = { name: string; uri: string; media_type?: string }
type CriterionResult = { id: string; met: boolean | null; evidence: string }
type CompletionCheck = { id: string; argv: string[]; timeout_s?: number; fail_on_warning?: boolean }
type CompletionPolicy = { checks: CompletionCheck[]; max_repair_attempts?: number }
type Request = {
  contract_version?: string
  task_id: string
  attempt: number
  agent_profile: { name: string; version: string }
  model: string
  objective: string
  repository: string
  base_branch: string
  work_branch: string
  artifact_refs: ArtifactRef[]
  acceptance_criteria: { id: string; description: string }[]
  limits: { max_duration_s: number; max_cost_usd?: number; max_steps?: number }
  permissions?: { sandbox?: "read_only" | "workspace_write" | "full_access" }
  completion?: CompletionPolicy
  session_mode: "new" | "resume"
}
type Profile = {
  harness: string
  system_prompt_append: string
  default_completion: CompletionPolicy
}
type AgentReport = {
  status: Exclude<Status, "aborted" | "error">
  criteria_results: CriterionResult[]
  summary: string
  rationale: string
  open_questions: string[]
}
type CheckResult = {
  check: CompletionCheck
  command: string
  output: string
  returncode: number | null
  timed_out: boolean
  warnings: number
  errors: number
  passed: boolean
}

const workspaceRoot = process.env.WORKSPACE_DIR || "/workspace"
const outputRoot = process.env.OUTPUT_DIR || "/output"
const profileRoot = process.env.AGENT_PROFILES_DIR || "/app/profiles"
const logFormat = (process.env.LOG_FORMAT || "human").toLowerCase()

function log(event: string, fields: Record<string, unknown> = {}) {
  if (logFormat === "json") {
    console.error(JSON.stringify({ timestamp: new Date().toISOString(), level: "INFO", event, ...fields }))
    return
  }
  const details = Object.entries(fields).map(([key, value]) => `${key}=${String(value)}`).join(" ")
  console.error(`[${new Date().toLocaleTimeString("en-GB", { hour12: false })}] ${event}${details ? ` (${details})` : ""}`)
}

function shellQuote(value: string) {
  return /^[A-Za-z0-9_./:=+-]+$/.test(value) ? value : `'${value.replaceAll("'", "'\\''")}'`
}

function commandText(argv: string[]) {
  return argv.map(shellQuote).join(" ")
}

async function runCommand(argv: string[], cwd: string, timeoutMs?: number) {
  const child = Bun.spawn({ cmd: argv, cwd, stdout: "pipe", stderr: "pipe" })
  let timer: ReturnType<typeof setTimeout> | undefined
  let timedOut = false
  const exitCode = await Promise.race([
    child.exited,
    new Promise<number>((resolve) => {
      if (timeoutMs) {
        timer = setTimeout(() => {
          timedOut = true
          child.kill()
          resolve(-1)
        }, timeoutMs)
      }
    }),
  ])
  if (timer) clearTimeout(timer)
  const [stdout, stderr] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text()])
  return { exitCode, output: `${stdout}${stderr}`, timedOut }
}

function assertRequest(value: unknown): asserts value is Request {
  const request = value as Partial<Request>
  if (!request || typeof request !== "object" || !request.task_id || !request.model || !request.agent_profile || !request.limits) {
    throw new Error("Invalid task contract: task_id, agent_profile, model, and limits are required")
  }
}

async function readProfile(request: Request): Promise<Profile> {
  const path = `${profileRoot}/${request.agent_profile.name}/${request.agent_profile.version}.yaml`
  if (!(await Bun.file(path).exists())) throw new Error(`unknown agent profile ${request.agent_profile.name}@${request.agent_profile.version}`)
  const profile = parseYaml(await Bun.file(path).text()) as Profile
  if (!profile || profile.harness !== "opencode-sdk" || !profile.default_completion) throw new Error(`Invalid OpenCode profile ${request.agent_profile.name}@${request.agent_profile.version}`)
  return profile
}

async function checkout(request: Request, directory: string) {
  const parent = directory.slice(0, directory.lastIndexOf("/"))
  await runCommand(["mkdir", "-p", parent], "/")
  let result = await runCommand(["git", "clone", request.repository, directory], parent)
  if (result.exitCode !== 0) throw new Error(result.output || "git clone failed")
  result = await runCommand(["git", "checkout", "-b", request.work_branch, `origin/${request.base_branch}`], directory)
  if (result.exitCode !== 0) throw new Error(result.output || "git checkout failed")
}

function reportSchema() {
  return `{"status":"succeeded|failed|needs_human|needs_external_check","criteria_results":[{"id":"...","met":true,"evidence":"..."}],"summary":"...","rationale":"...","open_questions":[]}`
}

function buildPrompt(request: Request, profile: Profile, completion: CompletionPolicy, workspace: string) {
  const criteria = request.acceptance_criteria.map((criterion) => `- ${criterion.id}: ${criterion.description}`).join("\n")
  const checks = completion.checks.map((check) => `- ${check.id}: ${commandText(check.argv)}; timeout=${check.timeout_s || 300}s; fail_on_warning=${check.fail_on_warning !== false}`).join("\n")
  return `${profile.system_prompt_append}\n\nObjective: ${request.objective}\nRequested model: ${request.model}\nRepository: ${workspace}\nAcceptance criteria:\n${criteria}\nMandatory completion checks:\n${checks}\n\nRun every completion check before your final response. The runner independently repeats them and will request a repair if they fail. Return exactly one JSON object without markdown fences matching: ${reportSchema()}`
}

async function foundryConfig() {
  if ((process.env.AI_PROVIDER || "").toLowerCase() !== "azure-foundry") return undefined
  const endpoint = process.env.AZURE_AI_FOUNDRY_ENDPOINT?.replace(/\/$/, "")
  const tenantId = process.env.AZURE_TENANT_ID
  const clientId = process.env.AZURE_CLIENT_ID
  const clientSecret = process.env.AZURE_CLIENT_SECRET
  if (!endpoint || !tenantId || !clientId || !clientSecret) throw new Error("Azure Foundry requires endpoint and service-principal credentials")
  const credential = new ClientSecretCredential(tenantId, clientId, clientSecret)
  const token = await credential.getToken(process.env.AZURE_AI_FOUNDRY_TOKEN_SCOPE || "https://ai.azure.com/.default")
  if (!token?.token) throw new Error("Could not get Azure Foundry access token")
  const api = (process.env.AZURE_AI_FOUNDRY_API || "openai").toLowerCase()
  if (api !== "openai" && api !== "anthropic") throw new Error("AZURE_AI_FOUNDRY_API must be 'openai' or 'anthropic'")
  return { endpoint, token: token.token, api: api as "openai" | "anthropic" }
}

function clip(value: string, max = 100) {
  const single = value.replace(/\s+/g, " ").trim()
  return single.length > max ? `${single.slice(0, max - 1)}…` : single
}

function describeToolInput(input: any): { tool: string; target: string } {
  if (!input || typeof input !== "object") return { tool: "tool", target: "" }
  if (typeof input.command === "string") return { tool: "shell", target: clip(input.command) }
  if (typeof input.oldString === "string") return { tool: "edit", target: typeof input.path === "string" ? input.path : "" }
  if (typeof input.content === "string") return { tool: "write", target: typeof input.path === "string" ? input.path : "" }
  if (typeof input.pattern === "string") return { tool: typeof input.path === "string" ? "grep" : "glob", target: clip(input.pattern) }
  if (typeof input.path === "string") return { tool: "read", target: input.path }
  if (typeof input.url === "string") return { tool: "webfetch", target: clip(input.url) }
  return { tool: "tool", target: "" }
}

function textParts(value: any): string {
  const content = Array.isArray(value) ? value : value?.content ?? value?.parts
  return Array.isArray(content) ? content.filter((part: any) => part?.type === "text" && typeof part.text === "string").map((part: any) => part.text).join("\n") : ""
}

function extractJsonObject(value: string): string {
  const start = value.indexOf("{")
  if (start < 0) return value
  let depth = 0
  let inString = false
  let escape = false
  for (let i = start; i < value.length; i++) {
    const ch = value[i]
    if (inString) {
      if (escape) escape = false
      else if (ch === "\\") escape = true
      else if (ch === '"') inString = false
      continue
    }
    if (ch === '"') inString = true
    else if (ch === "{") depth += 1
    else if (ch === "}") {
      depth -= 1
      if (depth === 0) return value.slice(start, i + 1)
    }
  }
  return value.slice(start)
}

function parseReport(value: string): AgentReport {
  const parsed = JSON.parse(extractJsonObject(value))
  if (!parsed || !["succeeded", "failed", "needs_human", "needs_external_check"].includes(parsed.status) || !Array.isArray(parsed.criteria_results)) {
    throw new Error("OpenCode final response was not a valid AgentReport JSON")
  }
  return parsed as AgentReport
}

function rulesFor(sandbox: "read_only" | "workspace_write" | "full_access") {
  if (sandbox === "full_access") return [{ action: "*", resource: "*", effect: "allow" }]
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

async function runAgent(request: Request, profile: Profile, completion: CompletionPolicy, workspace: string, deadline: number, activity: string[]): Promise<AgentReport> {
  const foundry = await foundryConfig()
  const opencode = await OpenCode.create({
    config: {
      project: false,
      content: JSON.stringify({
        model: foundry ? `azure_foundry/${request.model}` : request.model,
        default_agent: "general",
        providers: foundry ? { azure_foundry: { name: "Azure AI Foundry", package: foundry.api === "anthropic" ? "@opencode/ai/providers/anthropic-compatible" : "@opencode/ai/providers/openai-compatible", settings: { baseURL: foundry.api === "anthropic" ? `${foundry.endpoint}/anthropic` : `${foundry.endpoint}/openai/v1` }, headers: { Authorization: `Bearer ${foundry.token}` }, models: { [request.model]: { name: request.model } } } } : { anthropic: { settings: { apiKey: process.env.ANTHROPIC_API_KEY } } },
        permissions: rulesFor(request.permissions?.sandbox || "workspace_write"),
      }),
    },
  })
  try {
    const session = await opencode.sessions.create({ location: { directory: workspace }, title: "Contract agent task" })
    log("OpenCode session created", { model: request.model })
    const remaining = deadline - performance.now()
    if (remaining <= 0) throw new Error("Task reached max_duration_s")
    const watchdog = new AbortController()
    const watchdogTimer = setTimeout(() => watchdog.abort(), remaining)
    log("OpenCode agent is working")
    const events = await opencode.event.subscribe({
      types: ["session.execution.succeeded", "session.execution.failed", "session.execution.interrupted", "session.idle", "session.retry.scheduled", "session.tool.called", "session.tool.failed", "session.step.ended"],
    }, { signal: watchdog.signal })
    const record = (event: string, fields: Record<string, unknown> = {}) => {
      log(event, fields)
      const details = Object.entries(fields).filter(([, value]) => value !== undefined && value !== "").map(([key, value]) => `${key}=${String(value)}`).join(" ")
      activity.push(`${event}${details ? ` ${details}` : ""}`)
      if (activity.length > 2000) activity.splice(0, activity.length - 2000)
    }
    try {
      await opencode.sessions.prompt({ sessionID: session.id, text: buildPrompt(request, profile, completion, workspace) })
      let failure: { message?: string } | undefined
      let steps = 0
      let toolCalls = 0
      const toolById = new Map<string, { tool: string; target: string }>()
      for await (const event of events) {
        if (performance.now() >= deadline) throw new Error("Task reached max_duration_s")
        const data: any = (event as any).data
        if (!data || data.sessionID !== session.id) continue
        const type = (event as any).type
        if (type === "session.retry.scheduled") {
          log("OpenCode provider retry scheduled", { attempt: data.attempt, message: data.message })
          continue
        }
        if (type === "session.tool.called") {
          toolCalls += 1
          const { tool, target } = describeToolInput(data.input)
          toolById.set(data.id, { tool, target })
          record("Agent tool", { tool, target })
          continue
        }
        if (type === "session.tool.failed") {
          const { tool, target } = toolById.get(data.id) ?? describeToolInput(data.input)
          record("Agent tool failed", { tool, target, error: data.error?.message, reason: data.error?.type })
          continue
        }
        if (type === "session.step.ended") {
          steps += 1
          record("Agent step finished", {
            step: steps,
            finish: data.finish,
            tokens_in: data.tokens?.input,
            tokens_out: data.tokens?.output,
            cost: typeof data.cost === "number" ? `$${data.cost.toFixed(4)}` : undefined,
          })
          continue
        }
        if (type === "session.execution.failed") {
          failure = data.error
          break
        }
        if (type === "session.execution.interrupted") throw new Error("OpenCode session was interrupted")
        break
      }
      log("Agent run summary", { steps, tools: toolCalls })
      const pollUntil = Math.min(deadline, performance.now() + 60_000)
      let final = ""
      let infoError: any
      while (true) {
        const response = await opencode.message.list({ sessionID: session.id })
        const messages: any[] = response.data ?? []
        const assistants = [...messages].reverse().filter((message) => message?.type === "assistant" || message?.info?.role === "assistant")
        const errored = assistants.find((message) => message?.error ?? message?.info?.error)
        infoError = errored?.error ?? errored?.info?.error
        const textBearing = assistants.find((message) => textParts(message) !== "")
        final = textBearing ? textParts(textBearing) : ""
        if (final || infoError) break
        if (performance.now() >= pollUntil) break
        await new Promise((resolve) => setTimeout(resolve, 1000))
      }
      if (failure) throw new Error(`OpenCode session failed: ${failure.message || JSON.stringify(failure)}`)
      if (infoError) throw new Error(`OpenCode session error: ${infoError.message || JSON.stringify(infoError)}`)
      if (!final) throw new Error("OpenCode session did not return an assistant text response")
      log("OpenCode agent completed its response")
      return parseReport(final)
    } catch (error) {
      if (watchdog.signal.aborted) throw new Error("Task reached max_duration_s")
      throw error
    } finally {
      clearTimeout(watchdogTimer)
    }
  } finally {
    await opencode.close()
  }
}

async function runCheck(check: CompletionCheck, workspace: string): Promise<CheckResult> {
  const command = commandText(check.argv)
  log("Verification started", { id: check.id, command })
  const result = await runCommand(check.argv, workspace, (check.timeout_s || 300) * 1000)
  const warnings = (result.output.match(/\bwarning\s*:/gi) || []).length
  const errors = (result.output.match(/\berror\s*:/gi) || []).length
  const passed = !result.timedOut && result.exitCode === 0 && errors === 0 && (check.fail_on_warning === false || warnings === 0)
  log(`Verification ${passed ? "passed" : "failed"}`, { id: check.id, warnings, errors })
  return { check, command, output: result.output, returncode: result.exitCode, timed_out: result.timedOut, warnings, errors, passed }
}

async function publish(workspace: string, request: Request) {
  const changed = await runCommand(["git", "status", "--porcelain"], workspace)
  let commit: string | null = null
  if (changed.output.trim()) {
    for (const argv of [["git", "add", "-A"], ["git", "commit", "-m", "Agent task changes"]]) {
      const result = await runCommand(argv, workspace)
      if (result.exitCode !== 0) throw new Error(result.output || `${argv[0]} failed`)
    }
    let push = await runCommand(["git", "push", "origin", request.work_branch], workspace)
    if (push.exitCode !== 0) {
      log("Push rejected, force-pushing agent branch", { branch: request.work_branch })
      push = await runCommand(["git", "push", "--force", "origin", request.work_branch], workspace)
    }
    if (push.exitCode !== 0) throw new Error(push.output || "git push failed")
    commit = (await runCommand(["git", "rev-parse", "HEAD"], workspace)).output.trim()
  }
  const patch = await runCommand(["git", "diff", `origin/${request.base_branch}...HEAD`], workspace)
  return { commit, patch: patch.output }
}

async function main() {
  const started = performance.now()
  let request: Request | undefined
  let result: any
  let workspace = ""
  let output = ""
  const transcript: Record<string, unknown> = {}
  const activity: string[] = []
  try {
    const args = Bun.argv.slice(2)
    if (args[0] === "run") args.shift()
    const source = args[0]
    const raw = source ? await Bun.file(source).text() : await new Response(Bun.stdin.stream()).text()
    request = JSON.parse(raw)
    assertRequest(request)
    output = `${outputRoot}/${request.task_id}/${request.attempt}`
    workspace = `${workspaceRoot}/${request.task_id}/${request.attempt}`
    await runCommand(["mkdir", "-p", output], "/")
    result = { contract_version: request.contract_version || "1.0.0", task_id: request.task_id, attempt: request.attempt, status: "error", commit_hash: null, artifact_refs: [], criteria_results: [], summary: "Task did not complete.", rationale: "Runner did not receive a valid final report.", open_questions: [], usage: {} }
    log("Starting task", { task: request.task_id, attempt: request.attempt })
    if (request.session_mode !== "new") throw new Error("session_mode must be 'new'")
    const profile = await readProfile(request)
    const completion = request.completion || profile.default_completion
    if (request.permissions?.sandbox === "read_only") throw new Error("Completion checks require workspace_write or full_access permissions")
    log("Using OpenCode", { model: request.model, checks: completion.checks.length })
    log("Checking out the repository")
    await checkout(request, workspace)
    log("Repository checkout complete")
    const deadline = started + request.limits.max_duration_s * 1000
    let runRequest = request
    let repairs = 0
    let report: AgentReport | undefined
    let checks: CheckResult[] = []
    const artifacts: ArtifactRef[] = []
    while (true) {
      if (performance.now() >= deadline) throw new Error("Task reached max_duration_s")
      report = await runAgent(runRequest, profile, completion, workspace, deadline, activity)
      transcript.reports = [...((transcript.reports as unknown[]) || []), report]
      log("Running mandatory final verification", { pass: repairs + 1, checks: completion.checks.length })
      checks = []
      for (const check of completion.checks) {
        const checkResult = await runCheck(check, workspace)
        checks.push(checkResult)
        const artifactPath = `${output}/completion-${repairs + 1}-${check.id}.log`
        await Bun.write(artifactPath, `$ ${checkResult.command}\nexit_code=${checkResult.returncode} timed_out=${checkResult.timed_out} warnings=${checkResult.warnings} errors=${checkResult.errors}\n\n${checkResult.output}`)
        artifacts.push({ name: `completion-${repairs + 1}-${check.id}`, uri: `file://${artifactPath}`, media_type: "text/plain" })
      }
      const warnings = checks.reduce((total, check) => total + check.warnings, 0)
      const errors = checks.reduce((total, check) => total + check.errors, 0)
      const passed = checks.every((check) => check.passed)
      log(`Final verification ${passed ? "passed" : "failed"}`, { warnings, errors })
      if (passed || repairs >= (completion.max_repair_attempts ?? 2)) break
      repairs += 1
      runRequest = { ...request, objective: `${request.objective}\n\nFinal verification failed. Fix the workspace, then respond with JSON only.\n\n${checks.filter((check) => !check.passed).map((check) => `${check.check.id}: ${check.command}; warnings=${check.warnings}; errors=${check.errors};\n${check.output.slice(-4000)}`).join("\n\n")}` }
      log("Requesting a repair", { attempt: repairs })
    }
    const warnings = checks.reduce((total, check) => total + check.warnings, 0)
    const errors = checks.reduce((total, check) => total + check.errors, 0)
    result.status = checks.every((check) => check.passed) ? report!.status : "failed"
    result.criteria_results = [...report!.criteria_results, ...checks.map((check) => ({ id: `completion-${check.check.id}`, met: check.passed, evidence: `${check.command}: exit_code=${check.returncode}, timed_out=${check.timed_out}, warnings=${check.warnings}, errors=${check.errors}.` }))]
    result.summary = checks.every((check) => check.passed) ? `${report!.summary} Final completion checks passed (warnings=${warnings}, errors=${errors}).` : `Mandatory completion checks failed (warnings=${warnings}, errors=${errors}).`
    result.rationale = report!.rationale
    result.open_questions = report!.open_questions
    result.artifact_refs.push(...artifacts)
    result.usage = { completion_checks: checks.length, completion_repair_attempts: repairs, completion_warnings: warnings, completion_errors: errors }
    if (result.status !== "error") {
      log("Publishing changes", { branch: request.work_branch })
      const published = await publish(workspace, request)
      result.commit_hash = published.commit
      const patchPath = `${output}/changes.patch`
      await Bun.write(patchPath, published.patch)
      result.artifact_refs.push({ name: "patch", uri: `file://${patchPath}`, media_type: "text/x-diff" })
      log("Changes published", { commit: published.commit || "none" })
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (!result) result = { contract_version: "1.0.0", task_id: request?.task_id || null, attempt: request?.attempt || null, status: "error", commit_hash: null, artifact_refs: [], criteria_results: [], summary: "Technical error while running the task.", rationale: message, open_questions: [], usage: {} }
    result.status = "error"
    result.summary = "Technical error while running the task."
    result.rationale = message
    transcript.error = message
    log("Task failed", { reason: message })
  } finally {
    if (!output) output = `${outputRoot}/invalid-request/1`
    if (activity.length) transcript.activity = activity
    await runCommand(["mkdir", "-p", output], "/")
    result.usage.duration_s = Number(((performance.now() - started) / 1000).toFixed(2))
    const transcriptPath = `${output}/transcript.jsonl`
    const resultPath = `${output}/result.json`
    await Bun.write(transcriptPath, `${JSON.stringify(transcript)}\n`)
    result.artifact_refs.push({ name: "transcript", uri: `file://${transcriptPath}`, media_type: "application/jsonl" })
    result.artifact_refs.push({ name: "result", uri: `file://${resultPath}`, media_type: "application/json" })
    await Bun.write(resultPath, `${JSON.stringify(result, null, 2)}\n`)
    log("Task finished", { status: result.status, duration_s: result.usage.duration_s })
    console.log(JSON.stringify(result))
  }
}

await main()
