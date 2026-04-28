import json
import os
import pytest

from nexussy.config import load_config
from nexussy.swarm import local_pi_worker
from nexussy.swarm.local_pi_worker import run_tool
from nexussy.swarm.pi_rpc import spawn_pi_worker


@pytest.mark.asyncio
async def test_local_pi_worker_tools_are_worktree_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUSSY_WORKTREE", str(tmp_path))
    result = await run_tool("write_file", {"path": "src/app.txt", "content": "hello world"})
    assert result["path"] == "src/app.txt"

    read = await run_tool("read_file", {"path": "src/app.txt"})
    assert read["content"] == "hello world"

    edited = await run_tool("edit_file", {"path": "src/app.txt", "old": "world", "new": "nexussy"})
    assert edited["replacements"] == 1
    assert (tmp_path / "src" / "app.txt").read_text() == "hello nexussy"

    listing = await run_tool("list_dir", {"path": "."})
    assert {entry["name"] for entry in listing["entries"]} == {"src"}

    with pytest.raises(ValueError, match="path_rejected"):
        await run_tool("read_file", {"path": "../outside.txt"})


@pytest.mark.asyncio
async def test_bash_empty_command_raises():
    with pytest.raises(ValueError, match="command_empty"):
        await run_tool("bash", {"command": ""})


@pytest.mark.asyncio
async def test_bash_null_byte_raises():
    with pytest.raises(ValueError):
        await run_tool("bash", {"command": "echo\x00hello"})


@pytest.mark.asyncio
async def test_bash_too_long_raises():
    with pytest.raises(ValueError, match="too long"):
        await run_tool("bash", {"command": "x" * 8_001})


@pytest.mark.asyncio
async def test_bash_valid_echo(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUSSY_WORKTREE", str(tmp_path))
    result = await run_tool("bash", {"command": "echo hello"})
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_handle_run_sends_json_rpc_error_when_agent_raises(monkeypatch, capsys):
    async def fail_agent(task, context):
        raise RuntimeError("no api key")

    monkeypatch.setattr(local_pi_worker, "_run_agent", fail_agent)

    await local_pi_worker._handle_run({"jsonrpc": "2.0", "id": "req-1", "method": "agent.run", "params": {}})

    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    response = lines[-1]
    assert response["id"] == "req-1"
    assert "error" in response
    assert "result" not in response
    assert response["error"]["data"]["status"] == "error"
    assert "no api key" in response["error"]["message"]


@pytest.mark.asyncio
async def test_handle_run_converts_agent_error_result_to_json_rpc_error(monkeypatch, capsys):
    async def error_agent(task, context):
        return {"status": "error", "summary": "max agent turns exceeded"}

    monkeypatch.setattr(local_pi_worker, "_run_agent", error_agent)

    await local_pi_worker._handle_run({"jsonrpc": "2.0", "id": "req-2", "method": "agent.run", "params": {}})

    response = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert response["id"] == "req-2"
    assert response["error"]["code"] == -32001
    assert "result" not in response


@pytest.mark.asyncio
async def test_real_pi_command_writes_settings_and_uses_rpc_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUSSY_DISABLE_BUNDLED_PI", "1")
    child = tmp_path / "pi"
    child.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path('argv.txt').write_text(' '.join(sys.argv[1:]))\n"
        "pathlib.Path('model.txt').write_text(os.environ.get('PI_DEFAULT_MODEL',''))\n"
        "line=sys.stdin.readline()\n"
        "msg=json.loads(line)\n"
        "print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'status':'ok'}}), flush=True)\n"
    )
    child.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    cfg = load_config({"providers": {"default_model": "openai/test-model"}, "pi": {"command": "pi", "args": ["--ignored"], "shutdown_timeout_s": 0}})

    rpc = await spawn_pi_worker(cfg, "run", "worker", "backend", str(tmp_path), str(tmp_path))
    req_id = await rpc.request("task")
    assert (await rpc.wait_response(req_id, 5))["result"]["status"] == "ok"
    await rpc.stop(timeout_s=.1)

    assert (tmp_path / "argv.txt").read_text() == "--rpc-mode"
    assert (tmp_path / "model.txt").read_text() == "openai/test-model"
    settings = (tmp_path / ".pi" / "agent" / "settings.json").read_text()
    assert "openai/test-model" in settings
