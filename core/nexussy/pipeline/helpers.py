from __future__ import annotations

import json
import pathlib
import re

from nexussy.api.schemas import (
    ComplexityLevel,
    ComplexityProfile,
    ErrorResponse,
    InterviewArtifact,
    InterviewQuestionAnswer,
    PipelineStartRequest,
    ValidationIssue,
)
from nexussy.security import sanitize_path


def validate_existing_repo_path(path: str) -> pathlib.Path:
    """Validate an imported repo path and reject symlinks that escape it."""
    if "\x00" in path:
        raise ValueError("path_rejected")
    raw = pathlib.Path(path).expanduser()
    resolved = sanitize_path(str(raw), [raw.anchor or "/"], reject_symlink_escape=True).resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("path_rejected")
    for child in resolved.rglob("*"):
        if child.is_symlink():
            target = child.resolve(strict=True)
            if target != resolved and resolved not in target.parents:
                raise ValueError("path_rejected")
    return resolved


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:63]
    return slug or "project"


def complexity(desc: str, existing: bool = False) -> ComplexityProfile:
    text = desc.lower()
    signals = {}
    score = 0

    def has(pattern: str) -> bool:
        return re.search(pattern, text) is not None

    checks = [
        ("multiple_languages", 10, has(r"\bfrontend\b\s+and\s+\bbackend\b|\btypescript\b|\bpython\b|\bjava\b|\bgo\b|\bgolang\b")),
        ("persistence", 10, has(r"\bdatabase\b|\bsqlite\b|\bpostgres\b|\bpersist\b")),
        ("auth", 15, has(r"\bauth(entication|orization)?\b|\bsecurity\b|\bpassword\b")),
        ("external_api", 10, has(r"\bapi\b")),
        ("ui_backend", 15, has(r"\bui\b|\bdashboard\b|\bweb\b|\btui\b")),
        ("deployment", 10, has(r"\bdeploy\b|\bdocker\b|\binfra\b")),
        ("existing_repo", 10, existing),
        ("qa", 10, has(r"\btest\b|\bqa\b")),
        ("ambiguous", 15, len(desc.split()) < 8),
    ]
    if not any(check[2] for check in checks):
        signals["simple"] = 5
        score += 5
    for key, points, enabled in checks:
        if enabled:
            signals[key] = points
            score += points
    score = min(score, 100)
    if score <= 25:
        level = ComplexityLevel.minimal
        phase_count = 2
        task_group_size = 3
    elif score <= 60:
        level = ComplexityLevel.standard
        phase_count = 4
        task_group_size = 4
    else:
        level = ComplexityLevel.detailed
        phase_count = 6
        task_group_size = 5
    return ComplexityProfile(
        level=level,
        score=score,
        phase_count=phase_count,
        task_group_size=task_group_size,
        template_depth=level,
        signals=signals,
        rationale="Deterministic rubric from SPEC section 11.3",
    )


def strip_markdown_fences(text: str) -> str:
    stripped = (text or "").strip()
    match = re.fullmatch(r"```(?:[a-zA-Z0-9_-]+)?\s*\n([\s\S]*?)\n```", stripped)
    return (match.group(1) if match else stripped).strip() + "\n"


def issues_from_provider_text(text: str) -> list[ValidationIssue]:
    raw = (text or "").strip()
    data = None
    try:
        data = json.loads(raw)
    except Exception:
        data = None
    source = []
    if isinstance(data, dict):
        source = data.get("issues") or []
    elif isinstance(data, list):
        source = data
    issues = []
    for item in source:
        if isinstance(item, dict):
            msg = str(item.get("message") or item.get("issue") or item.get("text") or "").strip()
            if not msg:
                continue
            sev = str(item.get("severity") or "error").lower()
            if sev not in {"info", "warning", "error", "blocker"}:
                sev = "error"
            issues.append(ValidationIssue(severity=sev, category=str(item.get("category") or "provider"), message=msg, artifact_path=item.get("artifact_path"), anchor=item.get("anchor"), fix_required=bool(item.get("fix_required", sev in {"error", "blocker"}))))
        elif isinstance(item, str) and item.strip():
            issues.append(ValidationIssue(severity="error", category="provider", message=item.strip(), fix_required=True))
    if issues:
        return issues
    for line in raw.splitlines():
        lower = line.lower().strip(" -*)\t")
        if lower.startswith(("issue:", "error:", "blocker:", "fix:")):
            severity = "blocker" if lower.startswith("blocker:") else "error"
            issues.append(ValidationIssue(severity=severity, category="provider", message=line.split(":", 1)[-1].strip() or line.strip(), fix_required=True))
    return issues


def corrected_design(text: str, original: str) -> str:
    try:
        data = json.loads((text or "").strip())
    except Exception:
        data = None
    if isinstance(data, dict):
        for key in ("corrected_design", "validated_design", "design"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip() + "\n"
    return original or text


def review_feedback(text: str, issues: list[ValidationIssue]) -> str:
    if issues:
        return "\n".join(issue.message for issue in issues)
    try:
        data = json.loads((text or "").strip())
        if isinstance(data, dict) and isinstance(data.get("feedback_for_plan_stage"), str):
            return data["feedback_for_plan_stage"]
    except Exception:
        pass
    return ""


def devplan_with_anchors(text: str) -> tuple[str, bool]:
    body = strip_markdown_fences(text)
    start = "<!-- NEXT_TASK_GROUP_START -->"
    end = "<!-- NEXT_TASK_GROUP_END -->"
    if body.count(start) == 1 and body.count(end) == 1 and body.index(start) < body.index(end):
        return body, False
    task_re = re.compile(r"(?m)(^\s*- \[ \][\s\S]*?)(?=\n\s*\n|\Z)")
    match = task_re.search(body)
    if match:
        tasks = match.group(1).rstrip()
        wrapped = f"{start}\n{tasks}\n{end}"
        body = body[: match.start()] + wrapped + body[match.end() :]
        if "<!-- PROGRESS_LOG_START -->" not in body:
            body = "# DevPlan\n\n<!-- PROGRESS_LOG_START -->\n- Created by nexussy.\n<!-- PROGRESS_LOG_END -->\n\n" + body.lstrip()
        return body.rstrip() + "\n", True
    fallback = "# DevPlan\n<!-- PROGRESS_LOG_START -->\n- Created by nexussy.\n- Warning: provider plan output lacked a task list with NEXT_TASK_GROUP anchors.\n<!-- PROGRESS_LOG_END -->\n<!-- NEXT_TASK_GROUP_START -->\n- [ ] A: implement requested work. Acceptance: tests pass. Tests: run relevant project tests.\n<!-- NEXT_TASK_GROUP_END -->\n"
    return fallback, True


def devplan_with_task_contract(text: str) -> tuple[str, bool, list[str]]:
    start = "<!-- NEXT_TASK_GROUP_START -->"
    end = "<!-- NEXT_TASK_GROUP_END -->"
    if start not in text or end not in text or text.index(start) > text.index(end):
        return text, True, ["missing NEXT_TASK_GROUP anchors"]
    before, rest = text.split(start, 1)
    tasks, after = rest.split(end, 1)
    issues: list[str] = []
    fixed: list[str] = []
    task_re = re.compile(r"^(\s*- \[ \]\s*)(.*)$")
    task_count = 0
    for line in tasks.splitlines():
        match = task_re.match(line)
        if not match:
            fixed.append(line)
            continue
        task_count += 1
        prefix, body = match.groups()
        body = body.strip()
        if not re.match(r"(?:[A-D]|core|tui|web|ops|docs|backend|frontend|qa|orchestrator)\s*:", body, re.I):
            body = "A: " + body
            issues.append("task missing owner")
        if "acceptance" not in body.lower():
            body += " Acceptance: implementation satisfies the requested behavior."
            issues.append("task missing acceptance criteria")
        if "test" not in body.lower():
            body += " Tests: run relevant project tests."
            issues.append("task missing tests")
        fixed.append(prefix + body)
    if task_count == 0:
        fixed.append("- [ ] A: implement requested work. Acceptance: tests pass. Tests: run relevant project tests.")
        issues.append("missing tasks")
    return before + start + "\n" + "\n".join(fixed).strip() + "\n" + end + after, bool(issues), sorted(set(issues))


def parse_interview_questions(text: str) -> list[InterviewQuestionAnswer]:
    text = _extract_json_text(text)
    try:
        raw = json.loads(text)
    except Exception:
        raw = []
    if not isinstance(raw, list):
        raw = []
    questions = []
    seen = set()
    for idx, item in enumerate(raw[:8], start=1):
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("id") or item.get("question_id") or f"q{idx}").strip() or f"q{idx}"
        question = str(item.get("question") or "").strip()
        if not question or question_id in seen:
            continue
        seen.add(question_id)
        suggested = item.get("suggested_answer") if isinstance(item.get("suggested_answer"), str) else None
        evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
        questions.append(InterviewQuestionAnswer(question_id=question_id, question=question, answer="pending", source="user", suggested_answer=suggested, evidence=[str(x) for x in evidence[:4]]))
    if len(questions) < 4:
        questions = [
            InterviewQuestionAnswer(question_id="q_goal", question="What outcome should this project deliver for its first useful proof of concept? If you are unsure, say so and nexussy will suggest a small default.", answer="pending", source="user", suggested_answer="Start with the smallest working proof of concept."),
            InterviewQuestionAnswer(question_id="q_users", question="Who will use it first, and what is the main job they need it to do?", answer="pending", source="user"),
            InterviewQuestionAnswer(question_id="q_stack", question="Do you have a preferred stack, or should nexussy recommend one based on this repository and the requested outcome?", answer="pending", source="user", suggested_answer="Let nexussy recommend a stack if there is no strong preference."),
            InterviewQuestionAnswer(question_id="q_quality", question="What local testing or quality check should prove the first version works?", answer="pending", source="user", suggested_answer="Include a small automated smoke test."),
        ]
    return questions[:8]


def parse_interview_turn(text: str, prior_count: int, req: PipelineStartRequest) -> tuple[bool, InterviewQuestionAnswer | None, dict[str, list[str]]]:
    text = _extract_json_text(text)
    try:
        raw = json.loads(text)
    except Exception:
        raw = None
    if isinstance(raw, list):
        questions = parse_interview_questions(text)
        return False, questions[0] if questions else _fallback_interview_turn(prior_count, req), {}
    if isinstance(raw, dict):
        if bool(raw.get("done")):
            summary = {
                "requirements": _string_list(raw.get("requirements")),
                "constraints": _string_list(raw.get("constraints")),
                "risks": _string_list(raw.get("risks")),
            }
            return True, None, summary
        item = raw.get("question") if isinstance(raw.get("question"), dict) else raw
        if isinstance(item, dict):
            question_id = str(item.get("id") or item.get("question_id") or f"q{prior_count + 1}").strip() or f"q{prior_count + 1}"
            question = str(item.get("question") or item.get("text") or "").strip()
            if question:
                suggested = item.get("suggested_answer") if isinstance(item.get("suggested_answer"), str) else None
                evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
                return False, InterviewQuestionAnswer(question_id=question_id, question=question, answer="pending", source="user", suggested_answer=suggested, evidence=[str(x) for x in evidence[:4]]), {}
    return False, _fallback_interview_turn(prior_count, req), {}


def parse_auto_answers(text: str, questions: list[InterviewQuestionAnswer], req: PipelineStartRequest) -> dict[str, str]:
    text = _extract_json_text(text)
    try:
        raw = json.loads(text)
    except Exception:
        raw = {}
    answers = raw.get("answers", raw) if isinstance(raw, dict) else {}
    out = {}
    for question in questions:
        answer = answers.get(question.question_id) if isinstance(answers, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            answer = req.project_name if "name" in question.question.lower() else req.description
        out[question.question_id] = answer.strip()
    return out


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:12]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _fallback_interview_turn(prior_count: int, req: PipelineStartRequest) -> InterviewQuestionAnswer:
    fallbacks = [
        InterviewQuestionAnswer(question_id="q_goal", question="What should the first useful version accomplish?", answer="pending", source="user", suggested_answer="Start with the smallest working proof of concept."),
        InterviewQuestionAnswer(question_id="q_users", question="Who will use it first, and what should they be able to do?", answer="pending", source="user"),
        InterviewQuestionAnswer(question_id="q_interface", question="How should people interact with it first: CLI, web UI, API, chat, or something else?", answer="pending", source="user", suggested_answer="Choose the simplest interface that proves the idea."),
        InterviewQuestionAnswer(question_id="q_quality", question="What check should prove it works locally?", answer="pending", source="user", suggested_answer="Add a small automated smoke test."),
    ]
    if prior_count < len(fallbacks):
        return fallbacks[prior_count]
    return InterviewQuestionAnswer(question_id=f"q{prior_count + 1}", question=f"What important constraint is still missing for {req.project_name}?", answer="pending", source="user")


def _extract_json_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I).strip()
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    first_array = stripped.find("[")
    last_array = stripped.rfind("]")
    first_obj = stripped.find("{")
    last_obj = stripped.rfind("}")
    if first_obj >= 0 and last_obj > first_obj and (first_array < 0 or first_obj < first_array):
        return stripped[first_obj:last_obj + 1]
    if first_array >= 0 and last_array > first_array:
        return stripped[first_array:last_array + 1]
    if first_obj >= 0 and last_obj > first_obj:
        return stripped[first_obj:last_obj + 1]
    return stripped


def interview_summary(artifact: InterviewArtifact | None) -> str:
    if not artifact:
        return ""
    lines = ["Project Requirements (from Interview)"]
    for qa in artifact.questions:
        lines.append(f"{qa.question.replace('?', '').strip()}: {qa.answer}")
    if artifact.requirements:
        lines.append("Requirements: " + "; ".join(artifact.requirements))
    return "\n".join(lines)


def provider_declared_passed(text: str, default: bool) -> bool:
    try:
        data = json.loads((text or "").strip())
        if isinstance(data, dict) and isinstance(data.get("passed"), bool):
            return data["passed"]
    except Exception:
        pass
    return default


class ProviderStartError(Exception):
    def __init__(self, error: ErrorResponse):
        self.error = error
        super().__init__(error.message)
