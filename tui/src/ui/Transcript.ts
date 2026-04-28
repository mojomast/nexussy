import { reduceEvent } from "../state";
import type { EventEnvelope, StageName } from "../types";
import { renderArtifactLink } from "./ArtifactLink";
import { renderToolCard } from "./ToolCard";
import { renderWorkerCard } from "./WorkerCard";
import type { ChatUiState, TranscriptItem } from "./types";

function title(s:string): string { return s ? s[0].toUpperCase() + s.slice(1) : s; }

function summarizeRpcLine(workerId:string, line:string): string {
  try {
    const obj = JSON.parse(line);
    if (obj?.method === "agent.event") {
      const params = obj.params ?? {};
      const payload = params.payload ?? {};
      if (payload.delta) return `${workerId} says: ${payload.delta}`;
      if (params.type) return `${workerId} event: ${params.type}`;
    }
    if (obj?.result?.status) return `${workerId} completed RPC: ${obj.result.status}`;
    if (obj?.error?.message) return `${workerId} RPC failed: ${obj.error.message}`;
  } catch {}
  return `${workerId}: ${line}`;
}

function summarizeGitEvent(p:any): string {
  const worker = p.worker_id ? `${p.worker_id} ` : "";
  if (p.action === "repo_initialized") return "initialized repository";
  if (p.action === "worktree_created") return `${worker}created worktree${p.branch_name ? ` ${p.branch_name}` : ""}`;
  if (p.action === "merge_started") return `${worker}started merge${p.branch_name ? ` from ${p.branch_name}` : ""}`;
  if (p.action === "merge_completed") return `${worker}merged successfully`;
  if (p.action === "merge_conflict") return `${worker}hit merge conflict${Array.isArray(p.paths) && p.paths.length ? ` in ${p.paths.join(", ")}` : ""}`;
  if (p.action === "worktree_removed") return `${worker}cleaned up worktree`;
  return p.message ? `${worker}${p.message}` : `${worker}${p.action}`;
}

function summarizeWorkerStatus(p:any): string {
  const task = p.task_title ? ` - ${p.task_title}` : "";
  if (p.status === "finished") return `${p.worker_id} finished${task}`;
  if (p.status === "failed") return `${p.worker_id} failed${task}`;
  if (p.status === "running") return `${p.worker_id} running${task}`;
  return `${p.worker_id} ${p.status}${task}`;
}

export function actionableError(message:string): {text:string; actions:string[]} {
  if (/pi cli|missing pi|no such\/pi|missing Pi CLI/i.test(message)) return { text:"Missing dependency: Pi CLI\n\nnexussy can use its bundled Pi-compatible fallback for local runs, or an external `pi` command for production worker subprocesses.", actions:["/doctor inspect environment", "unset NEXUSSY_DISABLE_BUNDLED_PI to allow bundled fallback", "/new ... start another run"] };
  if (/LiteLLM is not installed/i.test(message)) return { text:"Missing dependency: LiteLLM\n\nThe core Python runtime needs LiteLLM for provider calls.", actions:["./install.sh --non-interactive", "./nexussy.sh doctor", "/new ... retry after install"] };
  return { text:message, actions:["/doctor inspect environment", "/secrets check provider keys", "/new ... start another run"] };
}

export function transcriptItemFromEvent(env:EventEnvelope): TranscriptItem | null {
  const p = env.payload as any;
  if (env.type === "heartbeat" || env.type === "cost_update") return null;
  if (env.type === "run_started") return { kind:"run_started", id:env.event_id, text:`Run started (${p.status ?? "running"})` };
  if (env.type === "stage_transition") {
    const stage = p.to_stage as StageName;
    const status = String(p.to_status ?? "running");
    const icon = status === "passed" ? "✓" : status === "failed" ? "✗" : "●";
    return { kind:"stage", id:env.event_id, stage, status, text:`${icon} ${title(stage)}${p.reason ? ` - ${p.reason}` : ""}` };
  }
  if (env.type === "stage_status") {
    const stage = p.stage as StageName; const status = String(p.status ?? "running"); const icon = status === "passed" ? "✓" : status === "failed" ? "✗" : "●";
    return { kind:"stage", id:env.event_id, stage, status, text:`${icon} ${title(stage)} ${status}` };
  }
  if (env.type === "content_delta") return { kind:"assistant", id:env.event_id, role:p.role ?? "assistant", text:p.delta ?? "" };
  if (env.type === "tool_call") return { kind:"tool", id:p.call_id ?? env.event_id, title:`${p.tool_name}`, text:JSON.stringify(p.arguments ?? {}), collapsed:true };
  if (env.type === "tool_progress") return { kind:"tool", id:p.call_id ?? env.event_id, title:"tool progress", text:p.message ?? "", collapsed:false };
  if (env.type === "tool_output") return { kind:"tool", id:p.call_id ?? env.event_id, title:p.success === false ? "tool failed" : "tool output", text:p.result_text ?? p.error?.message ?? "", collapsed:p.success !== false };
  if (env.type === "worker_spawned") return { kind:"worker", id:env.event_id, worker_id:p.worker_id, text:`${p.role} worker ${p.worker_id} spawned` };
  if (env.type === "worker_status") return { kind:"worker", id:env.event_id, worker_id:p.worker_id, text:summarizeWorkerStatus(p) };
  if (env.type === "worker_task") return { kind:"worker", id:env.event_id, worker_id:p.worker_id, text:`${p.worker_id} ${p.status}: ${p.task_title}` };
  if (env.type === "worker_stream") return { kind:"worker", id:env.event_id, worker_id:p.worker_id, text:p.stream_kind === "rpc" ? summarizeRpcLine(p.worker_id, p.line ?? "") : `${p.worker_id} ${p.stream_kind}: ${p.line}` };
  if (env.type === "file_claimed") return { kind:"file", id:env.event_id, text:`claimed ${p.path} by ${p.worker_id}` };
  if (env.type === "file_released") return { kind:"file", id:env.event_id, text:`released ${p.path} by ${p.worker_id}` };
  if (env.type === "file_lock_waiting") return { kind:"file", id:env.event_id, text:`waiting for ${p.path} by ${p.worker_id}` };
  if (env.type === "artifact_updated") return { kind:"artifact", id:env.event_id, artifact:p.artifact, text:`${p.action} ${p.artifact?.path}` };
  if (env.type === "git_event") return { kind:"file", id:env.event_id, text:summarizeGitEvent(p) };
  if (env.type === "checkpoint_saved") return { kind:"meta", id:env.event_id, text:`checkpoint ${p.stage}: ${p.path}` };
  if (env.type === "pipeline_error") { const e = actionableError(p.message ?? p.error_code); return { kind:"error", id:env.event_id, text:e.text, actions:e.actions }; }
  if (env.type === "done") { const err = p.error ? actionableError(p.error.message ?? p.error.error_code) : null; if (err) return { kind:"error", id:env.event_id, text:err.text, actions:err.actions }; return { kind:"done", id:env.event_id, status:p.final_status, text:p.summary ?? "done" }; }
  return { kind:"meta", id:env.event_id, text:`${env.type}` };
}

export function reduceChatEvent(state:ChatUiState, env:EventEnvelope): ChatUiState {
  const app = reduceEvent(state.app, env);
  const item = transcriptItemFromEvent(env);
  return { ...state, app, rawEvents:[...state.rawEvents, env], transcript:item ? [...state.transcript, item] : state.transcript, connection:{ connected:true, lastEventId:env.event_id } };
}

export function renderTranscriptItem(item:TranscriptItem): string[] {
  if (item.kind === "tool") return renderToolCard(item);
  if (item.kind === "worker") return [renderWorkerCard(item)];
  if (item.kind === "artifact") return [renderArtifactLink(item)];
  if (item.kind === "file") return [`  └─ ${item.text}`];
  if (item.kind === "error") return [`✗ ${item.text}`, "", "Next actions:", ...item.actions.map(a => `  ${a}`)];
  if (item.kind === "done") return [item.status === "passed" ? "✓ Done" : `✗ Done (${item.status})`, item.text].filter(Boolean);
  if (item.kind === "meta") return [`  ${item.text}`];
  return [item.text];
}

export function renderTranscript(items:TranscriptItem[]): string[] {
  return items.flatMap(item => [...renderTranscriptItem(item), ""]).slice(0, -1);
}
