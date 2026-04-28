from __future__ import annotations

import hashlib, json, shutil, subprocess
from pathlib import Path

from nexussy.api.schemas import ChangedFile, ChangedFilesManifest, MergeReport
from nexussy.security import sanitize_relative_path

def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.STDOUT).strip()

def init_repo(path: str) -> str:
    repo = Path(path); repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "nexussy@example.invalid")
    _git(repo, "config", "user.name", "nexussy")
    if not (repo / ".gitignore").exists(): (repo / ".gitignore").write_text(".nexussy/workers/\n")
    _git(repo, "add", ".");
    try: _git(repo, "commit", "-m", "initial")
    except subprocess.CalledProcessError: pass
    return _git(repo, "rev-parse", "HEAD")

def create_worktree(repo: str, worker_root: str, worker_id: str, base_commit: str = "HEAD") -> tuple[str, str]:
    main = Path(repo); wt = Path(worker_root) / worker_id; wt.parent.mkdir(parents=True, exist_ok=True)
    branch = f"worker/{worker_id}"
    _git(main, "worktree", "add", "-b", branch, str(wt), base_commit)
    _git(wt, "config", "user.email", "nexussy@example.invalid"); _git(wt, "config", "user.name", "nexussy")
    return str(wt), branch

def commit_worker(worktree: str, message: str = "worker changes") -> str:
    wt = Path(worktree); _git(wt, "add", ".")
    try:
        _git(wt, "commit", "-m", message)
    except subprocess.CalledProcessError as e:
        if "nothing to commit" in (e.output or ""):
            return _git(wt, "rev-parse", "HEAD")
        raise
    return _git(wt, "rev-parse", "HEAD")

def remove_worktree(repo: str, worktree: str, branch: str):
    main = Path(repo)
    try:
        _git(main, "worktree", "remove", worktree)
    finally:
        try: _git(main, "branch", "-d", branch)
        except subprocess.CalledProcessError: pass

def merge_no_ff(repo: str, branch: str) -> MergeReport:
    main = Path(repo); base = _git(main, "rev-parse", "HEAD")
    try:
        _git(main, "merge", "--no-ff", branch, "-m", f"merge {branch}")
        return MergeReport(run_id="git", base_commit=base, merge_commit=_git(main, "rev-parse", "HEAD"), merged_workers=[branch.split("/")[-1]], passed=True)
    except subprocess.CalledProcessError:
        conflicts = [sanitize_relative_path(p) for p in _git(main, "diff", "--name-only", "--diff-filter=U").splitlines() if p]
        _git(main, "merge", "--abort")
        return MergeReport(run_id="git", base_commit=base, conflicts=conflicts, passed=False)

def extract_changed_files(repo: str, base_commit: str, dest: str, run_id: str = "git") -> ChangedFilesManifest:
    main = Path(repo); out = Path(dest); out.mkdir(parents=True, exist_ok=True)
    files=[]
    for line in _git(main, "diff", "--name-status", base_commit, "HEAD").splitlines():
        if not line: continue
        status, path = line.split("\t", 1)[0], line.split("\t")[-1]
        rel = sanitize_relative_path(path)
        cf_path = main / rel
        if cf_path.exists() and cf_path.is_file():
            target = out / rel; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(cf_path, target)
            data = cf_path.read_bytes(); sha = hashlib.sha256(data).hexdigest(); size = len(data)
        else:
            sha = None; size = None
        files.append(ChangedFile(path=rel, status={"A":"added","M":"modified","D":"deleted","R":"renamed"}.get(status[0], "modified"), sha256=sha, bytes=size))
    manifest = ChangedFilesManifest(run_id=run_id, base_commit=base_commit, merge_commit=_git(main, "rev-parse", "HEAD"), files=files)
    (out / "changed_files.json").write_text(manifest.model_dump_json(indent=2))
    return manifest

def prune_worktrees(repo: str):
    _git(Path(repo), "worktree", "prune")
