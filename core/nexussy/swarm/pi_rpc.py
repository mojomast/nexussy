from __future__ import annotations

import asyncio, json, os, pathlib, signal, sys
from collections import deque
from dataclasses import dataclass, field

from nexussy.api.schemas import WorkerStreamPayload
from nexussy.security import scrub_log

MAX_FRAMES = 10_000

@dataclass
class PiFrame:
    kind: str
    payload: WorkerStreamPayload | dict

@dataclass
class PiRPCProcess:
    process: asyncio.subprocess.Process
    worker_id: str | None = None
    protocol: str = "jsonrpc"
    frames: deque[PiFrame] = field(default_factory=lambda: deque(maxlen=MAX_FRAMES))
    _tasks: list[asyncio.Task] = field(default_factory=list)
    cancelled: bool = False
    responses: dict[str, dict] = field(default_factory=dict)
    _response_event: asyncio.Event = field(default_factory=asyncio.Event)

    async def request(self, task: str, context: str = "") -> str:
        rid = os.urandom(4).hex()
        if self.protocol == "pi":
            prompt = task if not context else f"{task}\n\nContext:\n{context}"
            msg = {"id":rid,"type":"prompt","prompt":prompt}
        else:
            msg = {"jsonrpc":"2.0","id":rid,"method":"agent.run","params":{"task":task,"context":context}}
        if self.process.stdin is None:
            raise RuntimeError("PiRPCProcess stdin is not available")
        self.process.stdin.write((json.dumps(msg)+"\n").encode())
        await self.process.stdin.drain()
        return rid

    async def inject(self, message: str) -> None:
        if self.process.stdin is None:
            raise RuntimeError("PiRPCProcess stdin is not available")
        msg = {"id":os.urandom(4).hex(),"type":"prompt","prompt":message} if self.protocol == "pi" else {"jsonrpc":"2.0","method":"agent.inject","params":{"message":message}}
        self.process.stdin.write((json.dumps(msg)+"\n").encode())
        await self.process.stdin.drain()

    async def wait_response(self, request_id: str, timeout_s: float = 900) -> dict:
        loop = asyncio.get_running_loop(); deadline = loop.time() + timeout_s
        remaining = deadline - loop.time()
        while remaining > 0:
            if request_id in self.responses:
                return self.responses[request_id]
            if self.process.returncode is not None:
                await asyncio.gather(*self._tasks, return_exceptions=True)
                if request_id in self.responses:
                    return self.responses[request_id]
                break
            try:
                await asyncio.wait_for(self._response_event.wait(), timeout=min(remaining, 1.0))
            except asyncio.TimeoutError:
                pass
            remaining = deadline - loop.time()
        raise TimeoutError("Pi RPC response timeout")

    async def stop(self, timeout_s: float = 10):
        self.cancelled = True
        try:
            if self.process.stdin:
                payload = {"type":"cancel"} if self.protocol == "pi" else {"jsonrpc":"2.0","method":"agent.cancel","params":{}}
                self.process.stdin.write((json.dumps(payload)+"\n").encode())
                await self.process.stdin.drain()
        except Exception:
            pass
        try:
            if self.process.returncode is not None:
                await asyncio.gather(*self._tasks, return_exceptions=True)
                return
            if sys.platform == "win32":
                self.process.terminate()
            else:
                os.killpg(self.process.pid, signal.SIGTERM)
            await asyncio.wait_for(self.process.wait(), timeout_s)
        except ProcessLookupError:
            pass
        except asyncio.TimeoutError:
            try:
                if sys.platform == "win32":
                    self.process.kill()
                else:
                    os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await self.process.wait()
        await asyncio.gather(*self._tasks, return_exceptions=True)

async def spawn_pi_worker(config, run_id: str, worker_id: str, role: str, project_root: str, worktree: str, core_base_url: str = "http://127.0.0.1:7771") -> PiRPCProcess:
    env = os.environ.copy() | {"NEXUSSY_RUN_ID":run_id,"NEXUSSY_WORKER_ID":worker_id,"NEXUSSY_WORKER_ROLE":role,"NEXUSSY_PROJECT_ROOT":project_root,"NEXUSSY_WORKTREE":worktree,"NEXUSSY_CORE_BASE_URL":core_base_url}
    command = config.pi.command
    args = list(config.pi.args)
    default_model = getattr(config.providers, "default_model", None) or getattr(config.stages.develop, "model", "openai/gpt-5.5-fast")
    env.setdefault("PI_DEFAULT_MODEL", default_model)
    if command == "pi":
        _write_pi_settings(pathlib.Path(worktree), default_model)
        args = ["--mode", "rpc"]
    elif command in {"nexussy-pi", "local-pi-worker"}:
        env.setdefault("PI_DEFAULT_MODEL", default_model)
    try:
        proc = await asyncio.create_subprocess_exec(command, *args, cwd=worktree, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
    except FileNotFoundError as e:
        if command in {"pi", "nexussy-pi", "local-pi-worker"} and os.environ.get("NEXUSSY_DISABLE_BUNDLED_PI") != "1":
            command = sys.executable
            args = ["-m", "nexussy.swarm.local_pi_worker"]
            package_root = str(pathlib.Path(__file__).resolve().parents[2])
            env["PYTHONPATH"] = package_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            proc = await asyncio.create_subprocess_exec(command, *args, cwd=worktree, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        else:
            raise RuntimeError(f"missing Pi CLI: {config.pi.command}") from e
    rpc = PiRPCProcess(proc, worker_id=worker_id, protocol="pi" if command == "pi" else "jsonrpc")
    rpc._tasks = [asyncio.create_task(_drain(rpc, proc.stdout, "stdout", worker_id, config.pi.max_stdout_line_bytes)), asyncio.create_task(_drain(rpc, proc.stderr, "stderr", worker_id, config.pi.max_stdout_line_bytes))]
    return rpc

def _write_pi_settings(worktree: pathlib.Path, default_model: str) -> None:
    settings = worktree / ".pi" / "agent" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    provider, model_id = default_model.split("/", 1) if "/" in default_model else ("openai", default_model)
    settings.write_text(json.dumps({"defaultProvider": provider, "defaultModel": model_id, "defaultModelFull": default_model}, indent=2) + "\n")

async def _drain(rpc: PiRPCProcess, stream, kind: str, worker_id: str, max_bytes: int):
    if stream is None: return
    while True:
        line = await stream.readline()
        if not line: break
        truncated = len(line) > max_bytes
        if truncated: line = line[:max_bytes]
        text = scrub_log(line.decode(errors="replace").rstrip("\n"))
        parsed = False; payload = text
        if kind == "stdout":
            try:
                obj = json.loads(text); parsed = True; payload = obj
                if isinstance(obj, dict) and obj.get("id"):
                    rpc.responses[str(obj["id"])] = obj
                    rpc._response_event.set(); rpc._response_event.clear()
            except json.JSONDecodeError:
                pass
        rpc.frames.append(PiFrame(kind, WorkerStreamPayload(worker_id=worker_id, stream_kind="rpc" if parsed else kind, line=json.dumps(payload) if parsed else text, parsed=parsed, truncated=truncated)))
