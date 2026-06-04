from __future__ import annotations

import asyncio
import json

from nexussy.api.schemas import ArtifactRef, ErrorCode, ErrorResponse, InterviewArtifact, InterviewQuestionAnswer, PausePayload, SSEEventType, StageName
from nexussy.checkpoint import save_checkpoint
from nexussy.pipeline.helpers import parse_auto_answers, parse_interview_questions, parse_interview_turn
from nexussy.session import SessionStatus, now_utc, transition_session_status
from nexussy.swarm.project_graph import graph_summary_for_worktree


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    st = StageName.interview
    skip_interview = str(req.metadata.get("skip_interview", "")).lower() == "true"
    auto_mode = req.auto_approve_interview or skip_interview
    existing = await engine._latest_interview_artifact(rid) if req.resume_run_id else None
    graph_context = graph_summary_for_worktree(root)
    if existing and existing.questions and not auto_mode:
        questions = existing.questions
        engine.interview_questions[sid] = questions
        fut = asyncio.get_running_loop().create_future()
        engine.interview_waiters[sid] = fut
        engine.paused[rid] = True
        await engine.db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?", ("paused", rid)))
        await transition_session_status(engine.db, sid, SessionStatus.paused)
        await engine.emit(SSEEventType.pause_state_changed, sid, rid, PausePayload(paused=True, reason="waiting for interview answers"))
        answered = await fut
        engine.interview_waiters.pop(sid, None)
        engine.interview_questions.pop(sid, None)
        ia = InterviewArtifact(project_name=req.project_name, project_slug=detail.session.project_slug, description=req.description, questions=answered, requirements=[qa.answer for qa in answered])
        return [await engine._save_art(rid, sid, root, "interview", ia.model_dump_json(indent=2)), await engine._save_art(rid, sid, root, "complexity_profile", cp.model_dump_json(indent=2))]
    if not auto_mode:
        answered: list[InterviewQuestionAnswer] = []
        requirements = [req.description]
        constraints: list[str] = []
        risks: list[str] = []
        interview_cfg = getattr(engine.config.stages, "interview", None)
        timeout_s = getattr(interview_cfg, "answer_timeout_s", 3600) if interview_cfg else 3600
        for turn in range(8):
            history = "\n".join(f"- {q.question_id}: {q.question}\n  Answer: {q.answer}" for q in answered) or "- none yet"
            turn_prompt = (
                "You are nexussy's adaptive discovery interviewer. Ask exactly one next high-value question, or finish if enough is known. "
                "Use the owner's prior answers to adapt. Do not ask questions already answered. Prefer practical decisions that affect design, implementation, testing, or deployment. "
                "Return only JSON. To ask: {\"done\":false,\"question\":{\"id\":\"q_short_id\",\"question\":\"...\",\"suggested_answer\":\"optional default\",\"evidence\":[\"optional context\"]}}. "
                "To finish: {\"done\":true,\"requirements\":[\"...\"],\"constraints\":[\"...\"],\"risks\":[\"...\"]}. Ask at least one question before finishing.\n\n"
                f"{graph_context}\nProject name: {req.project_name}\nProject description: {req.description}\nPrior answers:\n{history}"
            )
            done, question, summary = parse_interview_turn(await engine._provider_text(st, sid, rid, turn_prompt, selected_models, allow_mock), len(answered), req)
            if done and answered:
                requirements = summary.get("requirements") or [qa.answer for qa in answered]
                constraints = summary.get("constraints") or []
                risks = summary.get("risks") or []
                break
            if not question:
                break
            if any(q.question_id == question.question_id for q in answered):
                question.question_id = f"q{len(answered) + 1}"
            pending = InterviewArtifact(project_name=req.project_name, project_slug=detail.session.project_slug, description=req.description, questions=[*answered, question], requirements=requirements, constraints=constraints, risks=risks)
            await engine._save_art(rid, sid, root, "interview", pending.model_dump_json(indent=2))
            engine.interview_questions[sid] = [question]
            fut = asyncio.get_running_loop().create_future()
            engine.interview_waiters[sid] = fut
            engine.paused[rid] = True
            await engine.db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?", ("paused", rid)))
            await transition_session_status(engine.db, sid, SessionStatus.paused)
            await engine.emit(SSEEventType.pause_state_changed, sid, rid, PausePayload(paused=True, reason=f"waiting for interview answer: {question.question_id}"))
            try:
                current_answered = await asyncio.wait_for(fut, timeout=timeout_s)
            except asyncio.TimeoutError:
                engine.interview_waiters.pop(sid, None)
                engine.interview_questions.pop(sid, None)
                engine.paused.pop(rid, None)
                await engine.db.write(lambda con: con.execute("UPDATE runs SET status=?, finished_at=? WHERE run_id=?", ("failed", now_utc().isoformat(), rid)))
                await transition_session_status(engine.db, sid, SessionStatus.failed)
                await engine.emit(SSEEventType.pipeline_error, sid, rid, ErrorResponse(error_code=ErrorCode.stage_failed, message="interview answer timeout", retryable=False))
                raise RuntimeError("interview answer timeout - user did not respond in time")
            finally:
                engine.interview_waiters.pop(sid, None)
                engine.interview_questions.pop(sid, None)
            answered.extend(current_answered)
        engine.paused.pop(rid, None)
        await engine.db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?", ("running", rid)))
        await transition_session_status(engine.db, sid, SessionStatus.running)
        await engine.emit(SSEEventType.pause_state_changed, sid, rid, PausePayload(paused=False, reason="interview complete"))
        ia = InterviewArtifact(project_name=req.project_name, project_slug=detail.session.project_slug, description=req.description, questions=answered, requirements=requirements if requirements != [req.description] else [qa.answer for qa in answered], constraints=constraints, risks=risks)
        return [await engine._save_art(rid, sid, root, "interview", ia.model_dump_json(indent=2)), await engine._save_art(rid, sid, root, "complexity_profile", cp.model_dump_json(indent=2))]

    question_prompt = (
        "You are nexussy's interactive discovery interviewer for a software-delivery pipeline. "
        "Generate a dynamic JSON array of 4-8 plain-language questions tailored to this specific request and repository context. "
        "Ask only high-value unknowns that affect design, implementation, testing, or deployment. Do not ask facts that are already strongly indicated by the project graph. "
        "If the owner may be unsure, include a useful suggested_answer and brief evidence so the TUI can help them choose instead of blocking. "
        "Questions may offer recommendations, tradeoffs, or defaults, but must still be answerable by a non-technical owner. "
        "Return only JSON objects with id, question, optional suggested_answer, and optional evidence fields.\n\n"
        f"{graph_context}\n"
        f"Project name: {req.project_name}\nProject description: {req.description}"
    )
    questions = parse_interview_questions(await engine._provider_text(st, sid, rid, question_prompt, selected_models, allow_mock))
    engine.interview_questions[sid] = questions
    question_content = json.dumps([q.model_dump(mode="json") for q in questions], sort_keys=True)
    ck = await save_checkpoint(engine.db, rid, StageName.interview, ".nexussy/checkpoints/interview-questions.json", content=question_content)
    await engine.emit(SSEEventType.checkpoint_saved, sid, rid, ck)
    if auto_mode:
        threshold = int(getattr(engine.config.stages.interview, "min_description_words", 50) or 50)
        confidence = "low" if len(req.description.split()) < threshold else "high"
        answer_prompt = (
            "Answer these interview questions as JSON using the project description and project graph context. Prefer small, conservative defaults when the description is ambiguous. "
            "Return a JSON object mapping each question id to a concise answer.\n\n"
            f"{graph_context}\n"
            f"Project name: {req.project_name}\nProject description: {req.description}\nQuestions: {json.dumps([{'id': q.question_id, 'question': q.question} for q in questions])}"
        )
        answers = parse_auto_answers(await engine._provider_text(st, sid, rid, answer_prompt, selected_models, allow_mock), questions, req)
        answered = [InterviewQuestionAnswer(question_id=q.question_id, question=q.question, answer=answers[q.question_id], source="auto", confidence=confidence) for q in questions]
    ia = InterviewArtifact(project_name=req.project_name, project_slug=detail.session.project_slug, description=req.description, questions=answered, requirements=[qa.answer for qa in answered])
    return [await engine._save_art(rid, sid, root, "interview", ia.model_dump_json(indent=2)), await engine._save_art(rid, sid, root, "complexity_profile", cp.model_dump_json(indent=2))]
