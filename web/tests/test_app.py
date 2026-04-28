from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import textwrap
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
    for section in ["session-list", "stages", "stream-log", "interview-form", "artifact-viewer"]:
        assert f'id="{section}"' in html
    for tab in ["artifacts", "swarm", "devplan", "config", "secrets"]:
        assert f'id="{tab}"' in html
        assert f'href="#{tab}"' in html
    assert '<link rel="stylesheet" href="/style.css">' in html
    assert '<script src="/app.js" defer></script>' in html
    assert "/api/config" in html
    assert "/api/secrets" in html
    assert 'id="error-banner"' in html
    assert "EventSource /api/pipeline/runs/{run_id}/stream" in html
    assert 'id="cost"' in html


def test_all_required_tabs_include_static_render_targets_and_api_routes(client: TestClient) -> None:
    html = client.get("/").text
    expected = {
        "artifacts": ["artifact-viewer", "review-report"],
        "swarm": ["worker-grid", "file-lock-feed", "worktree-status", "tool-rows"],
        "devplan": ["devplan-content"],
        "config": ["config-editor", "/api/config"],
        "secrets": ["secret-list", "/api/secrets"],
    }
    for global_target in ["session-list", "prev-sessions", "next-sessions", "stages", "transitions", "stream-log"]:
        assert global_target in html
    for tab, needles in expected.items():
        section_start = html.index(f'<section id="{tab}"')
        section_end = html.find('<section id="', section_start + 1)
        section = html[section_start : section_end if section_end != -1 else len(html)]
        for needle in needles:
            assert needle in html if needle.startswith("/api/") else needle in section


def test_fixture_events_have_render_handlers_for_live_dashboard(client: TestClient) -> None:
    script = client.get("/app.js").text
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "contract-events.json"
    event_types = {event["type"] for event in json.loads(fixture_path.read_text())}
    for event_type in event_types:
        assert event_type in script
    for rendered_target in ["stage(", "transition(", "worker(", "lock(", "toolRow(", "#cost", "#worktree-status"]:
        assert rendered_target in script


def test_health_proxies_to_core(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["contract_version"] == "1.0"


def test_zero_build_static_assets_are_served(client: TestClient) -> None:
    script = client.get("/app.js")
    style = client.get("/style.css")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("application/javascript")
    assert "EventSource('/api/pipeline/runs/'" in script.text
    assert "/pipeline/' + encodeURIComponent(sid) + '/interview/answer" in script.text
    assert style.status_code == 200
    assert style.headers["content-type"].startswith("text/css")
    assert "color-scheme:dark" in style.text


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
        ("POST", "/api/pipeline/018f0000-0000-4000-8000-000000000001/interview/answer", '{"answer":"yes"}'),
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
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error_code"] == "internal_error"
    assert payload["message"] == "Core stream response was not text/event-stream"
    assert payload["request_id"]
    assert payload["retryable"] is False


def test_core_unavailable_returns_json_error() -> None:
    def raise_connect_error(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    client = TestClient(
        create_app(core_base_url="http://core", core_transport=httpx.MockTransport(raise_connect_error))
    )
    response = client.get("/api/health")
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error_code"] == "provider_unavailable"
    assert payload["message"] == "Core API unavailable: ConnectError"
    assert payload["details"] == {"source": "web_proxy"}
    assert payload["request_id"]
    assert payload["retryable"] is True


def test_sse_proxy_forwards_first_chunk_before_stream_completion() -> None:
    asyncio.run(_assert_sse_proxy_forwards_first_chunk_before_stream_completion())


async def _assert_sse_proxy_forwards_first_chunk_before_stream_completion() -> None:
    class ControlledStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.first_sent = asyncio.Event()
            self.release_second = asyncio.Event()

        async def __aiter__(self):
            yield b"id: first\nevent: heartbeat\n"
            self.first_sent.set()
            await self.release_second.wait()
            yield b"retry: 3000\ndata: {}\n\n"

    upstream_stream = ControlledStream()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream; charset=utf-8"},
            stream=upstream_stream,
        )

    app = create_app(core_base_url="http://core", core_transport=httpx.MockTransport(handler))
    messages: list[dict[str, object]] = []
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(60)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    task = asyncio.create_task(
        app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "path": "/api/pipeline/runs/run-1/stream",
                "raw_path": b"/api/pipeline/runs/run-1/stream",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 7772),
                "scheme": "http",
            },
            receive,
            send,
        )
    )

    await asyncio.wait_for(upstream_stream.first_sent.wait(), timeout=1)
    first_bodies = [m.get("body", b"") for m in messages if m.get("type") == "http.response.body"]
    assert b"id: first" in b"".join(first_bodies)
    assert b"retry: 3000" not in b"".join(first_bodies)
    assert not task.done()

    upstream_stream.release_second.set()
    await asyncio.wait_for(task, timeout=1)
    all_bodies = [m.get("body", b"") for m in messages if m.get("type") == "http.response.body"]
    assert b"retry: 3000" in b"".join(all_bodies)


def test_dashboard_dom_behaviors_execute_without_build_step(client: TestClient) -> None:
    if shutil.which("node") is None:
        pytest.skip("node is unavailable for DOM execution smoke")

    html = client.get("/").text
    app_js = client.get("/app.js").text
    script = textwrap.dedent(
        r'''
        const fs = require('fs');
        const vm = require('vm');
        const html = fs.readFileSync(process.argv[2], 'utf8');
        const appScript = fs.readFileSync(process.argv[3], 'utf8');
        const assert = (ok, msg) => { if (!ok) throw new Error(msg); };

        class Element {
          constructor(id = '') {
            this.id = id;
            this.children = [];
            this.innerHTML = '';
            this.textContent = '';
            this.value = '';
            this.hash = '';
            this.className = '';
            this.classList = { toggle: () => {}, add: () => {}, remove: () => {} };
            this.style = {};
          }
          append(child) { this.children.push(child); }
          prepend(child) { this.children.unshift(child); this.innerHTML = child.innerHTML + this.innerHTML; }
        }

        const ids = ['health','run-id','error-banner','stream-log','cost','tool-rows','stages','transitions','worker-grid','file-lock-feed','worktree-status','devplan-content','config-editor','secret-list','secret-name','secret-value','load-config','save-config','load-secrets','set-secret','delete-secret','load-devplan','connect-stream','clear-log','load-artifact','artifact-kind','artifact-viewer','review-report','prev-sessions','next-sessions','session-list','pipeline-summary','interview-form','interview-question','interview-answer'];
        const elements = Object.fromEntries(ids.map(id => [id, new Element(id)]));
        elements['artifact-kind'].value = 'devplan';
        const document = {
          querySelector(selector) { if (!selector.startsWith('#')) return new Element(); const id = selector.slice(1); return elements[id] || (elements[id] = new Element(id)); },
          getElementById(id) { return elements[id] || null; },
          createElement() { return new Element(); },
          querySelectorAll() { return []; }
        };
        const localStorage = { data: {}, getItem(k) { return this.data[k] || ''; }, setItem(k, v) { this.data[k] = String(v); } };
        const location = { hash: '#chat' };
        const timers = [];
        const addEventListener = () => {};
        const setInterval = fn => { timers.push(fn); return timers.length; };
        const alert = msg => { throw new Error('unexpected alert: ' + msg); };
        let promptValue = 'session-1';
        const prompt = () => promptValue;
        const d3 = { select() { return { node: () => ({ clientWidth: 800 }), selectAll() { return this; }, remove() {}, append() { return this; }, data() { return this; }, join() { return this; }, attr() { return this; }, call() { return this; }, text() { return this; } }; }, forceSimulation() { return { force() { return this; }, on() { return this; } }; }, forceLink() { return { id() { return { distance() {} }; } }; }, forceManyBody() { return { strength() {} }; }, forceCenter() {}, drag() { return { on() { return this; } }; } };
        const responses = [];
        const fetchCalls = [];
        const jsonResponse = (body, ok = true, status = 200, statusText = 'OK') => ({ ok, status, statusText, json: async () => body });
        async function fetch(url, options = {}) {
          fetchCalls.push({ url, options });
          if (responses.length) return responses.shift();
          if (url === '/api/health') return jsonResponse({ status: 'ok', contract_version: '1.0' });
          if (url.startsWith('/api/sessions')) return jsonResponse([]);
          if (url === '/api/secrets') return jsonResponse([{ name: 'OPENAI_API_KEY', configured: false, source: 'env' }]);
          if (url.startsWith('/api/secrets/')) return jsonResponse({ ok: true });
          if (url.startsWith('/api/pipeline/status')) return jsonResponse({ status: 'running', current_stage: 'interview', run_id: 'run-1', session_id: 'session-1', stages: [{ stage: 'interview', status: 'running' }] });
          if (url.startsWith('/api/pipeline/session-1/interview/answer')) return jsonResponse({ ok: true });
          if (url === '/api/config' && options.method === 'PUT') return jsonResponse(JSON.parse(options.body));
          if (url === '/api/config') return jsonResponse({ version: '1.0', web: { port: 7772 } });
          if (url.startsWith('/api/pipeline/artifacts/devplan')) return jsonResponse({ content_text: '<!-- PROGRESS_LOG_START -->\nbody\n<!-- PROGRESS_LOG_END -->' });
          return jsonResponse({});
        }
        class EventSource {
          constructor(url) { this.url = url; this.listeners = {}; EventSource.last = this; }
          addEventListener(type, fn) { this.listeners[type] = fn; }
          close() { this.closed = true; }
          emit(type, data, id = 'evt-1') { this.listeners[type]({ type, data: JSON.stringify(data), lastEventId: id }); }
        }

        const event = { preventDefault() {} };
        const context = { document, localStorage, location, addEventListener, setInterval, alert, prompt, fetch, EventSource, d3, console, Number, JSON, encodeURIComponent, String };
        vm.createContext(context);
        vm.runInContext(appScript, context);

        (async () => {
          await context.refreshHealth();
          assert(elements.health.textContent === 'core: ok contract 1.0', 'health display did not render');

          responses.push(jsonResponse({ ok: false, error_code: 'unauthorized', message: 'bad key' }, false, 401, 'Unauthorized'));
          await context.refreshHealth();
          assert(elements['error-banner'].textContent.includes('unauthorized: bad key'), 'auth ErrorResponse not displayed');

          elements['run-id'].value = 'run-1';
          elements['connect-stream'].onclick();
          EventSource.last.onerror();
          assert(elements['error-banner'].textContent.includes('stream unavailable/auth/malformed SSE'), 'SSE error display missing');

          EventSource.last.emit('worker_status', { type: 'worker_status', payload: { worker_id: 'worker-1', role: 'developer', status: 'running', task_title: 'Build UI', worktree_path: 'wt' } });
          assert(elements['worker-grid'].children.length === 1, 'worker update did not render');
          assert(elements['worker-grid'].children[0].innerHTML.includes('worker-1'), 'worker id missing');

          EventSource.last.emit('pause_state_changed', { type: 'pause_state_changed', payload: { paused: true, session_id: 'session-1', run_id: 'run-1', question: 'What should we build?' } });
          assert(elements['interview-question'].textContent.includes('What should we build?'), 'interview question not shown');
          elements['interview-answer'].value = 'A dashboard';
          await elements['interview-form'].onsubmit(event);
          assert(fetchCalls.some(c => c.url === '/api/pipeline/session-1/interview/answer' && c.options.method === 'POST'), 'interview answer POST not called');

          await elements['load-devplan'].onclick();
          assert(elements['devplan-content'].innerHTML.includes('class="anchor"'), 'DevPlan anchors not highlighted');

          await elements['load-config'].onclick();
          assert(elements['config-editor'].value.includes('"version"'), 'config editor did not load');
          elements['config-editor'].value = '{"version":"1.0","web":{"port":7773}}';
          await elements['save-config'].onclick();
          assert(elements['config-editor'].value.includes('7773'), 'config editor did not save via API');

          await elements['load-secrets'].onclick();
          assert(elements['secret-list'].innerHTML.includes('OPENAI_API_KEY'), 'secret list did not render');
          elements['secret-name'].value = 'OPENAI_API_KEY';
          elements['secret-value'].value = 'secret-value';
          await elements['set-secret'].onclick();
          await elements['delete-secret'].onclick();
          const secretCalls = fetchCalls.filter(c => c.url.startsWith('/api/secrets'));
          assert(secretCalls.some(c => c.options.method === 'PUT'), 'secret PUT not called');
          assert(secretCalls.some(c => c.options.method === 'DELETE'), 'secret DELETE not called');
          assert(fetchCalls.every(c => c.url.startsWith('/api/')), 'dashboard called non-proxy route');
        })().catch(err => { console.error(err.stack || err); process.exit(1); });
        '''
    )
    tmp_html = Path("/tmp/nexussy-dashboard-dom.html")
    tmp_js = Path("/tmp/nexussy-dashboard-dom.js")
    tmp_app = Path("/tmp/nexussy-dashboard-app.js")
    tmp_html.write_text(html, encoding="utf-8")
    tmp_app.write_text(app_js, encoding="utf-8")
    tmp_js.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", str(tmp_js), str(tmp_html), str(tmp_app)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_devplan_anchor_highlighting_script_includes_all_anchor_names(client: TestClient) -> None:
    html = client.get("/app.js").text
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
