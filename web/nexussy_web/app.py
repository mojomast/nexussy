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
MAX_PROXY_BODY_BYTES = int(os.getenv("NEXUSSY_WEB_MAX_BODY_BYTES", str(10 * 1024 * 1024)))
PROXY_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
BODY_METHODS = {"POST", "PUT", "PATCH"}
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ]
)


def _core_base_url() -> str:
    return os.getenv("NEXUSSY_WEB_CORE_BASE_URL") or os.getenv(
        "NEXUSSY_CORE_BASE_URL", DEFAULT_CORE_BASE_URL
    )


def _core_api_key() -> str | None:
    """Return the dashboard's configured core API key, if any.

    Browser EventSource cannot attach custom headers, so the server-side proxy
    must inject the configured key whenever the browser did not already send
    one.  Support both web-scoped and core-scoped environment names so packaged
    installs and direct development runs can share the same setting.
    """
    return (
        os.getenv("NEXUSSY_WEB_CORE_API_KEY")
        or os.getenv("NEXUSSY_CORE_API_KEY")
        or os.getenv("NEXUSSY_API_KEY")
    )


def _forward_headers(request: Request) -> dict[str, str]:
    """Forward client headers, including Last-Event-ID, minus hop-by-hop ones."""
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }
    if not any(key.lower() == "x-api-key" for key in headers):
        api_key = getattr(request.app.state, "core_api_key", None)
        if api_key:
            headers["X-API-Key"] = api_key
    return headers


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _security_headers() -> dict[str, str]:
    """Browser mitigations for the trusted local dashboard proxy.

    The web proxy intentionally injects a configured core API key when browser
    requests lack one so EventSource can reach authenticated core SSE routes.
    Keep the dashboard zero-build and same-origin only, and block framing/base
    URI abuse to reduce the blast radius of any future DOM bug.
    """
    return {
        "Content-Security-Policy": CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
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
        timeout=PROXY_TIMEOUT,
        follow_redirects=False,
    )


def _upstream_path(request: Request, path: str) -> str:
    """Build upstream path while preserving duplicate query keys and ordering."""
    query = request.url.query
    return f"/{path}?{query}" if query else f"/{path}"


async def _bounded_body(request: Request) -> bytes:
    if request.method.upper() not in BODY_METHODS:
        return b""
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > MAX_PROXY_BODY_BYTES:
                raise ValueError
        except ValueError as exc:
            raise RuntimeError("Payload too large") from exc
    body = await request.body()
    if len(body) > MAX_PROXY_BODY_BYTES:
        raise RuntimeError("Payload too large")
    return body


async def dashboard(_: Request) -> HTMLResponse:
    template = resources.files("nexussy_web").joinpath("templates/index.html")
    return HTMLResponse(template.read_text(encoding="utf-8"), headers=_security_headers())


async def static_asset(request: Request) -> Response:
    """Serve the zero-build dashboard assets packaged with the web app."""
    filename = request.path_params["filename"]
    allowed = {
        "anchors.js": "application/javascript; charset=utf-8",
        "app.js": "application/javascript; charset=utf-8",
        "style.css": "text/css; charset=utf-8",
    }
    if filename not in allowed:
        return _json_error(404, "not_found", "Static asset not found")
    asset = resources.files("nexussy_web").joinpath("static", filename)
    return Response(asset.read_bytes(), media_type=allowed[filename], headers=_security_headers())


async def proxy_api(request: Request) -> Response:
    """Proxy every non-SSE `/api/*` request to core unchanged."""
    path = request.path_params["path"]
    try:
        body = await _bounded_body(request)
    except RuntimeError:
        return _json_error(413, "payload_too_large", "Payload too large")
    try:
        client = _client_for(request)
        upstream_request = client.build_request(
            request.method,
            _upstream_path(request, path),
            content=body,
            headers=_forward_headers(request),
        )
        upstream = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException as exc:
        if "client" in locals():
            await client.aclose()
        return _json_error(
            504,
            "provider_unavailable",
            f"Core API timed out: {exc.__class__.__name__}",
            retryable=True,
        )
    except httpx.RequestError as exc:
        if "client" in locals():
            await client.aclose()
        return _json_error(
            502,
            "provider_unavailable",
            f"Core API unavailable: {exc.__class__.__name__}",
            retryable=True,
        )
    async def stream() -> AsyncIterator[bytes]:
        async for chunk in upstream.aiter_raw():
            if chunk:
                yield chunk

    async def cleanup() -> None:
        await upstream.aclose()
        await client.aclose()

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=_response_headers(upstream),
        media_type=upstream.headers.get("content-type"),
        background=BackgroundTask(cleanup),
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
    except httpx.TimeoutException as exc:
        await client.aclose()
        return _json_error(
            504,
            "provider_unavailable",
            f"Core SSE timed out: {exc.__class__.__name__}",
            retryable=True,
        )
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
    Route("/{filename:str}", static_asset, methods=["GET"]),
    Route("/api/pipeline/runs/{run_id:str}/stream", proxy_sse, methods=["GET"]),
    Route("/api/swarm/workers/{worker_id:str}/stream", proxy_sse, methods=["GET"]),
    Route("/api/{path:path}", proxy_api, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
]


def create_app(
    core_base_url: str | None = None,
    core_transport: httpx.AsyncBaseTransport | None = None,
    core_api_key: str | None = None,
) -> Starlette:
    app = Starlette(debug=False, routes=routes)
    app.state.core_base_url = core_base_url or _core_base_url()
    app.state.core_transport = core_transport
    app.state.core_api_key = core_api_key if core_api_key is not None else _core_api_key()
    return app


app = create_app()


def main() -> None:
    host = os.getenv("NEXUSSY_WEB_HOST", DEFAULT_WEB_HOST)
    port = int(os.getenv("NEXUSSY_WEB_PORT", str(DEFAULT_WEB_PORT)))
    uvicorn.run("nexussy_web.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
