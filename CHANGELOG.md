# Changelog

## [Unreleased]

### Critical

- Fixed SQLite connection cleanup in write paths and added indexes for run, event, artifact, worker task, blocker, checkpoint, and memory lookups.
- Cleared paused run state on interview answer timeout and failed pipeline runs.
- Serialized core server startup initialization with an asyncio lock to prevent global state races.

### Major

- Added pipeline failure logging and worker RPC resume depth guarding.
- Converted git worktree operations to timeout-bounded async subprocess calls.
- Warn when provider secrets fall back to plaintext env-file storage and reuse cached provider env values during completion calls.
- Made SSE event sequencing atomic at insert time.
- Enforced production CORS safety and expanded the MCP start-pipeline input schema.

### Minor

- Hardened root shell scripts with `set -euo pipefail` and safer variable handling.
- Documented production security settings, worker orchestration extension points, interview timeout cleanup, and review-fix status.
