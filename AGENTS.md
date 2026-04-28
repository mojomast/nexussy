# READ THIS FIRST

This repository is governed by SPEC.md. Do not infer missing contracts.

# SUBAGENT BOUNDARIES

| Subagent | Owns | MUST NOT touch |
|---|---|---|
| A | `core/` | `tui/`, `web/`, `install.sh`, `nexussy.sh`, `AGENTS.md`, `README.md` |
| B | `tui/` | `core/`, `web/`, root scripts, root docs |
| C | `web/` | `core/`, `tui/`, root scripts, root docs |
| D | `install.sh`, `nexussy.sh`, `AGENTS.md`, `README.md`, root packaging notes | `core/`, `tui/`, `web/` implementation files |

# THREE-READ HANDOFF PROTOCOL

1. Read `handoff.md` between `QUICK_STATUS` anchors.
2. Read the matching subagent assignment anchor.
3. Read `devplan.md` between `NEXT_TASK_GROUP` anchors.

# ANCHOR SYSTEM

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

# TOKEN BUDGET

| File | Section | Token target | Read timing |
|---|---|---:|---|
| `handoff.md` | QUICK_STATUS | 200 | Start of every session |
| `handoff.md` | matching SUBAGENT assignment | 200 | Start of subagent task |
| `devplan.md` | NEXT_TASK_GROUP | 100 | Every work turn |
| `devplan.md` | PROGRESS_LOG | 100 | When status context is required |
| `phaseNNN.md` | PHASE_TASKS | 80 | When working that phase |
| `phaseNNN.md` | PHASE_PROGRESS | 80 | Before updating phase status |

Target artifact context per turn: 500 tokens or less.

# UPDATE RITUAL

Update `devplan.md`, the current `phaseNNN.md`, and `handoff.md` after every completed task group.

# SAFE FILE RULES

Resolve paths through the path sanitizer, validate anchors before writes, create backups for existing artifacts, write temporary files first, revalidate temporary content, then atomically replace the target.

# TEST COMMANDS

| Area | Commands |
|---|---|
| Core | `python -m pytest -q core/tests`; `python -m nexussy.api.server` |
| TUI | `cd tui && bun install`; `cd tui && bun test`; `cd tui && bun run typecheck`; `cd tui && bun run start` |
| Web | `python -m pytest -q web/tests`; `python -m nexussy_web.app` |
| Installer | `bash -n install.sh nexussy.sh`; `./install.sh --non-interactive --dry-run`; `./install.sh --non-interactive`; `./nexussy.sh start`; `./nexussy.sh status`; `./nexussy.sh stop`; `./nexussy.sh doctor` |

# DO NOT

- Do not make cross-boundary edits.
- Do not log secrets.
- Do not read full artifacts unless needed to debug corruption.
- Do not discover contracts by reading another module's source code.
- Do not depend on the `ussycode` repository.
