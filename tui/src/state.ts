import type { ArtifactRef, Blocker, EventEnvelope, FileLock, GitEventPayload, StageName, StageRunStatus, TokenUsage, Worker } from "./types";

export interface LogRow { id:string; kind:"content"|"tool"|"system"; title:string; text:string; collapsed:boolean; }
export interface TuiState { runId?:string; sessionId?:string; stages:Record<StageName,StageRunStatus>; workers:Record<string,Worker>; locks:FileLock[]; logs:LogRow[]; devplan:string[]; usage:TokenUsage; paused:boolean; lastEventId?:string; gitEvents:GitEventPayload[]; blockers:Record<string,Blocker>; artifacts:ArtifactRef[]; finalStatus?:string; connectionError?:string; authError?:string; }
export const STAGES: StageName[] = ["interview","design","validate","plan","review","develop"];
export const zeroUsage: TokenUsage = { input_tokens:0, output_tokens:0, cache_read_tokens:0, cache_write_tokens:0, total_tokens:0, cost_usd:0 };
export function createState(): TuiState { return { stages:Object.fromEntries(STAGES.map(s=>[s,"pending"])) as Record<StageName,StageRunStatus>, workers:{}, locks:[], logs:[], devplan:[], usage:{...zeroUsage}, paused:false, gitEvents:[], blockers:{}, artifacts:[] }; }
export function reduceConnectionError(state:TuiState, error:unknown): TuiState { const message = error instanceof Error ? error.message : String(error); return { ...state, connectionError:message, authError:/unauthorized|401/i.test(message) ? message : state.authError, logs:[...state.logs,{id:`connection-${state.logs.length+1}`,kind:"system",title:"connection_error",text:message,collapsed:false}] }; }
export function reduceEvent(state:TuiState, env:EventEnvelope): TuiState {
  const s:TuiState = { ...state, stages:{...state.stages}, workers:{...state.workers}, locks:[...state.locks], logs:[...state.logs], devplan:[...state.devplan], usage:{...state.usage}, gitEvents:[...state.gitEvents], blockers:{...state.blockers}, artifacts:[...state.artifacts], lastEventId:env.event_id, runId:env.run_id, sessionId:env.session_id, connectionError:undefined, authError:undefined };
  const p = env.payload as any;
  if (env.type === "run_started") { if(p.current_stage) s.stages[p.current_stage as StageName]="running"; s.usage=p.usage??s.usage; s.logs.push({id:env.event_id,kind:"system",title:"run_started",text:p.status??"running",collapsed:false}); }
  else if (env.type === "heartbeat") s.logs.push({id:env.event_id,kind:"system",title:"heartbeat",text:p.server_status,collapsed:true});
  else if (env.type === "stage_transition") { s.stages[p.to_stage as StageName]=p.to_status; s.logs.push({id:env.event_id,kind:"system",title:"stage_transition",text:`${p.from_stage??"start"} → ${p.to_stage}: ${p.to_status} (${p.reason})`,collapsed:false}); }
  else if (env.type === "stage_status") s.stages[p.stage as StageName]=p.status;
  else if (env.type === "content_delta") s.logs.push({id:env.event_id,kind:"content",title:`${p.stage}${p.worker_id?` ${p.worker_id}`:""}`,text:p.delta,collapsed:false});
  else if (env.type === "tool_call") s.logs.push({id:p.call_id??env.event_id,kind:"tool",title:`${p.tool_name}`,text:JSON.stringify(p.arguments??{}),collapsed:true});
  else if (env.type === "tool_output" || env.type === "tool_progress") { const row=s.logs.find(r=>r.id===p.call_id); if(row) row.text += `\n${p.result_text??p.message??""}`; }
  else if (env.type === "checkpoint_saved") s.logs.push({id:env.event_id,kind:"system",title:"checkpoint_saved",text:`${p.stage} ${p.path}`,collapsed:true});
  else if (env.type === "worker_spawned" || env.type === "worker_status") s.workers[p.worker_id]=p as Worker;
  else if (env.type === "worker_task") { const w=s.workers[p.worker_id]; if(w){ s.workers[p.worker_id]={...w, task_id:p.task_id, task_title:p.task_title, status:p.status === "running" ? "running" : w.status}; } }
  else if (env.type === "worker_stream") s.logs.push({id:env.event_id,kind:"system",title:`${p.worker_id} ${p.stream_kind}`,text:p.line,collapsed:Boolean(p.truncated)});
  else if (env.type === "file_claimed" || env.type === "file_released" || env.type === "file_lock_waiting") s.locks=[...s.locks.filter(l=>l.path!==p.path||l.worker_id!==p.worker_id), p as FileLock];
  else if (env.type === "artifact_updated") { s.artifacts=[...s.artifacts.filter(a=>a.kind!==p.artifact.kind || a.path!==p.artifact.path), p.artifact]; if (p.artifact?.kind === "devplan") s.devplan.push(`${p.action}: ${p.artifact.path}${p.anchor?`#${p.anchor}`:""}`); }
  else if (env.type === "git_event") s.gitEvents.push(p as GitEventPayload);
  else if (env.type === "blocker_created" || env.type === "blocker_resolved") s.blockers[p.blocker_id]=p as Blocker;
  else if (env.type === "cost_update") s.usage=p;
  else if (env.type === "pause_state_changed") s.paused=Boolean(p.paused);
  else if (env.type === "pipeline_error") s.logs.push({id:env.event_id,kind:"system",title:p.error_code,text:p.message,collapsed:false});
  else if (env.type === "done") { s.usage=p.usage??s.usage; s.finalStatus=p.final_status; if (Array.isArray(p.artifacts)) s.artifacts=p.artifacts; if (p.error) s.logs.push({id:`${env.event_id}-error`,kind:"system",title:p.error.error_code,text:p.error.message,collapsed:false}); s.logs.push({id:env.event_id,kind:"system",title:"done",text:p.summary,collapsed:false}); }
  return s;
}
export function toggleToolRow(state:TuiState, id:string): TuiState { return { ...state, logs: state.logs.map(r => r.id===id && r.kind==="tool" ? {...r, collapsed:!r.collapsed} : r) }; }
