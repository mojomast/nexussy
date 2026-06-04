import { reduceEvent } from "../state";
import { buildGateSummary } from "../lib/gateSummary";
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
  const clean = sanitizeErrorText(message);
  if (/openrouter/i.test(clean) && /key limit|limit exceeded|quota|credit|rate.?limit|insufficient|\b403\b|\b429\b/i.test(clean)) return { text:"OpenRouter provider limit reached. Your OpenRouter key appears to be quota-limited, rate-limited, or out of credits.\n\nThe raw provider traceback was omitted; check core logs if you need the full stack.", actions:["/secrets check provider keys", "Update OPENROUTER_API_KEY or add OpenRouter credits", "/models choose another configured provider", "/new ... retry after provider is fixed"] };
  if (/unable to connect|failed to fetch|ECONNREFUSED|core did not become healthy|SSE failed/i.test(clean)) return { text:`Core connection problem: ${clean}\n\nThe TUI talks to nexussy core through the local API. Direct \`bun run start\` now tries to start core automatically when NEXUSSY_CORE_URL is not set.`, actions:["Check ./nexussy.sh status", "Start core manually with ./nexussy.sh start", "If using a remote core, set NEXUSSY_CORE_URL", "/setup provider menu"] };
  if (/pi cli|missing pi|no such\/pi|missing Pi CLI/i.test(clean)) return { text:"Missing dependency: Pi CLI\n\nnexussy can use its bundled Pi-compatible fallback for local runs, or an external `pi` command for production worker subprocesses.", actions:["/doctor inspect environment", "unset NEXUSSY_DISABLE_BUNDLED_PI to allow bundled fallback", "/new ... start another run"] };
  if (/LiteLLM is not installed/i.test(clean)) return { text:"Missing dependency: LiteLLM\n\nThe core Python runtime needs LiteLLM for provider calls.", actions:["./install.sh --non-interactive", "./nexussy.sh doctor", "/new ... retry after install"] };
  if (/Traceback \(most recent call last\)|\n\s*File "/.test(clean)) return { text:`${firstMeaningfulErrorLine(clean)}\n\nTraceback omitted. Check core logs for full details.`, actions:["/doctor inspect environment", "/secrets check provider keys", "/models choose another provider", "/new ... retry after fixing the error"] };
  return { text:truncateError(clean), actions:["/doctor inspect environment", "/secrets check provider keys", "/new ... start another run"] };
}

export function sanitizeErrorText(message:string): string {
  return message
    .replace(/\x1b\[[0-9;]*[A-Za-z]/g, "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "")
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, "[redacted-key]")
    .replace(/sk-or-v1-[A-Za-z0-9_-]+/g, "[redacted-openrouter-key]")
    .replace(/(OPENROUTER_API_KEY|AGENTROUTER_API_KEY|AGENT_ROUTER_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY)=\S+/g, "$1=[redacted]")
    .replace(/\/keys\/[A-Za-z0-9]{16,}/g, "/keys/[redacted-key-id]");
}

function firstMeaningfulErrorLine(message:string): string {
  const lines = message.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  return lines.reverse().find(line => /error|exception|failed|limit|unauthorized|forbidden/i.test(line) && !line.startsWith("File ")) ?? lines[0] ?? "Pipeline failed";
}

function truncateError(message:string): string {
  const lines = message.split(/\r?\n/).map(line => line.trim()).filter(Boolean).slice(0, 6);
  const text = lines.join("\n");
  return text.length > 1000 ? `${text.slice(0, 1000)}...` : text;
}

export function transcriptItemFromEvent(env:EventEnvelope, activeStage?:StageName): TranscriptItem | null {
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
  if (env.type === "pause_state_changed") { const stage=(p.stage ?? activeStage ?? "plan") as StageName; return { kind:"stage", id:env.event_id, stage, status:p.paused ? "paused" : "running", text:p.paused ? `Ⅱ ${title(stage)} paused - ${p.reason ?? "user"}` : `● ${title(stage)} resumed - ${p.reason ?? "user"}` }; }
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
  if (state.rawEvents.some(event => event.event_id === env.event_id)) return state;
  const activeStage = activeStageFromState(state);
  const app = reduceEvent(state.app, env);
  const item = transcriptItemFromEvent(env, activeStage);
  const skippedGate = env.type === "stage_transition" && Boolean(state.pendingGate);
  const transcriptWithItem = item ? [...state.transcript, item] : state.transcript;
  const transcript = skippedGate ? [...transcriptWithItem, { kind:"meta" as const, id:`gate-skipped-${env.event_id}`, text:"gate_skipped: transition suppressed because a stage gate is already pending" }] : transcriptWithItem;
  const pendingGate = gateFromTransition(state, env, transcript) ?? state.pendingGate;
  return { ...state, app, pendingGate, pendingInterview:state.pendingInterview, rawEvents:[...state.rawEvents, env], transcript, connection:{ connected:true, lastEventId:env.event_id } };
}

export function renderTranscriptItem(item:TranscriptItem): string[] {
  if (item.kind === "tool") return renderToolCard(item);
  if (item.kind === "worker") return [renderWorkerCard(item)];
  if (item.kind === "artifact") return [renderArtifactLink(item)];
  if (item.kind === "file") return [`  └─ ${item.text}`];
  if (item.kind === "stage_control") return [`${item.action.toUpperCase()} ${title(item.stage)} - ${item.text}`];
  if (item.kind === "error") return [`✗ ${item.text}`, "", "Next actions:", ...item.actions.map(a => `  ${a}`)];
  if (item.kind === "done") return [item.status === "passed" ? "✓ Done" : `✗ Done (${item.status})`, item.text].filter(Boolean);
  if (item.kind === "meta") return [`  ${item.text}`];
  return [item.text];
}

export function renderTranscript(items:TranscriptItem[], stage?:StageName): string[] {
  const filtered = stage ? items.filter(item => itemStage(item) === stage || item.kind === "assistant" || item.kind === "error") : items;
  return filtered.flatMap(item => [...renderTranscriptItem(item), ""]).slice(0, -1);
}

function itemStage(item:TranscriptItem): StageName|undefined {
  if (item.kind === "stage" || item.kind === "stage_control") return item.stage;
  if (item.kind === "artifact") return item.artifact.kind === "devplan" ? "plan" : undefined;
  return undefined;
}

function activeStageFromState(state:ChatUiState): StageName|undefined {
  return Object.entries(state.app.stages).find(([, status]) => status === "running" || status === "paused")?.[0] as StageName|undefined;
}

function gateFromTransition(state:ChatUiState, env:EventEnvelope, transcript:TranscriptItem[]): ChatUiState["pendingGate"]|undefined {
  if (state.pendingGate) return undefined;
  if (env.type !== "stage_transition" || state.app.config.gateStages === false) return undefined;
  const p = env.payload as any;
  const from = p.from_stage as StageName|undefined|null;
  const to = p.to_stage as StageName|undefined;
  if (!from || !to || isRetry(from, to, p)) return undefined;
  return { completedStage:from, nextStage:to, summary:buildGateSummary(from, transcript), autoAdvance:false };
}

function isRetry(from:StageName, to:StageName, payload:any): boolean {
  return /retry/i.test(payload.reason ?? "") || payload.to_status === "retrying" || (from === "validate" && to === "design") || (from === "review" && to === "plan");
}
