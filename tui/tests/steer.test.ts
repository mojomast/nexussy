import { expect, test } from "bun:test";
import { handleComposerSubmit, createChatUiState } from "../src/ui/Composer";
import { createState } from "../src/state";
import type { Worker } from "../src/types";

function worker(worker_id:string): Worker {
  return {
    worker_id,
    run_id:"run-1",
    role:"backend",
    status:"running",
    worktree_path:"/tmp/wt",
    branch_name:`worker/${worker_id}`,
    model:"mock/model",
    usage:{input_tokens:0,output_tokens:0,total_tokens:0,cost_usd:0},
    created_at:new Date(0).toISOString(),
    updated_at:new Date(0).toISOString(),
  };
}

function stateWithRun() {
  const app = { ...createState(), runId:"run-1", sessionId:"sid-1" };
  return createChatUiState(() => app);
}

class MockClient {
  calls:any[] = [];
  workersResult = [worker("backend-abc123")];
  statusResult = { queue_length:2, recent:[
    { target:"orchestrator", message:"newest", priority:"normal", created_at:"2026-01-01T00:00:03Z", consumed_at:null },
    { target:"worker", worker_id:"backend-abc123", message:"middle", priority:"normal", created_at:"2026-01-01T00:00:02Z", consumed_at:null },
    { target:"orchestrator", message:"oldest", priority:"high", created_at:"2026-01-01T00:00:01Z", consumed_at:"2026-01-01T00:00:04Z" },
  ] };
  mcpCall(name:string, args:Record<string, unknown>) { this.calls.push(["mcp", name, args]); return name === "nexussy_steer_status" ? this.statusResult : { ok:true, id:1 }; }
  workers(run_id:string) { this.calls.push(["workers", run_id]); return this.workersResult; }
  startPipeline(){ throw new Error("not used"); }
  chat(){ throw new Error("not used"); }
  inject(){ throw new Error("not used"); }
  injectWorker(){ throw new Error("not used"); }
  pause(){ throw new Error("not used"); }
  resume(){ throw new Error("not used"); }
  skip(){ throw new Error("not used"); }
  spawn(){ throw new Error("not used"); }
  secrets(){ throw new Error("not used"); }
  status(){ throw new Error("not used"); }
  artifacts(){ throw new Error("not used"); }
}

test("steer_command_orchestrator", async () => {
  const client = new MockClient() as any;
  const [next, outcome] = await handleComposerSubmit(client, stateWithRun(), "/steer focus on auth");
  expect(outcome.message).toBe("Steering message sent to orchestrator");
  expect(next.statusMessage).toBe("Steering message sent to orchestrator");
  expect(client.calls[0]).toEqual(["mcp", "nexussy_steer", { target:"orchestrator", run_id:"run-1", message:"focus on auth", priority:"normal" }]);
});

test("steer_command_worker", async () => {
  const client = new MockClient() as any;
  const [next, outcome] = await handleComposerSubmit(client, stateWithRun(), "/steer @backend-abc123 refactor handler");
  expect(outcome.message).toBe("Steering message sent to worker backend-abc123");
  expect(next.app.workers["backend-abc123"].worker_id).toBe("backend-abc123");
  expect(client.calls[0]).toEqual(["workers", "run-1"]);
  expect(client.calls[1]).toEqual(["mcp", "nexussy_steer", { target:"worker", run_id:"run-1", worker_id:"backend-abc123", message:"refactor handler", priority:"normal" }]);
  await expect(handleComposerSubmit(client, stateWithRun(), "/steer @bad! nope")).rejects.toThrow("invalid worker_id");
  await expect(handleComposerSubmit(client, stateWithRun(), "/steer @backend-missing nope")).rejects.toThrow("worker not found");
});

test("steer_command_list_clear", async () => {
  const client = new MockClient() as any;
  const [, listOutcome] = await handleComposerSubmit(client, stateWithRun(), "/steer list");
  expect(listOutcome.message).toContain("steer queue: 2");
  expect(listOutcome.message).toContain("newest");
  expect(listOutcome.message).toContain("backend-abc123: middle");
  const [, clearOutcome] = await handleComposerSubmit(client, stateWithRun(), "/steer clear");
  expect(clearOutcome.message).toBe("Steering context cleared");
  expect(client.calls.at(-1)).toEqual(["mcp", "nexussy_steer", { target:"orchestrator", run_id:"run-1", message:"CLEAR_CONTEXT", priority:"normal" }]);
});
