import { expect, test } from "bun:test";
import { createDefaultChatState, renderApp, renderChat } from "../src/ui/App";
import { classifyInteraction, handleComposerSubmit, looksLikeProjectRequest, wantsInterviewFirst } from "../src/ui/Composer";
import { insertFileReference, fileReferenceQuery, fileReferenceSuggestions, rejectPathEscape } from "../src/ui/FileReferenceAutocomplete";
import { actionableError, reduceChatEvent, transcriptItemFromEvent } from "../src/ui/Transcript";
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
  skip(run_id:string, stage:string, reason:string){ this.calls.push(["skip", run_id, stage, reason]); return {}; }
  spawn(body:any){ this.calls.push(["spawn", body]); return {}; }
  secrets(){ this.calls.push(["secrets"]); return [{ name:"OPENROUTER_API_KEY", source:"config", configured:true }]; }
  status(run_id:string){ this.calls.push(["status", run_id]); return { ok:true, run:{ run_id, session_id:"sess-1", status:"running", usage }, stages:[{ stage:"design", status:"running" }], workers:[], paused:false, blockers:[] }; }
  workers(run_id:string){ this.calls.push(["workers", run_id]); return [{ worker_id:"backend-abc123", run_id, role:"backend", status:"running", worktree_path:"", branch_name:"", model:"mock", usage, created_at:"", updated_at:"" }]; }
  artifacts(session_id:string, run_id?:string){ this.calls.push(["artifacts", session_id, run_id]); return { artifacts:[{ kind:"devplan", path:".nexussy/artifacts/devplan.md", sha256:"abc", bytes:1, updated_at:"now" }] }; }
}

test("default render is chat transcript, not dashboard columns", () => {
  const state = createDefaultChatState();
  const out = renderApp(state, 120);
  expect(out).toContain("nexussy  session ready");
  expect(out).toContain("nexussy ›");
  expect(out).toContain("What it can do:");
  expect(out).toContain("● Plan");
  expect(out).toContain("● Develop");
  expect(out).not.toContain("Agents (0)");
  expect(out).not.toContain("DevPlan\n(no devplan updates)\nProvider Keys");
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
  expect(renderChat(state)).toContain("Ask mode only");
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
  expect(renderChat(state)).toContain("Use `/new <description>`");
});

test("greetings do not start expensive pipeline runs", async () => {
  const client = new MockClient() as any;
  let state = createDefaultChatState();
  let result;
  [state, result] = await handleComposerSubmit(client, state, "hi");
  expect(result.message).toBe("ask mode");
  expect(client.calls).toEqual([]);
  expect(renderChat(state)).toContain("use `/new <description>`");
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
  [state] = await handleComposerSubmit(client, state, "/pause stop"); expect(client.calls.at(-1)).toEqual(["pause", "run-123456", "stop"]);
  [state] = await handleComposerSubmit(client, state, "/resume-run"); expect(client.calls.at(-1)).toEqual(["resume", "run-123456"]);
  [state, result] = await handleComposerSubmit(client, state, "/stage plan"); expect(result.message).toContain("use /skip"); expect(client.calls.at(-1)[0]).toBe("resume");
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

test("file reference autocomplete inserts refs and rejects escape", () => {
  expect(fileReferenceQuery("please read @src/")).toBe("src/");
  expect(fileReferenceSuggestions("src/", ["src/index.ts", "README.md"])[0].label).toBe("@src/index.ts");
  expect(insertFileReference("open @src/", "src/index.ts")).toBe("open @src/index.ts");
  expect(() => rejectPathEscape("../secret")).toThrow("escapes");
  expect(() => rejectPathEscape("/etc/passwd")).toThrow("escapes");
});
