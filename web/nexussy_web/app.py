"""Starlette single-file web dashboard and core API proxy.

This module intentionally contains no pipeline business logic. All `/api/*`
requests are forwarded to the core service, with SSE routes streamed byte-for-
byte so browser EventSource clients can rely on core Last-Event-ID replay.
"""

from __future__ import annotations

import os
import json
import uuid
from importlib import resources
from typing import AsyncIterator

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response, StreamingResponse
from starlette.routing import Route


DEFAULT_CORE_BASE_URL = "http://127.0.0.1:7771"
DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 7772
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _core_base_url() -> str:
    return os.getenv("NEXUSSY_WEB_CORE_BASE_URL") or os.getenv(
        "NEXUSSY_CORE_BASE_URL", DEFAULT_CORE_BASE_URL
    )


def _forward_headers(request: Request) -> dict[str, str]:
    """Forward client headers, including Last-Event-ID, minus hop-by-hop ones."""
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _json_error(status_code: int, code: str, message: str, *, retryable: bool = False) -> Response:
    """Return public ErrorResponse JSON for proxy-layer failures only."""
    return Response(
        json.dumps(
            {
                "ok": False,
                "error_code": code,
                "message": message,
                "details": {"source": "web_proxy"},
                "request_id": str(uuid.uuid4()),
                "retryable": retryable,
            }
        ),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
    )


def _is_sse(response: httpx.Response) -> bool:
    return response.headers.get("content-type", "").lower().startswith("text/event-stream")


def _client_for(request: Request) -> httpx.AsyncClient:
    transport = getattr(request.app.state, "core_transport", None)
    return httpx.AsyncClient(
        base_url=request.app.state.core_base_url,
        transport=transport,
        timeout=None,
        follow_redirects=False,
    )


def _upstream_path(request: Request, path: str) -> str:
    """Build upstream path while preserving duplicate query keys and ordering."""
    query = request.scope.get("query_string", b"").decode("ascii")
    return f"/{path}?{query}" if query else f"/{path}"


async def dashboard(_: Request) -> HTMLResponse:
    template = resources.files("nexussy_web").joinpath("templates/index.html")
    return HTMLResponse(template.read_text(encoding="utf-8"))


async def proxy_api(request: Request) -> Response:
    """Proxy every non-SSE `/api/*` request to core unchanged."""
    path = request.path_params["path"]
    body = await request.body()
    try:
        async with _client_for(request) as client:
            upstream = await client.request(
                request.method,
                _upstream_path(request, path),
                content=body,
                headers=_forward_headers(request),
            )
    except httpx.RequestError as exc:
        return _json_error(
            502,
            "provider_unavailable",
            f"Core API unavailable: {exc.__class__.__name__}",
            retryable=True,
        )
    return Response(
        upstream.content,
        status_code=upstream.status_code,
        headers=_response_headers(upstream),
        media_type=upstream.headers.get("content-type"),
    )


async def proxy_sse(request: Request) -> Response:
    """Proxy core SSE without buffering or transforming SSE fields."""
    path = request.url.path.removeprefix("/api/")
    client = _client_for(request)
    upstream_request = client.build_request(
        "GET",
        _upstream_path(request, path),
        headers=_forward_headers(request),
    )
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        return _json_error(
            502,
            "provider_unavailable",
            f"Core SSE unavailable: {exc.__class__.__name__}",
            retryable=True,
        )

    if upstream.status_code >= 400:
        content = await upstream.aread()
        headers = _response_headers(upstream)
        await upstream.aclose()
        await client.aclose()
        return Response(
            content,
            status_code=upstream.status_code,
            headers=headers,
            media_type=upstream.headers.get("content-type"),
        )

    if not _is_sse(upstream):
        await upstream.aclose()
        await client.aclose()
        return _json_error(502, "internal_error", "Core stream response was not text/event-stream")

    async def stream() -> AsyncIterator[bytes]:
        async for chunk in upstream.aiter_raw():
            if chunk:
                yield chunk

    async def cleanup() -> None:
        await upstream.aclose()
        await client.aclose()

    headers = _response_headers(upstream)
    headers["Cache-Control"] = "no-cache"
    headers["Connection"] = "keep-alive"
    headers["X-Accel-Buffering"] = "no"
    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=headers,
        media_type="text/event-stream; charset=utf-8",
        background=BackgroundTask(cleanup),
    )


routes = [
    Route("/", dashboard, methods=["GET"]),
    Route("/api/pipeline/runs/{run_id:str}/stream", proxy_sse, methods=["GET"]),
    Route("/api/swarm/workers/{worker_id:str}/stream", proxy_sse, methods=["GET"]),
    Route("/api/{path:path}", proxy_api, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
]


def create_app(core_base_url: str | None = None, core_transport: httpx.AsyncBaseTransport | None = None) -> Starlette:
    app = Starlette(debug=False, routes=routes)
    app.state.core_base_url = core_base_url or _core_base_url()
    app.state.core_transport = core_transport
    return app


app = create_app()


def main() -> None:
    host = os.getenv("NEXUSSY_WEB_HOST", DEFAULT_WEB_HOST)
    port = int(os.getenv("NEXUSSY_WEB_PORT", str(DEFAULT_WEB_PORT)))
    uvicorn.run("nexussy_web.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
