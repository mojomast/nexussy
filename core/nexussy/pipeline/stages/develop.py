from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
from dataclasses import dataclass
from uuid import uuid4

from nexussy.api.schemas import (
    ArtifactRef,
    ChangedFilesManifest,
    DevelopReport,
    GitEventAction,
    GitEventPayload,
    MergeReport,
    SSEEventType,
    StageName,
    Worker,
    WorkerRole,
    WorkerStatus,
    WorkerTaskPayload,
    WorkerTaskStatus,
)
from nexussy.checkpoint import save_checkpoint
from nexussy.swarm.gitops import commit_worker, create_worktree, extract_changed_files, init_repo, merge_no_ff, prune_worktrees, remove_worktree
from nexussy.swarm.pi_rpc import spawn_pi_worker


@dataclass
class WorkerMergeResult:
    worker: Worker
    worker_id: str


_TASK_LINE_RE = re.compile(r"^\s*-\s*(?:\[[ xX]\]\s*)?(?:(T-\d+)\s*[:\-]\s*)?(.+?)\s*$")
_SUB_BULLET_RE = re.compile(r"^(\s+)[-*]\s*(.+?)\s*$")


def _valid_task_specs(value) -> list[dict] | None:
    if not isinstance(value, list):
        return None
    specs: list[dict] = []
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            return None
        title = str(item.get("title") or "").strip()
        if not title:
            return None
        specs.append({
            "id": str(item.get("id") or f"T-{idx:03d}"),
            "title": title,
            "acceptance_criteria": list(item.get("acceptance_criteria") or []),
            "files_allowed": list(item.get("files_allowed") or []),
        })
    return specs or None


def _slice_devplan_tasks(devplan_text: str, devplan_tasks_json: str | None = None) -> list[dict]:
    """Parse a devplan markdown artifact into atomic task specs.

    Each spec has keys: id, title, acceptance_criteria, files_allowed.
    """
    if devplan_text is None:
        raise TypeError("devplan_text must be a string")
    fallback = [{"id": "T-001", "title": "Implement devplan", "acceptance_criteria": [], "files_allowed": []}]
    if devplan_tasks_json:
        try:
            sidecar_specs = _valid_task_specs(json.loads(devplan_tasks_json))
        except Exception:
            sidecar_specs = None
        if sidecar_specs:
            return sidecar_specs
    if not devplan_text.strip():
        return fallback
    lines = devplan_text.splitlines()
    tasks: list[dict] = []
    in_tasks_section = False
    auto_id = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "<!-- NEXT_TASK_GROUP_START -->":
            in_tasks_section = True
            i += 1
            continue
        if stripped == "<!-- NEXT_TASK_GROUP_END -->":
            in_tasks_section = False
            i += 1
            continue
        # Detect heading sections
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            in_tasks_section = ("task" in heading) or heading.startswith("phase ")
            i += 1
            continue
        # Top-level task bullet (no leading indent)
        if in_tasks_section and re.match(r"^-\s", line):
            m = _TASK_LINE_RE.match(line)
            if not m:
                i += 1
                continue
            explicit_id = m.group(1)
            title = (m.group(2) or "").strip()
            if not title:
                i += 1
                continue
            auto_id += 1
            task_id = explicit_id or f"T-{auto_id:03d}"
            acceptance: list[str] = []
            files: list[str] = []
            # Look ahead for indented sub-bullets
            j = i + 1
            while j < len(lines):
                sub = lines[j]
                if not sub.strip():
                    j += 1
                    continue
                sm = _SUB_BULLET_RE.match(sub)
                if not sm:
                    break
                content = sm.group(2)
                low = content.lower()
                if low.startswith("acceptance criteria:") or low.startswith("acceptance:"):
                    _, _, rest = content.partition(":")
                    for piece in rest.split(","):
                        p = piece.strip()
                        if p:
                            acceptance.append(p)
                elif low.startswith("files_allowed:") or low.startswith("files:"):
                    _, _, rest = content.partition(":")
                    for piece in rest.split(","):
                        p = piece.strip()
                        if p:
                            files.append(p)
                j += 1
            tasks.append({"id": task_id, "title": title, "acceptance_criteria": acceptance, "files_allowed": files})
            i = j
            continue
        i += 1
    if not tasks:
        return fallback
    return tasks


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    main = pathlib.Path(root)
    workers_root = main.parent / "workers"
    if allow_mock and not req.metadata.get("fake_pi_command"):
        orch_model = engine.config.stages.develop.orchestrator_model or selected_models.get("develop") or engine.config.providers.default_model
        orch_id = f"orchestrator-{uuid4().hex[:6]}"
        orch = Worker(worker_id=orch_id, run_id=rid, role=WorkerRole.orchestrator, status=WorkerStatus.finished, worktree_path=str(workers_root / orch_id), branch_name=f"worker/{orch_id}", model=orch_model)
        await engine._persist_worker(orch)
        await engine.emit(SSEEventType.worker_spawned, sid, rid, orch)
        return [
            await engine._save_art(rid, sid, root, "develop_report", DevelopReport(run_id=rid, passed=True, workers=[orch], tasks_total=1, tasks_passed=1).model_dump_json(indent=2)),
            await engine._save_art(rid, sid, root, "merge_report", MergeReport(run_id=rid, base_commit="mock", merge_commit="mock", merged_workers=[orch.worker_id], passed=True).model_dump_json(indent=2)),
            await engine._save_art(rid, sid, root, "changed_files", ChangedFilesManifest(run_id=rid, base_commit="mock", merge_commit="mock").model_dump_json(indent=2)),
        ]
    context = await spawn_workers(engine, req, detail, rid, root, selected_models, spawn_fn=kwargs.get("spawn_fn", spawn_pi_worker))
    return await merge_workers(engine, req, detail, rid, root, context)


async def spawn_workers(engine, req, detail, rid, root, selected_models, spawn_fn=spawn_pi_worker):
    sid = detail.session.session_id
    main = pathlib.Path(root)
    workers_root = main.parent / "workers"
    base = await init_repo(str(main))
    await engine.emit(SSEEventType.git_event, sid, rid, GitEventPayload(action=GitEventAction.repo_initialized, commit_sha=base, message="repo initialized"))
    pi_cmd = req.metadata.get("fake_pi_command") or req.metadata.get("pi_command") or os.environ.get("NEXUSSY_PI_COMMAND") or engine.config.pi.command
    cfg = engine.config.model_copy(deep=True)
    cfg.pi.command = pi_cmd
    cfg.pi.args = req.metadata.get("fake_pi_args") or req.metadata.get("pi_args") or cfg.pi.args
    requested_roles = req.metadata.get("worker_roles") or ["backend", "frontend"]
    roles = []
    for raw in requested_roles:
        try:
            roles.append(WorkerRole(raw))
        except Exception:
            pass
    roles = roles[: max(1, min(engine.config.swarm.max_workers, engine.config.swarm.default_worker_count if not req.metadata.get("worker_roles") else len(roles)))] or [WorkerRole.backend]
    orch_model = engine.config.stages.develop.orchestrator_model or selected_models.get("develop") or engine.config.providers.default_model
    orch = Worker(worker_id=f"orchestrator-{uuid4().hex[:6]}", run_id=rid, role=WorkerRole.orchestrator, status=WorkerStatus.running, task_id=f"task-{uuid4().hex[:6]}", task_title="Orchestrate develop run", worktree_path=str(main), branch_name="main", model=orch_model)
    await engine._persist_worker(orch)
    await engine.emit(SSEEventType.worker_spawned, sid, rid, orch)
    return {"sid": sid, "main": main, "workers_root": workers_root, "artifacts_dir": main / ".nexussy" / "artifacts", "base": base, "cfg": cfg, "roles": roles, "orch": orch, "selected_models": selected_models, "spawn_fn": spawn_fn}


async def merge_workers(engine, req, detail, rid, root, context):
    sid = context["sid"]
    main = context["main"]
    artifacts_dir = context["artifacts_dir"]
    base = context["base"]
    roles = context["roles"]
    orch = context["orch"]
    workers = [orch]
    merged = []
    devplan_text = ""
    devplan_tasks_text = ""
    try:
        devplan_path = pathlib.Path(root) / "devplan.md"
        if devplan_path.exists():
            devplan_text = devplan_path.read_text(encoding="utf-8")
    except Exception:
        devplan_text = ""
    try:
        devplan_tasks_path = pathlib.Path(root) / ".nexussy" / "artifacts" / "devplan_tasks.json"
        if devplan_tasks_path.exists():
            devplan_tasks_text = devplan_tasks_path.read_text(encoding="utf-8")
    except Exception:
        devplan_tasks_text = ""
    specs = _slice_devplan_tasks(devplan_text, devplan_tasks_text)
    steer = await engine.consume_steer(rid)
    if steer:
        messages = [m.get("message", "") for m in steer if m.get("message")]
        if messages:
            block = "## Steering Instructions\n" + "\n".join(messages)
            specs = [{**spec, "steering_instructions": block} for spec in specs]
    worker_results = await asyncio.gather(*[run_single_worker(engine, req, detail, rid, root, role, idx, context, task_spec=specs[(idx - 1) % len(specs)]) for idx, role in enumerate(roles, start=1)], return_exceptions=True)
    for result in worker_results:
        if isinstance(result, Exception):
            raise result
        merge_result = await merge_single_worker(engine, result, req, detail, rid, root, context, workers, merged)
        workers.append(merge_result.worker)
        merged.append(merge_result.worker_id)
    await prune_worktrees(str(main))
    manifest = await extract_changed_files(str(main), base, str(artifacts_dir / "changed-files"), rid)
    orch.status = WorkerStatus.finished
    await engine._persist_worker(orch)
    await engine.emit(SSEEventType.worker_status, sid, rid, orch)
    merge_report = MergeReport(run_id=rid, base_commit=base, merge_commit=manifest.merge_commit, merged_workers=merged, passed=True)
    return [
        await engine._save_art(rid, sid, root, "develop_report", DevelopReport(run_id=rid, passed=True, workers=workers, tasks_total=len(workers), tasks_passed=len(workers)).model_dump_json(indent=2)),
        await engine._save_art(rid, sid, root, "merge_report", merge_report.model_dump_json(indent=2)),
        await engine._save_art(rid, sid, root, "changed_files", manifest.model_dump_json(indent=2)),
    ]


async def run_single_worker(engine, req, detail, rid, root, role, idx, context, task_spec: dict | None = None):
    sid = context["sid"]
    main = context["main"]
    workers_root = context["workers_root"]
    base = context["base"]
    cfg = context["cfg"]
    selected_models = context["selected_models"]
    wid = f"{role.value}-{uuid4().hex[:6]}"
    async with engine.git_lock:
        wt, branch = await create_worktree(str(main), str(workers_root), wid, base)
    await engine.emit(SSEEventType.git_event, sid, rid, GitEventPayload(action=GitEventAction.worktree_created, worker_id=wid, branch_name=branch, message="worktree created"))
    task_title = (task_spec or {}).get("title") or f"Develop task {idx}"
    worker = Worker(worker_id=wid, run_id=rid, role=role, status=WorkerStatus.running, task_id=f"task-{uuid4().hex[:6]}", task_title=task_title, worktree_path=wt, branch_name=branch, model=selected_models.get("develop") or engine.config.stages.develop.model)
    await engine._persist_worker(worker)
    await engine.emit(SSEEventType.worker_spawned, sid, rid, worker)
    await engine._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.running)
    await engine.emit(SSEEventType.worker_task, sid, rid, WorkerTaskPayload(worker_id=worker.worker_id, task_id=worker.task_id, phase_number=idx, task_title=worker.task_title, status=WorkerTaskStatus.running))
    await run_worker_rpc(engine, rid, sid, worker, idx, cfg, role, main, wt, spawn_fn=context["spawn_fn"], task_spec=task_spec)
    if not [path for path in pathlib.Path(wt).glob("**/*") if ".git" not in path.parts]:
        pathlib.Path(wt, f"{role.value}.txt").write_text(f"{role.value} completed\n")
    commit = await commit_worker(wt, f"nexussy: {wid} {worker.task_id}")
    return {"worker": worker, "idx": idx, "wid": wid, "wt": wt, "branch": branch, "commit": commit}


async def run_worker_rpc(engine, rid, sid, worker, idx, cfg, role, main, wt, _depth: int = 0, spawn_fn=spawn_pi_worker, task_spec: dict | None = None):
    if _depth >= 3:
        raise RuntimeError("worker RPC max resume depth exceeded")
    rpc = await spawn_fn(cfg, rid, worker.worker_id, role.value, str(main), wt)
    rpc.worker_id = worker.worker_id
    engine.active_worker_rpcs.setdefault(rid, []).append(rpc)
    prompt = json.dumps(task_spec) if task_spec else "nexussy develop task"
    req_id = await rpc.request(worker.task_title, prompt)
    was_paused_on_timeout = False
    try:
        await rpc.wait_response(req_id, engine.config.swarm.worker_task_timeout_s)
    except TimeoutError:
        was_paused_on_timeout = bool(engine.paused.get(rid))
        if not was_paused_on_timeout:
            raise
    finally:
        for frame in rpc.frames:
            await engine.emit(SSEEventType.worker_stream, sid, rid, frame.payload)
        await rpc.stop(engine.config.pi.shutdown_timeout_s)
        if rpc in engine.active_worker_rpcs.get(rid, []):
            engine.active_worker_rpcs[rid].remove(rpc)
    if was_paused_on_timeout:
        worker.status = WorkerStatus.paused
        await engine._persist_worker(worker)
        await engine.emit(SSEEventType.worker_status, sid, rid, worker)
        await engine._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.queued)
        await engine.emit(SSEEventType.worker_task, sid, rid, WorkerTaskPayload(worker_id=worker.worker_id, task_id=worker.task_id, phase_number=idx, task_title=worker.task_title, status=WorkerTaskStatus.queued))
        ck = await save_checkpoint(engine.db, rid, StageName.develop, f".nexussy/checkpoints/develop-{worker.task_id}.json", content=json.dumps({"worker_id": worker.worker_id, "task_id": worker.task_id, "status": "paused"}, sort_keys=True))
        await engine.emit(SSEEventType.checkpoint_saved, sid, rid, ck)
        while engine.paused.get(rid):
            await asyncio.sleep(0.05)
        worker.status = WorkerStatus.running
        await engine._persist_worker(worker)
        await engine.emit(SSEEventType.worker_status, sid, rid, worker)
        await engine._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.running)
        await engine.emit(SSEEventType.worker_task, sid, rid, WorkerTaskPayload(worker_id=worker.worker_id, task_id=worker.task_id, phase_number=idx, task_title=worker.task_title, status=WorkerTaskStatus.running))
        await run_worker_rpc(engine, rid, sid, worker, idx, cfg, role, main, wt, _depth=_depth + 1, spawn_fn=spawn_fn, task_spec=task_spec)


async def _git_proc(cwd: pathlib.Path, *args: str, timeout: float = 60.0) -> tuple[int, str]:
    """Run a git command via asyncio subprocess. Returns (returncode, combined_output)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"git {' '.join(args)} timed out after {timeout}s")
    return proc.returncode, stdout.decode(errors="replace")


async def _attempt_conflict_recovery(engine, main: pathlib.Path, branch: str, conflicts: list[str]) -> dict:
    """Re-run merge and apply the configured conflict strategy."""
    strategy = getattr(getattr(engine.config, "swarm", None), "conflict_strategy", "ours")
    if strategy not in {"ours", "diff3", "abort"}:
        strategy = "ours"
    auto_resolved: list[str] = []
    auto_resolution_failed: list[str] = []
    conflicts_detail: dict[str, str] = {path: "" for path in conflicts}
    # Re-enter merge state (merge_no_ff aborted it). Ignore failure return-code -
    # a conflicting merge will return non-zero but leave the index in MERGING state.
    merge_args = ("-c", "merge.conflictStyle=diff3", "merge", "--no-ff", branch, "-m", f"merge {branch}") if strategy == "diff3" else ("merge", "--no-ff", branch, "-m", f"merge {branch}")
    await _git_proc(main, *merge_args)
    if strategy == "abort":
        await _git_proc(main, "merge", "--abort")
        return {"recovered": False, "needs_review": False, "auto_resolved": [], "auto_resolution_failed": list(conflicts), "conflicts_detail": conflicts_detail, "aborted": True}
    for path in conflicts:
        if strategy == "diff3":
            try:
                conflicts_detail[path] = (main / path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                conflicts_detail[path] = ""
        co_rc, _ = await _git_proc(main, "checkout", "--ours", "--", path)
        if co_rc != 0:
            auto_resolution_failed.append(path)
            continue
        add_rc, _ = await _git_proc(main, "add", "--", path)
        if add_rc != 0:
            auto_resolution_failed.append(path)
            continue
        auto_resolved.append(path)
    if auto_resolution_failed:
        # Abort the in-progress merge so subsequent operations have a clean tree.
        await _git_proc(main, "merge", "--abort")
        return {"recovered": False, "needs_review": strategy == "diff3", "auto_resolved": auto_resolved, "auto_resolution_failed": auto_resolution_failed, "conflicts_detail": conflicts_detail, "aborted": False}
    commit_rc, _ = await _git_proc(main, "commit", "--no-edit")
    if commit_rc != 0:
        await _git_proc(main, "merge", "--abort")
        return {"recovered": False, "needs_review": strategy == "diff3", "auto_resolved": auto_resolved, "auto_resolution_failed": auto_resolution_failed, "conflicts_detail": conflicts_detail, "aborted": False}
    return {"recovered": strategy == "ours", "needs_review": strategy == "diff3", "auto_resolved": auto_resolved, "auto_resolution_failed": auto_resolution_failed, "conflicts_detail": conflicts_detail, "aborted": False}


async def merge_single_worker(engine, result, req, detail, rid, root, context, workers, merged) -> WorkerMergeResult:
    sid = context["sid"]
    main = context["main"]
    base = context["base"]
    roles = context["roles"]
    worker = result["worker"]
    idx = result["idx"]
    wid = result["wid"]
    wt = result["wt"]
    branch = result["branch"]
    commit = result["commit"]
    await engine.emit(SSEEventType.git_event, sid, rid, GitEventPayload(action=GitEventAction.merge_started, worker_id=wid, branch_name=branch, commit_sha=commit, message="merge started"))
    merge_result = await merge_no_ff(str(main), branch)
    if not merge_result.passed:
        await engine.emit(SSEEventType.git_event, sid, rid, GitEventPayload(action=GitEventAction.merge_conflict, worker_id=wid, branch_name=branch, paths=merge_result.conflicts, message="merge conflict"))
        recovery = await _attempt_conflict_recovery(engine, main, branch, merge_result.conflicts)
        report = {
            "run_id": rid,
            "worker_id": wid,
            "branch": branch,
            "conflicts": list(merge_result.conflicts),
            "auto_resolved": recovery["auto_resolved"],
            "auto_resolution_failed": recovery["auto_resolution_failed"],
            "recovered": recovery["recovered"],
            "needs_review": recovery["needs_review"],
            "conflicts_detail": recovery["conflicts_detail"],
        }
        await engine._save_art(rid, sid, root, "conflict_report", json.dumps(report, indent=2, sort_keys=True))
        if recovery["aborted"]:
            raise RuntimeError("merge conflict - aborted: " + ", ".join(merge_result.conflicts))
        if not recovery["recovered"] and not recovery["needs_review"]:
            await engine._save_art(rid, sid, root, "merge_report", MergeReport(run_id=rid, base_commit=base, merged_workers=merged, conflicts=merge_result.conflicts, passed=False).model_dump_json(indent=2))
            await engine._save_art(rid, sid, root, "develop_report", DevelopReport(run_id=rid, passed=False, workers=workers + [worker], tasks_total=len(roles), tasks_passed=len(merged), tasks_failed=1).model_dump_json(indent=2))
            raise RuntimeError("merge conflict - auto-resolution failed")
    await remove_worktree(str(main), wt, branch)
    await engine.emit(SSEEventType.git_event, sid, rid, GitEventPayload(action=GitEventAction.worktree_removed, worker_id=wid, branch_name=branch, message="worktree removed"))
    worker.status = WorkerStatus.finished
    await engine._persist_worker(worker)
    await engine.emit(SSEEventType.worker_status, sid, rid, worker)
    await engine._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.passed)
    await engine.emit(SSEEventType.worker_task, sid, rid, WorkerTaskPayload(worker_id=worker.worker_id, task_id=worker.task_id, phase_number=idx, task_title=worker.task_title, status=WorkerTaskStatus.passed))
    return WorkerMergeResult(worker=worker, worker_id=wid)
    await engine.emit(SSEEventType.git_event, sid, rid, GitEventPayload(action=GitEventAction.worktree_removed, worker_id=wid, branch_name=branch, message="worktree removed"))
    worker.status = WorkerStatus.finished
    await engine._persist_worker(worker)
    await engine.emit(SSEEventType.worker_status, sid, rid, worker)
    await engine._persist_worker_task(rid, worker.worker_id, worker.task_id, idx, worker.task_title, WorkerTaskStatus.passed)
    await engine.emit(SSEEventType.worker_task, sid, rid, WorkerTaskPayload(worker_id=worker.worker_id, task_id=worker.task_id, phase_number=idx, task_title=worker.task_title, status=WorkerTaskStatus.passed))
    return WorkerMergeResult(worker=worker, worker_id=wid)
