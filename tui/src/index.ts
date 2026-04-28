import { CoreClient, FixtureCoreClient } from "./client";
import { CONTRACT_EVENT_FIXTURES, FIXTURE_RUN_ID } from "./fixtures";
import { createState, reduceEvent, reduceStatusSnapshot } from "./state";
import { loadOptionalPiRuntime, renderPanels } from "./renderer";
import { createInterface } from "node:readline/promises";
import { runSlash } from "./commands";
import { runPiTui } from "./pi-app";
import { runOpenTui } from "./opentui-app";

export const OPENROUTER_MODEL_OPTIONS = [
  "openrouter/openai/gpt-4o-mini",
  "openrouter/anthropic/claude-sonnet-4",
  "openrouter/google/gemini-2.5-pro",
  "openrouter/meta-llama/llama-3.1-70b-instruct",
] as const;

export interface ProviderSetup { id:string; label:string; secretName:string; modelPrefix:string; models:string[]; }
export const PROVIDER_SETUPS: ProviderSetup[] = [
  { id:"openrouter", label:"OpenRouter", secretName:"OPENROUTER_API_KEY", modelPrefix:"openrouter", models:[...OPENROUTER_MODEL_OPTIONS] },
  { id:"openai", label:"OpenAI", secretName:"OPENAI_API_KEY", modelPrefix:"openai", models:["openai/gpt-5.5-fast", "openai/gpt-4o-mini"] },
  { id:"anthropic", label:"Anthropic", secretName:"ANTHROPIC_API_KEY", modelPrefix:"anthropic", models:["anthropic/claude-sonnet-4", "anthropic/claude-3-5-haiku-latest"] },
];

export async function readSecretNoEcho(prompt:string, input:NodeJS.ReadStream=process.stdin, output:NodeJS.WriteStream=process.stdout): Promise<string> {
  const rl = createInterface({ input, output, terminal:Boolean(input.isTTY) });
  const originalWrite = (rl as any)._writeToOutput;
  if (input.isTTY) (rl as any)._writeToOutput = function _writeToOutput() {};
  try {
    const value = await rl.question(prompt);
    if (input.isTTY) output.write("\n");
    return value;
  } finally {
    (rl as any)._writeToOutput = originalWrite;
    rl.close();
  }
}

export async function readLine(prompt:string, input:NodeJS.ReadStream=process.stdin, output:NodeJS.WriteStream=process.stdout): Promise<string> {
  const rl = createInterface({ input, output });
  try { return await rl.question(prompt); }
  finally { rl.close(); }
}

export function createPromptSession(input:NodeJS.ReadStream=process.stdin, output:NodeJS.WriteStream=process.stdout) {
  if (!input.isTTY) {
    const lines:string[] = [];
    const waiters:Array<(value:string)=>void> = [];
    let buffer = "";
    input.setEncoding("utf8");
    input.on("data", chunk => {
      buffer += String(chunk);
      const parts = buffer.split(/\r?\n/);
      buffer = parts.pop() ?? "";
      for (const line of parts) {
        const waiter = waiters.shift();
        if (waiter) waiter(line); else lines.push(line);
      }
    });
    input.resume();
    const nextLine = (prompt:string) => {
      output.write(prompt);
      if (lines.length) return Promise.resolve(lines.shift()!);
      return new Promise<string>(resolve => waiters.push(resolve));
    };
    return { readLine:nextLine, readSecret:nextLine, close() { input.pause(); } };
  }
  const rl = createInterface({ input, output, terminal:Boolean(input.isTTY) });
  const originalWrite = (rl as any)._writeToOutput;
  return {
    readLine(prompt:string) { return rl.question(prompt); },
    async readSecret(prompt:string) {
      if (input.isTTY) (rl as any)._writeToOutput = function _writeToOutput() {};
      try {
        const value = await rl.question(prompt);
        if (input.isTTY) output.write("\n");
        return value;
      } finally {
        (rl as any)._writeToOutput = originalWrite;
      }
    },
    close() { rl.close(); },
  };
}

export function normalizeOpenRouterModel(model:string): string {
  return normalizeProviderModel(PROVIDER_SETUPS[0], model);
}

export function normalizeProviderModel(provider:ProviderSetup, model:string): string {
  const trimmed = model.trim();
  if (!trimmed) throw new Error("model is required");
  return trimmed.startsWith(`${provider.modelPrefix}/`) ? trimmed : `${provider.modelPrefix}/${trimmed}`;
}

export function applyOpenRouterModel(config:any, model:string): any {
  return applyProviderModel(config, model);
}

export function applyProviderModel(config:any, model:string): any {
  const next = structuredClone(config);
  next.providers = { ...(next.providers ?? {}), default_model:model };
  next.stages = { ...(next.stages ?? {}) };
  for (const stage of ["interview", "design", "validate", "plan", "review"])
    next.stages[stage] = { ...(next.stages[stage] ?? {}), model };
  next.stages.develop = { ...(next.stages.develop ?? {}), model, orchestrator_model:model };
  return next;
}

export async function selectOpenRouterModel(readText=readLine, output:NodeJS.WriteStream=process.stdout): Promise<string> {
  return selectProviderModel(PROVIDER_SETUPS[0], readText, output);
}

export async function selectProviderModel(provider:ProviderSetup, readText=readLine, output:NodeJS.WriteStream=process.stdout): Promise<string> {
  output.write(`Choose a ${provider.label} model:\n`);
  provider.models.forEach((model, i) => output.write(`${i + 1}. ${model}\n`));
  output.write(`${provider.models.length + 1}. Custom ${provider.label} model\n`);
  const choice = (await readText("Model [1]: ")).trim();
  if (!choice) return provider.models[0];
  const n = Number(choice);
  if (Number.isInteger(n) && n >= 1 && n <= provider.models.length) return provider.models[n - 1];
  if (n === provider.models.length + 1) return normalizeProviderModel(provider, await readText(`Custom model, e.g. ${provider.models[0].replace(`${provider.modelPrefix}/`, "")}: `));
  return normalizeProviderModel(provider, choice);
}

export async function selectProvider(readText=readLine, output:NodeJS.WriteStream=process.stdout): Promise<ProviderSetup> {
  output.write("Choose a provider:\n");
  PROVIDER_SETUPS.forEach((provider, i) => output.write(`${i + 1}. ${provider.label}\n`));
  const choice = (await readText("Provider [1]: ")).trim();
  if (!choice) return PROVIDER_SETUPS[0];
  const n = Number(choice);
  const provider = Number.isInteger(n) ? PROVIDER_SETUPS[n - 1] : PROVIDER_SETUPS.find(p => p.id === choice.toLowerCase());
  if (!provider) throw new Error("invalid provider");
  return provider;
}

export async function setupOpenRouter(client:CoreClient, input:NodeJS.ReadStream=process.stdin, output:NodeJS.WriteStream=process.stdout, readSecret=readSecretNoEcho, readText=readLine): Promise<string> {
  return setupProvider(client, PROVIDER_SETUPS[0], input, output, readSecret, readText);
}

export async function setupProvider(client:CoreClient, provider:ProviderSetup, input:NodeJS.ReadStream=process.stdin, output:NodeJS.WriteStream=process.stdout, readSecret=readSecretNoEcho, readText=readLine): Promise<string> {
  output.write(`${provider.label} setup\n`);
  const key = await readSecret(`${provider.secretName}: `, input, output);
  if (!key.trim()) throw new Error(`${provider.secretName} is required`);
  const secret = await client.setSecret(provider.secretName, key);
  const model = await selectProviderModel(provider, readText, output);
  const config = await client.config();
  await client.updateConfig(applyProviderModel(config, model));
  output.write(`${provider.label} key configured via ${secret.source}\n`);
  output.write(`Default and stage models set to ${model}\n`);
  return model;
}

export interface CoreProcess { kill(signal?:unknown): unknown; }
export async function waitForCore(client:CoreClient, attempts=30, delayMs=250): Promise<void> {
  for (let i=0; i<attempts; i++) {
    try { await client.health(); return; }
    catch { if (i === attempts - 1) break; await new Promise(resolve => setTimeout(resolve, delayMs)); }
  }
  throw new Error("core did not become healthy");
}

export function startCoreProcess(output:NodeJS.WriteStream=process.stdout, spawnImpl:typeof Bun.spawn=Bun.spawn): CoreProcess {
  const root = new URL("../../", import.meta.url).pathname;
  output.write("Core is not running; starting local core for setup...\n");
  return spawnImpl(["python3", "-m", "nexussy.api.server"], { cwd:root, stdout:"ignore", stderr:"ignore", env:{ ...process.env, NEXUSSY_KEYRING_TIMEOUT_S:process.env.NEXUSSY_KEYRING_TIMEOUT_S ?? "0.5", PYTHONPATH:`${root}/core${process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : ""}` } });
}

export function useIsolatedSetupCore(client:CoreClient): void {
  if (process.env.NEXUSSY_CORE_URL) return;
  const port = 19000 + Math.floor(Math.random() * 20000);
  process.env.NEXUSSY_CORE_PORT = String(port);
  client.baseUrl = `http://127.0.0.1:${port}`;
}

export function shouldUseOpenTuiRenderer(env:{ NEXUSSY_TUI_RENDERER?: string }=process.env as any): boolean {
  return env.NEXUSSY_TUI_RENDERER === "opentui";
}

export async function ensureCoreForSetup(client:CoreClient, output:NodeJS.WriteStream=process.stdout, start=startCoreProcess): Promise<CoreProcess|undefined> {
  try { await client.health(); return undefined; }
  catch { const proc = start(output); await waitForCore(client); return proc; }
}

export async function setupWizard(client:CoreClient, input:NodeJS.ReadStream=process.stdin, output:NodeJS.WriteStream=process.stdout, readSecret=readSecretNoEcho, readText=readLine, start=startCoreProcess): Promise<string> {
  const proc = await ensureCoreForSetup(client, output, start);
  try {
    const provider = await selectProvider(readText, output);
    return await setupProvider(client, provider, input, output, readSecret, readText);
  } finally {
    proc?.kill();
  }
}

export function projectNameFromDescription(description:string): string {
  const words = description.trim().split(/\s+/).filter(Boolean).slice(0, 6).join(" ");
  return words || "nexussy run";
}

export async function startPipelineFromText(client:CoreClient, description:string): Promise<{runId:string; sessionId:string}> {
  const trimmed = description.trim();
  if (!trimmed) throw new Error("describe what you want nexussy to build");
  const started = await client.startPipeline({ project_name:projectNameFromDescription(trimmed), description:trimmed, auto_approve_interview:true });
  return { runId:started.run_id, sessionId:started.session_id };
}

export async function streamRunToPanels(client:CoreClient, state:ReturnType<typeof createState>, output:NodeJS.WriteStream=process.stdout): Promise<ReturnType<typeof createState>> {
  let current = state;
  if (!current.runId) throw new Error("run_id is required to stream");
  for await (const env of client.streamRun(current.runId)) {
    current = reduceEvent(current, env);
    const p = renderPanels(current);
    output.write(`${p.left}\n---\n${p.center}\n---\n${p.right}\n`);
    if (env.type === "done") break;
  }
  return current;
}

export async function interactiveShell(client:CoreClient, state=createState(), input:NodeJS.ReadStream=process.stdin, output:NodeJS.WriteStream=process.stdout): Promise<void> {
  const rl = createInterface({ input, output });
  let current = state;
  try {
    while (true) {
      const p = renderPanels(current);
      output.write(`${p.left}\n---\n${p.center}\n---\n${p.right}\n`);
      const line = (await rl.question("nexussy> ")).trim();
      if (!line) continue;
      if (line === "/quit" || line === "/exit") return;
      try {
        if (line.startsWith("/new ")) {
          const description = line.slice(5);
          const started = await startPipelineFromText(client, description);
          current = { ...current, runId:started.runId, sessionId:started.sessionId };
          output.write(`started run ${started.runId}\n`);
          current = await streamRunToPanels(client, current, output);
          continue;
        }
        if (!line.startsWith("/")) {
          output.write("ask mode: use /new <description> to start a pipeline or another slash command for actions\n");
          continue;
        }
        const result = await runSlash(line, client, current);
        output.write(`${result.message}\n`);
      } catch (e) {
        output.write(`error: ${e instanceof Error ? e.message : String(e)}\n`);
      }
    }
  } finally {
    rl.close();
  }
}

export async function main() {
  await loadOptionalPiRuntime();
  const mockMode = process.env.NEXUSSY_TUI_MODE === "mock-fixture" || process.argv.includes("--mock-fixture");
  const client = mockMode ? new FixtureCoreClient(CONTRACT_EVENT_FIXTURES) : new CoreClient({ baseUrl:process.env.NEXUSSY_CORE_URL ?? "http://127.0.0.1:7771", apiKey:process.env.NEXUSSY_API_KEY, mode:"live-core" });
  const setKeyIndex = process.argv.indexOf("--set-key");
  if (process.argv.includes("--setup") || process.argv.includes("--setup-openrouter")) {
    useIsolatedSetupCore(client);
    const proc = await ensureCoreForSetup(client);
    const prompts = createPromptSession();
    if (process.argv.includes("--setup-openrouter")) {
      try { await setupOpenRouter(client, process.stdin, process.stdout, prompts.readSecret, prompts.readLine); }
      finally { prompts.close(); proc?.kill(); }
      return;
    }
    try { const provider = await selectProvider(prompts.readLine, process.stdout); await setupProvider(client, provider, process.stdin, process.stdout, prompts.readSecret, prompts.readLine); }
    finally { prompts.close(); proc?.kill(); }
    return;
  }
  if (setKeyIndex >= 0) {
    const name = process.argv[setKeyIndex + 1];
    if (!name) throw new Error("--set-key requires a provider key name");
    useIsolatedSetupCore(client);
    const proc = await ensureCoreForSetup(client);
    try {
      const value = await readSecretNoEcho(`${name}: `);
      const summary = await client.setSecret(name, value);
      console.log(`${summary.name} configured via ${summary.source}`);
    } finally {
      proc?.kill();
    }
    return;
  }
  const state = createState();
  const runId = mockMode ? FIXTURE_RUN_ID : process.argv[2];
  if (!runId) {
    if (shouldUseOpenTuiRenderer()) await runOpenTui(client, state);
    else await runPiTui(client, state);
    return;
  }
  let current: typeof state = { ...state, runId };
  if (!mockMode) {
    try { current = reduceStatusSnapshot(current, await client.status(runId)); }
    catch (e) { console.error(`warning: failed to fetch run status before streaming: ${e instanceof Error ? e.message : String(e)}`); }
  }
  for await (const env of client.streamRun(runId)) { current = reduceEvent(current, env); console.clear(); const p=renderPanels(current); console.log(`${p.left}\n---\n${p.center}\n---\n${p.right}`); if(env.type==="done") break; }
}
if (import.meta.main) main().catch(e => { console.error(e); process.exit(1); });
