from __future__ import annotations

import json
import os
import pathlib
import sys


def _send(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def _handle_run(msg: dict) -> None:
    params = msg.get("params") or {}
    role = os.environ.get("NEXUSSY_WORKER_ROLE", "worker")
    worker_id = os.environ.get("NEXUSSY_WORKER_ID", role)
    worktree = pathlib.Path(os.environ.get("NEXUSSY_WORKTREE", ".")).resolve()
    task = str(params.get("task") or "develop task")
    _send({"jsonrpc":"2.0","method":"agent.event","params":{"type":"content_delta","payload":{"delta":f"{role} worker accepted task: {task}"}}})
    # Keep the fallback intentionally small: it proves the JSONL Pi RPC path and
    # leaves actual project edits to the engine's deterministic safety fallback.
    marker = worktree / f"{role}.txt"
    marker.write_text(f"{worker_id} completed {task}\n")
    _send({"jsonrpc":"2.0","id":msg.get("id"),"result":{"status":"ok","worker_id":worker_id,"role":role}})


def main() -> int:
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _send({"jsonrpc":"2.0","method":"agent.event","params":{"type":"stderr","payload":{"line":"invalid json"}}})
            continue
        method = msg.get("method")
        if method == "agent.cancel":
            return 0
        if method == "agent.run":
            try:
                _handle_run(msg)
            except Exception as e:
                _send({"jsonrpc":"2.0","id":msg.get("id"),"error":{"code":-32000,"message":str(e)}})
            continue
        _send({"jsonrpc":"2.0","method":"agent.event","params":{"type":"unknown","payload":{"method":method}}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
