from __future__ import annotations

import asyncio, json, os, signal
from dataclasses import dataclass, field

from nexussy.api.schemas import ErrorCode, ErrorResponse, WorkerStreamPayload
from nexussy.security import scrub_log

@dataclass
class PiFrame:
    kind: str
    payload: WorkerStreamPayload | dict

@dataclass
class PiRPCProcess:
    process: asyncio.subprocess.Process
    frames: list[PiFrame] = field(default_factory=list)
    _tasks: list[asyncio.Task] = field(default_factory=list)
    cancelled: bool = False
    responses: dict[str, dict] = field(default_factory=dict)

    async def request(self, task: str, context: str = "") -> str:
        rid = os.urandom(4).hex()
        msg = {"jsonrpc":"2.0","id":rid,"method":"agent.run","params":{"task":task,"context":context}}
        assert self.process.stdin is not None
        self.process.stdin.write((json.dumps(msg)+"\n").encode())
        await self.process.stdin.drain()
        return rid

    async def wait_response(self, request_id: str, timeout_s: float = 900) -> dict:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            if request_id in self.responses:
                return self.responses[request_id]
            if self.process.returncode is not None:
                break
            await asyncio.sleep(0.02)
        raise TimeoutError("Pi RPC response timeout")

    async def stop(self, timeout_s: float = 10):
        self.cancelled = True
        try:
            if self.process.stdin:
                self.process.stdin.write(b'{"jsonrpc":"2.0","method":"agent.cancel","params":{}}\n')
                await self.process.stdin.drain()
        except Exception:
            pass
        try:
            if self.process.returncode is not None:
                await asyncio.gather(*self._tasks, return_exceptions=True)
                return
            os.killpg(self.process.pid, signal.SIGTERM)
            await asyncio.wait_for(self.process.wait(), timeout_s)
        except ProcessLookupError:
            pass
        except asyncio.TimeoutError:
            os.killpg(self.process.pid, signal.SIGKILL)
            await self.process.wait()
        await asyncio.gather(*self._tasks, return_exceptions=True)

async def spawn_pi_worker(config, run_id: str, worker_id: str, role: str, project_root: str, worktree: str, core_base_url: str = "http://127.0.0.1:7771") -> PiRPCProcess:
    env = os.environ.copy() | {"NEXUSSY_RUN_ID":run_id,"NEXUSSY_WORKER_ID":worker_id,"NEXUSSY_WORKER_ROLE":role,"NEXUSSY_PROJECT_ROOT":project_root,"NEXUSSY_WORKTREE":worktree,"NEXUSSY_CORE_BASE_URL":core_base_url}
    try:
        proc = await asyncio.create_subprocess_exec(config.pi.command, *config.pi.args, cwd=worktree, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
    except FileNotFoundError as e:
        raise RuntimeError(f"missing Pi CLI: {config.pi.command}") from e
    rpc = PiRPCProcess(proc)
    rpc._tasks = [asyncio.create_task(_drain(rpc, proc.stdout, "stdout", worker_id, config.pi.max_stdout_line_bytes)), asyncio.create_task(_drain(rpc, proc.stderr, "stderr", worker_id, config.pi.max_stdout_line_bytes))]
    return rpc

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
            except json.JSONDecodeError:
                pass
        rpc.frames.append(PiFrame(kind, WorkerStreamPayload(worker_id=worker_id, stream_kind="rpc" if parsed else kind, line=json.dumps(payload) if parsed else text, parsed=parsed, truncated=truncated)))
