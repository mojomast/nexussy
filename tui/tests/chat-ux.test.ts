import { expect, test } from "bun:test";
import { createDefaultChatState, renderApp, renderChat } from "../src/ui/App";
import { classifyInteraction, handleComposerSubmit, looksLikeProjectRequest, pendingInterviewFromArtifact, wantsInterviewFirst } from "../src/ui/Composer";
import { insertFileReference, fileReferenceQuery, fileReferenceSuggestions, rejectPathEscape } from "../src/ui/FileReferenceAutocomplete";
import { actionableError, reduceChatEvent, transcriptItemFromEvent } from "../src/ui/Transcript";
import { closeOverlay } from "../src/ui/Overlay";
import { STAGES, reduceSecrets, reduceStageRoutingModel, reduceStatusSnapshot } from "../src/state";
import { findModelOption } from "../src/lib/routing";
import { renderPipelineRows } from "../src/ui/PipelineStrip";
import type { EventEnvelope } from "../src/types";
import type { ChatUiState } from "../src/ui/types";

const usage = { input_tokens:0, output_tokens:0, total_tokens:0, cost_usd:0 };
function env(type:any, payload:any, n=1): EventEnvelope { return { event_id:`e${n}`, sequence:n, contract_version:"1.0", type, session_id:"s", run_id:"r", ts:"2026-04-27T00:00:00Z", source:"core", payload } as EventEnvelope; }

class MockClient {
  calls:any[] = [];
  startPipeline(body:any){ this.calls.push(["startPipeline", body]); return { run_id:"run-123456", session_id:"sess-1" }; }
  chat(body:any){ this.calls.push(["chat", body]); return { message:`provider says: ${body.message}`, model:"openrouter/test-model" }; }
  inject(body:any){ this.calls.push(["inject", body]); return {}; }
  injectWorker(id:string, body:any){ this.calls.push(["injectWorker", id, body]); return {}; }
  pause(run_id:string, reason?:string){ this.calls.push(["pause", run_id, reason]); return {}; }
  resume(run_id:string){ this.calls.push(["resume", run_id]); return {}; }
  cancel(run_id:string, reason:string){ this.calls.push(["cancel", run_id, reason]); return {}; }
  interviewAnswer(session_id:string, answers:Record<string,string>){ this.calls.push(["interviewAnswer", session_id, answers]); return {}; }
  skip(run_id:string, stage:string, reason:string){ this.calls.push(["skip", run_id, stage, reason]); return {}; }
  spawn(body:any){ this.calls.push(["spawn", body]); return {}; }
  secrets(){ this.calls.push(["secrets"]); return [{ name:"OPENROUTER_API_KEY", source:"config", configured:true }]; }
  status(run_id:string){ this.calls.push(["status", run_id]); return { ok:true, run:{ run_id, session_id:"sess-1", status:"running", usage }, stages:STAGES.map(stage => ({ stage, status:stage === "design" ? "running" : "pending", attempt:1, max_attempts:1, input_artifacts:[], output_artifacts:[] })), workers:[], paused:false, blockers:[] }; }
  workers(run_id:string){ this.calls.push(["workers", run_id]); return [{ worker_id:"backend-abc123", run_id, role:"backend", status:"running", stage:"develop", worktree_path:"", branch_name:"", model:"mock", usage, created_at:"", updated_at:"" }]; }
  artifacts(session_id:string, run_id?:string){ this.calls.push(["artifacts", session_id, run_id]); return { artifacts:[{ kind:"devplan", path:".nexussy/artifacts/devplan.md", sha256:"abc", bytes:1, updated_at:"now" }] }; }
}

test("default render is chat transcript, not dashboard columns", () => {
  const state = createDefaultChatState();
  const out = renderApp(state, 120);
  expect(out).toContain("nexussy  session ready");
  expect(out).toContain("Discover pending");
  expect(out).toContain("Profile: default");
  expect(out).toContain("nexussy ›");
  expect(out).toContain("One CLI, two speeds");
  expect(out).toContain("What it can do:");
  expect(out).toContain("● Plan");
  expect(out).toContain("● Develop");
  expect(out).not.toContain("Agents (0)");
  expect(out).not.toContain("DevPlan\n(no devplan updates)\nProvider Keys");
});

test("pipeline strip and pipeline overlay show every stage", async () => {
  const client = new MockClient() as any;
  let state: ChatUiState = { ...createDefaultChatState(), app:{ ...createDefaultChatState().app, runId:"run-1", sessionId:"sess-1" } };
  [state] = await handleComposerSubmit(client, state, "/pipeline");
  const out = renderChat(state, 180);
  expect(out).toContain("Discover");
  expect(out).toContain("Design");
  expect(out).toContain("Validate");
  expect(out).toContain("Plan");
  expect(out).toContain("Review");
  expect(out).toContain("Implement");
  expect(out).toContain("Browser");
  expect(out).toContain("Focused controls");
});

test("status snapshot preserves and renders all stages", () => {
  const snapshot = { ok:true, run:{ run_id:"run-1", session_id:"sess-1", status:"running", usage }, stages:STAGES.map((stage, index) => ({ stage, status:index % 2 ? "pending" : "running", attempt:1, max_attempts:1, input_artifacts:[], output_artifacts:[] })), workers:[], paused:false, blockers:[] } as any;
  const app = reduceStatusSnapshot(createDefaultChatState().app, snapshot);
  for (const stage of STAGES) expect(app.stages[stage]).toBe(snapshot.stages.find((row:any) => row.stage === stage).status);
  expect(renderPipelineRows(app).length).toBe(STAGES.length);
});

test("dashboard and chat modes toggle", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  [state] = await handleComposerSubmit(client, state, "/dashboard");
  expect(state.mode).toBe("dashboard");
  expect(renderApp(state)).toContain("Agents");
  [state] = await handleComposerSubmit(client, state, "/chat");
  expect(state.mode).toBe("chat");
});

test("plain text stays in ask mode and slash new starts idle run", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  let result;
  [state, result] = await handleComposerSubmit(client, state, "Create a tiny CLI with tests");
  expect(result.message).toBe("ask mode");
  expect(client.calls).toEqual([]);
  expect(renderChat(state)).toContain("This looks buildable");
  expect(state.pendingAction?.command).toBe("/new Create a tiny CLI with tests");
  [state, result] = await handleComposerSubmit(client, state, "Yes, run it");
  expect(result.stream).toBe(true);
  expect(client.calls[0][0]).toBe("startPipeline");
  state = createDefaultChatState();
  [state, result] = await handleComposerSubmit(client, state, "/new Create a tiny CLI with tests");
  expect(result.stream).toBe(true);
  expect(client.calls[1][0]).toBe("startPipeline");
  [state, result] = await handleComposerSubmit(client, state, "add sqlite support");
  expect(result.message).toBe("ask mode");
  expect(client.calls.length).toBe(2);
  expect(renderChat(state)).toContain("This looks buildable");
});

test("slash new sends configured TUI routing as core model overrides", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  state = { ...state, app:reduceSecrets(state.app, [{ name:"AGENTROUTER_API_KEY", source:"env", configured:true }]) };
  [,] = await handleComposerSubmit(client, state, "/new build api");
  const body = client.calls.at(-1)[1];
  expect(body.auto_approve_interview).toBe(false);
  expect(body.model_overrides.interview).toBe("openai/deepseek-v4-flash");
  expect(body.model_overrides.plan).toBe("openai/deepseek-v4-flash");
  expect(body.model_overrides.validate_browser).toBe("openai/deepseek-v4-flash");
  expect(JSON.stringify(body)).not.toContain("AGENTROUTER_API_KEY");
});

test("slash new supports explicit auto interview opt-in", async () => {
  const client = new MockClient() as any;
  [,] = await handleComposerSubmit(client, createDefaultChatState(), "/new --auto-interview build api");
  expect(client.calls.at(-1)[1].auto_approve_interview).toBe(true);
});

test("slash new does not force static OpenRouter catalog defaults", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  state = { ...state, app:reduceSecrets(state.app, [{ name:"OPENROUTER_API_KEY", source:"env", configured:true }]) };
  [,] = await handleComposerSubmit(client, state, "/new build api");
  expect(client.calls.at(-1)[1].model_overrides).toBeUndefined();
});

test("slash new uses edited per-stage primary model override", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  const app = reduceSecrets(state.app, [{ name:"AGENTROUTER_API_KEY", source:"env", configured:true }]);
  const option = findModelOption(app.modelOptions, "openai/gpt-5.4");
  if (!option) throw new Error("missing test model option");
  state = { ...state, app:reduceStageRoutingModel(app, "plan", option, "primary") };
  [,] = await handleComposerSubmit(client, state, "/new build api");
  expect(client.calls.at(-1)[1].model_overrides.plan).toBe("openai/gpt-5.4");
  expect(client.calls.at(-1)[1].model_overrides.design).toBe("openai/deepseek-v4-flash");
});

test("plain questions use provider-backed Ask mode", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  const [next, result] = await handleComposerSubmit(client, state, "What tradeoffs matter for deployment?");
  state = next;
  expect(result.message).toBe("ask mode");
  expect(client.calls[0]).toEqual(["chat", { message:"What tradeoffs matter for deployment?" }]);
  expect(renderChat(state)).toContain("provider says: What tradeoffs matter for deployment?");
});

test("greetings do not start expensive pipeline runs", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  let result;
  [state, result] = await handleComposerSubmit(client, state, "hi");
  expect(result.message).toBe("ask mode");
  expect(client.calls).toEqual([]);
  expect(renderChat(state)).toContain("Ask for help");
  expect(looksLikeProjectRequest("Create a tiny CLI with tests")).toBe(true);
  expect(looksLikeProjectRequest("hi")).toBe(false);
});

test("interview-first requests stay local until explicit new run", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  let result;
  [state, result] = await handleComposerSubmit(client, state, "interview me please");
  expect(result.message).toBe("ask mode");
  expect(state.interviewMode).toBeUndefined();
  expect(client.calls).toEqual([]);
  [state, result] = await handleComposerSubmit(client, state, "to buiuld an app");
  expect(result.message).toBe("ask mode");
  expect(client.calls).toEqual([]);
  expect(wantsInterviewFirst("interview me please")).toBe(true);
});

test("interaction classifier only treats explicit triggers as action buckets", () => {
  const state = createDefaultChatState();
  expect(classifyInteraction("/status", state)).toBe("command");
  expect(classifyInteraction("Should I use the TUI or web dashboard?", state)).toBe("ask");
  expect(classifyInteraction("1", state)).toBe("ambiguous");
  expect(classifyInteraction("yes", state)).toBe("ambiguous");
  const pending = { ...state, pendingAction:{ description:"start", command:"/new build" } };
  expect(classifyInteraction("1", pending)).toBe("choice-selection");
  expect(classifyInteraction("Yes, run it", pending)).toBe("confirmation");
});

test("slash commands route or open overlays", async () => {
  const client = new MockClient() as any;
  let state: ChatUiState = { ...createDefaultChatState(), app:{ ...createDefaultChatState().app, runId:"run-1", sessionId:"sess-1" } };
  let result;
  [state] = await handleComposerSubmit(client, state, "/new build api"); expect(client.calls.at(-1)[0]).toBe("startPipeline");
  [state] = await handleComposerSubmit(client, state, "/pause stop"); expect(client.calls.at(-2)).toEqual(["pause", "run-123456", "stop"]);
  [state] = await handleComposerSubmit(client, state, "/resume-run"); expect(client.calls.at(-2)).toEqual(["resume", "run-123456"]);
  [state, result] = await handleComposerSubmit(client, state, "/stage plan"); expect(result.message).toContain("use /skip"); expect(client.calls.at(-2)[0]).toBe("resume");
  [state] = await handleComposerSubmit(client, state, "/skip validate reason here"); expect(client.calls.at(-1)).toEqual(["skip", "run-123456", "validate", "reason here"]);
  [state] = await handleComposerSubmit(client, state, "/spawn backend build API"); expect(client.calls.at(-1)).toEqual(["spawn", { run_id:"run-123456", role:"backend", task:"build API" }]);
  [state] = await handleComposerSubmit(client, state, "/inject backend-abc123 hello"); expect(client.calls.at(-1)).toEqual(["injectWorker", "backend-abc123", { run_id:"run-123456", worker_id:"backend-abc123", message:"hello" }]);
  const [, exported] = await handleComposerSubmit(client, state, "/export"); expect(exported.html).toContain("nexussy export");
  [state] = await handleComposerSubmit(client, state, "/workers"); expect(state.overlay).toBe("workers"); expect(state.app.workers["backend-abc123"].status).toBe("running");
  [state] = await handleComposerSubmit(client, state, "/onboarding"); expect(state.overlay).toBe("onboarding");
  [state] = await handleComposerSubmit(client, state, "/plan"); expect(state.overlay).toBe("plan");
  [state] = await handleComposerSubmit(client, state, "/artifacts"); expect(state.overlay).toBe("artifacts"); expect(state.app.artifacts[0].kind).toBe("devplan");
  [state] = await handleComposerSubmit(client, state, "/doctor"); expect(state.overlay).toBe("doctor");
  [state] = await handleComposerSubmit(client, state, "/secrets"); expect(state.overlay).toBe("secrets");
});

test("interview answers post to core and refresh status", async () => {
  const client = new MockClient() as any;
  let state: ChatUiState = { ...createDefaultChatState(), app:{ ...createDefaultChatState().app, runId:"run-1", sessionId:"sess-1" } };
  [state] = await handleComposerSubmit(client, state, "/interview-answer q1=Use local files q2=Keep it simple");
  expect(client.calls.at(-2)).toEqual(["interviewAnswer", "sess-1", { q1:"Use local files", q2:"Keep it simple" }]);
  expect(client.calls.at(-1)).toEqual(["status", "run-1"]);
  expect(state.statusMessage).toBe("interview answers submitted");
});

test("pending interview turns plain text into answers instead of Ask mode", async () => {
  const client = new MockClient() as any;
  let state: ChatUiState = { ...createDefaultChatState(), app:{ ...createDefaultChatState().app, runId:"run-1", sessionId:"sess-1", paused:true, stages:{ ...createDefaultChatState().app.stages, interview:"paused" } }, pendingInterview:{ questions:[{ question_id:"q1", question:"What should it do?" }, { question_id:"q2", question:"Any constraints?" }], answers:{}, index:0 } };
  let result;
  [state, result] = await handleComposerSubmit(client, state, "Build a local chatbot");
  expect(result.message).toBe("interview answer submitted; composer ready");
  expect(client.calls.some((call:any[]) => call[0] === "chat")).toBe(false);
  expect(state.pendingInterview).toBeUndefined();
  expect(client.calls.at(-2)).toEqual(["interviewAnswer", "sess-1", { q1:"Build a local chatbot" }]);
  expect(result.stream).toBe(true);
});

test("interview artifact content becomes pending interview questions", () => {
  const pending = pendingInterviewFromArtifact({ content_text:JSON.stringify({ questions:[{ question_id:"q1", question:"What should it do?", suggested_answer:"Start small" }] }) });
  expect(pending?.questions[0]).toEqual({ question_id:"q1", question:"What should it do?", suggested_answer:"Start small" });
  expect(renderChat({ ...createDefaultChatState(), transcript:[{ kind:"assistant", id:"q", role:"assistant", text:`Interview question 1/1: ${pending!.questions[0].question}\nSuggested default: ${pending!.questions[0].suggested_answer}` }] })).toContain("Suggested default: Start small");
});

test("interview artifact pending state ignores answered history", () => {
  const pending = pendingInterviewFromArtifact({ content_text:JSON.stringify({ questions:[{ question_id:"q1", question:"Goal?", answer:"Answered" }, { question_id:"q2", question:"Interface?", answer:"pending" }] }) });
  expect(pending?.questions).toEqual([{ question_id:"q2", question:"Interface?", suggested_answer:undefined }]);
});

test("pause state changed for interview marks interview paused and renders visibly", () => {
  let state = createDefaultChatState();
  state = reduceChatEvent(state, env("pause_state_changed", { paused:true, reason:"waiting for interview answers" }, 1));
  expect(state.app.stages.interview).toBe("paused");
  expect(renderChat(state)).toContain("Interview paused");
});

test("stage pause resume cancel and chat are structured", async () => {
  const client = new MockClient() as any;
  let state: ChatUiState = { ...createDefaultChatState(), app:{ ...createDefaultChatState().app, runId:"run-1", sessionId:"sess-1", stages:{ ...createDefaultChatState().app.stages, plan:"running" } } };
  [state] = await handleComposerSubmit(client, state, "/pause plan waiting for product input");
  expect(client.calls.at(-2)).toEqual(["pause", "run-1", "waiting for product input"]);
  expect(client.calls.at(-1)).toEqual(["status", "run-1"]);
  expect(state.app.stageControlNotes.at(-1)?.stage).toBe("plan");
  expect(renderChat(state)).toContain("PAUSE Plan - waiting for product input");
  [state] = await handleComposerSubmit(client, state, "/resume plan continue with defaults");
  expect(client.calls.at(-2)).toEqual(["resume", "run-1"]);
  expect(client.calls.at(-1)).toEqual(["status", "run-1"]);
  [state] = await handleComposerSubmit(client, state, "/stage-chat plan");
  expect(state.stageChat?.stage).toBe("plan");
  expect(renderChat(state)).toContain("plan ›");
  [state] = await handleComposerSubmit(client, state, "prefer a smaller task split");
  expect(client.calls.at(-1)).toEqual(["inject", { run_id:"run-1", message:"prefer a smaller task split", stage:"plan" }]);
  [state] = await handleComposerSubmit(client, state, "/chat");
  expect(state.stageChat).toBeUndefined();
  [state] = await handleComposerSubmit(client, state, "/cancel plan stop now");
  expect(client.calls.at(-2)).toEqual(["cancel", "run-1", "stop now"]);
});

test("stage scoped controls and stage chat work for every stage", async () => {
  for (const stage of STAGES) {
    const client = new MockClient() as any;
    let state: ChatUiState = { ...createDefaultChatState(), app:{ ...createDefaultChatState().app, runId:"run-1", sessionId:"sess-1" } };
    [state] = await handleComposerSubmit(client, state, `/pause ${stage} hold`);
    expect(client.calls.at(-2)).toEqual(["pause", "run-1", "hold"]);
    expect(state.app.stageControlNotes.at(-1)?.stage).toBe(stage);
    [state] = await handleComposerSubmit(client, state, `/resume ${stage} go`);
    expect(client.calls.at(-2)).toEqual(["resume", "run-1"]);
    [state] = await handleComposerSubmit(client, state, `/stage-chat ${stage}`);
    expect(state.overlay).toBe("stage-chat");
    expect(state.stageChat?.stage).toBe(stage);
    expect(renderChat(state)).toContain(`${stage} ›`);
    [state] = await handleComposerSubmit(client, state, "focus here");
    expect(client.calls.at(-1)).toEqual(["inject", { run_id:"run-1", message:"focus here", stage }]);
    state = closeOverlay(state);
    expect(state.stageChat).toBeUndefined();
    expect(state.transcriptFilter).toBeUndefined();
  }
});

test("model routing overlay uses configured providers and profile switch", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  [state] = await handleComposerSubmit(client, state, "/models");
  expect(state.overlay).toBe("models");
  const models = renderChat(state, 180);
  expect(models).toContain("Model Routing");
  expect(models).toContain("openrouter");
  expect(models).not.toContain("sk-");
  [state] = await handleComposerSubmit(client, state, "/profile fast");
  expect(state.app.routingProfile).toBe("fast");
  expect(renderChat(state)).toContain("Profile: fast");
  [state] = await handleComposerSubmit(client, state, "/model plan openrouter/openai/gpt-4o-mini");
  expect(state.app.routing.plan.primary?.model).toBe("openrouter/openai/gpt-4o-mini");
  [state] = await handleComposerSubmit(client, state, "/fallback validate_browser openrouter/anthropic/claude-sonnet-4");
  expect(state.app.routing.validate_browser.fallback?.model).toBe("openrouter/anthropic/claude-sonnet-4");
});

test("configured providers create routing entries for every stage", () => {
  const app = reduceSecrets(createDefaultChatState().app, [{ name:"AGENTROUTER_API_KEY", source:"env", configured:true }]);
  expect(Object.keys(app.routing)).toEqual(STAGES);
  for (const stage of STAGES) expect(app.routing[stage].primary?.configured).toBe(true);
});

test("setup overlay offers provider menu without accepting visible secrets", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  [state] = await handleComposerSubmit(client, state, "/setup");
  const menu = renderChat(state, 180);
  expect(state.overlay).toBe("setup");
  expect(menu).toContain("Provider Setup");
  expect(menu).toContain("AgentRouter");
  expect(menu).toContain("The visible TUI composer never accepts API keys");
  [state] = await handleComposerSubmit(client, state, "/setup agentrouter");
  expect(renderChat(state, 180)).toContain("Provider setup for agentrouter");
  expect(renderChat(state, 180)).not.toContain("sk-");
});

test("workers overlay supports status and stage filters", async () => {
  const client = new MockClient() as any;
  let state: ChatUiState = { ...createDefaultChatState(), app:{ ...createDefaultChatState().app, runId:"run-1", sessionId:"sess-1" } };
  [state] = await handleComposerSubmit(client, state, "/workers busy develop");
  expect(state.overlay).toBe("workers");
  expect(state.workerFilter).toBe("busy");
  expect(state.selectedStage).toBe("develop");
  expect(renderChat(state)).toContain("filter: busy stage:develop");
  expect(renderChat(state)).toContain("backend-abc123");
});

test("heartbeat does not render and stage/tool/worker events become transcript rows", () => {
  let state = createDefaultChatState();
  state = reduceChatEvent(state, env("heartbeat", { server_status:"ok" }, 1));
  expect(state.transcript.length).toBe(0);
  state = reduceChatEvent(state, env("stage_transition", { to_stage:"interview", to_status:"running", reason:"stage started" }, 2));
  state = reduceChatEvent(state, env("tool_call", { call_id:"c1", stage:"develop", tool_name:"bash", arguments:{cmd:"pytest -q"} }, 3));
  state = reduceChatEvent(state, env("worker_task", { worker_id:"backend-123", task_id:"t", task_title:"write files", status:"running" }, 4));
  const rendered = renderChat(state);
  expect(rendered).toContain("● Interview");
  expect(rendered).toContain("▸ bash");
  expect(rendered).toContain("◇ backend-123 running: write files");
});

test("duplicate SSE event ids do not replay transcript rows", () => {
  let state = createDefaultChatState();
  const event = env("run_started", { status:"running", current_stage:"interview", usage }, 1);
  state = reduceChatEvent(state, event);
  state = reduceChatEvent(state, event);
  expect(state.transcript.filter(item => item.kind === "run_started").length).toBe(1);
});

test("git events, worker status, and RPC JSON render as readable agent activity", () => {
  let state = createDefaultChatState();
  state = reduceChatEvent(state, env("git_event", { action:"worktree_created", worker_id:"backend-123", branch_name:"worker/backend-123", message:"worktree created" }, 1));
  state = reduceChatEvent(state, env("worker_status", { worker_id:"backend-123", status:"finished", task_title:"Develop task 1" }, 2));
  state = reduceChatEvent(state, env("worker_stream", { worker_id:"backend-123", stream_kind:"rpc", line:JSON.stringify({ jsonrpc:"2.0", method:"agent.event", params:{ type:"content_delta", payload:{ delta:"edited app/main.py" } } }) }, 3));
  state = reduceChatEvent(state, env("worker_stream", { worker_id:"backend-123", stream_kind:"rpc", line:JSON.stringify({ jsonrpc:"2.0", id:"abc", result:{ status:"ok" } }) }, 4));
  const rendered = renderChat(state);
  expect(rendered).toContain("backend-123 created worktree worker/backend-123");
  expect(rendered).toContain("backend-123 finished - Develop task 1");
  expect(rendered).toContain("backend-123 says: edited app/main.py");
  expect(rendered).toContain("backend-123 completed RPC: ok");
  expect(rendered).not.toContain("git_event");
  expect(rendered).not.toContain("worker_status");
  expect(rendered).not.toContain("jsonrpc");
});

test("missing Pi CLI error is actionable", () => {
  const err = actionableError("missing Pi CLI: pi");
  expect(err.text).toContain("Missing dependency: Pi CLI");
  expect(err.text).toContain("bundled Pi-compatible fallback");
  expect(err.actions.join("\n")).toContain("/doctor");
});

test("done with error renders actionable block", () => {
  const item = transcriptItemFromEvent(env("done", { final_status:"failed", summary:"pipeline failed", usage, error:{ message:"LiteLLM is not installed" } }, 1));
  expect(item?.kind).toBe("error");
  expect(JSON.stringify(item)).toContain("LiteLLM");
});

test("OpenRouter quota traceback is summarized and redacted", () => {
  const raw = `Traceback (most recent call last):\n  File "/tmp/litellm.py", line 1, in x\nlitellm.APIError: APIError: OpenrouterException - {"error":{"message":"Key limit exceeded (total limit). Manage it using https://openrouter.ai/workspaces/default/keys/3add9d32b66c4a82d83bcc849e18319f18a95993f3e41314020bc1c744994230","code":403}}`;
  let state = createDefaultChatState();
  state = reduceChatEvent(state, env("pipeline_error", { ok:false, error_code:"provider_unavailable", message:raw, request_id:"req", retryable:false }, 1));
  const rendered = renderChat(state, 180);
  expect(rendered).toContain("OpenRouter provider limit reached");
  expect(rendered).toContain("/models choose another configured provider");
  expect(rendered).not.toContain("Traceback (most recent call last)");
  expect(rendered).not.toContain("File \"/tmp/litellm.py\"");
  expect(rendered).not.toContain("3add9d32b66c4a82d83bcc849e18319f18a95993f3e41314020bc1c744994230");
});

test("generic Python traceback is shortened before transcript rendering", () => {
  const raw = `Traceback (most recent call last):\n  File "/home/me/core.py", line 10, in run\n    explode()\nValueError: provider failed loudly`;
  const item = transcriptItemFromEvent(env("done", { final_status:"failed", summary:"pipeline failed", usage, error:{ message:raw } }, 1));
  expect(item?.kind).toBe("error");
  const rendered = renderChat({ ...createDefaultChatState(), transcript:item ? [item] : [] }, 160);
  expect(rendered).toContain("provider failed loudly");
  expect(rendered).toContain("Traceback omitted");
  expect(rendered).not.toContain("File \"/home/me/core.py\"");
});

test("file reference autocomplete inserts refs and rejects escape", () => {
  expect(fileReferenceQuery("please read @src/")).toBe("src/");
  expect(fileReferenceSuggestions("src/", ["src/index.ts", "README.md"])[0].label).toBe("@src/index.ts");
  expect(insertFileReference("open @src/", "src/index.ts")).toBe("open @src/index.ts");
  expect(() => rejectPathEscape("../secret")).toThrow("escapes");
  expect(() => rejectPathEscape("/etc/passwd")).toThrow("escapes");
});
