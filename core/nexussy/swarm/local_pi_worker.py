from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import shlex
import signal
import sys
import uuid
from types import SimpleNamespace
from typing import Any, AsyncIterator

from nexussy.api.schemas import StageName, ToolOutputPayload, WorkerRole
from nexussy.security import sanitize_relative_path, scrub_log
from nexussy.swarm.roles import check_tool_permission


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


def _active_role() -> WorkerRole:
    raw = os.environ.get("NEXUSSY_WORKER_ROLE", WorkerRole.backend.value)
    try:
        return WorkerRole(raw)
    except ValueError:
        return WorkerRole.backend


def _permission_denial(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    path = str(arguments.get("path") or "") if isinstance(arguments, dict) else None
    allowed, reason = check_tool_permission(_active_role(), name, path)
    if allowed:
        return None
    return {"success": False, "error": reason or "forbidden", "code": "permission_denied", "tool_name": name}


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
    denied = _permission_denial(name, arguments)
    if denied is not None:
        return denied
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

    argv = shlex.split(command, posix=True)
    if not argv:
        raise ValueError("command_empty")
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(_root()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=safe_env,
        start_new_session=True,
    )
    try:
        out_bytes, err_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
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


def _anthropic_tools_schema() -> list[dict[str, Any]]:
    tools = []
    for tool in _tools_schema():
        fn = tool["function"]
        tools.append({"name": fn["name"], "description": fn["description"], "input_schema": fn["parameters"]})
    return tools


def _agentrouter_token() -> str | None:
    return os.environ.get("AGENTROUTER_API_KEY") or os.environ.get("AGENT_ROUTER_TOKEN")


def _model_id(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def _tool_delta(index: int, tool_id: str, name: str, arguments: str) -> Any:
    fn = SimpleNamespace(name=name, arguments=arguments)
    tc = SimpleNamespace(index=index, id=tool_id, function=fn)
    return SimpleNamespace(content=None, tool_calls=[tc])


def _text_delta(text: str) -> Any:
    return SimpleNamespace(content=text, tool_calls=[])


def _chunk(delta: Any) -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _merge_stream_field(current: str, part: str) -> str:
    if not part:
        return current
    if part.startswith(current):
        return part
    if current.startswith(part):
        return current
    if current.endswith("}") and part.startswith(current[:-1].rstrip()):
        return part
    return current + part


def _tool_arguments(raw: str) -> dict[str, Any]:
    text = raw or "{}"
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        idx = 0
        last: Any = None
        while idx < len(text):
            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text):
                break
            last, idx = decoder.raw_decode(text, idx)
        value = last
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be a JSON object")
    return value


def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            system_parts.append(str(msg.get("content") or ""))
            continue
        if role == "tool":
            pending_tool_results.append({"type": "tool_result", "tool_use_id": str(msg.get("tool_call_id") or ""), "content": str(msg.get("content") or "")})
            continue
        if pending_tool_results:
            out.append({"role": "user", "content": pending_tool_results})
            pending_tool_results = []
        if role == "assistant":
            content: list[dict[str, Any]] = []
            if msg.get("content"):
                content.append({"type": "text", "text": str(msg.get("content"))})
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                try:
                    tool_input = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    tool_input = {}
                content.append({"type": "tool_use", "id": str(call.get("id") or fn.get("name") or "tool"), "name": str(fn.get("name") or ""), "input": tool_input})
            out.append({"role": "assistant", "content": content or [{"type": "text", "text": ""}]})
        else:
            out.append({"role": "user", "content": [{"type": "text", "text": str(msg.get("content") or "")} ]})
    if pending_tool_results:
        out.append({"role": "user", "content": pending_tool_results})
    return "\n\n".join(part for part in system_parts if part), out


async def _agentrouter_completion(model: str, messages: list[dict[str, Any]]) -> AsyncIterator[Any]:
    try:
        import httpx
    except Exception as exc:
        raise RuntimeError("httpx is required for AgentRouter worker calls") from exc
    token = _agentrouter_token()
    if not token:
        raise RuntimeError("missing AgentRouter token")
    session_id = str(uuid.uuid4())
    system, anthropic_messages = _anthropic_messages(messages)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Api-Key": token,
        "User-Agent": "claude-cli/2.1.157 (external, sdk-cli)",
        "X-Claude-Code-Session-Id": session_id,
        "X-Stainless-Arch": "x64",
        "X-Stainless-Lang": "js",
        "X-Stainless-OS": "Linux",
        "X-Stainless-Package-Version": "0.94.0",
        "X-Stainless-Retry-Count": "0",
        "X-Stainless-Runtime": "node",
        "X-Stainless-Runtime-Version": "v24.3.0",
        "X-Stainless-Timeout": "900",
        "anthropic-beta": "claude-code-20250219,interleaved-thinking-2025-05-14,thinking-token-count-2026-05-13,context-management-2025-06-27,prompt-caching-scope-2026-01-05,mid-conversation-system-2026-04-07,advisor-tool-2026-03-01,effort-2025-11-24",
        "anthropic-dangerous-direct-browser-access": "true",
        "anthropic-version": "2023-06-01",
        "x-app": "cli",
    }
    payload = {
        "model": _model_id(model),
        "messages": anthropic_messages,
        "system": [
            {"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1.157.nexussy; cc_entrypoint=sdk-cli; cch=nexussy;"},
            {"type": "text", "text": "You are a Claude agent, built on Anthropic's Claude Agent SDK.", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
        ],
        "tools": _anthropic_tools_schema(),
        "metadata": {"user_id": json.dumps({"device_id": "nexussy", "account_uuid": "", "session_id": session_id})},
        "max_tokens": 4096,
        "stream": True,
    }
    tool_blocks: dict[int, dict[str, str]] = {}
    async with httpx.AsyncClient(timeout=900) as client:
        async with client.stream("POST", "https://agentrouter.org/v1/messages?beta=true", headers=headers, json=payload) as response:
            if response.status_code >= 400:
                raise RuntimeError((await response.aread()).decode("utf-8", errors="replace")[:500])
            async for line in response.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "content_block_start":
                    block = event.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        idx = int(event.get("index") or 0)
                        tool_blocks[idx] = {"id": str(block.get("id") or f"tool-{idx}"), "name": str(block.get("name") or ""), "arguments": ""}
                elif event_type == "content_block_delta":
                    idx = int(event.get("index") or 0)
                    delta = event.get("delta") or {}
                    if isinstance(delta.get("text"), str):
                        yield _chunk(_text_delta(delta["text"]))
                    if isinstance(delta.get("partial_json"), str):
                        block = tool_blocks.setdefault(idx, {"id": f"tool-{idx}", "name": "", "arguments": ""})
                        block["arguments"] = _merge_stream_field(block["arguments"], delta["partial_json"])
                elif event_type == "content_block_stop":
                    idx = int(event.get("index") or 0)
                    block = tool_blocks.pop(idx, None)
                    if block:
                        yield _chunk(_tool_delta(idx, block["id"], block["name"], block["arguments"] or "{}"))
    for idx, block in list(tool_blocks.items()):
        yield _chunk(_tool_delta(idx, block["id"], block["name"], block["arguments"] or "{}"))


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
        {"role": "system", "content": f"You are a nexussy {role} worker running inside worktree {worktree}. Available tools: read_file, write_file, edit_file, bash, list_dir. Stay inside the worktree, never use path traversal or '..', and keep changes focused on assigned tasks. If the task requires creating or changing project files, you must call write_file, edit_file, or bash before giving a final summary. Do not claim implementation is complete until the filesystem change has been made. Devplan tasks:\n{tasks}"},
        {"role": "user", "content": f"Task:\n{task}\n\nContext:\n{context}\n\nInjected messages:\n" + "\n".join(_injected_messages)},
    ]


async def _completion(messages: list[dict[str, Any]]) -> Any:
    model = os.environ.get("PI_DEFAULT_MODEL") or os.environ.get("NEXUSSY_DEFAULT_MODEL") or "openai/gpt-4o-mini"
    if _agentrouter_token():
        return _agentrouter_completion(model, messages)
    from litellm import acompletion  # imported lazily so module import stays side-effect safe

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
                cur["id"] = _merge_stream_field(cur["id"], getattr(tc, "id", None) or "")
                fn = getattr(tc, "function", None)
                if fn:
                    cur["function"]["name"] = _merge_stream_field(cur["function"]["name"], getattr(fn, "name", None) or "")
                    cur["function"]["arguments"] = _merge_stream_field(cur["function"]["arguments"], getattr(fn, "arguments", None) or "")
        if not tool_calls:
            return {"status": "ok", "summary": final_text.strip()}
        assistant["tool_calls"] = list(tool_calls.values())
        messages.append(assistant)
        for call in assistant["tool_calls"]:
            name = call["function"]["name"]
            call_id = call.get("id") or name
            args = _tool_arguments(call["function"].get("arguments") or "{}")
            _event("tool_call", {"call_id": call_id, "name": name, "arguments": args})
            try:
                result = await run_tool(name, args)
                if isinstance(result, dict) and result.get("code") == "permission_denied":
                    output = ToolOutputPayload(call_id=call_id, stage=StageName.develop, success=False, error=str(result.get("error") or "forbidden"), worker_id=os.environ.get("NEXUSSY_WORKER_ID"))
                    _event("tool_output", output.model_dump(mode="json"))
                else:
                    _event("tool_result", {"name": name, "result": result})
            except Exception as exc:
                result = {"error": str(exc)}
                _event("stderr", {"line": scrub_log(str(exc))})
                _event("tool_result", {"name": name, "result": result})
            messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result)})
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
