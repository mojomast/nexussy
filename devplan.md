# nexussy Implementation Devplan

Scope: graphify-style interview context RAG, OpenHarness-style permission manifests, design context packs, and cost analytics.

No new Python package dependencies are approved in this plan. All graph, permission, design-pack, and cost analytics work must use Python stdlib plus existing project dependencies.

<!-- PROGRESS_LOG_START -->
- 2026-05-01: Phase 0 orientation completed by reading required local architecture files and external READMEs for graphify, OpenHarness, and awesome-design-md.
- 2026-05-01: Phase 1 planning completed with four sequential planning subagents and merged into this implementation devplan.
<!-- PROGRESS_LOG_END -->

## Conflict Resolution

- `core/nexussy/api/schemas.py` is shared by permissions and design packs, so all schema/config work is marked `[SEQUENTIAL]` and must land before dependent feature workers.
- `core/nexussy/config.py` is shared by design-pack config and launcher-adjacent config behavior, so design-pack config lands before UI selection tasks.
- `core/nexussy/swarm/local_pi_worker.py` is only touched by permission hardening in the final plan; graph RAG must not touch it.
- `core/nexussy/pipeline/stages/design.py` and `core/nexussy/pipeline/stages/interview.py` are disjoint after schema work and can run in separate parallel branches.
- `nexussy.sh` and root ops tests are owned by root/ops work and must be sequenced after the core cost CLI exists.

## Execution Order

1. `[SEQUENTIAL]` Land shared schema/config foundations for permission manifests and design context packs.
2. `[PARALLEL-GROUP-A]` Run Graphify RAG and Design Packs core/UI work in separate branches only after shared schema/config foundations are committed.
3. Merge Parallel Group A and make milestone commit: `milestone: graphify RAG + design packs integrated`.
4. `[PARALLEL-GROUP-B]` Run Permission Governance and Cost Analytics in separate branches. Root launcher cost work starts only after core cost CLI is complete.
5. Merge Parallel Group B and make milestone commit: `milestone: permission hardening + cost analytics integrated`.
6. Make final feature milestone commit: `milestone: all 4 features complete — graphify/permissions/design-packs/costs`.
7. Run final verification subagent and release commit.

<!-- NEXT_TASK_GROUP_START -->

## Shared Foundations

### T-001 `[SEQUENTIAL]` Add RoleCapabilityManifest Schema

Description: Add a strict Pydantic `RoleCapabilityManifest` and role-to-capability defaults for `WorkerRole`.

Files to create or modify: `core/nexussy/api/schemas.py`, `core/nexussy/swarm/roles.py`, `core/tests/test_role_capabilities.py`.

Acceptance criteria: Model uses `ConfigDict(extra="forbid")`; every worker role has a manifest; only orchestrator has `spawn_subagent=true`; analyst is read-only; existing `ToolName` compatibility remains intact.

Dependencies: None.

Estimated complexity: medium.

### T-002 `[SEQUENTIAL]` Add DesignStageConfig Context Pack Schema

Description: Add `stages.design.context_pack` with additive defaults and allowed values `stripe`, `linear`, `minimal`, or no pack.

Files to create or modify: `core/nexussy/api/schemas.py`, `core/nexussy/config.py`, `core/tests/test_design_packs.py`.

Acceptance criteria: Existing installs keep current behavior by default; invalid configured pack names fail validation; request metadata convention is documented in tests as `metadata["design_context_pack"]`.

Dependencies: T-001 because both touch `schemas.py`.

Estimated complexity: medium.

## Graphify Integration (Context RAG)

### T-003 `[PARALLEL-GROUP-A]` Add Lightweight Project Graph Contract

Description: Define a local project graph contract for interview context RAG with nodes, edges, communities, file hashes, cache metadata, and `found` versus `inferred` tags.

Files to create or modify: `core/nexussy/swarm/project_graph.py`, `core/tests/test_project_graph.py`.

Acceptance criteria: Graph is JSON-serializable with stdlib; cache metadata includes schema version, worktree root, generated timestamp, and file hashes; summary output is deterministic and bounded; no new dependencies are introduced.

Dependencies: None.

Estimated complexity: medium.

### T-004 `[PARALLEL-GROUP-A]` Implement Graph Cache Build And Reuse

Description: Build/load graph cache under `.nexussy/graph_cache/graph.json` and reprocess only changed files.

Files to create or modify: `core/nexussy/swarm/project_graph.py`, `core/tests/test_project_graph.py`.

Acceptance criteria: Hashes detect added/changed/deleted files; binary and oversized files are skipped; ignored paths include `.git`, `.nexussy/graph_cache`, venvs, dependency folders, build output, and caches; corrupt cache falls back to rebuild.

Dependencies: T-003.

Estimated complexity: medium.

### T-005 `[PARALLEL-GROUP-A]` Add Compressed Graph Summary

Description: Generate compressed project structure, important files, entry points, relationships, communities, and confidence tags.

Files to create or modify: `core/nexussy/swarm/project_graph.py`, `core/tests/test_project_graph.py`.

Acceptance criteria: Summary avoids full raw file lists; labels facts as `found` or `inferred`; prioritizes SPEC, AGENTS, README, package/config files, source roots, tests, and entry points; synthetic large-project test shows at least 50% prompt-character reduction.

Dependencies: T-004.

Estimated complexity: medium.

### T-006 `[PARALLEL-GROUP-A]` Inject Graph Summary Into Interview Stage

Description: Build or load graph summary before interview LLM calls and inject it into interview prompts.

Files to create or modify: `core/nexussy/pipeline/stages/interview.py`, `core/tests/test_interview_graph_context.py`.

Acceptance criteria: Interview prompts receive graph summary before question and auto-answer calls; build failures fall back to minimal context without raw large file dumps; tests verify injection, cache reuse, and prompt safety.

Dependencies: T-005.

Estimated complexity: high.

## Design Stage Context Packs

### T-007 `[PARALLEL-GROUP-A]` Add Built-In Design Pack Assets

Description: Ship built-in `DESIGN.md`-style packs for Stripe, Linear, and Minimal.

Files to create or modify: `core/nexussy/assets/design_packs/stripe.md`, `core/nexussy/assets/design_packs/linear.md`, `core/nexussy/assets/design_packs/minimal.md`.

Acceptance criteria: Each pack covers visual theme, color palette, typography, components, layout, elevation, do/don'ts, responsive behavior, and agent prompt guide; descriptions match the requested Stripe, Linear, and Minimal design intent.

Dependencies: None.

Estimated complexity: low.

### T-008 `[PARALLEL-GROUP-A]` Inject Selected Design Pack In Design Stage

Description: Resolve `metadata["design_context_pack"]` before config `stages.design.context_pack` and inject selected markdown into the design prompt.

Files to create or modify: `core/nexussy/pipeline/stages/design.py`, `core/tests/test_design_packs.py`.

Acceptance criteria: No pack preserves current prompt behavior; metadata override wins over config; missing assets fail clearly; tests verify prompt injection and invalid pack handling.

Dependencies: T-002, T-007.

Estimated complexity: medium.

### T-009 `[PARALLEL-GROUP-A]` Add TUI Design Pack Selection

Description: Add TUI pipeline-start selection for `none`, `stripe`, `linear`, and `minimal`.

Files to create or modify: `tui/src/**`, `tui/tests/**`.

Acceptance criteria: Selected pack is sent as `metadata.design_context_pack`; no selection preserves existing start behavior; `cd tui && bun test` and `cd tui && bun run typecheck` pass.

Dependencies: T-002.

Estimated complexity: medium.

### T-010 `[PARALLEL-GROUP-A]` Add Web Design Pack Selection

Description: Add web dashboard pipeline-start selection for `none`, `stripe`, `linear`, and `minimal`.

Files to create or modify: `web/nexussy_web/**`, `web/tests/**`.

Acceptance criteria: Selected pack is sent as `metadata.design_context_pack`; no selection preserves existing start behavior; `python3 -m pytest -q web/tests` passes.

Dependencies: T-002.

Estimated complexity: medium.

## OpenHarness Permission Governance

### T-011 `[PARALLEL-GROUP-B]` Replace Ad Hoc Role Checks With Manifests

Description: Map tools to manifest capabilities and add a non-throwing permission helper for runtime worker use while preserving `enforce_tool()` for existing callers.

Files to create or modify: `core/nexussy/swarm/roles.py`, `core/tests/test_role_capabilities.py`.

Acceptance criteria: read/list/search map to `read_files`; write/edit map to `write_files`; bash maps to `run_bash`; spawn/assign maps to `spawn_subagent`; orchestrator plan-artifact write restriction remains enforced.

Dependencies: T-001.

Estimated complexity: medium.

### T-012 `[PARALLEL-GROUP-B]` Enforce Manifests In Local Pi Worker

Description: Enforce active worker role permissions before any local tool touches filesystem, subprocess, or model-call behavior.

Files to create or modify: `core/nexussy/swarm/local_pi_worker.py`, `core/tests/test_local_pi_worker.py`.

Acceptance criteria: Role is derived from launch environment, not LLM arguments; denied read/write/bash/list/edit attempts do not execute; allowed worker behavior remains unchanged.

Dependencies: T-011.

Estimated complexity: medium.

### T-013 `[PARALLEL-GROUP-B]` Emit Permission Denials As Failed Tool Output

Description: Convert permission denials into structured `tool_output`-compatible payloads with `success=false` instead of uncaught exceptions or stderr-only events.

Files to create or modify: `core/nexussy/swarm/local_pi_worker.py`, `core/nexussy/swarm/pi_rpc.py`, `core/tests/test_worker_permission_sse.py`.

Acceptance criteria: Denials are fed back to the LLM as tool output; JSON-RPC run does not fail solely because a tool was denied; SSE emits `SSEEventType.tool_output` with a valid failed payload, worker id, and stage `develop`.

Dependencies: T-012.

Estimated complexity: medium.

### T-014 `[PARALLEL-GROUP-B]` Harden Subagent Spawn Permission

Description: Ensure only orchestrator role can initiate worker/subagent creation across runtime/API/MCP paths where role context exists.

Files to create or modify: `core/nexussy/api/server.py`, `core/nexussy/mcp.py`, `core/nexussy/pipeline/stages/develop.py`, `core/nexussy/swarm/roles.py`, `core/tests/test_role_capabilities.py`.

Acceptance criteria: Non-orchestrator spawn attempts are denied with forbidden responses or failed tool output as appropriate; orchestrator develop spawning still works; tests prove non-orchestrator roles cannot spawn.

Dependencies: T-011.

Estimated complexity: medium.

## Cost Analytics Command

### T-015 `[PARALLEL-GROUP-B]` Add Cost Analytics DB Read Helpers

Description: Add read-only helpers using existing SQLite metadata from `runs.usage_json`, `events` cost updates, and `stage_runs` context.

Files to create or modify: `core/nexussy/db.py`, `core/tests/test_cost_analytics.py`.

Acceptance criteria: No schema migrations; single-run mode validates run existence; aggregate mode groups by run and stage; no usage events returns zero per-stage totals plus run-level total when present.

Dependencies: None.

Estimated complexity: medium.

### T-016 `[PARALLEL-GROUP-B]` Add Core Cost CLI Module

Description: Add `python3 -m nexussy.cli.costs [run_id] [--json] [--all]` for per-stage token and cost analytics.

Files to create or modify: `core/nexussy/cli/costs.py`, `core/tests/test_cost_analytics.py`.

Acceptance criteria: Rejects `[run_id]` with `--all`; reads DB path from existing config defaults; does not require API server; human output includes run, stage, token, cost, provider, and model columns; JSON output has deterministic `runs` and `totals` keys.

Dependencies: T-015.

Estimated complexity: medium.

### T-017 `[SEQUENTIAL]` Wire Launcher Analyze-Costs Command

Description: Add `./nexussy.sh analyze-costs [run_id] [--json] [--all]` forwarding to the core CLI module.

Files to create or modify: `nexussy.sh`, `ops_tests.sh`.

Acceptance criteria: Usage includes the new command; launcher sets `PYTHONPATH` to include `core`; arguments are forwarded safely; shell syntax and ops command-help tests pass.

Dependencies: T-016; must be sequenced after core CLI implementation.

Estimated complexity: low.

## Verification Tasks

### T-018 `[SEQUENTIAL]` Feature Branch Verification

Description: Each execution subagent runs focused tests, `python3 -m ruff check` when available, and `python3 -m pytest core/tests/ -x -q` or area-specific suites before committing.

Files to create or modify: none.

Acceptance criteria: Subagents report exact commands and results; if `python` or `ruff` is unavailable, record that and use available `python3` commands without hiding the deviation.

Dependencies: Feature tasks.

Estimated complexity: low.

### T-019 `[SEQUENTIAL]` Final Integration Verification

Description: Run full verification, update `SPEC_COVERAGE.md` if new requirements are added, update `CHANGELOG.md`, and commit release summary.

Files to create or modify: `SPEC_COVERAGE.md` if needed, `CHANGELOG.md`.

Acceptance criteria: `python3 -m pytest core/tests/ -v`, `cd tui && bun test`, `python3 -m pytest web/tests/ -q`, and `bash -n install.sh nexussy.sh` pass; changelog summarizes all four features.

Dependencies: All feature and milestone commits.

Estimated complexity: medium.

<!-- NEXT_TASK_GROUP_END -->
