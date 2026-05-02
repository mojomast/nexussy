from __future__ import annotations

import asyncio
import json
import shlex
import shutil
from dataclasses import dataclass

from nexussy.api.schemas import ArtifactRef, BrowserValidationReport


_OUTPUT_LIMIT = 4000


@dataclass
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _tail(text: str, limit: int = _OUTPUT_LIMIT) -> str:
    return text[-limit:] if len(text) > limit else text


def _command_parts(command: str | None) -> list[str] | None:
    if command:
        parts = shlex.split(command)
        if not parts:
            return None
        resolved = shutil.which(parts[0]) if "/" not in parts[0] else parts[0]
        return [resolved or parts[0], *parts[1:]] if resolved or "/" in parts[0] else None
    resolved = shutil.which("browser-harness")
    return [resolved] if resolved else None


async def _run_command(args: list[str], timeout_s: int) -> CommandResult:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        stdout_b, stderr_b = await proc.communicate()
        return CommandResult(124, stdout_b.decode("utf-8", "replace"), stderr_b.decode("utf-8", "replace") + "\ntimeout")
    return CommandResult(proc.returncode, stdout_b.decode("utf-8", "replace"), stderr_b.decode("utf-8", "replace"))


def _browser_script(target_url: str) -> str:
    return f'''
new_tab({target_url!r})
wait_for_load()
page = js("""
return {{
  title: document.title,
  url: location.href,
  readyState: document.readyState,
  bodyText: document.body ? document.body.innerText.slice(0, 2000) : ""
}}
""")
events = drain_events()
print(json.dumps({{"page": page, "events": events}}))
'''


def _findings_from_stdout(stdout: str) -> list[str]:
    findings: list[str] = []
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, list):
            return findings
        for event in events:
            if not isinstance(event, dict):
                continue
            method = str(event.get("method") or "")
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            if method == "Runtime.exceptionThrown":
                details = params.get("exceptionDetails") if isinstance(params, dict) else {}
                findings.append(str(details.get("text") or "browser JavaScript exception"))
            if method == "Runtime.consoleAPICalled" and params.get("type") == "error":
                args = params.get("args") if isinstance(params.get("args"), list) else []
                text = " ".join(str(arg.get("value") or arg.get("description") or "") for arg in args if isinstance(arg, dict)).strip()
                findings.append(text or "browser console error")
        return findings
    return findings


def _report(rid: str, *, passed: bool, skipped: bool = False, reason: str | None = None, command: str | None = None, target_url: str | None = None, result: CommandResult | None = None, findings: list[str] | None = None) -> BrowserValidationReport:
    return BrowserValidationReport(
        run_id=rid,
        passed=passed,
        skipped=skipped,
        reason=reason,
        command=command,
        target_url=target_url,
        returncode=result.returncode if result else None,
        stdout_tail=_tail(result.stdout) if result else "",
        stderr_tail=_tail(result.stderr) if result else "",
        findings=findings or [],
    )


async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs) -> list[ArtifactRef]:
    sid = detail.session.session_id
    cfg = engine.config.stages.validate_browser
    runner = kwargs.get("command_runner") or _run_command
    failure_policy = cfg.failure_policy

    async def save(report: BrowserValidationReport) -> list[ArtifactRef]:
        return [await engine._save_art(rid, sid, root, "validate_browser_report", report.model_dump_json(indent=2))]

    if not cfg.enabled:
        return await save(_report(rid, passed=True, skipped=True, reason="validate_browser disabled"))

    command = _command_parts(cfg.command)
    display_command = cfg.command or "browser-harness"
    if not command:
        skipped = failure_policy == "skip"
        return await save(_report(rid, passed=skipped, skipped=skipped, reason="browser-harness command not found", command=display_command))
    if not cfg.target_url:
        skipped = failure_policy == "skip"
        return await save(_report(rid, passed=skipped, skipped=skipped, reason="target_url not configured", command=display_command))

    doctor = await runner([*command, "--doctor"], cfg.timeout_s)
    if doctor.returncode != 0:
        skipped = failure_policy == "skip"
        return await save(_report(rid, passed=skipped, skipped=skipped, reason="browser-harness doctor failed", command=display_command, target_url=cfg.target_url, result=doctor))

    result = await runner([*command, "-c", _browser_script(cfg.target_url)], cfg.timeout_s)
    findings = _findings_from_stdout(result.stdout)
    passed = result.returncode == 0 and not findings
    reason = None if passed else "browser validation failed"
    return await save(_report(rid, passed=passed, reason=reason, command=display_command, target_url=cfg.target_url, result=result, findings=findings))
