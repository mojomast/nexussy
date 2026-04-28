from __future__ import annotations
import hashlib, os, pathlib, shutil
from nexussy.security import sanitize_relative_path

ANCHORS = {
    "devplan.md": ["<!-- PROGRESS_LOG_START -->","<!-- PROGRESS_LOG_END -->","<!-- NEXT_TASK_GROUP_START -->","<!-- NEXT_TASK_GROUP_END -->"],
    "handoff.md": ["<!-- QUICK_STATUS_START -->","<!-- QUICK_STATUS_END -->","<!-- HANDOFF_NOTES_START -->","<!-- HANDOFF_NOTES_END -->","<!-- SUBAGENT_A_ASSIGNMENT_START -->","<!-- SUBAGENT_A_ASSIGNMENT_END -->","<!-- SUBAGENT_B_ASSIGNMENT_START -->","<!-- SUBAGENT_B_ASSIGNMENT_END -->","<!-- SUBAGENT_C_ASSIGNMENT_START -->","<!-- SUBAGENT_C_ASSIGNMENT_END -->","<!-- SUBAGENT_D_ASSIGNMENT_START -->","<!-- SUBAGENT_D_ASSIGNMENT_END -->"],
}
PHASE_ANCHORS = ["<!-- PHASE_TASKS_START -->","<!-- PHASE_TASKS_END -->","<!-- PHASE_PROGRESS_START -->","<!-- PHASE_PROGRESS_END -->"]

def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def validate_anchors(rel_path: str, content: str) -> None:
    name = pathlib.PurePosixPath(rel_path).name
    required = PHASE_ANCHORS if name.startswith("phase") and name.endswith(".md") else ANCHORS.get(name, [])
    missing=[a for a in required if a not in content]
    if missing: raise ValueError("validation_error: missing anchors " + ",".join(missing))

def safe_write(root: str, rel_path: str, content: str) -> dict:
    rel=sanitize_relative_path(rel_path)
    base=pathlib.Path(root).expanduser().resolve(strict=False); target=(base/rel).resolve(strict=False)
    if not (target == base or base in target.parents): raise ValueError("path_rejected")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp=pathlib.Path(str(target)+".tmp")
    try:
        validate_anchors(rel, content)
    except ValueError:
        tmp.write_text(content, encoding="utf-8")
        raise
    if target.exists(): shutil.copy2(target, str(target)+".bak")
    tmp.write_text(content, encoding="utf-8")
    validate_anchors(rel, tmp.read_text(encoding="utf-8"))
    os.replace(tmp, target)
    b=target.read_bytes()
    return {"path":rel,"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)}

def artifact_path(kind: str, phase_number: int|None=None) -> str:
    mapping={"interview":".nexussy/artifacts/interview.json","complexity_profile":".nexussy/artifacts/complexity_profile.json","design_draft":".nexussy/artifacts/design_draft.md","validated_design":".nexussy/artifacts/validated_design.md","validation_report":".nexussy/artifacts/validation_report.json","devplan":"devplan.md","handoff":"handoff.md","review_report":".nexussy/artifacts/review_report.json","develop_report":".nexussy/artifacts/develop_report.json","merge_report":".nexussy/artifacts/merge_report.json","changed_files":".nexussy/artifacts/changed_files.json"}
    if kind == "phase": return f"phase{phase_number or 1:03d}.md"
    return mapping[kind]
