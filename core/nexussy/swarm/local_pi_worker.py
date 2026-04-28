from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import sys
from typing import Any

from nexussy.security import sanitize_relative_path, scrub_log


# Security model for the bundled local worker:
# The bash tool runs commands in a stripped environment (no inherited secrets,
# no PATH extensions) with a hard timeout and 64KB output cap. Commands run
# as the current OS user - this worker is for LOCAL DEVELOPMENT ONLY.
# For production multi-tenant deployments, set PI_COMMAND in nexussy.yaml
# to point at a properly sandboxed executor (Docker exec, nsjail, Firecracker).
# Mitigations in place:
#   - Stripped env: only HOME, PATH, SHELL, TERM, LANG, NEXUSSY_WORKTREE are set
#   - Hard timeout: 120s max (default 30s per call)
#   - Output cap: 64KB combined stdout+stderr
#   - cwd=worktree enforces working directory confinement
#   - sanitize_relative_path() blocks path traversal in file tools
# Known gaps (acceptable for local dev, not for multi-tenant prod):
#   - No seccomp/AppArmor syscall filtering
#   - No network namespace isolation
#   - No filesystem namespace isolation
TOOL_NAMES = {"read_file", "write_file", "edit_file", "bash", "list_dir"}
_injected_messages: list[str] = []


def _send(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, separators=(",", ":")), flush=True)


def _event(event_type: str, payload: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "method": "agent.event", "params": {"type": event_type, "payload": payload}})


def _root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("NEXUSSY_WORKTREE", ".")).resolve(strict=False)


def _safe_path(path: str) -> pathlib.Path:
    rel = sanitize_relative_path(path)
    root = _root()
    target = (root / rel).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError("path_rejected")
    return target


async def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOL_NAMES:
        raise ValueError("unknown_tool")
    if name == "read_file":
        path = _safe_path(str(arguments.get("path") or ""))
        max_bytes = int(arguments.get("max_bytes") or 131_072)
        data = path.read_bytes()[:max_bytes]
        return {"path": str(path.relative_to(_root())), "content": data.decode(errors="replace"), "truncated": path.stat().st_size > max_bytes}
    if name == "write_file":
        path = _safe_path(str(arguments.get("path") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        content = str(arguments.get("content") or "")
        path.write_text(content)
        return {"path": str(path.relative_to(_root())), "bytes": len(content.encode())}
    if name == "edit_file":
        path = _safe_path(str(arguments.get("path") or ""))
        old = str(arguments.get("old") or "")
        new = str(arguments.get("new") or "")
        if not old:
            raise ValueError("old_required")
        text = path.read_text()
        count = int(arguments.get("count") or 1)
        updated = text.replace(old, new, count)
        if updated == text:
            raise ValueError("old_not_found")
        path.write_text(updated)
        return {"path": str(path.relative_to(_root())), "replacements": text.count(old) if count == 0 else min(text.count(old), count)}
    if name == "list_dir":
        path = _safe_path(str(arguments.get("path") or "."))
        limit = int(arguments.get("limit") or 200)
        entries = []
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:limit]:
            entries.append({"name": child.name, "type": "dir" if child.is_dir() else "file"})
        return {"path": str(path.relative_to(_root())), "entries": entries}
    # bash tool - hardened stripped-env subprocess
    command = str(arguments.get("command") or "")
    if not command.strip():
        raise ValueError("command_empty")
    if "\x00" in command:
        raise ValueError("command_rejected: null byte")
    if len(command) > 8_000:
        raise ValueError("command_rejected: too long")

    timeout = min(float(arguments.get("timeout_s") or 30), 120.0)
    MAX_OUTPUT_BYTES = 65_536

    safe_env = {
        "HOME": str(_root()),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "SHELL": "/bin/sh",
        "TERM": "dumb",
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "NEXUSSY_WORKTREE": str(_root()),
    }

    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(_root()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=safe_env,
    )
    try:
        out_bytes, err_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise TimeoutError("command_timeout")

    out_str = scrub_log(out_bytes[:MAX_OUTPUT_BYTES].decode(errors="replace"))
    err_str = scrub_log(err_bytes[:MAX_OUTPUT_BYTES].decode(errors="replace"))
    truncated = len(out_bytes) > MAX_OUTPUT_BYTES or len(err_bytes) > MAX_OUTPUT_BYTES

    return {
        "exit_code": proc.returncode,
        "stdout": out_str,
        "stderr": err_str,
        "truncated": truncated,
    }


def _tools_schema() -> list[dict[str, Any]]:
    def fn(name: str, description: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": props, "required": required}}}
    return [
        fn("read_file", "Read a UTF-8 file under the worktree", {"path": {"type": "string"}, "max_bytes": {"type": "integer"}}, ["path"]),
        fn("write_file", "Write a UTF-8 file under the worktree", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
        fn("edit_file", "Replace text in a file under the worktree", {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}, "count": {"type": "integer"}}, ["path", "old", "new"]),
        fn("list_dir", "List a directory under the worktree", {"path": {"type": "string"}, "limit": {"type": "integer"}}, ["path"]),
        fn("bash", "Run a safe shell command in the worktree", {"command": {"type": "string"}, "timeout_s": {"type": "number"}}, ["command"]),
    ]


def _devplan_tasks() -> str:
    path = _root() / ".nexussy" / "artifacts" / "devplan.md"
    if not path.exists():
        path = _root() / "devplan.md"
    if not path.exists():
        return "No devplan task block found."
    text = path.read_text(errors="replace")
    match = re.search(r"<!-- NEXT_TASK_GROUP_START -->([\s\S]*?)<!-- NEXT_TASK_GROUP_END -->", text)
    return match.group(1).strip() if match else text[:4000]


def _messages(task: str, context: str) -> list[dict[str, Any]]:
    role = os.environ.get("NEXUSSY_WORKER_ROLE", "worker")
    worktree = str(_root())
    tasks = _devplan_tasks()
    return [
        {"role": "system", "content": f"You are a nexussy {role} worker running inside worktree {worktree}. Available tools: read_file, write_file, edit_file, bash, list_dir. Stay inside the worktree, never use path traversal or '..', and keep changes focused on assigned tasks. Devplan tasks:\n{tasks}"},
        {"role": "user", "content": f"Task:\n{task}\n\nContext:\n{context}\n\nInjected messages:\n" + "\n".join(_injected_messages)},
    ]


async def _completion(messages: list[dict[str, Any]]) -> Any:
    from litellm import acompletion  # imported lazily so module import stays side-effect safe

    model = os.environ.get("PI_DEFAULT_MODEL") or os.environ.get("NEXUSSY_DEFAULT_MODEL") or "openai/gpt-4o-mini"
    return await acompletion(model=model, messages=messages, tools=_tools_schema(), stream=True)


async def _run_agent(task: str, context: str) -> dict[str, Any]:
    messages = _messages(task, context)
    final_text = ""
    for _ in range(int(os.environ.get("NEXUSSY_PI_MAX_TURNS", "8"))):
        stream = await _completion(messages)
        assistant: dict[str, Any] = {"role": "assistant", "content": ""}
        tool_calls: dict[int, dict[str, Any]] = {}
        async for chunk in stream:
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                final_text += content
                assistant["content"] += content
                _event("content_delta", {"delta": content})
            for tc in getattr(delta, "tool_calls", None) or []:
                idx = int(tc.index or 0)
                cur = tool_calls.setdefault(idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                cur["id"] += getattr(tc, "id", None) or ""
                fn = getattr(tc, "function", None)
                if fn:
                    cur["function"]["name"] += getattr(fn, "name", None) or ""
                    cur["function"]["arguments"] += getattr(fn, "arguments", None) or ""
        if not tool_calls:
            return {"status": "ok", "summary": final_text.strip()}
        assistant["tool_calls"] = list(tool_calls.values())
        messages.append(assistant)
        for call in assistant["tool_calls"]:
            name = call["function"]["name"]
            args = json.loads(call["function"].get("arguments") or "{}")
            _event("tool_call", {"name": name, "arguments": args})
            try:
                result = await run_tool(name, args)
                _event("tool_result", {"name": name, "result": result})
            except Exception as exc:
                result = {"error": str(exc)}
                _event("stderr", {"line": scrub_log(str(exc))})
                _event("tool_result", {"name": name, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.get("id") or name, "content": json.dumps(result)})
    return {"status": "error", "summary": "max agent turns exceeded"}


async def _handle_run(msg: dict[str, Any]) -> None:
    params = msg.get("params") or {}
    task = str(params.get("task") or "develop task")
    try:
        result = await _run_agent(task, str(params.get("context") or ""))
    except Exception as exc:
        scrubbed = scrub_log(str(exc))
        _event("stderr", {"line": scrubbed})
        _send({
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {"code": -32000, "message": scrubbed, "data": {"status": "error", "summary": scrubbed}},
        })
        return
    if isinstance(result, dict) and result.get("status") == "error":
        _send({
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {"code": -32001, "message": result.get("summary", "agent error"), "data": result},
        })
        return
    _send({"jsonrpc": "2.0", "id": msg.get("id"), "result": result})


async def _amain() -> int:
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            return 0
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _event("stderr", {"line": "invalid json"})
            continue
        if msg.get("method") == "agent.cancel":
            _event("stderr", {"line": "worker cancelled"})
            return 0
        if msg.get("method") == "agent.inject":
            params = msg.get("params") or {}
            _injected_messages.append(str(params.get("message") or ""))
            continue
        if msg.get("method") == "agent.run":
            try:
                await _handle_run(msg)
            except Exception as exc:
                _event("stderr", {"line": scrub_log(str(exc))})
                _send({"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32000, "message": scrub_log(str(exc))}})
            continue
        _event("stderr", {"line": f"unknown method {msg.get('method')}"})
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
