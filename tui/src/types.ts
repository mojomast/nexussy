export type StageName = "interview"|"design"|"validate"|"plan"|"review"|"develop";
export type StageRunStatus = "pending"|"running"|"passed"|"failed"|"skipped"|"blocked"|"paused"|"retrying";
export type RunStatus = "created"|"running"|"paused"|"passed"|"failed"|"cancelled"|"blocked";
export type WorkerRole = "orchestrator"|"backend"|"frontend"|"qa"|"devops"|"writer"|"analyst";
export type WorkerStatus = "starting"|"idle"|"assigned"|"running"|"paused"|"blocked"|"finished"|"failed"|"stopped";
export type WorkerTaskStatus = "queued"|"assigned"|"running"|"passed"|"failed"|"skipped"|"blocked";
export type ToolName = "spawn_worker"|"assign_task"|"get_swarm_state"|"read_file"|"write_file"|"edit_file"|"bash"|"list_files"|"search_code"|"claim_file"|"release_file"|"add_context";
export type ArtifactKind = "interview"|"complexity_profile"|"design_draft"|"validated_design"|"validation_report"|"devplan"|"handoff"|"phase"|"review_report"|"develop_report"|"merge_report"|"changed_files";
export type LockStatus = "claimed"|"released"|"waiting"|"expired";
export type GitEventAction = "repo_initialized"|"worktree_created"|"worktree_removed"|"merge_started"|"merge_completed"|"merge_conflict"|"merge_aborted"|"artifact_extracted";
export type ErrorCode = "bad_request"|"unauthorized"|"forbidden"|"not_found"|"conflict"|"validation_error"|"stage_not_ready"|"stage_failed"|"run_not_active"|"worker_not_found"|"worker_unavailable"|"file_locked"|"path_rejected"|"provider_unavailable"|"model_unavailable"|"rate_limited"|"subprocess_failed"|"sse_client_slow"|"internal_error";
export type SSEEventType = "heartbeat"|"run_started"|"content_delta"|"tool_call"|"tool_output"|"tool_progress"|"stage_transition"|"stage_status"|"checkpoint_saved"|"artifact_updated"|"worker_spawned"|"worker_status"|"worker_task"|"worker_stream"|"file_claimed"|"file_released"|"file_lock_waiting"|"git_event"|"blocker_created"|"blocker_resolved"|"cost_update"|"pause_state_changed"|"pipeline_error"|"done";
export const EVENT_TYPES: readonly SSEEventType[] = ["heartbeat","run_started","content_delta","tool_call","tool_output","tool_progress","stage_transition","stage_status","checkpoint_saved","artifact_updated","worker_spawned","worker_status","worker_task","worker_stream","file_claimed","file_released","file_lock_waiting","git_event","blocker_created","blocker_resolved","cost_update","pause_state_changed","pipeline_error","done"] as const;
export type JsonValue = null|boolean|number|string|JsonValue[]|{[k:string]:JsonValue};
export interface TokenUsage { input_tokens:number; output_tokens:number; cache_read_tokens?:number; cache_write_tokens?:number; total_tokens:number; cost_usd:number; provider?:string|null; model?:string|null; }
export interface ErrorResponse { ok:false; error_code:ErrorCode; message:string; details?:Record<string,JsonValue>; request_id:string; retryable:boolean; }
export interface ArtifactRef { kind:ArtifactKind; path:string; sha256:string; bytes:number; updated_at:string; phase_number?:number|null; }
export interface ToolDisplay { kind:"text"|"json"|"diff"|"table"|"tree"|"markdown"; title?:string|null; text?:string|null; language?:string|null; json?:JsonValue; truncated:boolean; }
export interface RunSummary { run_id:string; session_id:string; status:RunStatus; current_stage?:StageName|null; started_at?:string|null; finished_at?:string|null; usage:TokenUsage; }
export interface StageStatusSchema { stage:StageName; status:StageRunStatus; attempt:number; max_attempts:number; started_at?:string|null; finished_at?:string|null; input_artifacts:ArtifactRef[]; output_artifacts:ArtifactRef[]; error?:ErrorResponse|null; }
export interface Worker { worker_id:string; run_id:string; role:WorkerRole; status:WorkerStatus; task_id?:string|null; task_title?:string|null; worktree_path:string; branch_name:string; pid?:number|null; model:string; usage:TokenUsage; created_at:string; updated_at:string; last_error?:ErrorResponse|null; }
export interface FileLock { path:string; worker_id:string; run_id:string; status:LockStatus; claimed_at:string; expires_at:string; }
export interface Blocker { blocker_id:string; run_id:string; worker_id?:string|null; stage:StageName; severity:"warning"|"blocker"; message:string; resolved:boolean; created_at:string; resolved_at?:string|null; }
export interface HeartbeatPayload { ts:string; server_status:string; }
export interface ContentDeltaPayload { message_id:string; stage:StageName; worker_id?:string|null; role:string; delta:string; final?:boolean; }
export interface ToolCallPayload { call_id:string; stage:StageName; worker_id?:string|null; tool_name:ToolName; arguments?:Record<string,JsonValue>; }
export interface ToolOutputPayload { call_id:string; stage:StageName; worker_id?:string|null; success:boolean; result_text?:string; display?:ToolDisplay|null; error?:ErrorResponse|null; }
export interface ToolProgressPayload { call_id:string; stage:StageName; worker_id?:string|null; message:string; percent?:number|null; }
export interface StageTransitionPayload { from_stage?:StageName|null; to_stage:StageName; from_status?:StageRunStatus|null; to_status:StageRunStatus; reason:string; }
export interface CheckpointPayload { checkpoint_id:string; stage:StageName; path:string; sha256:string; created_at:string; }
export interface ArtifactUpdatedPayload { artifact:ArtifactRef; action:"created"|"updated"|"deleted"; anchor?:string|null; }
export interface WorkerTaskPayload { worker_id:string; task_id:string; phase_number?:number|null; task_title:string; status:WorkerTaskStatus; }
export interface WorkerStreamPayload { worker_id:string; stream_kind:"rpc"|"stdout"|"stderr"; line:string; parsed?:boolean; truncated?:boolean; }
export interface GitEventPayload { action:GitEventAction; worker_id?:string|null; branch_name?:string|null; commit_sha?:string|null; paths?:string[]; message:string; }
export interface PausePayload { paused:boolean; reason:string; requested_by?:string; }
export interface DonePayload { final_status:RunStatus; summary:string; artifacts?:ArtifactRef[]; usage:TokenUsage; error?:ErrorResponse|null; }
export type SecretSource = "keyring"|"env"|"config";
export interface SecretSummary { name:string; source:SecretSource; configured:boolean; updated_at?:string|null; }
export type EventPayloadMap = {
  heartbeat: HeartbeatPayload; run_started: RunSummary; content_delta: ContentDeltaPayload; tool_call: ToolCallPayload; tool_output: ToolOutputPayload; tool_progress: ToolProgressPayload; stage_transition: StageTransitionPayload; stage_status: StageStatusSchema; checkpoint_saved: CheckpointPayload; artifact_updated: ArtifactUpdatedPayload; worker_spawned: Worker; worker_status: Worker; worker_task: WorkerTaskPayload; worker_stream: WorkerStreamPayload; file_claimed: FileLock; file_released: FileLock; file_lock_waiting: FileLock; git_event: GitEventPayload; blocker_created: Blocker; blocker_resolved: Blocker; cost_update: TokenUsage; pause_state_changed: PausePayload; pipeline_error: ErrorResponse; done: DonePayload;
};
export type TypedEventEnvelope<K extends SSEEventType> = { event_id:string; sequence:number; contract_version:"1.0"; type:K; session_id:string; run_id:string; ts:string; source:"core"|"worker"|"tui"|"web"; payload:EventPayloadMap[K]; };
export type EventEnvelope = { [K in SSEEventType]: TypedEventEnvelope<K> }[SSEEventType];
export interface PipelineStatusResponse { ok:true; run:RunSummary; stages:StageStatusSchema[]; workers:Worker[]; paused:boolean; blockers:Blocker[]; }
export interface RunStartResponse { ok:true; session_id:string; run_id:string; status:RunStatus; stream_url:string; status_url:string; }
