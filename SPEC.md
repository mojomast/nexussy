# nexussy — v1.1 Implementation Specification

Fifth-generation Ussyverse coding harness lineage: devussy -> swarmussy -> ralphussy -> geoffrussy -> nexussy.

This document is the sole build contract for nexussy. All implementation agents MUST follow this document exactly. Missing behavior MUST be treated as a defect in the implementation, not as permission to invent behavior.

Target coding-agent reader: GPT-5.5 Fast or better, operating in parallel with no mid-build coordination.

## 0. Non-Negotiable Build Rules

1. nexussy MUST NOT depend on the ussycode repository.
2. "Ussycoded" means Ussyverse style, lineage continuity, human-facing naming, operator ergonomics, and brrrr-grade momentum. Machine contracts MUST remain stable, typed, and boring.
3. Subagents MUST NOT modify files outside their ownership boundary.
4. Subagents MUST NOT import source code from another module to discover a contract.
5. The contract between modules is this SPEC.md plus generated mock fixtures copied into each module by that module's tests.
6. The core API schema MUST be treated as public. Breaking changes REQUIRE an explicit `contract_version` bump.
7. All Pydantic schemas MUST use Pydantic v2, `extra="forbid"`, strict validation, UTC datetimes, and JSON-serializable fields.
8. All JSON APIs MUST return UTF-8 JSON.
9. All SSE streams MUST use `text/event-stream; charset=utf-8`.
10. All local HTTP services MUST bind to `127.0.0.1` by default.
11. All file paths MUST be resolved, normalized, and validated through the path sanitizer before use.
12. All subprocesses MUST be cancellable, drain stdout and stderr concurrently, and run in an isolated process group.
13. All SQLite writes MUST use bounded transactions, WAL mode, `busy_timeout`, and retry handling.
14. Agents MUST use imperative language in repository instructions. Repository instructions MUST NOT contain ambiguous planning language.

## 1. Product Definition

nexussy is a staged software-delivery pipeline with a live multi-agent swarm execution engine. It accepts a project description, interviews the user when required, produces stateless artifacts, validates the artifacts, launches isolated coding workers, merges their work, and leaves enough anchored context for another agent to continue without chat history.

nexussy is not a chat app. The TUI and web dashboard are control surfaces for the core pipeline.

### 1.1 Lineage Duties

nexussy MUST preserve these lineage patterns:

| Source | Pattern nexussy MUST preserve |
|---|---|
| devussy | Interview-to-DevPlan flow, anchor-based context management, adaptive complexity scoring, per-stage model overrides, checkpoint resumption, stateless artifacts |
| swarmussy | Role-based orchestration, dedicated orchestrator, worker role separation, file claiming, real-time dashboard panels |
| ralphussy | Git worktree isolation, detached/resumable runs, live context injection, changed-file artifact extraction, SQLite WAL retry discipline |
| geoffrussy | Interview -> design -> plan -> review -> develop pipeline, explicit review gate, provider/quota persistence, path sanitizer, log scrubber, pause/resume/skip/blocker controls, MCP stdio integration |
| Pi | TypeScript TUI primitives, pi-ai provider ergonomics, pi-agent-core agent runtime concepts, pi-tui differential rendering, Pi RPC subprocess mode |

## 2. Repository Ownership

```
nexussy/
├── core/                          # Subagent A owns exclusively
│   ├── nexussy/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── providers.py
│   │   ├── pipeline/
│   │   ├── swarm/
│   │   ├── artifacts/
│   │   ├── session.py
│   │   ├── checkpoint.py
│   │   ├── security.py
│   │   ├── mcp.py
│   │   └── api/
│   ├── tests/
│   ├── requirements.txt
│   └── pyproject.toml
├── tui/                           # Subagent B owns exclusively
│   ├── src/
│   ├── tests/
│   ├── package.json
│   └── tsconfig.json
├── web/                           # Subagent C owns exclusively
│   ├── nexussy_web/
│   ├── tests/
│   ├── requirements.txt
│   └── pyproject.toml
├── install.sh                     # Subagent D owns
├── nexussy.sh                     # Subagent D owns
├── SPEC.md                        # Subagent D owns after initial commit
├── AGENTS.md                      # Subagent D owns
└── README.md                      # Subagent D owns
```

### 2.1 Boundary Rules

| Subagent | Owns | MUST NOT touch |
|---|---|---|
| A | `core/` | `tui/`, `web/`, `install.sh`, `nexussy.sh`, `AGENTS.md`, `README.md` |
| B | `tui/` | `core/`, `web/`, root scripts, root docs |
| C | `web/` | `core/`, `tui/`, root scripts, root docs |
| D | `install.sh`, `nexussy.sh`, `AGENTS.md`, `README.md`, root packaging notes | `core/`, `tui/`, `web/` implementation files |

Subagent B and Subagent C MUST build against mock HTTP/SSE fixtures derived from this document before Subagent A exists.

## 3. Runtime Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ tui/ nexussy-tui                                                 │
│ TypeScript + Bun + OpenTUI default, Pi TUI opt-in                 │
│ Consumes core HTTP and SSE only                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP + SSE
┌──────────────────────────▼──────────────────────────────────────┐
│ core/ nexussy-core                                               │
│ Python 3.11+ + Starlette + aiosqlite + LiteLLM                   │
│ Owns pipeline, state, provider calls, swarm, Pi subprocesses      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP proxy + SSE proxy
┌──────────────────────────▼──────────────────────────────────────┐
│ web/ nexussy-web                                                 │
│ Python 3.11+ + Starlette + single HTML dashboard                  │
│ Proxies `/api/*` to core and serves dashboard on port 7772        │
└─────────────────────────────────────────────────────────────────┘
```

## 4. Runtime Ports, Processes, and Commands

| Process | Command | Host | Port | Log file | PID file |
|---|---|---:|---:|---|---|
| core | `python -m nexussy.api.server` | `127.0.0.1` | `7771` | `/tmp/nexussy-core.log` | `~/.nexussy/run/core.pid` |
| web | `python -m nexussy_web.app` | `127.0.0.1` | `7772` | `/tmp/nexussy-web.log` | `~/.nexussy/run/web.pid` |
| tui | `bun run start` from `tui/` | none | none | `/tmp/nexussy-tui.log` | `~/.nexussy/run/tui.pid` |

`nexussy.sh start` MUST start core and web. `nexussy.sh start-tui` MUST start the TUI after verifying core health.

## 5. Path Contract

### 5.1 Fixed Paths

| Purpose | Path |
|---|---|
| User home | `~/.nexussy/` |
| Config file | `~/.nexussy/nexussy.yaml` |
| Env file | `~/.nexussy/.env` |
| Global DB | `~/.nexussy/state.db` |
| Runtime dir | `~/.nexussy/run/` |
| Logs dir | `~/.nexussy/logs/` |
| Project home | `~/nexussy-projects/` |
| Project root | `~/nexussy-projects/<project_slug>/` |
| Main worktree | `~/nexussy-projects/<project_slug>/main/` |
| Worker worktree root | `~/nexussy-projects/<project_slug>/workers/` |
| Worker worktree | `~/nexussy-projects/<project_slug>/workers/<worker_id>/` |
| Project DB | `~/nexussy-projects/<project_slug>/.nexussy/state.db` |
| Project logs | `~/nexussy-projects/<project_slug>/.nexussy/logs/` |
| Project artifacts | `~/nexussy-projects/<project_slug>/main/.nexussy/artifacts/` |
| Changed-file extraction | `~/nexussy-projects/<project_slug>/main/.nexussy/artifacts/changed-files/` |

`project_slug` MUST match `^[a-z0-9][a-z0-9-]{0,62}$`. User-facing project names MUST be converted to slugs by lowercasing, replacing non-alphanumeric runs with `-`, trimming leading/trailing `-`, and appending `-<6-char-hash>` on collision.

### 5.2 Artifact Paths

All artifacts MUST live under the project main worktree unless explicitly marked global.

| Artifact | Path | Format |
|---|---|---|
| Interview result | `.nexussy/artifacts/interview.json` | JSON matching `InterviewArtifact` |
| Complexity profile | `.nexussy/artifacts/complexity_profile.json` | JSON matching `ComplexityProfile` |
| Design draft | `.nexussy/artifacts/design_draft.md` | Markdown |
| Validated design | `.nexussy/artifacts/validated_design.md` | Markdown |
| Validation report | `.nexussy/artifacts/validation_report.json` | JSON matching `ValidationReport` |
| DevPlan | `devplan.md` | Anchored Markdown |
| Handoff | `handoff.md` | Anchored Markdown |
| Phase file | `phaseNNN.md` | Anchored Markdown, zero-padded NNN |
| Review report | `.nexussy/artifacts/review_report.json` | JSON matching `ReviewReport` |
| Develop report | `.nexussy/artifacts/develop_report.json` | JSON matching `DevelopReport` |
| Merge report | `.nexussy/artifacts/merge_report.json` | JSON matching `MergeReport` |
| Changed files manifest | `.nexussy/artifacts/changed_files.json` | JSON matching `ChangedFilesManifest` |

## 6. Configuration Contract

### 6.1 Loading Precedence

Core MUST load configuration in this order, highest precedence last:

1. Built-in defaults.
2. `~/.nexussy/nexussy.yaml`.
3. Environment variables from `~/.nexussy/.env`.
4. Process environment variables.
5. Request-scoped overrides supplied to API routes.

### 6.2 Default `nexussy.yaml`

Subagent D MUST generate this file exactly when absent:

```yaml
version: "1.0"
home_dir: "~/.nexussy"
projects_dir: "~/nexussy-projects"
core:
  host: "127.0.0.1"
  port: 7771
web:
  host: "127.0.0.1"
  port: 7772
auth:
  enabled: false
  api_key_env: "NEXUSSY_API_KEY"
database:
  global_path: "~/.nexussy/state.db"
  project_relative_path: ".nexussy/state.db"
  wal_enabled: true
  busy_timeout_ms: 5000
  write_retry_count: 5
  write_retry_base_ms: 100
providers:
  default_model: "openai/gpt-5.5-fast"
  allow_fallback: false
  request_timeout_s: 120
  max_retries: 3
  retry_base_ms: 500
stages:
  interview:
    model: "openai/gpt-5.5-fast"
    max_retries: 3
  design:
    model: "openai/gpt-5.5-fast"
    max_retries: 3
  validate:
    model: "openai/gpt-5.5-fast"
    max_iterations: 3
    max_retries: 2
  plan:
    model: "openai/gpt-5.5-fast"
    max_retries: 3
  review:
    model: "openai/gpt-5.5-fast"
    max_iterations: 2
    max_retries: 2
  develop:
    model: "openai/gpt-5.5-fast"
    orchestrator_model: "openai/gpt-5.5-fast"
    max_retries: 2
swarm:
  max_workers: 8
  default_worker_count: 2
  worker_task_timeout_s: 900
  worker_start_timeout_s: 30
  file_lock_timeout_s: 120
  file_lock_retry_ms: 250
  merge_strategy: "no_ff"
pi:
  command: "pi"
  args: ["--rpc"]
  startup_timeout_s: 30
  shutdown_timeout_s: 10
  max_stdout_line_bytes: 1048576
sse:
  heartbeat_interval_s: 15
  client_queue_max_events: 1000
  replay_max_events: 10000
  retry_ms: 3000
security:
  scrub_logs: true
  reject_symlink_escape: true
  keyring_service: "nexussy"
logging:
  level: "INFO"
  core_log_file: "/tmp/nexussy-core.log"
  web_log_file: "/tmp/nexussy-web.log"
  tui_log_file: "/tmp/nexussy-tui.log"
```

### 6.3 Environment Variables

| Env var | Type | Default | Purpose |
|---|---|---|---|
| `NEXUSSY_HOME` | path | `~/.nexussy` | Override home dir |
| `NEXUSSY_CONFIG` | path | `~/.nexussy/nexussy.yaml` | Override config path |
| `NEXUSSY_ENV_FILE` | path | `~/.nexussy/.env` | Override env file path |
| `NEXUSSY_PROJECTS_DIR` | path | `~/nexussy-projects` | Override project home |
| `NEXUSSY_CORE_HOST` | string | `127.0.0.1` | Core bind host |
| `NEXUSSY_CORE_PORT` | int | `7771` | Core port |
| `NEXUSSY_WEB_HOST` | string | `127.0.0.1` | Web bind host |
| `NEXUSSY_WEB_PORT` | int | `7772` | Web port |
| `NEXUSSY_API_KEY` | string | unset | API key when auth enabled |
| `NEXUSSY_AUTH_ENABLED` | bool | `false` | Enable API key auth |
| `NEXUSSY_DATABASE_PATH` | path | `~/.nexussy/state.db` | Global DB path |
| `NEXUSSY_DEFAULT_MODEL` | string | `openai/gpt-5.5-fast` | Default model |
| `NEXUSSY_INTERVIEW_MODEL` | string | config value | Interview model |
| `NEXUSSY_DESIGN_MODEL` | string | config value | Design model |
| `NEXUSSY_VALIDATE_MODEL` | string | config value | Validate model |
| `NEXUSSY_PLAN_MODEL` | string | config value | Plan model |
| `NEXUSSY_REVIEW_MODEL` | string | config value | Review model |
| `NEXUSSY_DEVELOP_MODEL` | string | config value | Worker default model |
| `NEXUSSY_ORCHESTRATOR_MODEL` | string | config value | Orchestrator model |
| `NEXUSSY_PI_COMMAND` | string | `pi` | Pi executable |
| `NEXUSSY_LOG_LEVEL` | string | `INFO` | Logging verbosity |
| `OPENAI_API_KEY` | string | unset | OpenAI provider key |
| `ANTHROPIC_API_KEY` | string | unset | Anthropic provider key |
| `OPENROUTER_API_KEY` | string | unset | OpenRouter provider key |
| `GROQ_API_KEY` | string | unset | Groq provider key |
| `GEMINI_API_KEY` | string | unset | Google Gemini provider key |
| `MISTRAL_API_KEY` | string | unset | Mistral provider key |
| `TOGETHER_API_KEY` | string | unset | Together provider key |
| `FIREWORKS_API_KEY` | string | unset | Fireworks provider key |
| `XAI_API_KEY` | string | unset | xAI provider key |
| `GLM_API_KEY` | string | unset | Z.AI GLM provider key |
| `ZAI_API_KEY` | string | unset | Z.AI provider key |
| `REQUESTY_API_KEY` | string | unset | Requesty provider key |
| `AETHER_API_KEY` | string | unset | Aether provider key |
| `OLLAMA_BASE_URL` | URL | unset | Ollama endpoint |

## 7. Shared Type System

### 7.1 Scalar Aliases

| Alias | Type | Validation |
|---|---|---|
| `SessionID` | string | ULID or UUIDv4 string |
| `RunID` | string | ULID or UUIDv4 string |
| `WorkerID` | string | `^(orchestrator|backend|frontend|qa|devops|writer|analyst)-[a-z0-9]{6,12}$` |
| `TaskID` | string | `^task-[a-z0-9]{6,12}$` |
| `EventID` | string | ULID string |
| `ProjectSlug` | string | `^[a-z0-9][a-z0-9-]{0,62}$` |
| `RelativePath` | string | relative POSIX path with no `..`, no leading `/`, no NUL |
| `AbsolutePath` | string | absolute normalized path |
| `ModelString` | string | `provider/model-name` |
| `JsonScalar` | union | `str | int | float | bool | None` |
| `JsonValue` | union | `JsonScalar | list[JsonValue] | dict[str, JsonValue]` |

### 7.2 Enums

| Enum | Values |
|---|---|
| `StageName` | `interview`, `design`, `validate`, `plan`, `review`, `develop` |
| `StageRunStatus` | `pending`, `running`, `passed`, `failed`, `skipped`, `blocked`, `paused`, `retrying` |
| `RunStatus` | `created`, `running`, `paused`, `passed`, `failed`, `cancelled`, `blocked` |
| `ComplexityLevel` | `minimal`, `standard`, `detailed` |
| `WorkerRole` | `orchestrator`, `backend`, `frontend`, `qa`, `devops`, `writer`, `analyst` |
| `WorkerStatus` | `starting`, `idle`, `assigned`, `running`, `paused`, `blocked`, `finished`, `failed`, `stopped` |
| `WorkerTaskStatus` | `queued`, `assigned`, `running`, `passed`, `failed`, `skipped`, `blocked` |
| `ArtifactKind` | `interview`, `complexity_profile`, `design_draft`, `validated_design`, `validation_report`, `devplan`, `handoff`, `phase`, `review_report`, `develop_report`, `merge_report`, `changed_files` |
| `ToolName` | `spawn_worker`, `assign_task`, `get_swarm_state`, `read_file`, `write_file`, `edit_file`, `bash`, `list_files`, `search_code`, `claim_file`, `release_file`, `add_context` |
| `LockStatus` | `claimed`, `released`, `waiting`, `expired` |
| `GitEventAction` | `repo_initialized`, `worktree_created`, `worktree_removed`, `merge_started`, `merge_completed`, `merge_conflict`, `merge_aborted`, `artifact_extracted` |
| `ErrorCode` | `bad_request`, `unauthorized`, `forbidden`, `not_found`, `conflict`, `validation_error`, `stage_not_ready`, `stage_failed`, `run_not_active`, `worker_not_found`, `worker_unavailable`, `file_locked`, `path_rejected`, `provider_unavailable`, `model_unavailable`, `rate_limited`, `subprocess_failed`, `sse_client_slow`, `internal_error` |
| `SSEEventType` | `heartbeat`, `run_started`, `content_delta`, `tool_call`, `tool_output`, `tool_progress`, `stage_transition`, `stage_status`, `checkpoint_saved`, `artifact_updated`, `worker_spawned`, `worker_status`, `worker_task`, `worker_stream`, `file_claimed`, `file_released`, `file_lock_waiting`, `git_event`, `blocker_created`, `blocker_resolved`, `cost_update`, `pause_state_changed`, `pipeline_error`, `done` |

## 8. Pydantic Schema Contract

Every schema in this section MUST be implemented in `core/nexussy/api/schemas.py`. Subagent B and Subagent C MUST mirror these schemas as TypeScript or fixture types inside their own module without importing Python code.

### 8.1 Common Schemas

#### `ErrorResponse`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `ok` | bool | yes | `false` | Always false |
| `error_code` | `ErrorCode` | yes | none | Stable machine code |
| `message` | string | yes | none | Human-safe message |
| `details` | `dict[str, JsonValue]` | no | `{}` | Structured details |
| `request_id` | string | yes | generated | Request correlation ID |
| `retryable` | bool | yes | `false` | True only when retry is safe |

#### `TokenUsage`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `input_tokens` | int | yes | `0` | Prompt tokens |
| `output_tokens` | int | yes | `0` | Completion tokens |
| `cache_read_tokens` | int | no | `0` | Cached tokens read |
| `cache_write_tokens` | int | no | `0` | Cached tokens written |
| `total_tokens` | int | yes | computed | Sum of token fields |
| `cost_usd` | float | yes | `0.0` | Cost in USD |
| `provider` | string | no | `null` | Provider name |
| `model` | string | no | `null` | Model string |

#### `ArtifactRef`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `kind` | `ArtifactKind` | yes | none | Artifact kind |
| `path` | `RelativePath` | yes | none | Path relative to main worktree |
| `sha256` | string | yes | none | Hex sha256 of content |
| `bytes` | int | yes | `0` | Byte length |
| `updated_at` | datetime | yes | now | UTC update time |
| `phase_number` | int | no | `null` | Phase number for phase files |

#### `ToolDisplay`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `kind` | enum `text|json|diff|table|tree|markdown` | yes | `text` | Display type |
| `title` | string | no | `null` | UI title |
| `text` | string | no | `null` | Text payload |
| `language` | string | no | `null` | Syntax language |
| `json` | `JsonValue` | no | `null` | Structured payload |
| `truncated` | bool | yes | `false` | True when shortened |

### 8.2 Session Schemas

#### `SessionCreateRequest`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `project_name` | string | yes | none | Human project name |
| `project_slug` | `ProjectSlug` | no | generated | Stable project slug |
| `description` | string | yes | none | Project description |
| `existing_repo_path` | `AbsolutePath` | no | `null` | Repo to copy or attach |
| `model_overrides` | `dict[StageName, ModelString]` | no | `{}` | Stage model overrides |
| `tags` | list[string] | no | `[]` | User tags |

#### `SessionSummary`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `session_id` | `SessionID` | yes | generated | Session ID |
| `project_name` | string | yes | none | Human project name |
| `project_slug` | `ProjectSlug` | yes | none | Project slug |
| `status` | `RunStatus` | yes | `created` | Latest run status |
| `current_stage` | `StageName` | no | `null` | Current stage |
| `created_at` | datetime | yes | now | UTC creation time |
| `updated_at` | datetime | yes | now | UTC update time |
| `last_run_id` | `RunID` | no | `null` | Last run ID |

#### `SessionDetail`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `session` | `SessionSummary` | yes | none | Session summary |
| `project_root` | `AbsolutePath` | yes | none | Project root |
| `main_worktree` | `AbsolutePath` | yes | none | Main worktree path |
| `artifacts` | list[`ArtifactRef`] | yes | `[]` | Artifact manifest |
| `runs` | list[`RunSummary`] | yes | `[]` | Run summaries |

### 8.3 Pipeline Schemas

#### `PipelineStartRequest`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `project_name` | string | yes | none | Human project name |
| `description` | string | yes | none | Project description |
| `project_slug` | `ProjectSlug` | no | generated | Stable slug |
| `existing_repo_path` | `AbsolutePath` | no | `null` | Existing repo path |
| `start_stage` | `StageName` | no | `interview` | First stage to run |
| `stop_after_stage` | `StageName` | no | `null` | Stop after this stage |
| `model_overrides` | `dict[StageName, ModelString]` | no | `{}` | Stage models |
| `resume_run_id` | `RunID` | no | `null` | Resume run |
| `auto_approve_interview` | bool | no | `false` | Use defaults without interactive Q&A |
| `metadata` | `dict[str, JsonValue]` | no | `{}` | Extra caller data |

#### `RunStartResponse`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `ok` | bool | yes | `true` | Success flag |
| `session_id` | `SessionID` | yes | none | Session ID |
| `run_id` | `RunID` | yes | none | Run ID |
| `status` | `RunStatus` | yes | `running` | Run status |
| `stream_url` | string | yes | `/pipeline/runs/{run_id}/stream` | SSE URL |
| `status_url` | string | yes | `/pipeline/status?run_id={run_id}` | Status URL |

#### `RunSummary`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `run_id` | `RunID` | yes | generated | Run ID |
| `session_id` | `SessionID` | yes | none | Session ID |
| `status` | `RunStatus` | yes | `created` | Run status |
| `current_stage` | `StageName` | no | `null` | Current stage |
| `started_at` | datetime | no | `null` | UTC start time |
| `finished_at` | datetime | no | `null` | UTC finish time |
| `usage` | `TokenUsage` | yes | zero usage | Aggregate usage |

#### `StageStatusSchema`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `stage` | `StageName` | yes | none | Stage name |
| `status` | `StageRunStatus` | yes | `pending` | Stage status |
| `attempt` | int | yes | `0` | Current attempt |
| `max_attempts` | int | yes | config | Max attempts |
| `started_at` | datetime | no | `null` | UTC start time |
| `finished_at` | datetime | no | `null` | UTC finish time |
| `input_artifacts` | list[`ArtifactRef`] | yes | `[]` | Inputs |
| `output_artifacts` | list[`ArtifactRef`] | yes | `[]` | Outputs |
| `error` | `ErrorResponse` | no | `null` | Failure error |

#### `PipelineStatusResponse`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `ok` | bool | yes | `true` | Success flag |
| `run` | `RunSummary` | yes | none | Run summary |
| `stages` | list[`StageStatusSchema`] | yes | six entries | All stage statuses |
| `workers` | list[`Worker`] | yes | `[]` | Worker states |
| `paused` | bool | yes | `false` | Pause state |
| `blockers` | list[`Blocker`] | yes | `[]` | Active blockers |

#### `PipelineInjectRequest`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `run_id` | `RunID` | yes | none | Run ID |
| `message` | string | yes | none | Context message |
| `worker_id` | `WorkerID` | no | `null` | Target worker |
| `stage` | `StageName` | no | `null` | Target stage |

#### `ControlResponse`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `ok` | bool | yes | `true` | Success flag |
| `run_id` | `RunID` | yes | none | Run ID |
| `status` | `RunStatus` | yes | none | New status |
| `message` | string | yes | none | Human summary |

#### `StageSkipRequest`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `run_id` | `RunID` | yes | none | Run ID |
| `stage` | `StageName` | yes | none | Stage to skip |
| `reason` | string | yes | none | Required audit reason |

### 8.4 Artifact Schemas

#### `InterviewArtifact`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `project_name` | string | yes | none | Human project name |
| `project_slug` | `ProjectSlug` | yes | none | Project slug |
| `description` | string | yes | none | Original description |
| `questions` | list[`InterviewQuestionAnswer`] | yes | `[]` | Q&A pairs |
| `requirements` | list[string] | yes | `[]` | Extracted requirements |
| `constraints` | list[string] | yes | `[]` | Constraints |
| `risks` | list[string] | yes | `[]` | Risks |
| `created_at` | datetime | yes | now | UTC creation time |

#### `InterviewQuestionAnswer`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `question_id` | string | yes | none | Stable question ID |
| `question` | string | yes | none | Question text |
| `answer` | string | yes | none | Answer text |
| `source` | enum `user|auto|default` | yes | `user` | Answer source |

#### `ComplexityProfile`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `level` | `ComplexityLevel` | yes | none | Complexity level |
| `score` | int | yes | none | 0 to 100 |
| `phase_count` | int | yes | none | Planned phase count |
| `task_group_size` | int | yes | none | Tasks per handoff group |
| `template_depth` | `ComplexityLevel` | yes | none | Prompt/detail depth |
| `signals` | `dict[str, int]` | yes | `{}` | Scoring signals |
| `rationale` | string | yes | none | Human rationale |

#### `ValidationIssue`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `issue_id` | string | yes | generated | Issue ID |
| `severity` | enum `info|warning|error|blocker` | yes | none | Severity |
| `category` | string | yes | none | Category |
| `message` | string | yes | none | Human-safe issue |
| `artifact_path` | `RelativePath` | no | `null` | Related artifact |
| `anchor` | string | no | `null` | Related anchor |
| `fix_required` | bool | yes | `false` | True blocks stage |

#### `ValidationReport`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `passed` | bool | yes | none | Validation result |
| `iteration` | int | yes | `1` | Validation iteration |
| `max_iterations` | int | yes | config | Max iterations |
| `issues` | list[`ValidationIssue`] | yes | `[]` | Issues |
| `corrected` | bool | yes | `false` | True after correction pass |
| `created_at` | datetime | yes | now | UTC creation time |

#### `ReviewReport`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `passed` | bool | yes | none | Review result |
| `iteration` | int | yes | `1` | Review iteration |
| `max_iterations` | int | yes | config | Max iterations |
| `issues` | list[`ValidationIssue`] | yes | `[]` | Plan issues |
| `feedback_for_plan_stage` | string | yes | `""` | Feedback injected into plan retry |
| `created_at` | datetime | yes | now | UTC creation time |

#### `ArtifactManifestResponse`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `ok` | bool | yes | `true` | Success flag |
| `session_id` | `SessionID` | yes | none | Session ID |
| `run_id` | `RunID` | no | `null` | Run ID |
| `artifacts` | list[`ArtifactRef`] | yes | `[]` | Artifact refs |

#### `ArtifactContentResponse`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `ok` | bool | yes | `true` | Success flag |
| `artifact` | `ArtifactRef` | yes | none | Artifact ref |
| `content_text` | string | yes | none | UTF-8 content |
| `content_type` | string | yes | none | MIME type |

### 8.5 Swarm Schemas

#### `Worker`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `worker_id` | `WorkerID` | yes | generated | Worker ID |
| `run_id` | `RunID` | yes | none | Run ID |
| `role` | `WorkerRole` | yes | none | Worker role |
| `status` | `WorkerStatus` | yes | `starting` | Worker status |
| `task_id` | `TaskID` | no | `null` | Current task |
| `task_title` | string | no | `null` | Current task title |
| `worktree_path` | `AbsolutePath` | yes | none | Worktree path |
| `branch_name` | string | yes | none | Git branch |
| `pid` | int | no | `null` | Subprocess PID |
| `model` | `ModelString` | yes | none | Worker model |
| `usage` | `TokenUsage` | yes | zero usage | Worker usage |
| `created_at` | datetime | yes | now | UTC creation time |
| `updated_at` | datetime | yes | now | UTC update time |
| `last_error` | `ErrorResponse` | no | `null` | Last error |

#### `WorkerSpawnRequest`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `run_id` | `RunID` | yes | none | Run ID |
| `role` | `WorkerRole` | yes | none | Role to spawn |
| `task` | string | yes | none | Initial task text |
| `phase_number` | int | no | `null` | Related phase |
| `model` | `ModelString` | no | stage default | Worker model |

#### `WorkerAssignRequest`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `run_id` | `RunID` | yes | none | Run ID |
| `worker_id` | `WorkerID` | yes | none | Worker ID |
| `task_id` | `TaskID` | no | generated | Task ID |
| `task` | string | yes | none | Task text |
| `phase_number` | int | no | `null` | Related phase |

#### `WorkerInjectRequest`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `run_id` | `RunID` | yes | none | Run ID |
| `worker_id` | `WorkerID` | yes | none | Worker ID |
| `message` | string | yes | none | Context message |

#### `FileLock`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `path` | `RelativePath` | yes | none | Project-relative path |
| `worker_id` | `WorkerID` | yes | none | Lock owner |
| `run_id` | `RunID` | yes | none | Run ID |
| `status` | `LockStatus` | yes | `claimed` | Lock status |
| `claimed_at` | datetime | yes | now | UTC claim time |
| `expires_at` | datetime | yes | now + timeout | UTC expiry time |

#### `Blocker`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `blocker_id` | string | yes | generated | Blocker ID |
| `run_id` | `RunID` | yes | none | Run ID |
| `worker_id` | `WorkerID` | no | `null` | Worker ID |
| `stage` | `StageName` | yes | none | Stage |
| `severity` | enum `warning|blocker` | yes | `blocker` | Severity |
| `message` | string | yes | none | Message |
| `resolved` | bool | yes | `false` | Resolution state |
| `created_at` | datetime | yes | now | UTC creation time |
| `resolved_at` | datetime | no | `null` | UTC resolution time |

#### `ChangedFilesManifest`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `run_id` | `RunID` | yes | none | Run ID |
| `base_commit` | string | yes | none | Base commit SHA |
| `merge_commit` | string | no | `null` | Merge commit SHA |
| `files` | list[`ChangedFile`] | yes | `[]` | Changed files |
| `created_at` | datetime | yes | now | UTC creation time |

#### `ChangedFile`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `path` | `RelativePath` | yes | none | Changed path |
| `status` | enum `added|modified|deleted|renamed` | yes | none | Git status |
| `sha256` | string | no | `null` | SHA for existing file |
| `bytes` | int | no | `null` | Byte length |

#### `MergeReport`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `run_id` | `RunID` | yes | none | Run ID |
| `base_commit` | string | yes | none | Base commit SHA |
| `merge_commit` | string | no | `null` | Merge commit SHA |
| `merged_workers` | list[`WorkerID`] | yes | `[]` | Merged workers |
| `conflicts` | list[`RelativePath`] | yes | `[]` | Conflict paths |
| `passed` | bool | yes | none | Merge result |
| `created_at` | datetime | yes | now | UTC creation time |

#### `DevelopReport`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `run_id` | `RunID` | yes | none | Run ID |
| `passed` | bool | yes | none | Develop result |
| `workers` | list[`Worker`] | yes | `[]` | Final workers |
| `tasks_total` | int | yes | `0` | Total tasks |
| `tasks_passed` | int | yes | `0` | Passed tasks |
| `tasks_failed` | int | yes | `0` | Failed tasks |
| `tests_command` | string | no | `null` | Test command run |
| `tests_passed` | bool | no | `null` | Test result |
| `created_at` | datetime | yes | now | UTC creation time |

### 8.6 Config Schemas

#### `NexussyConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `version` | string | yes | `"1.0"` |
| `home_dir` | path | yes | `~/.nexussy` |
| `projects_dir` | path | yes | `~/nexussy-projects` |
| `core` | `CoreConfig` | yes | defaults |
| `web` | `WebConfig` | yes | defaults |
| `auth` | `AuthConfig` | yes | defaults |
| `database` | `DatabaseConfig` | yes | defaults |
| `providers` | `ProvidersConfig` | yes | defaults |
| `stages` | `StagesConfig` | yes | defaults |
| `swarm` | `SwarmConfig` | yes | defaults |
| `pi` | `PiConfig` | yes | defaults |
| `sse` | `SSEConfig` | yes | defaults |
| `security` | `SecurityConfig` | yes | defaults |
| `logging` | `LoggingConfig` | yes | defaults |

#### `CoreConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `host` | string | yes | `127.0.0.1` |
| `port` | int | yes | `7771` |
| `cors_allow_origins` | list[string] | yes | `["http://127.0.0.1:7772"]` |

#### `WebConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `host` | string | yes | `127.0.0.1` |
| `port` | int | yes | `7772` |
| `core_base_url` | string | yes | `http://127.0.0.1:7771` |

#### `AuthConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `enabled` | bool | yes | `false` |
| `api_key_env` | string | yes | `NEXUSSY_API_KEY` |
| `header_name` | string | yes | `X-API-Key` |

#### `DatabaseConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `global_path` | path | yes | `~/.nexussy/state.db` |
| `project_relative_path` | string | yes | `.nexussy/state.db` |
| `wal_enabled` | bool | yes | `true` |
| `busy_timeout_ms` | int | yes | `5000` |
| `write_retry_count` | int | yes | `5` |
| `write_retry_base_ms` | int | yes | `100` |

#### `ProvidersConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `default_model` | `ModelString` | yes | `openai/gpt-5.5-fast` |
| `allow_fallback` | bool | yes | `false` |
| `request_timeout_s` | int | yes | `120` |
| `max_retries` | int | yes | `3` |
| `retry_base_ms` | int | yes | `500` |

#### `StageModelConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `model` | `ModelString` | yes | providers default |
| `max_retries` | int | yes | `3` |
| `max_iterations` | int | no | `null` |

#### `StagesConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `interview` | `StageModelConfig` | yes | default model, 3 retries |
| `design` | `StageModelConfig` | yes | default model, 3 retries |
| `validate` | `StageModelConfig` | yes | default model, 2 retries, 3 iterations |
| `plan` | `StageModelConfig` | yes | default model, 3 retries |
| `review` | `StageModelConfig` | yes | default model, 2 retries, 2 iterations |
| `develop` | `DevelopStageConfig` | yes | defaults |

#### `DevelopStageConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `model` | `ModelString` | yes | providers default |
| `orchestrator_model` | `ModelString` | yes | providers default |
| `max_retries` | int | yes | `2` |

#### `SwarmConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `max_workers` | int | yes | `8` |
| `default_worker_count` | int | yes | `2` |
| `worker_task_timeout_s` | int | yes | `900` |
| `worker_start_timeout_s` | int | yes | `30` |
| `file_lock_timeout_s` | int | yes | `120` |
| `file_lock_retry_ms` | int | yes | `250` |
| `merge_strategy` | enum `no_ff|squash` | yes | `no_ff` |

#### `PiConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `command` | string | yes | `pi` |
| `args` | list[string] | yes | `["--rpc"]` |
| `startup_timeout_s` | int | yes | `30` |
| `shutdown_timeout_s` | int | yes | `10` |
| `max_stdout_line_bytes` | int | yes | `1048576` |

#### `SSEConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `heartbeat_interval_s` | int | yes | `15` |
| `client_queue_max_events` | int | yes | `1000` |
| `replay_max_events` | int | yes | `10000` |
| `retry_ms` | int | yes | `3000` |

#### `SecurityConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `scrub_logs` | bool | yes | `true` |
| `reject_symlink_escape` | bool | yes | `true` |
| `keyring_service` | string | yes | `nexussy` |

#### `LoggingConfig`

| Field | Type | Required | Default |
|---|---|---:|---|
| `level` | enum `DEBUG|INFO|WARNING|ERROR` | yes | `INFO` |
| `core_log_file` | path | yes | `/tmp/nexussy-core.log` |
| `web_log_file` | path | yes | `/tmp/nexussy-web.log` |
| `tui_log_file` | path | yes | `/tmp/nexussy-tui.log` |

## 9. SSE Contract

### 9.1 Frame Format

Every SSE frame MUST use this shape:

```text
id: <event_id>
event: <type>
retry: 3000
data: {"event_id":"...","sequence":1,"contract_version":"1.0","type":"heartbeat","session_id":"...","run_id":"...","ts":"2026-04-27T00:00:00Z","source":"core","payload":{...}}

```

`data: [DONE]` MUST NOT be used. Completion MUST use the `done` event.

### 9.2 `EventEnvelope`

| Field | Type | Required | Default | Description |
|---|---|---:|---|---|
| `event_id` | `EventID` | yes | generated | Stable event ID |
| `sequence` | int | yes | incrementing | Monotonic per run |
| `contract_version` | string | yes | `"1.0"` | Contract version |
| `type` | `SSEEventType` | yes | none | Event type |
| `session_id` | `SessionID` | yes | none | Session ID |
| `run_id` | `RunID` | yes | none | Run ID |
| `ts` | datetime | yes | now | UTC timestamp |
| `source` | enum `core|worker|tui|web` | yes | `core` | Emitter |
| `payload` | event payload schema | yes | none | Payload |

### 9.3 SSE Event Payloads

| Event | Payload schema | Description | Emits | Consumes |
|---|---|---|---|---|
| `heartbeat` | `HeartbeatPayload` | Keeps connection alive | A, C proxy | B, C browser |
| `run_started` | `RunSummary` | Run creation acknowledged | A | B, C |
| `content_delta` | `ContentDeltaPayload` | Streaming model text | A | B, C |
| `tool_call` | `ToolCallPayload` | Tool call started | A | B, C |
| `tool_output` | `ToolOutputPayload` | Tool call finished | A | B, C |
| `tool_progress` | `ToolProgressPayload` | Tool progress update | A | B, C |
| `stage_transition` | `StageTransitionPayload` | Stage changed | A | B, C |
| `stage_status` | `StageStatusSchema` | Stage status snapshot | A | B, C |
| `checkpoint_saved` | `CheckpointPayload` | Checkpoint persisted | A | B, C |
| `artifact_updated` | `ArtifactUpdatedPayload` | Artifact changed | A | B, C |
| `worker_spawned` | `Worker` | Worker created | A | B, C |
| `worker_status` | `Worker` | Worker status changed | A | B, C |
| `worker_task` | `WorkerTaskPayload` | Worker task changed | A | B, C |
| `worker_stream` | `WorkerStreamPayload` | Sanitized worker JSONL/stdout/stderr line | A | B, C |
| `file_claimed` | `FileLock` | File lock acquired | A | B, C |
| `file_released` | `FileLock` | File lock released | A | B, C |
| `file_lock_waiting` | `FileLock` | Worker waits on lock | A | B, C |
| `git_event` | `GitEventPayload` | Worktree/merge/artifact extraction update | A | B, C |
| `blocker_created` | `Blocker` | Blocker opened | A | B, C |
| `blocker_resolved` | `Blocker` | Blocker resolved | A | B, C |
| `cost_update` | `TokenUsage` | Usage update | A | B, C |
| `pause_state_changed` | `PausePayload` | Pause/resume state changed | A | B, C |
| `pipeline_error` | `ErrorResponse` | Recoverable or fatal error | A | B, C |
| `done` | `DonePayload` | Run stream complete | A | B, C |

#### Payload Field Tables

`HeartbeatPayload`: `ts: datetime` required, `server_status: string` required default `ok`.

`ContentDeltaPayload`: `message_id: string` required, `stage: StageName` required, `worker_id: WorkerID|null` default `null`, `role: string` required, `delta: string` required, `final: bool` default `false`.

`ToolCallPayload`: `call_id: string` required, `stage: StageName` required, `worker_id: WorkerID|null` default `null`, `tool_name: ToolName` required, `arguments: dict[str, JsonValue]` default `{}`.

`ToolOutputPayload`: `call_id: string` required, `stage: StageName` required, `worker_id: WorkerID|null` default `null`, `success: bool` required, `result_text: string` default `""`, `display: ToolDisplay|null` default `null`, `error: ErrorResponse|null` default `null`.

`ToolProgressPayload`: `call_id: string` required, `stage: StageName` required, `worker_id: WorkerID|null` default `null`, `message: string` required, `percent: float|null` default `null`.

`StageTransitionPayload`: `from_stage: StageName|null` default `null`, `to_stage: StageName` required, `from_status: StageRunStatus|null` default `null`, `to_status: StageRunStatus` required, `reason: string` required.

`CheckpointPayload`: `checkpoint_id: string` required, `stage: StageName` required, `path: RelativePath` required, `sha256: string` required, `created_at: datetime` required.

`ArtifactUpdatedPayload`: `artifact: ArtifactRef` required, `action: enum created|updated|deleted` required, `anchor: string|null` default `null`.

`WorkerTaskPayload`: `worker_id: WorkerID` required, `task_id: TaskID` required, `phase_number: int|null` default `null`, `task_title: string` required, `status: WorkerTaskStatus` required.

`WorkerStreamPayload`: `worker_id: WorkerID` required, `stream_kind: enum rpc|stdout|stderr` required, `line: string` required, `parsed: bool` default `false`, `truncated: bool` default `false`.

`GitEventPayload`: `action: GitEventAction` required, `worker_id: WorkerID|null` default `null`, `branch_name: string|null` default `null`, `commit_sha: string|null` default `null`, `paths: list[RelativePath]` default `[]`, `message: string` required.

`PausePayload`: `paused: bool` required, `reason: string` required, `requested_by: string` default `api`.

`DonePayload`: `final_status: RunStatus` required, `summary: string` required, `artifacts: list[ArtifactRef]` default `[]`, `usage: TokenUsage` required, `error: ErrorResponse|null` default `null`.

### 9.4 SSE Reliability

1. A MUST persist each event to SQLite before broadcasting it.
2. A MUST increment `sequence` by one per run.
3. A MUST accept `Last-Event-ID` on stream routes.
4. A MUST replay persisted events after `Last-Event-ID` before streaming live events.
5. A MUST emit `heartbeat` every `sse.heartbeat_interval_s` seconds.
6. A MUST keep a bounded queue of `sse.client_queue_max_events` per client.
7. A MUST emit `pipeline_error` with `error_code="sse_client_slow"` and close the connection when a client queue overflows.
8. C MUST proxy SSE without buffering and MUST preserve `id`, `event`, `retry`, and `data` lines.
9. B and C browser code MUST reconnect using EventSource and MUST rely on `Last-Event-ID` replay.

## 10. HTTP API Contract

Base URL: `http://127.0.0.1:7771`.

Auth: When `auth.enabled=true`, every route except `GET /health` MUST require header `X-API-Key: <NEXUSSY_API_KEY>`. Missing or invalid keys MUST return 401 `unauthorized`.

All error responses MUST use `ErrorResponse`.

### 10.1 Health

| Method | Path | Request | Success response | Error responses | Owner |
|---|---|---|---|---|---|
| GET | `/health` | none | `HealthResponse` | 500 `internal_error` | A |

`HealthResponse`: `ok: bool=true`, `status: string="ok"`, `version: string`, `contract_version: string="1.0"`, `db_ok: bool`, `providers_configured: list[string]`, `pi_available: bool`.

### 10.2 Sessions

| Method | Path | Request | Success response | Error responses | Owner |
|---|---|---|---|---|---|
| POST | `/sessions` | `SessionCreateRequest` | `SessionDetail` | 400 `validation_error`, 409 `conflict`, 500 `internal_error` | A |
| GET | `/sessions` | query `limit:int=50`, `offset:int=0` | `list[SessionSummary]` | 400 `bad_request`, 500 `internal_error` | A |
| GET | `/sessions/{session_id}` | path `session_id` | `SessionDetail` | 404 `not_found`, 500 `internal_error` | A |
| DELETE | `/sessions/{session_id}` | path `session_id`, query `delete_files:bool=false` | `ControlResponse` | 404 `not_found`, 409 `conflict`, 500 `internal_error` | A |

### 10.3 Pipeline

| Method | Path | Request | Success response | Error responses | Owner |
|---|---|---|---|---|---|
| POST | `/pipeline/start` | `PipelineStartRequest` | `RunStartResponse` | 400 `validation_error`, 409 `conflict`, 503 `provider_unavailable`, 500 `internal_error` | A |
| GET | `/pipeline/runs/{run_id}/stream` | path `run_id`, header `Last-Event-ID` optional | SSE `EventEnvelope` stream | 404 `not_found`, 409 `run_not_active`, 500 `internal_error` | A |
| GET | `/pipeline/status` | query `run_id` required | `PipelineStatusResponse` | 404 `not_found`, 500 `internal_error` | A |
| POST | `/pipeline/inject` | `PipelineInjectRequest` | `ControlResponse` | 404 `not_found`, 409 `run_not_active`, 500 `internal_error` | A |
| POST | `/pipeline/pause` | body `{run_id: RunID, reason: string="user"}` | `ControlResponse` | 404 `not_found`, 409 `run_not_active`, 500 `internal_error` | A |
| POST | `/pipeline/resume` | body `{run_id: RunID}` | `ControlResponse` | 404 `not_found`, 409 `run_not_active`, 500 `internal_error` | A |
| POST | `/pipeline/skip` | `StageSkipRequest` | `ControlResponse` | 400 `stage_not_ready`, 404 `not_found`, 409 `conflict` | A |
| POST | `/pipeline/cancel` | body `{run_id: RunID, reason: string}` | `ControlResponse` | 404 `not_found`, 409 `run_not_active`, 500 `internal_error` | A |

### 10.4 Artifacts

| Method | Path | Request | Success response | Error responses | Owner |
|---|---|---|---|---|---|
| GET | `/pipeline/artifacts` | query `session_id` required, `run_id` optional | `ArtifactManifestResponse` | 404 `not_found`, 500 `internal_error` | A |
| GET | `/pipeline/artifacts/{kind}` | query `session_id` required, `phase_number` optional | `ArtifactContentResponse` | 400 `bad_request`, 404 `not_found`, 500 `internal_error` | A |

### 10.5 Swarm

| Method | Path | Request | Success response | Error responses | Owner |
|---|---|---|---|---|---|
| GET | `/swarm/workers` | query `run_id` required | `list[Worker]` | 404 `not_found`, 500 `internal_error` | A |
| GET | `/swarm/workers/{worker_id}` | path `worker_id`, query `run_id` required | `Worker` | 404 `worker_not_found`, 500 `internal_error` | A |
| POST | `/swarm/spawn` | `WorkerSpawnRequest` | `Worker` | 400 `validation_error`, 409 `conflict`, 500 `internal_error` | A |
| POST | `/swarm/assign` | `WorkerAssignRequest` | `Worker` | 404 `worker_not_found`, 409 `worker_unavailable`, 500 `internal_error` | A |
| GET | `/swarm/workers/{worker_id}/stream` | path `worker_id`, query `run_id`, header `Last-Event-ID` optional | SSE `EventEnvelope` stream filtered by worker | 404 `worker_not_found`, 500 `internal_error` | A |
| POST | `/swarm/workers/{worker_id}/inject` | `WorkerInjectRequest` | `ControlResponse` | 404 `worker_not_found`, 409 `worker_unavailable`, 500 `internal_error` | A |
| POST | `/swarm/workers/{worker_id}/stop` | body `{run_id: RunID, reason: string}` | `ControlResponse` | 404 `worker_not_found`, 500 `internal_error` | A |
| GET | `/swarm/file-locks` | query `run_id` required | `list[FileLock]` | 404 `not_found`, 500 `internal_error` | A |

### 10.6 Config, Secrets, Memory, Graph, Events

| Method | Path | Request | Success response | Error responses | Owner |
|---|---|---|---|---|---|
| GET | `/config` | none | `NexussyConfig` | 500 `internal_error` | A |
| PUT | `/config` | `NexussyConfig` | `NexussyConfig` | 400 `validation_error`, 500 `internal_error` | A |
| GET | `/secrets` | none | `list[SecretSummary]` | 500 `internal_error` | A |
| PUT | `/secrets/{name}` | body `{value: string}` | `SecretSummary` | 400 `bad_request`, 500 `internal_error` | A |
| DELETE | `/secrets/{name}` | path `name` | `ControlResponse` | 404 `not_found`, 500 `internal_error` | A |
| GET | `/memory` | query `session_id` optional | `list[MemoryEntry]` | 500 `internal_error` | A |
| POST | `/memory` | `MemoryEntryCreateRequest` | `MemoryEntry` | 400 `validation_error`, 500 `internal_error` | A |
| DELETE | `/memory/{memory_id}` | path `memory_id` | `ControlResponse` | 404 `not_found`, 500 `internal_error` | A |
| GET | `/graph` | query `session_id` optional, `run_id` optional | `GraphResponse` | 400 `bad_request`, 500 `internal_error` | A |
| GET | `/events` | query `run_id` required, `after_sequence:int=0`, `limit:int=500` | `list[EventEnvelope]` | 404 `not_found`, 500 `internal_error` | A |

`SecretSummary`: `name:string`, `source: enum keyring|env|config`, `configured:bool`, `updated_at:datetime|null`.

`MemoryEntryCreateRequest`: `session_id:SessionID|null`, `key:string`, `value:string`, `tags:list[string]=[]`.

`MemoryEntry`: `memory_id:string`, `session_id:SessionID|null`, `key:string`, `value:string`, `tags:list[string]`, `created_at:datetime`, `updated_at:datetime`.

`GraphResponse`: `nodes:list[GraphNode]`, `edges:list[GraphEdge]`.

`GraphNode`: `id:string`, `label:string`, `kind:enum session|run|stage|worker|artifact|file|task`, `status:string|null`, `metadata:dict[str, JsonValue]={}`.

`GraphEdge`: `source:string`, `target:string`, `kind:string`, `metadata:dict[str, JsonValue]={}`.

### 10.7 Web Proxy Contract

C MUST expose `http://127.0.0.1:7772`.

| Method | Path | Behavior | Owner |
|---|---|---|---|
| GET | `/` | Serve `templates/index.html` | C |
| any | `/api/{path:path}` | Proxy to `http://127.0.0.1:7771/{path}` | C |
| GET | `/api/pipeline/runs/{run_id}/stream` | Proxy SSE without buffering | C |
| GET | `/api/swarm/workers/{worker_id}/stream` | Proxy SSE without buffering | C |

C MUST NOT implement business logic. C MUST render data returned by A.

## 11. Pipeline State Machine

### 11.1 Stage Order

The only automatic forward order is:

`interview -> design -> validate -> plan -> review -> develop`

`review` failure returns to `plan`. `validate` failure enters correction and retries `validate`. `develop` failure leaves the run `blocked` or `failed` based on the failure kind.

### 11.2 Stage Contract Table

| Stage | Entry condition | Inputs | Outputs | Success condition | Failure condition | Retry behavior |
|---|---|---|---|---|---|---|
| interview | Session exists and run status is `created` or previous checkpoint targets `interview` | `PipelineStartRequest`, existing repo summary when supplied | `interview.json`, `complexity_profile.json`, checkpoint | Both JSON files validate; complexity has level, score, phase count | User cancellation, provider failure after retries, invalid JSON after retries | Save checkpoint after each question batch; retry provider calls `stages.interview.max_retries` |
| design | Interview stage passed | `interview.json`, `complexity_profile.json` | `design_draft.md`, checkpoint | Markdown contains Goals, Architecture, Dependencies, Risks, Test Strategy | Provider failure after retries, missing required sections | Retry provider calls `stages.design.max_retries` |
| validate | Design stage passed | `design_draft.md`, interview and complexity artifacts | `validated_design.md`, `validation_report.json`, checkpoint | Report `passed=true`; no issue with `fix_required=true` | Iterations exceed `stages.validate.max_iterations`; blocker issue remains | Run rule checks, LLM reviewer, correction loop; retry provider calls `stages.validate.max_retries` per iteration |
| plan | Validate stage passed or review returned feedback | `validated_design.md`, `validation_report.json`, optional review feedback | `devplan.md`, `handoff.md`, `phaseNNN.md`, checkpoint | All anchors exist; phase count equals complexity profile; every task has owner, acceptance criteria, tests | Missing anchors, schema mismatch, provider failure after retries | Retry provider calls `stages.plan.max_retries`; include review feedback on review loop |
| review | Plan stage passed | `devplan.md`, `handoff.md`, all phase files | `review_report.json`, checkpoint | Report `passed=true`; no blocking plan issue | Review iterations exceed `stages.review.max_iterations` | On fail, emit transition to `plan` and inject `feedback_for_plan_stage` |
| develop | Review stage passed | All plan artifacts, project repo, provider config | worktrees, worker events, merge report, changed files manifest, develop report, final handoff update | All required tasks passed or explicitly skipped; merges complete; configured tests pass or no test command exists | Worker unrecoverable failure, merge conflict, file lock timeout, subprocess failure, test failure | Retry failed worker task up to `stages.develop.max_retries`; pause creates checkpoint; resume restarts from checkpoint |

### 11.3 Complexity Scoring

A MUST compute complexity deterministically before any LLM override:

| Signal | Points |
|---|---:|
| One language, no persistence, no auth, no external APIs | +5 |
| Multiple languages | +10 |
| Database or persistence | +10 |
| Auth/security-sensitive work | +15 |
| External API integrations | +10 |
| UI plus backend | +15 |
| Deployment/infra requirement | +10 |
| Existing repo migration | +10 |
| Explicit test/QA complexity | +10 |
| Ambiguous requirements | +15 |

`0-25` => `minimal`, `phase_count=2`, `task_group_size=3`.

`26-60` => `standard`, `phase_count=4`, `task_group_size=4`.

`61-100` => `detailed`, `phase_count=6`, `task_group_size=5`.

LLM output MUST NOT increase phase count above this rubric without setting `ComplexityProfile.signals["llm_adjustment"]` and recording rationale.

## 12. Artifact System

### 12.1 Anchor Constants

A and D MUST document these anchors. A MUST validate them before writes.

| Constant | Value | Required file |
|---|---|---|
| `PROGRESS_LOG_START` | `<!-- PROGRESS_LOG_START -->` | `devplan.md` |
| `PROGRESS_LOG_END` | `<!-- PROGRESS_LOG_END -->` | `devplan.md` |
| `NEXT_TASK_GROUP_START` | `<!-- NEXT_TASK_GROUP_START -->` | `devplan.md` |
| `NEXT_TASK_GROUP_END` | `<!-- NEXT_TASK_GROUP_END -->` | `devplan.md` |
| `PHASE_TASKS_START` | `<!-- PHASE_TASKS_START -->` | `phaseNNN.md` |
| `PHASE_TASKS_END` | `<!-- PHASE_TASKS_END -->` | `phaseNNN.md` |
| `PHASE_PROGRESS_START` | `<!-- PHASE_PROGRESS_START -->` | `phaseNNN.md` |
| `PHASE_PROGRESS_END` | `<!-- PHASE_PROGRESS_END -->` | `phaseNNN.md` |
| `QUICK_STATUS_START` | `<!-- QUICK_STATUS_START -->` | `handoff.md` |
| `QUICK_STATUS_END` | `<!-- QUICK_STATUS_END -->` | `handoff.md` |
| `HANDOFF_NOTES_START` | `<!-- HANDOFF_NOTES_START -->` | `handoff.md` |
| `HANDOFF_NOTES_END` | `<!-- HANDOFF_NOTES_END -->` | `handoff.md` |
| `SUBAGENT_A_ASSIGNMENT_START` | `<!-- SUBAGENT_A_ASSIGNMENT_START -->` | `handoff.md` |
| `SUBAGENT_A_ASSIGNMENT_END` | `<!-- SUBAGENT_A_ASSIGNMENT_END -->` | `handoff.md` |
| `SUBAGENT_B_ASSIGNMENT_START` | `<!-- SUBAGENT_B_ASSIGNMENT_START -->` | `handoff.md` |
| `SUBAGENT_B_ASSIGNMENT_END` | `<!-- SUBAGENT_B_ASSIGNMENT_END -->` | `handoff.md` |
| `SUBAGENT_C_ASSIGNMENT_START` | `<!-- SUBAGENT_C_ASSIGNMENT_START -->` | `handoff.md` |
| `SUBAGENT_C_ASSIGNMENT_END` | `<!-- SUBAGENT_C_ASSIGNMENT_END -->` | `handoff.md` |
| `SUBAGENT_D_ASSIGNMENT_START` | `<!-- SUBAGENT_D_ASSIGNMENT_START -->` | `handoff.md` |
| `SUBAGENT_D_ASSIGNMENT_END` | `<!-- SUBAGENT_D_ASSIGNMENT_END -->` | `handoff.md` |

### 12.2 Safe Write Rules

A MUST implement safe artifact writes with this sequence:

1. Resolve the target path through the path sanitizer.
2. Validate required anchors for the target artifact kind.
3. Write a `.bak` copy when the file exists.
4. Write new content to `<path>.tmp`.
5. Re-read `<path>.tmp` and validate anchors again.
6. Atomically replace the target path.
7. Emit `artifact_updated` SSE.
8. Persist artifact metadata to SQLite.

If validation fails, A MUST keep `<path>.tmp`, MUST NOT replace the original file, and MUST raise `validation_error`.

### 12.3 Token Budget

Agents MUST read anchored sections only unless debugging artifact corruption.

| File | Section | Token target | Read timing |
|---|---|---:|---|
| `handoff.md` | QUICK_STATUS | 200 | Start of every session |
| `handoff.md` | matching SUBAGENT assignment | 200 | Start of subagent task |
| `devplan.md` | NEXT_TASK_GROUP | 100 | Every work turn |
| `devplan.md` | PROGRESS_LOG | 100 | When status context is required |
| `phaseNNN.md` | PHASE_TASKS | 80 | When working that phase |
| `phaseNNN.md` | PHASE_PROGRESS | 80 | Before updating phase status |

Target artifact context per turn: 500 tokens or less.

## 13. Swarm Engine Contract

### 13.1 Roles

The orchestrator MUST exist for every develop run. Worker roles MUST be created only when the plan contains tasks for that role.

| Role | Purpose | Tool permissions |
|---|---|---|
| orchestrator | Delegates, monitors, merges, updates plan artifacts | `spawn_worker`, `assign_task`, `get_swarm_state`, `read_file`, `write_file` for plan artifacts only |
| backend | API, DB, server code | Worker tools |
| frontend | TUI/web UI code | Worker tools |
| qa | Tests, review, verification | Worker tools |
| devops | Installer, CI, deployment | Worker tools |
| writer | Docs and API docs | Worker tools |
| analyst | Research and design exploration | `read_file`, `list_files`, `search_code`, `claim_file`, `release_file` |

Worker tools are `read_file`, `write_file`, `edit_file`, `bash`, `list_files`, `search_code`, `claim_file`, `release_file`.

A MUST reject unauthorized tool calls with `forbidden` and emit `tool_output` with `success=false`.

### 13.2 Worktree Lifecycle

For each worker A MUST:

1. Ensure project main worktree is a git repo.
2. Record `base_commit` before spawning workers.
3. Create branch `worker/<worker_id>`.
4. Create worktree at `workers/<worker_id>/` with `git worktree add <path> -b worker/<worker_id> <base_commit>`.
5. Start the Pi subprocess with `cwd` set to the worker worktree.
6. On task completion, verify clean process exit and collect git diff.
7. Commit worker changes on `worker/<worker_id>` with message `nexussy: <worker_id> <task_id>`.
8. Merge to main using `git merge --no-ff worker/<worker_id>` when `swarm.merge_strategy=no_ff`.
9. On merge conflict, abort merge, mark run `blocked`, emit `git_event` with `merge_conflict`, and keep the worktree.
10. On success, remove worktree with `git worktree remove <path>` and delete branch after merge.
11. Run `git worktree prune` after all workers finish.
12. Extract changed files with `git diff --name-status <base_commit>..<merge_commit>`.

### 13.3 File Locking

A MUST store file locks in SQLite table `file_locks` with unique active key `(run_id, path)`.

`claim_file(path, worker_id)` MUST:

1. Sanitize `path` as a project-relative path.
2. Use `BEGIN IMMEDIATE`.
3. Delete expired locks for the same run.
4. Insert lock when no active lock exists.
5. Emit `file_claimed`.
6. On conflict, emit `file_lock_waiting`, sleep `file_lock_retry_ms`, and retry until `file_lock_timeout_s`.
7. Return `file_locked` after timeout.

`release_file(path, worker_id)` MUST release only locks owned by that worker. Releasing another worker's lock MUST return `forbidden`.

### 13.4 Pause, Resume, Skip, Blocker

Pause MUST stop assigning new tasks, send cancellation to running workers, checkpoint active task state, and keep worktrees.

Resume MUST reload checkpoint, restart required Pi subprocesses, and requeue unfinished tasks.

Skip MUST require a reason, mark the stage or task skipped, update `handoff.md`, and emit `stage_status` or `worker_task`.

A blocker MUST set run status `blocked` when severity is `blocker`. Resolving all blocker-severity blockers MUST restore the previous run status.

## 14. Pi RPC Subprocess Contract

A owns all Pi subprocess integration. B and C MUST NOT talk to Pi directly.

### 14.1 Spawn Command

A MUST spawn workers using:

`<pi.command> <pi.args...>`

Default resolved command: `pi --rpc`.

A MUST set environment:

| Env var | Value |
|---|---|
| `NEXUSSY_RUN_ID` | run ID |
| `NEXUSSY_WORKER_ID` | worker ID |
| `NEXUSSY_WORKER_ROLE` | worker role |
| `NEXUSSY_PROJECT_ROOT` | main worktree path |
| `NEXUSSY_WORKTREE` | worker worktree path |
| `NEXUSSY_CORE_BASE_URL` | core base URL |

### 14.2 JSONL Framing

A MUST treat Pi RPC stdio as newline-delimited JSON.

A MUST send messages shaped as:

```json
{"jsonrpc":"2.0","id":"<request-id>","method":"agent.run","params":{"task":"...","context":"..."}}
```

A MUST accept response lines shaped as:

```json
{"jsonrpc":"2.0","id":"<request-id>","result":{"status":"ok"}}
```

A MUST accept notification lines shaped as:

```json
{"jsonrpc":"2.0","method":"agent.event","params":{"type":"content_delta","payload":{}}}
```

A MUST map unknown Pi events to `worker_stream` with `parsed=false` instead of failing the run.

### 14.3 Subprocess Safety

A MUST:

1. Start each worker in a new process group.
2. Drain stdout and stderr concurrently.
3. Reject stdout or stderr lines over `pi.max_stdout_line_bytes` by truncating and setting `truncated=true`.
4. Scrub logs before persistence or SSE emission.
5. Terminate process group on cancellation.
6. Send graceful shutdown and wait `pi.shutdown_timeout_s` before kill.
7. Mark worker `failed` on nonzero exit unless cancellation was requested.

## 15. Provider System

A MUST use LiteLLM for provider calls.

### 15.1 Provider Discovery

| Env var | Provider prefix |
|---|---|
| `OPENAI_API_KEY` | `openai/` |
| `ANTHROPIC_API_KEY` | `anthropic/` |
| `OPENROUTER_API_KEY` | `openrouter/` |
| `GROQ_API_KEY` | `groq/` |
| `GEMINI_API_KEY` | `google/` |
| `MISTRAL_API_KEY` | `mistral/` |
| `TOGETHER_API_KEY` | `together/` |
| `FIREWORKS_API_KEY` | `fireworks/` |
| `XAI_API_KEY` | `xai/` |
| `GLM_API_KEY` | `zai/` |
| `ZAI_API_KEY` | `zai/` |
| `REQUESTY_API_KEY` | `requesty/` |
| `AETHER_API_KEY` | `aether/` |
| `OLLAMA_BASE_URL` | `ollama/` |

A MUST validate the selected model before the first provider call in a run. When `providers.allow_fallback=false`, unavailable models MUST return `model_unavailable`. When `providers.allow_fallback=true`, fallback MUST use `providers.default_model` and emit `pipeline_error` with `retryable=true`.

### 15.2 Rate-Limit Persistence

A MUST persist provider rate-limit events to SQLite with fields: `provider`, `model`, `reset_at`, `reason`, `created_at`. Before starting a provider call, A MUST block calls whose provider/model has an active `reset_at` in the future and return `rate_limited`.

## 16. SQLite Contract

A MUST initialize both global and project DBs with:

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
```

A MUST use one async writer lane per DB file and separate read connections. Long-running LLM calls, subprocess waits, and filesystem scans MUST NOT occur inside a SQLite transaction.

Required tables:

| Table | Required columns |
|---|---|
| `sessions` | `session_id`, `project_slug`, `project_name`, `status`, `created_at`, `updated_at` |
| `runs` | `run_id`, `session_id`, `status`, `current_stage`, `started_at`, `finished_at`, `usage_json` |
| `stage_runs` | `run_id`, `stage`, `status`, `attempt`, `started_at`, `finished_at`, `error_json` |
| `events` | `event_id`, `run_id`, `sequence`, `type`, `payload_json`, `created_at` |
| `artifacts` | `run_id`, `kind`, `path`, `sha256`, `bytes`, `updated_at` |
| `checkpoints` | `checkpoint_id`, `run_id`, `stage`, `path`, `sha256`, `created_at` |
| `workers` | `worker_id`, `run_id`, `role`, `status`, `task_id`, `worktree_path`, `branch_name`, `pid`, `usage_json`, `last_error_json` |
| `worker_tasks` | `task_id`, `run_id`, `worker_id`, `phase_number`, `title`, `status`, `created_at`, `updated_at` |
| `file_locks` | `run_id`, `path`, `worker_id`, `status`, `claimed_at`, `expires_at` |
| `rate_limits` | `provider`, `model`, `reset_at`, `reason`, `created_at` |
| `memory_entries` | `memory_id`, `session_id`, `key`, `value`, `tags_json`, `created_at`, `updated_at` |

## 17. Security Contract

A MUST implement:

1. Path sanitizer rejecting absolute paths outside allowed roots.
2. Symlink escape rejection.
3. Log scrubber for API keys, bearer tokens, passwords, SSH keys, and provider secrets.
4. Keyring storage with service name `security.keyring_service`.
5. `.env` fallback only when keyring is unavailable or disabled by config.
6. API key auth when `auth.enabled=true`.
7. CORS limited to configured origins.
8. Worker subprocess `cwd` locked to the worker worktree.
9. Worker write tools blocked unless file lock is held.
10. Shell commands logged after scrubbing.

## 18. TUI Contract

B MUST implement a TypeScript/Bun TUI using OpenTUI as the default renderer. The previous Pi TUI renderer remains available with `NEXUSSY_TUI_RENDERER=pi-tui`, and B MUST keep the `@mariozechner/pi-tui`, `@mariozechner/pi-ai`, and `@mariozechner/pi-agent-core` package probes/compatibility paths available through npm.

B MUST communicate with A exclusively through `tui/src/client.ts`.

### 18.1 Layout

B MUST render three panels:

| Panel | Content |
|---|---|
| Left | Agent roster, stage progress, worker status |
| Center | Chat/stream log, collapsible tool rows, input bar |
| Right | DevPlan anchor viewer, token/cost meter, file activity |

### 18.2 Slash Commands

| Command | API call |
|---|---|
| `/stage <stage>` | `POST /pipeline/skip` for completed skip or status navigation in UI only |
| `/spawn <role> <task>` | `POST /swarm/spawn` |
| `/inject [worker_id] <message>` | `POST /pipeline/inject` or `POST /swarm/workers/{worker_id}/inject` |
| `/pause <reason>` | `POST /pipeline/pause` |
| `/resume` | `POST /pipeline/resume` |
| `/export` | Local Pi HTML export of displayed session data |

B MUST implement SSE reconnect with `Last-Event-ID`.

## 19. Web Dashboard Contract

C MUST implement a single-file Starlette dashboard on port 7772. C MUST NOT require npm or a build step.

`web/nexussy_web/templates/index.html` MUST include tabs:

| Tab | Required content |
|---|---|
| `#chat` | Stream log, tool rows, cost badge |
| `#pipeline` | Six-stage progress, artifact viewer, transition history, review report |
| `#swarm` | Worker grid, file lock feed, worktree status |
| `#sessions` | Paginated session browser |
| `#devplan` | Live `devplan.md` with highlighted anchors |
| `#graph` | D3 force-directed graph using `/api/graph` |
| `#config` | Config viewer/editor using `/api/config` |
| `#secrets` | Secret status and set/delete controls using `/api/secrets` |

C MUST proxy all `/api/*` routes to A and MUST preserve streaming behavior.

## 20. Installer and Launcher Contract

D MUST implement `install.sh` and `nexussy.sh` in POSIX-compatible Bash.

### 20.1 `install.sh`

`install.sh` MUST:

1. Detect Python 3.11+.
2. Detect Bun 1.x+.
3. Detect `git`.
4. Detect `curl`.
5. Install core with `python -m pip install -e core/`.
6. Install TUI with `cd tui && bun install`.
7. Install web with `python -m pip install -e web/`.
8. Create `~/.nexussy/`, `~/.nexussy/run/`, and `~/.nexussy/logs/`.
9. Generate `~/.nexussy/nexussy.yaml` only when absent.
10. Generate `~/.nexussy/.env` only when absent.
11. Write all provider env var placeholders to `.env`.
12. Prompt for keyring setup only in interactive mode.
13. Generate systemd user service files only when invoked with `--systemd-user`.
14. Run health check by starting core temporarily and calling `GET /health`.
15. Print exact remediation commands on failure.

`install.sh --non-interactive` MUST never prompt.

### 20.2 `nexussy.sh`

`nexussy.sh` MUST support:

| Command | Behavior |
|---|---|
| `start` | Start core and web if not running |
| `start-tui` | Verify core, then start TUI |
| `stop` | Stop TUI, web, and core using PID files |
| `status` | Print health for core, web, tui PID, ports, config path |
| `logs core` | Tail core log |
| `logs web` | Tail web log |
| `logs tui` | Tail TUI log |
| `update` | Run `git pull`, reinstall core/web, run `bun install` |
| `doctor` | Validate dependencies, config, ports, Pi command, provider keys |

## 21. AGENTS.md Contract

D MUST create root `AGENTS.md` with these sections in this order:

1. `READ THIS FIRST` with the statement: "This repository is governed by SPEC.md. Do not infer missing contracts."
2. `SUBAGENT BOUNDARIES` table matching Section 2.1.
3. `THREE-READ HANDOFF PROTOCOL`:
   - Read `handoff.md` between `QUICK_STATUS` anchors.
   - Read the matching subagent assignment anchor.
   - Read `devplan.md` between `NEXT_TASK_GROUP` anchors.
4. `ANCHOR SYSTEM` listing every anchor from Section 12.1.
5. `TOKEN BUDGET` table from Section 12.3.
6. `UPDATE RITUAL` requiring updates to `devplan.md`, current `phaseNNN.md`, and `handoff.md` after every completed task group.
7. `SAFE FILE RULES` requiring safe writes and backups.
8. `TEST COMMANDS` listing each subagent test command.
9. `DO NOT` list: no cross-boundary edits, no secret logging, no full-artifact reads unless needed, no source-code contract discovery across modules.

A cold coding agent MUST locate its assignment within three anchored reads of `handoff.md` and `devplan.md`.

## 22. Subagent A — Core Definition of Done

A is done only when all criteria pass:

1. `python -m pytest -q core/tests` passes.
2. `python -m nexussy.api.server` starts on `127.0.0.1:7771`.
3. `GET /health` returns `ok=true`, `db_ok=true`, and `contract_version="1.0"`.
4. `POST /pipeline/start` with a mock provider creates a run and returns `RunStartResponse`.
5. `GET /pipeline/runs/{run_id}/stream` emits `run_started`, all six ordered stage transitions, `checkpoint_saved`, and `done` using valid `EventEnvelope` JSON.
6. SSE replay with `Last-Event-ID` returns missed events in order.
7. Bad design input forces validate correction and stops after `max_iterations` with `stage_failed`.
8. Bad plan input forces review failure and returns to plan no more than `max_iterations`.
9. File lock tests prove two workers cannot write the same file simultaneously.
10. Git worktree test creates two worker worktrees, commits both, merges both, extracts only changed files, and prunes worktrees.
11. Pi worker adapter passes against a fake JSONL subprocess fixture.
12. Path sanitizer rejects `..`, absolute escape paths, and symlink escapes.
13. Log scrubber redacts all provider key patterns in tests.
14. No file under `tui/`, `web/`, or root owned by D is modified.

## 23. Subagent B — TUI Definition of Done

B is done only when all criteria pass:

1. `bun test` passes in `tui/`.
2. `bun run typecheck` passes in `tui/`.
3. The TUI renders the three-panel layout from mock event fixtures without a running core.
4. `tui/src/client.ts` implements every route from Section 10 used by the TUI.
5. SSE client parses every event from Section 9 and rejects malformed envelopes.
6. SSE client reconnects with `Last-Event-ID` in tests.
7. Slash commands call the exact endpoints in Section 18.2.
8. Tool rows collapse and expand in tests or a scripted demo.
9. Agent roster updates from `worker_spawned`, `worker_status`, and `worker_task` fixtures.
10. No file under `core/`, `web/`, or root owned by D is modified.

## 24. Subagent C — Web Definition of Done

C is done only when all criteria pass:

1. `python -m pytest -q web/tests` passes.
2. `python -m nexussy_web.app` starts on `127.0.0.1:7772`.
3. `/` returns a single HTML document.
4. No npm, Node, bundler, transpiler, or build output is required.
5. `/api/health` proxies to mock or live core.
6. `/api/pipeline/runs/{run_id}/stream` proxies SSE and preserves `id`, `event`, `retry`, and `data` lines.
7. Every tab in Section 19 exists and renders fixture data.
8. DevPlan viewer highlights all anchors from Section 12.1.
9. Config and secrets tabs call only `/api/config` and `/api/secrets` routes.
10. No file under `core/`, `tui/`, or root owned by D is modified.

## 25. Subagent D — Installer Definition of Done

D is done only when all criteria pass:

1. `bash -n install.sh nexussy.sh` passes.
2. `./install.sh --non-interactive` completes on Ubuntu 24.04 with Python 3.11+, Bun 1.x+, git, and curl installed.
3. Running `./install.sh --non-interactive` twice leaves existing config and env files unchanged.
4. `~/.nexussy/nexussy.yaml` contains every config key from Section 6.2.
5. `~/.nexussy/.env` contains every provider env var from Section 6.3.
6. `./nexussy.sh start` starts core and web and writes PID files.
7. `./nexussy.sh status` reports core health, web health, TUI PID state, ports, and config path.
8. `./nexussy.sh stop` stops processes and removes stale PID files.
9. `./nexussy.sh doctor` reports missing Pi command and missing provider keys without crashing.
10. `AGENTS.md` contains every required section from Section 21.
11. `README.md` explains install, start, TUI, web, config, provider keys, and Ussyverse lineage.
12. No file under `core/`, `tui/`, or `web/` is modified.

## 26. Integration Test Matrix

| Test | Required command or behavior | Owner |
|---|---|---|
| Core health | `curl http://127.0.0.1:7771/health` returns `ok=true` | A |
| Web health proxy | `curl http://127.0.0.1:7772/api/health` returns core health | C |
| Pipeline mock run | Mock provider emits six stages in order | A |
| SSE replay | Reconnect with `Last-Event-ID` receives missed event | A, B, C |
| Validate correction | Bad design loops then passes or fails exactly at max iteration | A |
| Review gate | Bad devplan returns to plan and blocks after max review loops | A |
| Worktree isolation | Two workers modify separate files and merge cleanly | A |
| Lock conflict | Two workers target same file and one waits, then succeeds or times out | A |
| Inject | `/inject` reaches running worker fixture | A, B |
| Pause/resume | Pause checkpoints and resume continues from checkpoint | A, B, C |
| Artifact extraction | Manifest contains only files changed since `base_commit` | A |
| TUI render | Fixture stream renders panels and command responses | B |
| Web render | Fixture stream renders all tabs | C |
| Installer | Non-interactive install, start, status, stop pass on Ubuntu 24.04 | D |

## 27. Reference Appendix

### 27.1 CLI Commands

| Command | Owner |
|---|---|
| `./install.sh` | D |
| `./install.sh --non-interactive` | D |
| `./install.sh --systemd-user` | D |
| `./nexussy.sh start` | D |
| `./nexussy.sh start-tui` | D |
| `./nexussy.sh stop` | D |
| `./nexussy.sh status` | D |
| `./nexussy.sh logs core` | D |
| `./nexussy.sh logs web` | D |
| `./nexussy.sh logs tui` | D |
| `./nexussy.sh update` | D |
| `./nexussy.sh doctor` | D |
| `python -m nexussy.api.server` | A |
| `python -m nexussy_web.app` | C |
| `bun run start` from `tui/` | B |
| `python -m pytest -q core/tests` | A |
| `bun test` | B |
| `bun run typecheck` | B |
| `python -m pytest -q web/tests` | C |

### 27.2 Config Keys

`version`, `home_dir`, `projects_dir`, `core.host`, `core.port`, `core.cors_allow_origins`, `web.host`, `web.port`, `web.core_base_url`, `auth.enabled`, `auth.api_key_env`, `auth.header_name`, `database.global_path`, `database.project_relative_path`, `database.wal_enabled`, `database.busy_timeout_ms`, `database.write_retry_count`, `database.write_retry_base_ms`, `providers.default_model`, `providers.allow_fallback`, `providers.request_timeout_s`, `providers.max_retries`, `providers.retry_base_ms`, `stages.interview.model`, `stages.interview.max_retries`, `stages.design.model`, `stages.design.max_retries`, `stages.validate.model`, `stages.validate.max_iterations`, `stages.validate.max_retries`, `stages.plan.model`, `stages.plan.max_retries`, `stages.review.model`, `stages.review.max_iterations`, `stages.review.max_retries`, `stages.develop.model`, `stages.develop.orchestrator_model`, `stages.develop.max_retries`, `swarm.max_workers`, `swarm.default_worker_count`, `swarm.worker_task_timeout_s`, `swarm.worker_start_timeout_s`, `swarm.file_lock_timeout_s`, `swarm.file_lock_retry_ms`, `swarm.merge_strategy`, `pi.command`, `pi.args`, `pi.startup_timeout_s`, `pi.shutdown_timeout_s`, `pi.max_stdout_line_bytes`, `sse.heartbeat_interval_s`, `sse.client_queue_max_events`, `sse.replay_max_events`, `sse.retry_ms`, `security.scrub_logs`, `security.reject_symlink_escape`, `security.keyring_service`, `logging.level`, `logging.core_log_file`, `logging.web_log_file`, `logging.tui_log_file`.

### 27.3 Ports

| Name | Port |
|---|---:|
| Core API | 7771 |
| Web dashboard | 7772 |

### 27.4 API Headers

| Header | Direction | Required |
|---|---|---:|
| `X-API-Key` | request | when auth enabled |
| `Last-Event-ID` | request | optional SSE replay |
| `Content-Type: application/json` | request/response | JSON routes |
| `Content-Type: text/event-stream; charset=utf-8` | response | SSE routes |
| `Cache-Control: no-cache` | response | SSE routes |
| `Connection: keep-alive` | response | SSE routes |

### 27.5 Provider Env Vars

`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `XAI_API_KEY`, `GLM_API_KEY`, `ZAI_API_KEY`, `REQUESTY_API_KEY`, `AETHER_API_KEY`, `OLLAMA_BASE_URL`.

### 27.6 Machine Contract Version

`contract_version` is `1.0` for every API response and every SSE event in this specification. A breaking contract change MUST increment this value.

*End of SPEC.md.*
