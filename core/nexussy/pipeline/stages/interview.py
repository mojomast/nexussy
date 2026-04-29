from __future__ import annotations

import asyncio
import json

from nexussy.api.schemas import ArtifactRef, InterviewArtifact, InterviewQuestionAnswer, PausePayload, SSEEventType, StageName
from nexussy.checkpoint import save_checkpoint
from nexussy.pipeline.helpers import parse_auto_answers, parse_interview_questions
from nexussy.session import SessionStatus, transition_session_status


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    st = StageName.interview
    existing = await engine._latest_interview_artifact(rid) if req.resume_run_id else None
    if existing and existing.questions and not req.auto_approve_interview:
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
    question_prompt = (
        "Generate a JSON array of 4-8 plain-language interview questions for a non-technical project owner. "
        "Cover project name, primary languages, short description/requirements, project type, and optional frameworks, database, auth, deployment, and testing preferences. "
        "Return only JSON objects with id and question fields.\n\n"
        f"Project description: {req.description}"
    )
    questions = parse_interview_questions(await engine._provider_text(st, sid, rid, question_prompt, selected_models, allow_mock))
    engine.interview_questions[sid] = questions
    question_content = json.dumps([q.model_dump(mode="json") for q in questions], sort_keys=True)
    ck = await save_checkpoint(engine.db, rid, StageName.interview, ".nexussy/checkpoints/interview-questions.json", content=question_content)
    await engine.emit(SSEEventType.checkpoint_saved, sid, rid, ck)
    if req.auto_approve_interview:
        answer_prompt = (
            "Answer these interview questions as JSON using only the project description. "
            "Return a JSON object mapping each question id to a concise answer.\n\n"
            f"Project name: {req.project_name}\nProject description: {req.description}\nQuestions: {json.dumps([{'id': q.question_id, 'question': q.question} for q in questions])}"
        )
        answers = parse_auto_answers(await engine._provider_text(st, sid, rid, answer_prompt, selected_models, allow_mock), questions, req)
        answered = [InterviewQuestionAnswer(question_id=q.question_id, question=q.question, answer=answers[q.question_id], source="auto") for q in questions]
    else:
        pending = InterviewArtifact(project_name=req.project_name, project_slug=detail.session.project_slug, description=req.description, questions=questions, requirements=[req.description])
        await engine._save_art(rid, sid, root, "interview", pending.model_dump_json(indent=2))
        fut = asyncio.get_running_loop().create_future()
        engine.interview_waiters[sid] = fut
        engine.paused[rid] = True
        await engine.db.write(lambda con: con.execute("UPDATE runs SET status=? WHERE run_id=?", ("paused", rid)))
        await transition_session_status(engine.db, sid, SessionStatus.paused)
        await engine.emit(SSEEventType.pause_state_changed, sid, rid, PausePayload(paused=True, reason="waiting for interview answers"))
        interview_cfg = getattr(engine.config.stages, "interview", None)
        timeout_s = getattr(interview_cfg, "answer_timeout_s", 3600) if interview_cfg else 3600
        try:
            answered = await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError:
            engine.interview_waiters.pop(sid, None)
            engine.interview_questions.pop(sid, None)
            engine.paused.pop(rid, None)
            raise RuntimeError("interview answer timeout - user did not respond in time")
        engine.interview_waiters.pop(sid, None)
        engine.interview_questions.pop(sid, None)
    ia = InterviewArtifact(project_name=req.project_name, project_slug=detail.session.project_slug, description=req.description, questions=answered, requirements=[qa.answer for qa in answered])
    return [await engine._save_art(rid, sid, root, "interview", ia.model_dump_json(indent=2)), await engine._save_art(rid, sid, root, "complexity_profile", cp.model_dump_json(indent=2))]
