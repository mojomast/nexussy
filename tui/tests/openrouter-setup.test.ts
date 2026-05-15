import { expect, test } from "bun:test";
import { applyOpenRouterModel, ensureCoreForSetup, hasConfiguredProviderSecret, normalizeOpenRouterModel, parseNewCommand, projectNameFromDescription, promptProviderSetupIfNeeded, PROVIDER_SETUPS, selectOpenRouterModel, selectProvider, selectProviderModel, setupOpenRouter, setupWizard, shouldUseOpenTuiRenderer, startPipelineFromText, useIsolatedSetupCore } from "../src/index";

class Output { text=""; write(s:string){ this.text += s; return true; } }

test("normalizes OpenRouter model names", () => {
  expect(normalizeOpenRouterModel("openai/gpt-4o-mini")).toBe("openrouter/openai/gpt-4o-mini");
  expect(normalizeOpenRouterModel("openrouter/anthropic/claude-sonnet-4")).toBe("openrouter/anthropic/claude-sonnet-4");
});

test("applies selected OpenRouter model to all pipeline stages", () => {
  const cfg = { providers:{ default_model:"openai/gpt-5.5-fast" }, stages:{ interview:{}, design:{}, validate:{}, plan:{}, review:{}, develop:{} } };
  const next = applyOpenRouterModel(cfg, "openrouter/openai/gpt-4o-mini");
  expect(next.providers.default_model).toBe("openrouter/openai/gpt-4o-mini");
  expect(next.stages.design.model).toBe("openrouter/openai/gpt-4o-mini");
  expect(next.stages.develop.orchestrator_model).toBe("openrouter/openai/gpt-4o-mini");
  expect(cfg.providers.default_model).toBe("openai/gpt-5.5-fast");
});

test("model picker supports numbered and custom choices", async () => {
  const out = new Output() as any;
  expect(await selectOpenRouterModel(async () => "2", out)).toBe("openrouter/anthropic/claude-sonnet-4");
  const answers = ["5", "google/gemini-2.5-flash"];
  expect(await selectOpenRouterModel(async () => answers.shift()!, out)).toBe("openrouter/google/gemini-2.5-flash");
});

test("provider picker and model picker are provider-generic", async () => {
  const out = new Output() as any;
  expect((await selectProvider(async () => "openai", out)).secretName).toBe("OPENAI_API_KEY");
  expect(await selectProviderModel(PROVIDER_SETUPS[1], async () => "gpt-4o-mini", out)).toBe("openai/gpt-4o-mini");
});

test("guided setup stores key and updates model without outputting secret", async () => {
  const calls:any[] = [];
  const client = {
    setSecret(name:string, value:string){ calls.push(["setSecret", name, value]); return { name, source:"config", configured:true }; },
    config(){ return { providers:{}, stages:{ interview:{}, design:{}, validate:{}, plan:{}, review:{}, develop:{} } }; },
    updateConfig(cfg:any){ calls.push(["updateConfig", cfg]); return cfg; },
  } as any;
  const out = new Output() as any;
  const model = await setupOpenRouter(client, undefined as any, out, async () => "sk-test-secret", async () => "1");
  expect(model).toBe("openrouter/openai/gpt-4o-mini");
  expect(calls[0]).toEqual(["setSecret", "OPENROUTER_API_KEY", "sk-test-secret"]);
  expect(calls[1][1].stages.review.model).toBe("openrouter/openai/gpt-4o-mini");
  expect(out.text).not.toContain("sk-test-secret");
});

test("setup wizard starts local core only when needed", async () => {
  const out = new Output() as any;
  let healthChecks = 0;
  let killed = false;
  const client = {
    async health(){ healthChecks++; if (healthChecks === 1) throw new Error("down"); return { ok:true }; },
    setSecret(){ return { name:"OPENROUTER_API_KEY", source:"config", configured:true }; },
    config(){ return { providers:{}, stages:{ interview:{}, design:{}, validate:{}, plan:{}, review:{}, develop:{} } }; },
    updateConfig(cfg:any){ return cfg; },
  } as any;
  const proc = await ensureCoreForSetup(client, out, () => ({ kill(){ killed = true; } }));
  expect(proc).toBeTruthy();
  proc?.kill();
  expect(killed).toBe(true);
});

test("single-terminal setup wizard selects provider, stores key, and stops owned core", async () => {
  const out = new Output() as any;
  let killed = false;
  let healthChecks = 0;
  const calls:any[] = [];
  const client = {
    async health(){ healthChecks++; if (healthChecks === 1) throw new Error("down"); return { ok:true }; },
    setSecret(name:string, value:string){ calls.push(["setSecret", name, value]); return { name, source:"config", configured:true }; },
    config(){ return { providers:{}, stages:{ interview:{}, design:{}, validate:{}, plan:{}, review:{}, develop:{} } }; },
    updateConfig(cfg:any){ calls.push(["updateConfig", cfg]); return cfg; },
  } as any;
  const answers = ["1", "1"];
  const model = await setupWizard(client, undefined as any, out, async () => "sk-test-secret", async () => answers.shift()!, () => ({ kill(){ killed = true; } } as any));
  expect(model).toBe("openrouter/openai/gpt-4o-mini");
  expect(calls[0]).toEqual(["setSecret", "OPENROUTER_API_KEY", "sk-test-secret"]);
  expect(killed).toBe(true);
  expect(out.text).not.toContain("sk-test-secret");
});

test("setup uses isolated core URL unless explicitly configured", () => {
  const oldUrl = process.env.NEXUSSY_CORE_URL;
  const oldPort = process.env.NEXUSSY_CORE_PORT;
  delete process.env.NEXUSSY_CORE_URL;
  const client = { baseUrl:"http://127.0.0.1:7771" } as any;
  useIsolatedSetupCore(client);
  expect(client.baseUrl).not.toBe("http://127.0.0.1:7771");
  expect(process.env.NEXUSSY_CORE_PORT).toBeTruthy();
  if (oldUrl === undefined) delete process.env.NEXUSSY_CORE_URL; else process.env.NEXUSSY_CORE_URL = oldUrl;
  if (oldPort === undefined) delete process.env.NEXUSSY_CORE_PORT; else process.env.NEXUSSY_CORE_PORT = oldPort;
});

test("normal TUI launch can prompt for provider setup when no key is configured", async () => {
  const out = new Output() as any;
  const calls:any[] = [];
  const client = {
    secrets(){ calls.push(["secrets"]); return [{ name:"OPENROUTER_API_KEY", source:"config", configured:false }]; },
    setSecret(name:string, value:string){ calls.push(["setSecret", name, value]); return { name, source:"config", configured:true }; },
    config(){ return { providers:{}, stages:{ interview:{}, design:{}, validate:{}, plan:{}, review:{}, develop:{} } }; },
    updateConfig(cfg:any){ calls.push(["updateConfig", cfg]); return cfg; },
  } as any;
  const answers = ["", "", "1"];
  const ran = await promptProviderSetupIfNeeded(client, undefined as any, out, async () => "sk-test-secret", async () => answers.shift()!);
  expect(ran).toBe(true);
  expect(calls[0]).toEqual(["secrets"]);
  expect(calls[1]).toEqual(["setSecret", "OPENROUTER_API_KEY", "sk-test-secret"]);
  expect(calls[2][1].providers.default_model).toBe("openrouter/openai/gpt-4o-mini");
  expect(out.text).toContain("No provider API key");
  expect(out.text).not.toContain("sk-test-secret");
});

test("normal TUI launch skips provider prompt when a key exists or user declines", async () => {
  const out = new Output() as any;
  expect(hasConfiguredProviderSecret([{ name:"OPENAI_API_KEY", source:"config", configured:true }])).toBe(true);
  expect(hasConfiguredProviderSecret([{ name:"OPENAI_API_KEY", source:"config", configured:false }])).toBe(false);
  const configuredClient = { secrets(){ return [{ name:"OPENAI_API_KEY", source:"config", configured:true }]; } } as any;
  expect(await promptProviderSetupIfNeeded(configuredClient, undefined as any, out, async () => "unused", async () => { throw new Error("should not prompt"); })).toBe(false);
  const declinedClient = { secrets(){ return []; } } as any;
  expect(await promptProviderSetupIfNeeded(declinedClient, undefined as any, out, async () => "unused", async () => "n")).toBe(false);
  expect(out.text).toContain("Continuing without provider setup");
});

test("explicit new helper can start a pipeline run", async () => {
  const calls:any[] = [];
  const client = { startPipeline(body:any){ calls.push(body); return { run_id:"run-1", session_id:"sess-1", status:"running", stream_url:"/s", status_url:"/p" }; } } as any;
  expect(projectNameFromDescription("build a tiny api with tests please")).toBe("build a tiny api with tests");
  const started = await startPipelineFromText(client, "build a tiny api with tests please");
  expect(started).toEqual({ runId:"run-1", sessionId:"sess-1" });
  expect(calls[0]).toEqual({ project_name:"build a tiny api with tests", description:"build a tiny api with tests please", auto_approve_interview:true });
});

test("pipeline start design pack selection is sent only when selected", async () => {
  const calls:any[] = [];
  const client = { startPipeline(body:any){ calls.push(body); return { run_id:"run-1", session_id:"sess-1", status:"running", stream_url:"/s", status_url:"/p" }; } } as any;
  expect(parseNewCommand("--design-pack stripe build a polished checkout")).toEqual({ description:"build a polished checkout", designContextPack:"stripe" });
  await startPipelineFromText(client, "build a polished checkout", "stripe");
  await startPipelineFromText(client, "build a plain docs site", "none");
  expect(calls[0].metadata).toEqual({ design_context_pack:"stripe" });
  expect(calls[1].metadata).toBeUndefined();
  expect(() => parseNewCommand("--pack brutalist build app")).toThrow("design pack must be one of");
});

test("OpenTUI is default and Pi TUI requires explicit opt-in", () => {
  expect(shouldUseOpenTuiRenderer({})).toBe(true);
  expect(shouldUseOpenTuiRenderer({ NEXUSSY_TUI_RENDERER:"pi-tui" })).toBe(false);
  expect(shouldUseOpenTuiRenderer({ NEXUSSY_TUI_RENDERER:"opentui" })).toBe(true);
});
