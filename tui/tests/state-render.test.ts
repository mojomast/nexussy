import { expect, test } from "bun:test";
import { createState, reduceConnectionError, reduceEvent, reduceSecrets, toggleToolRow } from "../src/state";
import { exportHtml, loadOptionalPiRuntime, renderPanels } from "../src/renderer";
import { EVENT_TYPES } from "../src/types";
import { minimalPayloadFor } from "../src/sse";
import type { EventEnvelope, Worker } from "../src/types";

const usage = { input_tokens:0, output_tokens:0, total_tokens:0, cost_usd:0 };
function envelope(type:any, payload:any, sequence=1): EventEnvelope { return { event_id:`e${sequence}`, sequence, contract_version:"1.0", type, session_id:"s", run_id:"r", ts:"2026-04-27T00:00:00Z", source:"core", payload } as EventEnvelope; }
function worker(status:any, task_title?:string): Worker { return { worker_id:"backend-abc123", run_id:"r", role:"backend", status, task_title, task_id:null, worktree_path:"/tmp/w", branch_name:"nexussy/backend-abc123", pid:null, model:"openai/gpt-5.5-fast", usage, created_at:"2026-04-27T00:00:00Z", updated_at:"2026-04-27T00:00:00Z" }; }

test("agent roster updates from spawned, status, and task events", () => {
  let s = createState();
  s = reduceEvent(s, envelope("worker_spawned", worker("starting"), 1));
  s = reduceEvent(s, envelope("worker_status", worker("running"), 2));
  s = reduceEvent(s, envelope("worker_task", { worker_id:"backend-abc123", task_id:"task-abc123", task_title:"Implement API", status:"running" }, 3));
  expect(s.workers["backend-abc123"].status).toBe("running");
  expect(s.workers["backend-abc123"].task_title).toBe("Implement API");
});

test("collapsible tool rows expand and collapse", () => {
  let s = reduceEvent(createState(), envelope("tool_call", { call_id:"c1", stage:"develop", tool_name:"bash", arguments:{cmd:"bun test"} }, 1));
  expect(s.logs[0].collapsed).toBe(true);
  s = toggleToolRow(s, "c1");
  expect(s.logs[0].collapsed).toBe(false);
});

test("render smoke produces three panels and export html", () => {
  let s = createState();
  s = reduceEvent(s, envelope("run_started", { status:"running", current_stage:"interview", usage }, 1));
  s = reduceEvent(s, envelope("content_delta", { stage:"interview", role:"assistant", delta:"hello" }, 2));
  const p = renderPanels(s);
  expect(p.left).toContain("Stages");
  expect(p.center).toContain("hello");
  expect(p.right).toContain("Tokens");
  expect(p.html).toContain("<!doctype html>");
});

test("reducer consumes fixture payloads for every Section 9 event and updates panels", () => {
  let s = createState();
  EVENT_TYPES.forEach((type, i) => { s = reduceEvent(s, envelope(type, minimalPayloadFor(type), i + 1)); });
  expect(s.workers["backend-abc123"].task_title).toBe("Build API");
  expect(s.locks.length).toBeGreaterThan(0);
  expect(s.gitEvents[0].action).toBe("merge_completed");
  expect(s.usage.total_tokens).toBe(3);
  expect(Object.values(s.blockers).some(b => b.resolved)).toBe(true);
  expect(s.paused).toBe(true);
  expect(s.artifacts[0].kind).toBe("devplan");
  expect(s.stages.design).toBe("running");
  expect(s.finalStatus).toBe("passed");
  const panels = renderPanels(s);
  expect(panels.left).toContain("Paused: yes");
  expect(panels.center).toContain("done");
  expect(panels.right).toContain("Git");
});

test("connection and auth error display state renders visibly", () => {
  const s = reduceConnectionError(createState(), new Error("401 unauthorized"));
  const panels = renderPanels(s);
  expect(s.authError).toContain("unauthorized");
  expect(panels.center).toContain("auth");
});

test("optional Pi runtime probes all required packages", async () => {
  const attempted:string[] = [];
  const runtime = await loadOptionalPiRuntime(async (name) => { attempted.push(name); return {}; });
  expect(attempted).toEqual(["@mariozechner/pi-tui", "@mariozechner/pi-ai", "@mariozechner/pi-agent-core"]);
  expect(runtime).toEqual({ tui:true, ai:true, agentCore:true, missing:[] });
});

test("export html escapes displayed session data", () => {
  const html = exportHtml("<left>", "center & stream", "right > files");
  expect(html).toContain("&lt;left&gt;");
  expect(html).toContain("center &amp; stream");
  expect(html).toContain("right &gt; files");
});

test("provider key panel renders only secret summaries", () => {
  const s = reduceSecrets(createState(), [{ name:"OPENAI_API_KEY", source:"keyring", configured:true } as any]);
  const panels = renderPanels(s);
  expect(panels.right).toContain("Provider Keys");
  expect(panels.right).toContain("configured OPENAI_API_KEY (keyring)");
  expect(panels.right).not.toContain("sk-");
});
