from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexussy_web.app import create_app


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "status": "ok",
            "version": "0.1.0",
            "contract_version": "1.0",
            "db_ok": True,
            "providers_configured": ["mock"],
            "pi_available": False,
        }
    )


async def config(request: Request) -> JSONResponse:
    payload = {
        "version": "1.0",
        "web": {"host": "127.0.0.1", "port": 7772, "core_base_url": "http://127.0.0.1:7771"},
    }
    if request.method == "PUT":
        return JSONResponse(await request.json())
    return JSONResponse(payload)


async def secrets(_: Request) -> JSONResponse:
    return JSONResponse([{"name": "OPENAI_API_KEY", "source": "env", "configured": False, "updated_at": None}])


async def echo(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "method": request.method,
            "query": str(request.url.query),
            "body": (await request.body()).decode(),
            "authorization": request.headers.get("authorization"),
            "x_api_key": request.headers.get("x-api-key"),
            "content_type": request.headers.get("content-type"),
        },
        status_code=207,
    )


async def route_probe(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query),
            "body": (await request.body()).decode(),
            "authorization": request.headers.get("authorization"),
            "x_api_key": request.headers.get("x-api-key"),
        },
        status_code=209,
    )


async def stream(request: Request) -> StreamingResponse:
    if request.query_params.get("auth") == "fail":
        return JSONResponse({"error": {"code": "auth_failed", "message": "bad key"}}, status_code=401)
    if request.query_params.get("malformed") == "true":
        return JSONResponse({"not": "sse"})
    if request.headers.get("last-event-id"):
        assert request.headers.get("last-event-id") == "01HV0000000000000000000000"
    envelope = {
        "event_id": "01HV0000000000000000000001",
        "sequence": 2,
        "contract_version": "1.0",
        "type": "heartbeat",
        "session_id": "018f0000-0000-4000-8000-000000000001",
        "run_id": request.path_params["run_id"],
        "ts": "2026-04-27T00:00:00Z",
        "source": "core",
        "payload": {"ts": "2026-04-27T00:00:00Z", "server_status": "ok"},
    }
    frames = [
        "id: 01HV0000000000000000000001\n",
        "event: heartbeat\n",
        "retry: 3000\n",
        "data: " + json.dumps(envelope) + "\n\n",
        "id: 01HV0000000000000000000002\nevent: content_delta\ndata: {\"contract_version\":\"1.0\",\"type\":\"content_delta\",\"payload\":{\"text\":\"hi\"}}\n\n",
    ]

    async def chunks():
        for frame in frames:
            await asyncio.sleep(0)
            yield frame.encode()

    return StreamingResponse(chunks(), media_type="text/event-stream; charset=utf-8")


async def worker_stream(_: Request) -> StreamingResponse:
    frames = [
        b"id: worker-1\nevent: worker_status\n",
        b"retry: 3000\ndata: {\"contract_version\":\"1.0\"}\n\n",
        b"id: worker-2\nevent: worker_stream\ndata: {\"contract_version\":\"1.0\"}\n\n",
    ]
    return StreamingResponse(iter(frames), media_type="text/event-stream; charset=utf-8")


@pytest.fixture()
def client() -> TestClient:
    core = Starlette(
        routes=[
            Route("/health", health),
            Route("/config", config, methods=["GET", "PUT"]),
            Route("/secrets", secrets),
            Route("/echo", echo, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
            Route("/pipeline/runs/{run_id:str}/stream", stream),
            Route("/swarm/workers/{worker_id:str}/stream", worker_stream),
            Route("/{path:path}", route_probe, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
        ]
    )
    transport = httpx.ASGITransport(app=core)
    return TestClient(create_app(core_base_url="http://core", core_transport=transport))


def test_index_is_single_html_with_required_tabs(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    for tab in ["chat", "pipeline", "swarm", "sessions", "devplan", "graph", "config", "secrets"]:
        assert f'id="{tab}"' in html
        assert f'href="#{tab}"' in html
    assert "cdn.jsdelivr.net/npm/d3@7" in html
    assert "Last-Event-ID" in html
    assert "/api/config" in html
    assert "/api/secrets" in html
    assert 'id="error-banner"' in html
    assert "core unavailable" in html
    assert "auth/malformed SSE" in html
    chat_start = html.index('id="chat"')
    pipeline_start = html.index('id="pipeline"')
    assert 'id="cost"' in html[chat_start:pipeline_start]


def test_all_required_tabs_include_static_render_targets_and_api_routes(client: TestClient) -> None:
    html = client.get("/").text
    expected = {
        "chat": ["stream-log", "tool-rows", "cost"],
        "pipeline": ["stages", "artifact-viewer", "transitions", "review-report"],
        "swarm": ["worker-grid", "file-lock-feed", "worktree-status"],
        "sessions": ["session-list", "prev-sessions", "next-sessions"],
        "devplan": ["devplan-content", "anchor"],
        "graph": ["load-graph", "/api/graph", "forceSimulation"],
        "config": ["config-editor", "/api/config"],
        "secrets": ["secret-list", "/api/secrets"],
    }
    for tab, needles in expected.items():
        section_start = html.index(f'<section id="{tab}"')
        section_end = html.find('<section id="', section_start + 1)
        section = html[section_start : section_end if section_end != -1 else len(html)]
        for needle in needles:
            assert needle in html if needle.startswith("/api/") or needle in {"forceSimulation", "anchor"} else needle in section


def test_fixture_events_have_render_handlers_for_live_dashboard(client: TestClient) -> None:
    html = client.get("/").text
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "contract-events.json"
    event_types = {event["type"] for event in json.loads(fixture_path.read_text())}
    for event_type in event_types:
        assert event_type in html
    for rendered_target in ["stage(", "transition(", "worker(", "lock(", "toolRow(", "#cost", "#worktree-status"]:
        assert rendered_target in html


def test_health_proxies_to_core(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["contract_version"] == "1.0"


def test_api_proxy_preserves_method_body_query_auth_status_and_content_type(client: TestClient) -> None:
    response = client.patch(
        "/api/echo?foo=bar&foo=baz",
        content=b'{"hello":"world"}',
        headers={
            "Authorization": "Bearer token",
            "X-API-Key": "secret",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 207
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["method"] == "PATCH"
    assert payload["query"] == "foo=bar&foo=baz"
    assert payload["body"] == '{"hello":"world"}'
    assert payload["authorization"] == "Bearer token"
    assert payload["x_api_key"] == "secret"
    assert payload["content_type"] == "application/json"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/sessions", '{"project_name":"demo"}'),
        ("GET", "/api/sessions?limit=2&offset=1", ""),
        ("GET", "/api/sessions/018f0000-0000-4000-8000-000000000001", ""),
        ("DELETE", "/api/sessions/018f0000-0000-4000-8000-000000000001?delete_files=true", ""),
        ("POST", "/api/pipeline/start", '{"session_id":"s"}'),
        ("GET", "/api/pipeline/status?run_id=run-1", ""),
        ("POST", "/api/pipeline/inject", '{"run_id":"run-1","message":"hi"}'),
        ("POST", "/api/pipeline/pause", '{"run_id":"run-1","reason":"user"}'),
        ("POST", "/api/pipeline/resume", '{"run_id":"run-1"}'),
        ("POST", "/api/pipeline/skip", '{"run_id":"run-1","stage":"review"}'),
        ("POST", "/api/pipeline/cancel", '{"run_id":"run-1","reason":"user"}'),
        ("GET", "/api/pipeline/artifacts?session_id=s", ""),
        ("GET", "/api/pipeline/artifacts/devplan?session_id=s&phase_number=1", ""),
        ("GET", "/api/swarm/workers?run_id=run-1", ""),
        ("GET", "/api/swarm/workers/worker-1?run_id=run-1", ""),
        ("POST", "/api/swarm/spawn", '{"run_id":"run-1"}'),
        ("POST", "/api/swarm/assign", '{"worker_id":"worker-1"}'),
        ("POST", "/api/swarm/workers/worker-1/inject", '{"run_id":"run-1","message":"hi"}'),
        ("POST", "/api/swarm/workers/worker-1/stop", '{"run_id":"run-1","reason":"user"}'),
        ("GET", "/api/swarm/file-locks?run_id=run-1", ""),
        ("GET", "/api/config", ""),
        ("PUT", "/api/config", '{"version":"1.0"}'),
        ("GET", "/api/secrets", ""),
        ("PUT", "/api/secrets/OPENAI_API_KEY", '{"value":"x"}'),
        ("DELETE", "/api/secrets/OPENAI_API_KEY", ""),
        ("GET", "/api/memory?session_id=s", ""),
        ("POST", "/api/memory", '{"key":"k","value":"v"}'),
        ("DELETE", "/api/memory/mem-1", ""),
        ("GET", "/api/graph?session_id=s&run_id=run-1", ""),
        ("GET", "/api/events?run_id=run-1&after_sequence=3&limit=9", ""),
    ],
)
def test_proxy_covers_relevant_section_10_api_methods_and_routes(
    client: TestClient, method: str, path: str, body: str
) -> None:
    response = client.request(method, path, content=body, headers={"Authorization": "Bearer route-test"})
    assert response.status_code in {200, 209}
    payload = response.json()
    if not isinstance(payload, dict):
        assert response.status_code == 200
        return
    assert payload.get("method", method) == method
    if response.status_code == 209:
        assert payload["path"] == path.split("?", 1)[0].removeprefix("/api")
        assert payload["body"] == body
        assert payload["authorization"] == "Bearer route-test"


def test_config_and_secrets_proxy_routes(client: TestClient) -> None:
    assert client.get("/api/config").json()["version"] == "1.0"
    assert client.get("/api/secrets").json()[0]["name"] == "OPENAI_API_KEY"
    saved = client.put("/api/config", json={"version": "1.0", "web": {"port": 7772}})
    assert saved.json()["web"]["port"] == 7772


def test_sse_proxy_preserves_required_fields_and_last_event_id(client: TestClient) -> None:
    with client.stream(
        "GET",
        "/api/pipeline/runs/018f0000-0000-4000-8000-000000000002/stream",
        headers={"Last-Event-ID": "01HV0000000000000000000000"},
    ) as response:
        body = response.read().decode()
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 01HV0000000000000000000001" in body
    assert "event: heartbeat" in body
    assert "retry: 3000" in body
    assert "data: " in body
    assert "event: content_delta" in body
    assert response.headers["cache-control"] == "no-cache"


def test_worker_sse_proxy_preserves_sse_lines(client: TestClient) -> None:
    with client.stream("GET", "/api/swarm/workers/worker-1/stream?run_id=run-1") as response:
        body = response.read().decode()
    assert response.status_code == 200
    assert "id: worker-1" in body
    assert "event: worker_status" in body
    assert "retry: 3000" in body
    assert "data: " in body
    assert "id: worker-2" in body
    assert "event: worker_stream" in body


def test_sse_proxy_preserves_auth_failure_json_status(client: TestClient) -> None:
    response = client.get("/api/pipeline/runs/run-1/stream?auth=fail")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "auth_failed"


def test_sse_proxy_reports_malformed_sse_content_type(client: TestClient) -> None:
    response = client.get("/api/pipeline/runs/run-1/stream?malformed=true")
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "malformed_sse"


def test_core_unavailable_returns_json_error() -> None:
    def raise_connect_error(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    client = TestClient(
        create_app(core_base_url="http://core", core_transport=httpx.MockTransport(raise_connect_error))
    )
    response = client.get("/api/health")
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "core_unavailable"


def test_devplan_anchor_highlighting_script_includes_all_anchor_names(client: TestClient) -> None:
    html = client.get("/").text
    for anchor in [
        "PROGRESS_LOG_START",
        "PROGRESS_LOG_END",
        "NEXT_TASK_GROUP_START",
        "NEXT_TASK_GROUP_END",
        "PHASE_TASKS_START",
        "PHASE_TASKS_END",
        "PHASE_PROGRESS_START",
        "PHASE_PROGRESS_END",
        "QUICK_STATUS_START",
        "QUICK_STATUS_END",
        "HANDOFF_NOTES_START",
        "HANDOFF_NOTES_END",
        "SUBAGENT_A_ASSIGNMENT_START",
        "SUBAGENT_A_ASSIGNMENT_END",
        "SUBAGENT_B_ASSIGNMENT_START",
        "SUBAGENT_B_ASSIGNMENT_END",
        "SUBAGENT_C_ASSIGNMENT_START",
        "SUBAGENT_C_ASSIGNMENT_END",
        "SUBAGENT_D_ASSIGNMENT_START",
        "SUBAGENT_D_ASSIGNMENT_END",
    ]:
        assert anchor in html


def test_web_requires_no_npm_node_modules_or_build_output() -> None:
    web_root = Path(__file__).resolve().parents[1]
    forbidden = [
        web_root / "package.json",
        web_root / "package-lock.json",
        web_root / "bun.lockb",
        web_root / "node_modules",
        web_root / "dist",
        web_root / "build",
    ]
    assert [path for path in forbidden if path.exists()] == []
