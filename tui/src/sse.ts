import { EVENT_TYPES, type EventEnvelope, type SSEEventType } from "./types";

export interface SSEFrame { id?: string; event?: string; retry?: number; data: string; }
export interface ReconnectState { lastEventId?: string; retryMs: number; attempts: number; }

export class SSEParseError extends Error {}

export function parseSSEFrames(chunk: string): SSEFrame[] {
  const frames: SSEFrame[] = [];
  for (const raw of chunk.replace(/\r\n/g, "\n").split(/\n\n+/)) {
    if (!raw.trim()) continue;
    const frame: SSEFrame = { data: "" };
    for (const line of raw.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const idx = line.indexOf(":");
      if (idx < 0) throw new SSEParseError(`Malformed SSE line: ${line}`);
      const field = line.slice(0, idx);
      const value = line.slice(idx + 1).replace(/^ /, "");
      if (field === "id") frame.id = value;
      else if (field === "event") frame.event = value;
      else if (field === "retry") {
        const retry = Number(value);
        if (!Number.isInteger(retry) || retry < 0) throw new SSEParseError("Invalid retry");
        frame.retry = retry;
      } else if (field === "data") frame.data += (frame.data ? "\n" : "") + value;
    }
    if (!frame.data) throw new SSEParseError("SSE frame missing data");
    frames.push(frame);
  }
  return frames;
}

export function parseEnvelope(frame: SSEFrame): EventEnvelope {
  if (frame.data === "[DONE]") throw new SSEParseError("[DONE] sentinel is forbidden by contract");
  let parsed: unknown;
  try { parsed = JSON.parse(frame.data); } catch (e) { throw new SSEParseError(`Invalid JSON data: ${String(e)}`); }
  if (!isEnvelope(parsed)) throw new SSEParseError("Malformed EventEnvelope");
  if (frame.id !== undefined && frame.id !== parsed.event_id) throw new SSEParseError("SSE id does not match envelope event_id");
  if (frame.event !== undefined && frame.event !== parsed.type) throw new SSEParseError("SSE event does not match envelope type");
  return parsed;
}

export function isEnvelope(v: unknown): v is EventEnvelope {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return typeof o.event_id === "string" && Number.isInteger(o.sequence) && o.contract_version === "1.0" &&
    typeof o.type === "string" && (EVENT_TYPES as readonly string[]).includes(o.type) &&
    typeof o.session_id === "string" && typeof o.run_id === "string" && typeof o.ts === "string" &&
    ["core","worker","tui","web"].includes(String(o.source)) && payloadMatches(o.type as SSEEventType, o.payload);
}

function obj(v: unknown): v is Record<string, unknown> { return !!v && typeof v === "object" && !Array.isArray(v); }
function str(o: Record<string, unknown>, k: string) { return typeof o[k] === "string"; }
function bool(o: Record<string, unknown>, k: string) { return typeof o[k] === "boolean"; }
function usage(v: unknown) { return obj(v) && typeof v.input_tokens === "number" && typeof v.output_tokens === "number" && typeof v.total_tokens === "number" && typeof v.cost_usd === "number"; }
function artifact(v: unknown) { return obj(v) && str(v,"kind") && str(v,"path") && str(v,"sha256") && typeof v.bytes === "number" && str(v,"updated_at"); }
function error(v: unknown) { return obj(v) && v.ok === false && str(v,"error_code") && str(v,"message") && str(v,"request_id") && bool(v,"retryable"); }
function worker(v: unknown) { return obj(v) && str(v,"worker_id") && str(v,"run_id") && str(v,"role") && str(v,"status") && str(v,"worktree_path") && str(v,"branch_name") && str(v,"model") && usage(v.usage) && str(v,"created_at") && str(v,"updated_at"); }
function lock(v: unknown) { return obj(v) && str(v,"path") && str(v,"worker_id") && str(v,"run_id") && str(v,"status") && str(v,"claimed_at") && str(v,"expires_at"); }
function blocker(v: unknown) { return obj(v) && str(v,"blocker_id") && str(v,"run_id") && str(v,"stage") && str(v,"severity") && str(v,"message") && bool(v,"resolved") && str(v,"created_at"); }
function payloadMatches(type: SSEEventType, p: unknown): boolean {
  if (!obj(p)) return false;
  switch (type) {
    case "heartbeat": return str(p,"ts") && str(p,"server_status");
    case "run_started": return str(p,"run_id") && str(p,"session_id") && str(p,"status") && usage(p.usage);
    case "content_delta": return str(p,"message_id") && str(p,"stage") && str(p,"role") && str(p,"delta");
    case "tool_call": return str(p,"call_id") && str(p,"stage") && str(p,"tool_name") && (!p.arguments || obj(p.arguments));
    case "tool_output": return str(p,"call_id") && str(p,"stage") && bool(p,"success") && (!p.error || error(p.error));
    case "tool_progress": return str(p,"call_id") && str(p,"stage") && str(p,"message");
    case "stage_transition": return str(p,"to_stage") && str(p,"to_status") && str(p,"reason");
    case "stage_status": return str(p,"stage") && str(p,"status") && typeof p.attempt === "number" && typeof p.max_attempts === "number" && Array.isArray(p.input_artifacts) && Array.isArray(p.output_artifacts);
    case "checkpoint_saved": return str(p,"checkpoint_id") && str(p,"stage") && str(p,"path") && str(p,"sha256") && str(p,"created_at");
    case "artifact_updated": return artifact(p.artifact) && str(p,"action");
    case "worker_spawned": case "worker_status": return worker(p);
    case "worker_task": return str(p,"worker_id") && str(p,"task_id") && str(p,"task_title") && str(p,"status");
    case "worker_stream": return str(p,"worker_id") && str(p,"stream_kind") && str(p,"line");
    case "file_claimed": case "file_released": case "file_lock_waiting": return lock(p);
    case "git_event": return str(p,"action") && str(p,"message") && (!p.paths || Array.isArray(p.paths));
    case "blocker_created": case "blocker_resolved": return blocker(p);
    case "cost_update": return usage(p);
    case "pause_state_changed": return bool(p,"paused") && str(p,"reason");
    case "pipeline_error": return error(p);
    case "done": return str(p,"final_status") && str(p,"summary") && usage(p.usage) && (!p.artifacts || Array.isArray(p.artifacts)) && (!p.error || error(p.error));
  }
}

export function applyReconnect(state: ReconnectState, env: EventEnvelope, retry?: number): ReconnectState {
  return { attempts: 0, lastEventId: env.event_id, retryMs: retry ?? state.retryMs };
}

export function reconnectHeaders(state: ReconnectState): HeadersInit {
  return state.lastEventId ? { "Last-Event-ID": state.lastEventId } : {};
}

export function fixtureFrame(env: EventEnvelope, retry = 3000): string {
  return `id: ${env.event_id}\nevent: ${env.type}\nretry: ${retry}\ndata: ${JSON.stringify(env)}\n\n`;
}

export function minimalPayloadFor(type: SSEEventType): unknown {
  const ts = "2026-04-27T00:00:00Z";
  const usage = { input_tokens:1, output_tokens:2, cache_read_tokens:0, cache_write_tokens:0, total_tokens:3, cost_usd:0.01, provider:"mock", model:"openai/gpt-5.5-fast" };
  const artifact = { kind:"devplan", path:"devplan.md", sha256:"a".repeat(64), bytes:12, updated_at:ts };
  const error = { ok:false, error_code:"internal_error", message:"boom", details:{}, request_id:"req-1", retryable:false };
  const worker = { worker_id:"backend-abc123", run_id:"018f0000-0000-4000-8000-000000000002", role:"backend", status:"running", task_id:null, task_title:"Build API", worktree_path:"/tmp/w", branch_name:"nexussy/backend-abc123", pid:null, model:"openai/gpt-5.5-fast", usage, created_at:ts, updated_at:ts, last_error:null };
  const lock = { path:"src/app.ts", worker_id:"backend-abc123", run_id:"018f0000-0000-4000-8000-000000000002", status:type === "file_released" ? "released" : type === "file_lock_waiting" ? "waiting" : "claimed", claimed_at:ts, expires_at:ts };
  const blocker = { blocker_id:"blocker-1", run_id:"018f0000-0000-4000-8000-000000000002", worker_id:"backend-abc123", stage:"develop", severity:"blocker", message:"Need input", resolved:type === "blocker_resolved", created_at:ts, resolved_at:type === "blocker_resolved" ? ts : null };
  switch (type) {
    case "heartbeat": return { ts, server_status:"ok" };
    case "run_started": return { run_id:"018f0000-0000-4000-8000-000000000002", session_id:"018f0000-0000-4000-8000-000000000001", status:"running", current_stage:"interview", started_at:ts, finished_at:null, usage };
    case "content_delta": return { message_id:"msg-1", stage:"interview", worker_id:null, role:"assistant", delta:"hello", final:false };
    case "tool_call": return { call_id:"call-1", stage:"develop", worker_id:"backend-abc123", tool_name:"bash", arguments:{ command:"bun test" } };
    case "tool_output": return { call_id:"call-1", stage:"develop", worker_id:"backend-abc123", success:true, result_text:"ok", display:null, error:null };
    case "tool_progress": return { call_id:"call-1", stage:"develop", worker_id:"backend-abc123", message:"halfway", percent:50 };
    case "stage_transition": return { from_stage:"interview", to_stage:"design", from_status:"passed", to_status:"running", reason:"next" };
    case "stage_status": return { stage:"design", status:"running", attempt:1, max_attempts:3, started_at:ts, finished_at:null, input_artifacts:[], output_artifacts:[], error:null };
    case "checkpoint_saved": return { checkpoint_id:"ckpt-1", stage:"design", path:".nexussy/checkpoints/ckpt.json", sha256:"b".repeat(64), created_at:ts };
    case "artifact_updated": return { artifact, action:"updated", anchor:"NEXT_TASK_GROUP_START" };
    case "worker_spawned": case "worker_status": return worker;
    case "worker_task": return { worker_id:"backend-abc123", task_id:"task-abc123", phase_number:1, task_title:"Build API", status:"running" };
    case "worker_stream": return { worker_id:"backend-abc123", stream_kind:"stdout", line:"log", parsed:false, truncated:false };
    case "file_claimed": case "file_released": case "file_lock_waiting": return lock;
    case "git_event": return { action:"merge_completed", worker_id:"backend-abc123", branch_name:"nexussy/backend-abc123", commit_sha:"abc", paths:["src/app.ts"], message:"merged" };
    case "blocker_created": case "blocker_resolved": return blocker;
    case "cost_update": return usage;
    case "pause_state_changed": return { paused:true, reason:"user", requested_by:"api" };
    case "pipeline_error": return error;
    case "done": return { final_status:"passed", summary:"complete", artifacts:[artifact], usage, error:null };
  }
}
