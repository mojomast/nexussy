from __future__ import annotations

import json
import os
import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


class CoreClientError(RuntimeError):
    pass


@dataclass
class ReconnectState:
    last_event_id: str | None = None
    retry_ms: int = 3000


class CoreClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = (base_url or os.environ.get("NEXUSSY_CORE_URL") or "http://127.0.0.1:7771").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("NEXUSSY_API_KEY")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=None, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if extra:
            headers.update(extra)
        return headers

    async def request(self, method: str, path: str, *, json_body: Any = None, params: dict[str, Any] | None = None) -> Any:
        response = await self._client.request(method, path, headers=self.headers(), json=json_body, params=params)
        if response.status_code >= 400:
            raise CoreClientError(response.text or f"{method} {path} failed {response.status_code}")
        return response.json()

    async def health(self) -> Any:
        return await self.request("GET", "/health")

    async def list_sessions(self, limit: int = 10, offset: int = 0) -> Any:
        return await self.request("GET", "/sessions", params={"limit": limit, "offset": offset})

    async def start_pipeline(self, body: dict[str, Any]) -> Any:
        return await self.request("POST", "/pipeline/start", json_body=body)

    async def status(self, run_id: str) -> Any:
        return await self.request("GET", "/pipeline/status", params={"run_id": run_id})

    async def pause(self, run_id: str, reason: str = "user") -> Any:
        return await self.request("POST", "/pipeline/pause", json_body={"run_id": run_id, "reason": reason})

    async def resume(self, run_id: str) -> Any:
        return await self.request("POST", "/pipeline/resume", json_body={"run_id": run_id})

    async def cancel(self, run_id: str, reason: str = "user") -> Any:
        return await self.request("POST", "/pipeline/cancel", json_body={"run_id": run_id, "reason": reason})

    async def skip(self, run_id: str, stage: str, reason: str = "user") -> Any:
        return await self.request("POST", "/pipeline/skip", json_body={"run_id": run_id, "stage": stage, "reason": reason})

    async def inject(self, run_id: str, message: str, stage: str | None = None, worker_id: str | None = None) -> Any:
        return await self.request("POST", "/pipeline/inject", json_body={"run_id": run_id, "message": message, "stage": stage, "worker_id": worker_id})

    async def interview_answer(self, session_id: str, answers: dict[str, str]) -> Any:
        return await self.request("POST", f"/pipeline/{session_id}/interview/answer", json_body={"answers": answers})

    async def artifacts(self, session_id: str, run_id: str | None = None) -> Any:
        return await self.request("GET", "/pipeline/artifacts", params={"session_id": session_id, "run_id": run_id})

    async def workers(self, run_id: str) -> Any:
        return await self.request("GET", "/swarm/workers", params={"run_id": run_id})

    async def config(self) -> Any:
        return await self.request("GET", "/config")

    async def update_config(self, body: dict[str, Any]) -> Any:
        return await self.request("PUT", "/config", json_body=body)

    async def secrets(self) -> Any:
        return await self.request("GET", "/secrets")

    async def stream_run(self, run_id: str, reconnect: ReconnectState | None = None) -> AsyncIterator[dict[str, Any]]:
        reconnect = reconnect or ReconnectState()
        while True:
            try:
                headers = self.headers({"Accept": "text/event-stream"})
                if reconnect.last_event_id:
                    headers["Last-Event-ID"] = reconnect.last_event_id
                async with self._client.stream("GET", f"/pipeline/runs/{run_id}/stream", headers=headers) as response:
                    if response.status_code >= 400:
                        raise CoreClientError(f"SSE failed {response.status_code}")
                    async for frame in parse_sse(response):
                        try:
                            event = parse_envelope(frame)
                        except CoreClientError as exc:
                            yield {"type": "pipeline_error", "event_id": "parse-error", "payload": {"message": str(exc)}}
                            continue
                        reconnect.last_event_id = event.get("event_id")
                        if frame.get("retry"):
                            reconnect.retry_ms = int(frame["retry"])
                        yield event
                        if event.get("type") == "done":
                            return
            except (httpx.ReadError, httpx.ConnectError):
                await asyncio.sleep(reconnect.retry_ms / 1000)
                reconnect.retry_ms = min(reconnect.retry_ms * 2, 30000)
                continue


async def parse_sse(response: httpx.Response) -> AsyncGenerator[dict[str, str], None]:
    buffer = ""
    async for chunk in response.aiter_text():
        buffer += chunk
        while "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
            frame = parse_sse_frame(raw)
            if frame:
                yield frame
    frame = parse_sse_frame(buffer)
    if frame:
        yield frame


def parse_sse_frame(raw: str) -> dict[str, str]:
    frame: dict[str, str] = {}
    data: list[str] = []
    for line in raw.splitlines():
        if not line or line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "data":
            data.append(value)
        else:
            frame[field] = value
    if data:
        frame["data"] = "\n".join(data)
    return frame


def parse_envelope(frame: dict[str, str]) -> dict[str, Any]:
    data = frame.get("data", "")
    if data == "[DONE]":
        return {"type": "done", "event_id": frame.get("id", "done"), "payload": {"final_status": "passed"}}
    try:
        envelope = json.loads(data)
    except json.JSONDecodeError as exc:
        raise CoreClientError(f"invalid SSE envelope JSON: {exc}") from exc
    if frame.get("id") and envelope.get("event_id") != frame["id"]:
        raise CoreClientError("SSE id does not match envelope event_id")
    if frame.get("event") and envelope.get("type") != frame["event"]:
        raise CoreClientError("SSE event does not match envelope type")
    return envelope
