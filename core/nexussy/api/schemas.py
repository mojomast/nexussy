from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nexussy.security import sanitize_relative_path
from nexussy.session import now_utc


def new_id() -> str:
    return str(uuid4())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank_strings(cls, value):
        if cls.__name__.endswith("Request") and isinstance(value, str) and value.strip() == "":
            raise ValueError("blank strings are not allowed")
        return value

    @field_validator("*", mode="after")
    @classmethod
    def require_utc_datetimes(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware UTC")
        if isinstance(value, datetime) and value.utcoffset() != timedelta(0):
            raise ValueError("datetime must be UTC")
        return value


class StageName(str, Enum):
    interview="interview"; design="design"; validate="validate"; plan="plan"; review="review"; develop="develop"
class StageRunStatus(str, Enum):
    pending="pending"; running="running"; passed="passed"; failed="failed"; skipped="skipped"; blocked="blocked"; paused="paused"; retrying="retrying"
class RunStatus(str, Enum):
    created="created"; running="running"; paused="paused"; passed="passed"; failed="failed"; cancelled="cancelled"; blocked="blocked"
class ComplexityLevel(str, Enum):
    minimal="minimal"; standard="standard"; detailed="detailed"
class WorkerRole(str, Enum):
    orchestrator="orchestrator"; backend="backend"; frontend="frontend"; qa="qa"; devops="devops"; writer="writer"; analyst="analyst"
class WorkerStatus(str, Enum):
    starting="starting"; idle="idle"; assigned="assigned"; running="running"; paused="paused"; blocked="blocked"; finished="finished"; failed="failed"; stopped="stopped"
class WorkerTaskStatus(str, Enum):
    queued="queued"; assigned="assigned"; running="running"; passed="passed"; failed="failed"; skipped="skipped"; blocked="blocked"
class ArtifactKind(str, Enum):
    interview="interview"; complexity_profile="complexity_profile"; design_draft="design_draft"; validated_design="validated_design"; validation_report="validation_report"; devplan="devplan"; handoff="handoff"; phase="phase"; review_report="review_report"; develop_report="develop_report"; merge_report="merge_report"; changed_files="changed_files"
class ToolName(str, Enum):
    spawn_worker="spawn_worker"; assign_task="assign_task"; get_swarm_state="get_swarm_state"; read_file="read_file"; write_file="write_file"; edit_file="edit_file"; bash="bash"; list_files="list_files"; search_code="search_code"; claim_file="claim_file"; release_file="release_file"; add_context="add_context"
class LockStatus(str, Enum):
    claimed="claimed"; released="released"; waiting="waiting"; expired="expired"
class GitEventAction(str, Enum):
    repo_initialized="repo_initialized"; worktree_created="worktree_created"; worktree_removed="worktree_removed"; merge_started="merge_started"; merge_completed="merge_completed"; merge_conflict="merge_conflict"; merge_aborted="merge_aborted"; artifact_extracted="artifact_extracted"
class ErrorCode(str, Enum):
    bad_request="bad_request"; unauthorized="unauthorized"; forbidden="forbidden"; not_found="not_found"; conflict="conflict"; validation_error="validation_error"; stage_not_ready="stage_not_ready"; stage_failed="stage_failed"; run_not_active="run_not_active"; worker_not_found="worker_not_found"; worker_unavailable="worker_unavailable"; file_locked="file_locked"; path_rejected="path_rejected"; provider_unavailable="provider_unavailable"; model_unavailable="model_unavailable"; rate_limited="rate_limited"; subprocess_failed="subprocess_failed"; sse_client_slow="sse_client_slow"; internal_error="internal_error"
class SSEEventType(str, Enum):
    heartbeat="heartbeat"; run_started="run_started"; content_delta="content_delta"; tool_call="tool_call"; tool_output="tool_output"; tool_progress="tool_progress"; stage_transition="stage_transition"; stage_status="stage_status"; checkpoint_saved="checkpoint_saved"; artifact_updated="artifact_updated"; worker_spawned="worker_spawned"; worker_status="worker_status"; worker_task="worker_task"; worker_stream="worker_stream"; file_claimed="file_claimed"; file_released="file_released"; file_lock_waiting="file_lock_waiting"; git_event="git_event"; blocker_created="blocker_created"; blocker_resolved="blocker_resolved"; cost_update="cost_update"; pause_state_changed="pause_state_changed"; pipeline_error="pipeline_error"; done="done"

JsonValue = Any

class ErrorResponse(StrictModel):
    ok: bool = False; error_code: ErrorCode; message: str; details: dict[str, JsonValue] = Field(default_factory=dict); request_id: str = Field(default_factory=new_id); retryable: bool = False
class TokenUsage(StrictModel):
    input_tokens:int=0; output_tokens:int=0; cache_read_tokens:int=0; cache_write_tokens:int=0; total_tokens:int=0; cost_usd:float=0.0; provider:str|None=None; model:str|None=None
    @model_validator(mode="after")
    def total(self): self.total_tokens=self.input_tokens+self.output_tokens+self.cache_read_tokens+self.cache_write_tokens; return self
class ArtifactRef(StrictModel):
    kind:ArtifactKind; path:str; sha256:str; bytes:int=0; updated_at:datetime=Field(default_factory=now_utc); phase_number:int|None=None
    @field_validator("path")
    @classmethod
    def artifact_path_valid(cls, v):
        return sanitize_relative_path(v)
class ToolDisplay(StrictModel):
    kind:Literal["text","json","diff","table","tree","markdown"]="text"; title:str|None=None; text:str|None=None; language:str|None=None; json:JsonValue|None=None; truncated:bool=False
class ToolCallPayload(StrictModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True, strict=True)
    call_id:str; stage:StageName; tool_name:str; arguments:dict[str,JsonValue]=Field(default_factory=dict); worker_id:str|None=None
class ToolOutputPayload(StrictModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True, strict=True)
    call_id:str; stage:StageName; success:bool; result_text:str|None=None; error:str|None=None; worker_id:str|None=None
    @model_validator(mode="after")
    def result_or_error(self):
        if self.success and self.result_text is None:
            raise ValueError("successful tool output requires result_text")
        if not self.success and self.error is None:
            raise ValueError("failed tool output requires error")
        return self

class SessionCreateRequest(StrictModel):
    project_name:str; project_slug:str|None=None; description:str; existing_repo_path:str|None=None; model_overrides:dict[StageName,str]=Field(default_factory=dict); tags:list[str]=Field(default_factory=list)
    @field_validator("project_slug")
    @classmethod
    def slug_valid(cls, v):
        if v is not None and not re_match(r"^[a-z0-9][a-z0-9-]{0,62}$", v): raise ValueError("invalid project_slug")
        return v
class RunSummary(StrictModel):
    run_id:str=Field(default_factory=new_id); session_id:str; status:RunStatus=RunStatus.created; current_stage:StageName|None=None; started_at:datetime|None=None; finished_at:datetime|None=None; usage:TokenUsage=Field(default_factory=TokenUsage)
class SessionSummary(StrictModel):
    session_id:str=Field(default_factory=new_id); project_name:str; project_slug:str; status:RunStatus=RunStatus.created; current_stage:StageName|None=None; created_at:datetime=Field(default_factory=now_utc); updated_at:datetime=Field(default_factory=now_utc); last_run_id:str|None=None
class SessionDetail(StrictModel):
    session:SessionSummary; project_root:str; main_worktree:str; artifacts:list[ArtifactRef]=Field(default_factory=list); runs:list[RunSummary]=Field(default_factory=list)

class PipelineStartRequest(StrictModel):
    project_name:str; description:str; project_slug:str|None=None; existing_repo_path:str|None=None; start_stage:StageName=StageName.interview; stop_after_stage:StageName|None=None; model_overrides:dict[StageName,str]=Field(default_factory=dict); resume_run_id:str|None=None; auto_approve_interview:bool=False; metadata:dict[str,JsonValue]=Field(default_factory=dict)
    @field_validator("project_slug")
    @classmethod
    def pipeline_slug_valid(cls, v):
        if v is not None and not re_match(r"^[a-z0-9][a-z0-9-]{0,62}$", v): raise ValueError("invalid project_slug")
        return v
    @field_validator("model_overrides")
    @classmethod
    def model_overrides_valid(cls, v):
        for model in v.values():
            if not isinstance(model, str) or "/" not in model: raise ValueError("invalid model string")
        return v
    @field_validator("metadata")
    @classmethod
    def metadata_json_safe(cls, v):
        assert_json_safe(v)
        return v
class RunStartResponse(StrictModel):
    ok:bool=True; session_id:str; run_id:str; status:RunStatus=RunStatus.running; stream_url:str; status_url:str
class StageStatusSchema(StrictModel):
    stage:StageName; status:StageRunStatus=StageRunStatus.pending; attempt:int=0; max_attempts:int=3; started_at:datetime|None=None; finished_at:datetime|None=None; input_artifacts:list[ArtifactRef]=Field(default_factory=list); output_artifacts:list[ArtifactRef]=Field(default_factory=list); error:ErrorResponse|None=None
class PipelineStatusResponse(StrictModel):
    ok:bool=True; run:RunSummary; stages:list[StageStatusSchema]; workers:list['Worker']=Field(default_factory=list); paused:bool=False; blockers:list['Blocker']=Field(default_factory=list)
class PipelineInjectRequest(StrictModel):
    run_id:str; message:str; worker_id:str|None=None; stage:StageName|None=None
    @field_validator("run_id", "message", "worker_id")
    @classmethod
    def non_empty_public_strings(cls, v):
        if v is not None and not str(v).strip(): raise ValueError("blank strings are not allowed")
        return v
class ControlResponse(StrictModel):
    ok:bool=True; run_id:str; status:RunStatus; message:str
class StageSkipRequest(StrictModel):
    run_id:str; stage:StageName; reason:str; task_id:str|None=None
class InterviewAnswerRequest(StrictModel):
    answers:dict[str,str]
    @field_validator("answers")
    @classmethod
    def answers_non_empty(cls, v):
        if not v: raise ValueError("answers required")
        for key, value in v.items():
            if not key.strip() or not isinstance(value, str) or not value.strip(): raise ValueError("answers must be non-empty strings")
        return v
class AssistantReplyRequest(StrictModel):
    message:str; model:str|None=None
    @field_validator("model")
    @classmethod
    def model_valid(cls, v):
        if v is not None and "/" not in v: raise ValueError("invalid model string")
        return v
class AssistantReplyResponse(StrictModel):
    ok:bool=True; message:str; model:str; usage:TokenUsage=Field(default_factory=TokenUsage)

class InterviewQuestionAnswer(StrictModel):
    question_id:str; question:str; answer:str; source:Literal["user","auto","default"]="user"
class InterviewArtifact(StrictModel):
    project_name:str; project_slug:str; description:str; questions:list[InterviewQuestionAnswer]=Field(default_factory=list); requirements:list[str]=Field(default_factory=list); constraints:list[str]=Field(default_factory=list); risks:list[str]=Field(default_factory=list); created_at:datetime=Field(default_factory=now_utc)
class ComplexityProfile(StrictModel):
    level:ComplexityLevel; score:int; phase_count:int; task_group_size:int; template_depth:ComplexityLevel; signals:dict[str,int]=Field(default_factory=dict); rationale:str
class ValidationIssue(StrictModel):
    issue_id:str=Field(default_factory=new_id); severity:Literal["info","warning","error","blocker"]; category:str; message:str; artifact_path:str|None=None; anchor:str|None=None; fix_required:bool=False
class ValidationReport(StrictModel):
    passed:bool; iteration:int=1; max_iterations:int=3; issues:list[ValidationIssue]=Field(default_factory=list); corrected:bool=False; created_at:datetime=Field(default_factory=now_utc)
class ReviewReport(StrictModel):
    passed:bool; iteration:int=1; max_iterations:int=2; issues:list[ValidationIssue]=Field(default_factory=list); feedback_for_plan_stage:str=""; created_at:datetime=Field(default_factory=now_utc)
class ArtifactManifestResponse(StrictModel):
    ok:bool=True; session_id:str; run_id:str|None=None; artifacts:list[ArtifactRef]=Field(default_factory=list)
class ArtifactContentResponse(StrictModel):
    ok:bool=True; artifact:ArtifactRef; content_text:str; content_type:str

class Worker(StrictModel):
    worker_id:str; run_id:str; role:WorkerRole; status:WorkerStatus=WorkerStatus.starting; task_id:str|None=None; task_title:str|None=None; worktree_path:str; branch_name:str; pid:int|None=None; model:str; usage:TokenUsage=Field(default_factory=TokenUsage); created_at:datetime=Field(default_factory=now_utc); updated_at:datetime=Field(default_factory=now_utc); last_error:ErrorResponse|None=None
class WorkerSpawnRequest(StrictModel):
    run_id:str; role:WorkerRole; task:str; phase_number:int|None=None; model:str|None=None
class WorkerAssignRequest(StrictModel):
    run_id:str; worker_id:str; task_id:str|None=None; task:str; phase_number:int|None=None
class WorkerInjectRequest(StrictModel):
    run_id:str; worker_id:str; message:str
class BlockerCreateRequest(StrictModel):
    run_id:str; stage:StageName; message:str; worker_id:str|None=None; severity:Literal["warning","blocker"]="blocker"
class BlockerResolveRequest(StrictModel):
    run_id:str; blocker_id:str; reason:str="resolved"
class FileLock(StrictModel):
    path:str; worker_id:str; run_id:str; status:LockStatus=LockStatus.claimed; claimed_at:datetime=Field(default_factory=now_utc); expires_at:datetime=Field(default_factory=lambda: now_utc()+timedelta(seconds=120))
    @field_validator("path")
    @classmethod
    def lock_path_valid(cls, v):
        return sanitize_relative_path(v)
class Blocker(StrictModel):
    blocker_id:str=Field(default_factory=new_id); run_id:str; worker_id:str|None=None; stage:StageName; severity:Literal["warning","blocker"]="blocker"; message:str; resolved:bool=False; created_at:datetime=Field(default_factory=now_utc); resolved_at:datetime|None=None
class ChangedFile(StrictModel):
    path:str; status:Literal["added","modified","deleted","renamed"]; sha256:str|None=None; bytes:int|None=None
    @field_validator("path")
    @classmethod
    def changed_path_valid(cls, v):
        return sanitize_relative_path(v)
class ChangedFilesManifest(StrictModel):
    run_id:str; base_commit:str; merge_commit:str|None=None; files:list[ChangedFile]=Field(default_factory=list); created_at:datetime=Field(default_factory=now_utc)
class MergeReport(StrictModel):
    run_id:str; base_commit:str; merge_commit:str|None=None; merged_workers:list[str]=Field(default_factory=list); conflicts:list[str]=Field(default_factory=list); passed:bool; created_at:datetime=Field(default_factory=now_utc)
class DevelopReport(StrictModel):
    run_id:str; passed:bool; workers:list[Worker]=Field(default_factory=list); tasks_total:int=0; tasks_passed:int=0; tasks_failed:int=0; tests_command:str|None=None; tests_passed:bool|None=None; created_at:datetime=Field(default_factory=now_utc)

class CoreConfig(StrictModel): host:str="127.0.0.1"; port:int=7771; cors_allow_origins:list[str]=Field(default_factory=lambda:["http://127.0.0.1:7772"])
class WebConfig(StrictModel): host:str="127.0.0.1"; port:int=7772; core_base_url:str="http://127.0.0.1:7771"
class AuthConfig(StrictModel): enabled:bool=False; api_key_env:str="NEXUSSY_API_KEY"; header_name:str="X-API-Key"
class DatabaseConfig(StrictModel): global_path:str="~/.nexussy/state.db"; project_relative_path:str=".nexussy/state.db"; wal_enabled:bool=True; busy_timeout_ms:int=5000; write_retry_count:int=5; write_retry_base_ms:int=100
class ProvidersConfig(StrictModel): default_model:str="openai/gpt-5.5-fast"; allow_fallback:bool=False; request_timeout_s:int=120; max_retries:int=3; retry_base_ms:int=500
class StageModelConfig(StrictModel): model:str="openai/gpt-5.5-fast"; max_retries:int=3; max_iterations:int|None=None
class InterviewStageConfig(StageModelConfig): answer_timeout_s:int=3600
class DevelopStageConfig(StrictModel): model:str="openai/gpt-5.5-fast"; orchestrator_model:str="openai/gpt-5.5-fast"; max_retries:int=2
class StagesConfig(StrictModel):
    interview:InterviewStageConfig=Field(default_factory=InterviewStageConfig); design:StageModelConfig=Field(default_factory=StageModelConfig); validate:StageModelConfig=Field(default_factory=lambda:StageModelConfig(max_retries=2,max_iterations=3)); plan:StageModelConfig=Field(default_factory=StageModelConfig); review:StageModelConfig=Field(default_factory=lambda:StageModelConfig(max_retries=2,max_iterations=2)); develop:DevelopStageConfig=Field(default_factory=DevelopStageConfig)
class SwarmConfig(StrictModel): max_workers:int=8; default_worker_count:int=2; worker_task_timeout_s:int=900; worker_start_timeout_s:int=30; file_lock_timeout_s:int=120; file_lock_retry_ms:int=250; merge_strategy:Literal["no_ff","squash"]="no_ff"
class PiConfig(StrictModel): command:str="nexussy-pi"; args:list[str]=Field(default_factory=list); startup_timeout_s:int=30; shutdown_timeout_s:int=10; max_stdout_line_bytes:int=1048576
class SSEConfig(StrictModel): heartbeat_interval_s:int=15; client_queue_max_events:int=1000; replay_max_events:int=10000; retry_ms:int=3000
class SecurityConfig(StrictModel): scrub_logs:bool=True; reject_symlink_escape:bool=True; keyring_service:str="nexussy"; cors_origins:list[str]=Field(default_factory=lambda:["*"])
class LoggingConfig(StrictModel): level:Literal["DEBUG","INFO","WARNING","ERROR"]="INFO"; core_log_file:str="/tmp/nexussy-core.log"; web_log_file:str="/tmp/nexussy-web.log"; tui_log_file:str="/tmp/nexussy-tui.log"
class NexussyConfig(StrictModel):
    version:str="1.0"; home_dir:str="~/.nexussy"; projects_dir:str="~/nexussy-projects"; core:CoreConfig=Field(default_factory=CoreConfig); web:WebConfig=Field(default_factory=WebConfig); auth:AuthConfig=Field(default_factory=AuthConfig); database:DatabaseConfig=Field(default_factory=DatabaseConfig); providers:ProvidersConfig=Field(default_factory=ProvidersConfig); stages:StagesConfig=Field(default_factory=StagesConfig); swarm:SwarmConfig=Field(default_factory=SwarmConfig); pi:PiConfig=Field(default_factory=PiConfig); sse:SSEConfig=Field(default_factory=SSEConfig); security:SecurityConfig=Field(default_factory=SecurityConfig); logging:LoggingConfig=Field(default_factory=LoggingConfig)

class HealthResponse(StrictModel):
    ok:bool=True; status:str="ok"; version:str; contract_version:str="1.0"; db_ok:bool; providers_configured:list[str]=Field(default_factory=list); pi_available:bool=False
class SecretSummary(StrictModel): name:str; source:Literal["keyring","env","config"]; configured:bool; updated_at:datetime|None=None
class MemoryEntryCreateRequest(StrictModel): session_id:str|None=None; key:str; value:str; tags:list[str]=Field(default_factory=list)
class MemoryEntry(StrictModel): memory_id:str=Field(default_factory=new_id); session_id:str|None=None; key:str; value:str; tags:list[str]=Field(default_factory=list); created_at:datetime=Field(default_factory=now_utc); updated_at:datetime=Field(default_factory=now_utc)
class GraphNode(StrictModel): id:str; label:str; kind:Literal["session","run","stage","worker","artifact","file","task"]; status:str|None=None; metadata:dict[str,JsonValue]=Field(default_factory=dict)
class GraphEdge(StrictModel): source:str; target:str; kind:str; metadata:dict[str,JsonValue]=Field(default_factory=dict)
class GraphResponse(StrictModel): nodes:list[GraphNode]=Field(default_factory=list); edges:list[GraphEdge]=Field(default_factory=list)

class HeartbeatPayload(StrictModel): ts:datetime=Field(default_factory=now_utc); server_status:str="ok"
class StageTransitionPayload(StrictModel): from_stage:StageName|None=None; to_stage:StageName; from_status:StageRunStatus|None=None; to_status:StageRunStatus; reason:str
class CheckpointPayload(StrictModel): checkpoint_id:str; stage:StageName; path:str; sha256:str; created_at:datetime
class ArtifactUpdatedPayload(StrictModel): artifact:ArtifactRef; action:Literal["created","updated","deleted"]; anchor:str|None=None
class WorkerTaskPayload(StrictModel): worker_id:str; task_id:str; phase_number:int|None=None; task_title:str; status:WorkerTaskStatus
class WorkerStreamPayload(StrictModel): worker_id:str; stream_kind:Literal["rpc","stdout","stderr"]; line:str; parsed:bool=False; truncated:bool=False
class GitEventPayload(StrictModel): action:GitEventAction; worker_id:str|None=None; branch_name:str|None=None; commit_sha:str|None=None; paths:list[str]=Field(default_factory=list); message:str
class PausePayload(StrictModel): paused:bool; reason:str; requested_by:str="api"
class DonePayload(StrictModel): final_status:RunStatus; summary:str; artifacts:list[ArtifactRef]=Field(default_factory=list); usage:TokenUsage=Field(default_factory=TokenUsage); error:ErrorResponse|None=None
class EventEnvelope(StrictModel):
    event_id:str=Field(default_factory=new_id); sequence:int; contract_version:str="1.0"; type:SSEEventType; session_id:str; run_id:str; ts:datetime=Field(default_factory=now_utc); source:Literal["core","worker","tui","web"]="core"; payload:JsonValue

PipelineStatusResponse.model_rebuild()

def re_match(pattern: str, value: str) -> bool:
    import re
    return re.match(pattern, value) is not None

def assert_json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        for item in value: assert_json_safe(item)
        return
    if isinstance(value, dict):
        for k, item in value.items():
            if not isinstance(k, str): raise ValueError("JSON object keys must be strings")
            assert_json_safe(item)
        return
    raise ValueError("metadata must be JSON-compatible")
