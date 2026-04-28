import { computeBudget, defaultContextWindowSize, type ContextBudget } from "./lib/contextBudget";
import type { ArtifactRef, Blocker, EventEnvelope, FileLock, GitEventPayload, PipelineStatusResponse, SecretSummary, StageName, StageRunStatus, TokenUsage, Worker } from "./types";

export interface LogRow { id:string; kind:"content"|"tool"|"system"; title:string; text:string; collapsed:boolean; }
export interface TuiConfig { contextWindowSize?:number; model?:string; projectName?:string; }
export interface HandoffPrompt { trigger:"token_warning"|"token_critical"|"subagent_finished"|"user_command"|"paused"; blocking:boolean; workerId?:string; }
export interface TuiState { runId?:string; sessionId?:string; stages:Record<StageName,StageRunStatus>; checkpoints:Partial<Record<StageName,true>>; workers:Record<string,Worker>; locks:FileLock[]; logs:LogRow[]; devplan:string[]; usage:TokenUsage; contextBudget:ContextBudget; config:TuiConfig; paused:boolean; handoffPrompt?:HandoffPrompt; lastEventId?:string; gitEvents:GitEventPayload[]; blockers:Record<string,Blocker>; artifacts:ArtifactRef[]; secrets:SecretSummary[]; secretNotice?:string; finalStatus?:string; connectionError?:string; authError?:string; }
export const STAGES: StageName[] = ["interview","design","validate","plan","review","develop"];
export const zeroUsage: TokenUsage = { input_tokens:0, output_tokens:0, cache_read_tokens:0, cache_write_tokens:0, total_tokens:0, cost_usd:0 };
export function createState(config:TuiConfig = {}): TuiState { const usage={...zeroUsage, model:config.model}; return { stages:Object.fromEntries(STAGES.map(s=>[s,"pending"])) as Record<StageName,StageRunStatus>, checkpoints:{}, workers:{}, locks:[], logs:[], devplan:[], usage, contextBudget:budgetFor(usage, config), config, paused:false, gitEvents:[], blockers:{}, artifacts:[], secrets:[] }; }
export function reduceSecrets(state:TuiState, secrets:SecretSummary[], notice?:string): TuiState { return { ...state, secrets:[...secrets], secretNotice:notice }; }
export function reduceConnectionError(state:TuiState, error:unknown): TuiState { const message = error instanceof Error ? error.message : String(error); return { ...state, connectionError:message, authError:/unauthorized|401/i.test(message) ? message : state.authError, logs:[...state.logs,{id:`connection-${state.logs.length+1}`,kind:"system",title:"connection_error",text:message,collapsed:false}] }; }
export function reduceStatusSnapshot(state:TuiState, snapshot:PipelineStatusResponse): TuiState {
  const stages = { ...state.stages };
  for (const stage of snapshot.stages ?? []) stages[stage.stage] = stage.status;
  const workers = Object.fromEntries((snapshot.workers ?? []).map(worker => [worker.worker_id, worker])) as Record<string,Worker>;
  const artifacts = (snapshot.stages ?? []).flatMap(stage => [...(stage.input_artifacts ?? []), ...(stage.output_artifacts ?? [])]);
  return { ...state, runId:snapshot.run.run_id, sessionId:snapshot.run.session_id, stages, workers:{ ...state.workers, ...workers }, paused:snapshot.paused, blockers:Object.fromEntries((snapshot.blockers ?? []).map(blocker => [blocker.blocker_id, blocker])) as Record<string,Blocker>, usage:snapshot.run.usage ?? state.usage, contextBudget:budgetFor(snapshot.run.usage ?? state.usage, state.config), finalStatus:snapshot.run.status === "running" || snapshot.run.status === "created" ? undefined : snapshot.run.status, artifacts:artifacts.length ? mergeArtifacts(state.artifacts, artifacts) : state.artifacts };
}
export function reduceWorkersSnapshot(state:TuiState, workers:Worker[]): TuiState { return { ...state, workers:{ ...state.workers, ...Object.fromEntries(workers.map(worker => [worker.worker_id, worker])) as Record<string,Worker> } }; }
export function reduceArtifactsSnapshot(state:TuiState, response:unknown): TuiState { const artifacts = extractArtifacts(response); return artifacts.length ? { ...state, artifacts:mergeArtifacts(state.artifacts, artifacts) } : state; }
export function reduceEvent(state:TuiState, env:EventEnvelope): TuiState {
  const s:TuiState = { ...state, stages:{...state.stages}, checkpoints:{...state.checkpoints}, workers:{...state.workers}, locks:[...state.locks], logs:[...state.logs], devplan:[...state.devplan], usage:{...state.usage}, contextBudget:{...state.contextBudget}, gitEvents:[...state.gitEvents], blockers:{...state.blockers}, artifacts:[...state.artifacts], lastEventId:env.event_id, runId:env.run_id, sessionId:env.session_id, connectionError:undefined, authError:undefined };
  const p = env.payload as any;
  if (env.type === "run_started") { if(p.current_stage) s.stages[p.current_stage as StageName]="running"; s.usage=p.usage??s.usage; s.contextBudget=budgetFor(s.usage,s.config); s.logs.push({id:env.event_id,kind:"system",title:"run_started",text:p.status??"running",collapsed:false}); }
  else if (env.type === "heartbeat") s.logs.push({id:env.event_id,kind:"system",title:"heartbeat",text:p.server_status,collapsed:true});
  else if (env.type === "stage_transition") { const from=p.from_stage as StageName|undefined|null; const to=p.to_stage as StageName; if(from) s.stages[from]=isRetryTransition(from,to,p.reason)?"retrying":(p.from_status??"passed"); s.stages[to]="running"; s.logs.push({id:env.event_id,kind:"system",title:"stage_transition",text:`${from??"start"} → ${to}: running (${p.reason})`,collapsed:false}); }
  else if (env.type === "stage_status") s.stages[p.stage as StageName]=p.status;
  else if (env.type === "content_delta") s.logs.push({id:env.event_id,kind:"content",title:`${p.stage}${p.worker_id?` ${p.worker_id}`:""}`,text:p.delta,collapsed:false});
  else if (env.type === "tool_call") s.logs.push({id:p.call_id??env.event_id,kind:"tool",title:`${p.tool_name}`,text:JSON.stringify(p.arguments??{}),collapsed:true});
  else if (env.type === "tool_output" || env.type === "tool_progress") { const row=s.logs.find(r=>r.id===p.call_id); if(row) row.text += `\n${p.result_text??p.message??""}`; }
  else if (env.type === "checkpoint_saved") { s.checkpoints[p.stage as StageName]=true; s.logs.push({id:env.event_id,kind:"system",title:"checkpoint_saved",text:`${p.stage} ${p.path}`,collapsed:true}); }
  else if (env.type === "worker_spawned" || env.type === "worker_status") { s.workers[p.worker_id]=p as Worker; if(env.type === "worker_status" && p.status === "finished") s.handoffPrompt={trigger:"subagent_finished",blocking:false,workerId:p.worker_id}; }
  else if (env.type === "worker_task") { const w=s.workers[p.worker_id]; if(w){ s.workers[p.worker_id]={...w, task_id:p.task_id, task_title:p.task_title, status:p.status === "running" ? "running" : w.status}; } }
  else if (env.type === "worker_stream") s.logs.push({id:env.event_id,kind:"system",title:`${p.worker_id} ${p.stream_kind}`,text:p.line,collapsed:Boolean(p.truncated)});
  else if (env.type === "file_claimed" || env.type === "file_released" || env.type === "file_lock_waiting") s.locks=[...s.locks.filter(l=>l.path!==p.path||l.worker_id!==p.worker_id), p as FileLock];
  else if (env.type === "artifact_updated") { s.artifacts=[...s.artifacts.filter(a=>a.kind!==p.artifact.kind || a.path!==p.artifact.path), p.artifact]; if (p.artifact?.kind === "devplan") s.devplan.push(`${p.action}: ${p.artifact.path}${p.anchor?`#${p.anchor}`:""}`); }
  else if (env.type === "git_event") s.gitEvents.push(p as GitEventPayload);
  else if (env.type === "blocker_created" || env.type === "blocker_resolved") s.blockers[p.blocker_id]=p as Blocker;
  else if (env.type === "cost_update") { s.usage=p; s.contextBudget=budgetFor(s.usage,s.config); if(s.contextBudget.atLimit) s.handoffPrompt={trigger:"token_critical",blocking:true}; else if(s.contextBudget.nearLimit) s.handoffPrompt={trigger:"token_warning",blocking:false}; }
  else if (env.type === "pause_state_changed") { s.paused=Boolean(p.paused); if(s.paused) s.handoffPrompt={trigger:"paused",blocking:false}; }
  else if (env.type === "pipeline_error") s.logs.push({id:env.event_id,kind:"system",title:p.error_code,text:p.message,collapsed:false});
  else if (env.type === "done") { s.usage=p.usage??s.usage; s.contextBudget=budgetFor(s.usage,s.config); s.finalStatus=p.final_status; if (Array.isArray(p.artifacts)) s.artifacts=p.artifacts; if (p.error) s.logs.push({id:`${env.event_id}-error`,kind:"system",title:p.error.error_code,text:p.error.message,collapsed:false}); s.logs.push({id:env.event_id,kind:"system",title:"done",text:p.summary,collapsed:false}); }
  return s;
}
export function toggleToolRow(state:TuiState, id:string): TuiState { return { ...state, logs: state.logs.map(r => r.id===id && r.kind==="tool" ? {...r, collapsed:!r.collapsed} : r) }; }
export function triggerHandoff(state:TuiState, trigger:HandoffPrompt["trigger"]="user_command"): TuiState { return { ...state, handoffPrompt:{trigger,blocking:trigger==="token_critical"} }; }
function budgetFor(usage:TokenUsage, config:TuiConfig): ContextBudget { return computeBudget(usage, config.contextWindowSize ?? defaultContextWindowSize(config.model ?? usage.model ?? "")); }
function isRetryTransition(from:StageName|undefined|null, to:StageName, reason?:string): boolean { return /retry/i.test(reason ?? "") || (from === "validate" && to === "design") || (from === "review" && to === "plan"); }
function mergeArtifacts(current:ArtifactRef[], next:ArtifactRef[]): ArtifactRef[] { return [...current.filter(a => !next.some(b => b.kind === a.kind && b.path === a.path)), ...next]; }
function extractArtifacts(response:unknown): ArtifactRef[] {
  if (Array.isArray(response)) return response.filter(isArtifactRef);
  if (response && typeof response === "object") {
    const obj = response as Record<string,unknown>;
    if (Array.isArray(obj.artifacts)) return obj.artifacts.filter(isArtifactRef);
  }
  return [];
}
function isArtifactRef(value:unknown): value is ArtifactRef { return Boolean(value && typeof value === "object" && typeof (value as ArtifactRef).kind === "string" && typeof (value as ArtifactRef).path === "string"); }
