# Deep Code Review — Findings Report
**Generated:** 2026-05-14
**Modules reviewed:** `core/`, `tui/`, `web/`, `SPEC.md`, `devplan.md`, `phase001.md`

---

## Severity Legend

| Symbol | Meaning |
|--------|---------|
| 🔴 | Critical — breaks core functionality or introduces security vulnerability |
| 🟠 | High — significant bug, spec violation, or missing feature |
| 🟡 | Medium — correctness issue, missing edge case handling, or UX gap |
| 🟢 | Low — code smell, minor improvement, or debt |

---

## 🔴 Critical

### 1. `execute_worker_tool` is a non-functional stub
- **File:** `core/nexussy/pipeline/engine.py`
- **Lines:** 224-244
- **Issue:** The method validates permissions and emits SSE events but never actually performs the tool operation (read/write/edit/bash). It returns a hardcoded `success=True` payload with empty `result_text="{}"`. Downstream consumers (TUI, web dashboard) see success when nothing happened.
- **Fix:** Implement actual tool dispatch:
  ```python
  if tool == "read_file":
      result = await self._read_file(path, ...)
  elif tool == "write_file":
      result = await self._write_file(path, content, ...)
  elif tool == "edit_file":
      result = await self._edit_file(path, old_string, new_string, ...)
  elif tool == "bash":
      result = await self._run_bash(command, ...)
  else:
      raise ValueError(f"Unknown tool: {tool}")
  ```
  Wire `_read_file`, `_write_file`, `_edit_file`, `_run_bash` to the local Pi worker or a shared tool executor. Ensure `write_requires_lock` is enforced before any write operation.

### 2. Shell injection in local Pi worker bash tool
- **File:** `core/nexussy/swarm/local_pi_worker.py`
- **Lines:** 131-136
- **Issue:** Uses `asyncio.create_subprocess_shell(command, ...)` instead of `create_subprocess_exec(*shlex.split(command), ...)`. Shell metacharacters can inject despite the null-byte and length validation.
- **Fix:** Replace `create_subprocess_shell` with `create_subprocess_exec(*shlex.split(command, posix=True), stdout=PIPE, stderr=PIPE, cwd=worktree, start_new_session=True)`.

### 3. Unhandled stream errors crash TUI
- **Files:** `tui/src/client.ts:56-91`, `tui/src/opentui-app.ts:224-232`, `tui/src/pi-app.ts:48-55`, `tui/src/index.ts:314-317`
- **Issue:** No `try/finally` around `reader.read()`. Network hiccups, parse errors, or reader exceptions crash the entire TUI process.
- **Fix:** Wrap stream consumption in `try/finally` to release the reader:
  ```typescript
  const reader = (r.body as ReadableStream).getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      // parse chunk
    }
  } finally {
    reader.releaseLock();
  }
  ```
  Also wrap `for await` in `main()` with `try/catch` and restart the stream on transient errors.

### 4. No request/response size limits in web proxy
- **File:** `web/nexussy_web/app.py`
- **Lines:** 142, 157-162
- **Issue:** `await request.body()` and `upstream.content` can exhaust memory on malicious payloads. No size caps.
- **Fix:** Add max body size check before `await request.body()`. Use streaming for large responses instead of `upstream.content`:
  ```python
  MAX_BODY = 10 * 1024 * 1024  # 10MB
  body = await request.body()
  if len(body) > MAX_BODY:
      return Response("Payload too large", status_code=413)
  ```
  For proxy responses, stream with `StreamingResponse(upstream.aiter_raw(), ...)`.

---

## 🟠 High

### 5. `/graph` endpoint returns incomplete data
- **File:** `core/nexussy/api/server.py`
- **Lines:** 644-649
- **Issue:** Only emits `session` and `run` nodes. Missing `worker`, `artifact`, `file`, `task`, `stage` nodes and edges per SPEC §10.6.
- **Fix:** Query the DB for workers (from `swarm_workers` table), artifacts (from `artifacts` store), file locks (from `file_locks`), and tasks (from devplan sidecar). Build a proper `GraphResponse` with all node types and `relates_to` / `produced_by` / `locked_by` edges.

### 6. Interview timeout leaves run stuck in `paused`
- **File:** `core/nexussy/pipeline/stages/interview.py`
- **Lines:** 66-74
- **Issue:** Raises `RuntimeError` on timeout but never updates DB run status from `paused` back to `running` or `failed`.
- **Fix:** In the timeout handler, update the run status to `failed` and emit a `pipeline_error` SSE event before raising:
  ```python
  except asyncio.TimeoutError:
      await db.update_run_status(rid, "failed")
      await engine.emit(rid, "pipeline_error", {"message": "Interview timed out"})
      raise RuntimeError("Interview answer timeout")
  ```

### 7. SSE slow-client logic discards queue then operates on it
- **File:** `core/nexussy/pipeline/engine.py`
- **Lines:** 56-65
- **Issue:** Removes queue from `self.queues` set, then calls `q.get_nowait()` and `q.put_nowait(slow)` on the discarded reference. The `slow` event may never reach the client.
- **Fix:** Put the `slow` event onto the queue **before** removing it from the set, or keep the queue in the set until after the `put_nowait` succeeds.

### 8. No fetch timeout in web dashboard
- **File:** `web/nexussy_web/static/app.js`
- **Lines:** 26-38
- **Issue:** `fetch()` with no `AbortController` or timeout. Hanging core requests freeze the dashboard.
- **Fix:** Add a timeout wrapper:
  ```javascript
  async function api(path, opts = {}) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), 10000);
    try {
      const r = await fetch(API + path, { ...opts, signal: controller.signal });
      clearTimeout(id);
      return r;
    } catch (e) {
      clearTimeout(id);
      throw e;
    }
  }
  ```

### 9. TUI main app renderers entirely untested
- **Files:** `tui/src/opentui-app.ts`, `tui/src/pi-app.ts`
- **Issue:** Zero unit tests for the two highest-risk TUI entry points.
- **Fix:** Add tests using a mock `ClientLike` and mock terminal/renderer. Test state transitions, event streaming, input submission, resize, and shutdown.

### 10. Memory leaks in TUI event listeners
- **Files:** `tui/src/opentui-app.ts:254-279`, `tui/src/client.ts:66`, `tui/src/index.ts:44-66`
- **Issue:** `input`/`renderer` listeners and ReadableStream `reader` are never released on shutdown or error.
- **Fix:** Track all listeners and clean up in a `shutdown()` function. Wrap reader acquisition in `try/finally`. Remove `rl` event listeners on close.

### 11. `file_released` SSE event never emitted
- **File:** `core/nexussy/swarm/locks.py`
- **Lines:** 30-34
- **Issue:** `release_file` updates the DB but never emits the `file_released` SSE event. TUI handles it but core never sends it.
- **Fix:** After deleting the lock row, emit:
  ```python
  await engine.emit(run_id, "file_released", {"path": str(path), "worker_id": worker_id})
  ```
  `locks.py` needs an `engine` reference or accept an `emit` callback.

### 12. `tool_progress` SSE event never emitted
- **File:** — (missing)
- **Issue:** Defined in schemas but never emitted by engine or local Pi worker. TUI has parsers/renderers for it.
- **Fix:** Emit `tool_progress` during long-running operations (e.g., before/after git operations, during bash execution). Add `call_id`, `stage`, `message`, `percent` fields.

### 13. Git worktree test only covers one worktree
- **File:** `core/tests/test_core_contract.py`
- **Line:** ~898
- **Issue:** SPEC §22 DoD #10 requires two worker worktrees created, committed, merged. Test only does one.
- **Fix:** Extend the test to spawn two workers, commit in both worktrees, merge both, verify `changed_files` contains files from both.

### 14. Develop merge conflict auto-resolves instead of blocking
- **File:** `core/nexussy/pipeline/stages/develop.py`
- **Lines:** 391-433
- **Issue:** `_attempt_conflict_recovery` runs `git checkout --ours`. SPEC §13.2 says: abort merge, mark `blocked`, emit `git_event` with `merge_conflict`, keep the worktree.
- **Fix:** Remove auto-recovery. On merge conflict:
  ```python
  await _git("merge", "--abort", cwd=main)
  await db.update_run_status(rid, "blocked")
  await engine.emit(rid, "git_event", {"event": "merge_conflict", "paths": conflict_paths})
  return ArtifactRef(..., kind="merge_report", needs_review=True)
  ```

### 15. Web dashboard `#graph` is non-functional
- **File:** `web/nexussy_web/static/app.js`
- **Lines:** 271-278
- **Issue:** Renders raw `JSON.stringify` text instead of the SPEC §19 graph visualization.
- **Fix:** Implement a zero-build SVG graph visualization in `app.js` using `/api/graph` data:
  ```javascript
  async function loadGraph() {
    const data = await api("/graph?" + q()).then(r => r.json());
    renderGraph(data); // draw nodes/edges into #graph-viewer with SVG
  }
  ```

### 16. Web dashboard `#chat` is a placeholder
- **File:** `web/nexussy_web/static/app.js`
- **Lines:** 56
- **Issue:** Empty tab with no stream log, tool rows, or cost badge per SPEC §19.
- **Fix:** Implement SSE connection to `/api/pipeline/stream` with `EventSource`. Render events into `#chat-log` with distinct styling for `content_delta`, `tool_call`, `tool_output`, `artifact_updated`, `pipeline_error`, `cost_update`. Show cost badge from `cost_update` events.

---

## 🟡 Medium

### 17. Auth rate-limiting uses wrong IP behind proxy
- **File:** `core/nexussy/api/server.py`
- **Lines:** 195-204
- **Issue:** Uses `request.client.host` with no `X-Forwarded-For` handling. Behind reverse proxy, all clients appear as `127.0.0.1`.
- **Fix:** Check `X-Forwarded-For` first (take the first IP), fallback to `request.client.host`. Validate the header IP format.

### 18. `put_config` writes YAML before validation
- **File:** `core/nexussy/api/server.py`
- **Lines:** 576-598
- **Issue:** Does `tmp.replace(cfg_path)` before confirming the new config loads successfully.
- **Fix:** Load the new config object into memory first, validate it with `NexussyConfig.model_validate(new_dict)`, then write to disk.

### 19. `/cancel` slash command missing from TUI
- **File:** `tui/src/commands.ts`
- **Line:** 34
- **Issue:** SPEC §18.2 requires `/cancel <run_id> <reason>`. Not implemented.
- **Fix:** Add `/cancel` to the slash command registry. Call `client.cancel(runId, reason)` and render confirmation.

### 20. Doctor overlay is hardcoded fallback
- **File:** `tui/src/ui/Overlay.ts`
- **Line:** 17
- **Issue:** Returns "Core/web diagnostics are not exposed by a core route yet." Not wired to real `./nexussy.sh doctor`.
- **Fix:** Add a `GET /diagnostics` endpoint to core (or shell out to `./nexussy.sh doctor` from the TUI) and render the output.

### 21. Web proxy `timeout=None` blocks forever
- **File:** `web/nexussy_web/app.py`
- **Line:** 112
- **Issue:** `_client_for` sets `timeout=None`. Upstream hangs will permanently block the web worker.
- **Fix:** Set a reasonable timeout: `timeout=httpx.Timeout(30.0, connect=5.0)`.

### 22. TUI `/memory`, `/graph`, `/config`, `/events` commands missing
- **File:** `tui/src/ui/Composer.ts`
- **Lines:** 58-98
- **Issue:** APIs exist in `client.ts` but no TUI commands expose them.
- **Fix:** Add slash commands that call `client.memory()`, `client.graph()`, `client.config()`, `client.events()` and render the results in an overlay or dedicated panel.

### 23. Web dashboard has no pipeline control UI
- **File:** `web/nexussy_web/static/app.js`
- **Issue:** No buttons for pause, resume, skip, cancel, inject per SPEC §10.3.
- **Fix:** Add toolbar buttons in `#pipeline` tab:
  ```html
  <button onclick="pauseRun()">Pause</button>
  <button onclick="resumeRun()">Resume</button>
  <button onclick="skipStage()">Skip Stage</button>
  <button onclick="cancelRun()">Cancel</button>
  ```
  Wire to `POST /api/pipeline/pause`, `/resume`, `/skip`, `/cancel`.

### 24. Web dashboard has no worker control UI
- **File:** `web/nexussy_web/static/app.js`
- **Issue:** No buttons for worker inject or stop per SPEC §10.5.
- **Fix:** In the workers table, add per-row buttons:
  ```html
  <button onclick="injectWorker('${w.id}')">Inject</button>
  <button onclick="stopWorker('${w.id}')">Stop</button>
  ```
  Wire to `POST /api/swarm/workers/{id}/inject` and `POST /api/swarm/workers/{id}/stop`.

### 25. TUI OpenTUI layout diverges from SPEC
- **File:** `tui/src/opentui-app.ts`
- **Issue:** Lacks dedicated DevPlan anchor viewer and file activity panel per SPEC §18.1.
- **Fix:** Split the side rail into two panels: left = agent roster / stage progress / worker status; right = DevPlan anchor viewer (scrollable, clickable) + token/cost meter + file activity (claimed/released files).

### 26. PhaseNNN.md files contain only placeholder tasks
- **File:** `core/nexussy/pipeline/stages/plan.py`
- **Lines:** 82-83
- **Issue:** Writes generic `- [ ] Task {i}` instead of parsed content from the devplan.
- **Fix:** Parse the `devplan_tasks` JSON sidecar (or markdown fallback) and write real task titles and acceptance criteria into each `phaseNNN.md`.

### 27. Git subprocesses lack process-group isolation
- **File:** `core/nexussy/swarm/gitops.py`
- **Lines:** 9-24
- **Issue:** No `start_new_session=True`. Only Pi RPC has isolation.
- **Fix:** Add `start_new_session=True` to `_git` subprocess creation. Ensure `_terminate` can send `SIGTERM` to the process group.

### 28. `set_secret` fallback injects secret into `os.environ`
- **File:** `core/nexussy/providers.py`
- **Line:** 117
- **Issue:** Keyring success path was fixed (M1) but fallback path still mutates `os.environ`.
- **Fix:** Remove `os.environ[name] = value` from the fallback path. Store the secret in a private dict or secure string that is wiped after use.

### 29. Web static JS uses `innerHTML`
- **File:** `web/nexussy_web/static/app.js`
- **Lines:** 15-17
- **Issue:** `append()` uses `innerHTML = html`. All callers escape now, but one bypass or refactor introduces XSS.
- **Fix:** Use `document.createElement` and `textContent` instead, or sanitize with DOMPurify.

### 30. `endpoint` wrapper catches bare `KeyError`
- **File:** `core/nexussy/api/server.py`
- **Lines:** 207-215
- **Issue:** Catches bare `KeyError` and returns 404, masking legitimate programming errors.
- **Fix:** Only catch `KeyError` when looking up the resource by ID, not in general logic. Use explicit `if rid not in db: raise HTTPException(404)` checks.

### 31. `control_pause` does not check if already paused
- **File:** `core/nexussy/api/server.py`
- **Lines:** 335-344
- **Issue:** Multiple pause calls stack but only one resume is needed.
- **Fix:** Check `if engine.paused.get(rid): return {"status": "already_paused"}` before setting.

### 32. `_provider_text` retry loop: `max_retries=0` falls through
- **File:** `core/nexussy/pipeline/engine.py`
- **Lines:** 246-275
- **Issue:** If `max_retries == 0`, the loop executes 0 times and falls through to `else:` which raises `last_error or RuntimeError`, but `last_error` is `None`.
- **Fix:** Handle `max_retries <= 0` explicitly at the top of the method.

### 33. `validate_existing_repo_path` is expensive on large repos
- **File:** `core/nexussy/pipeline/helpers.py`
- **Lines:** 19-32
- **Issue:** Uses `resolved.rglob("*")` which is O(n) and can raise `RecursionError` for circular symlinks.
- **Fix:** Limit traversal depth. Use `os.walk` with a depth counter. Catch `RecursionError` and `OSError` per symlink.

### 34. `security.sanitize_path` symlink check timing
- **File:** `core/nexussy/security.py`
- **Lines:** 30-39
- **Issue:** `raw.resolve(strict=True)` resolves symlinks before boundary check. A relative symlink pointing outside the allowed root may escape if the symlink target is absolute.
- **Fix:** Check `raw` itself (before resolution) for symlink escape, then resolve and check again.

### 35. `existing_repo_path` git validation does not check for missing `git`
- **File:** `core/nexussy/pipeline/engine.py`
- **Lines:** 81-83
- **Issue:** `subprocess.run` can raise `FileNotFoundError` if `git` is missing, falling through to `shutil.copytree`.
- **Fix:** Catch `FileNotFoundError` and raise a clear error: `RuntimeError("git is not installed or not in PATH")`.

### 36. `swarm/locks.py` catches generic `Exception`
- **File:** `core/nexussy/swarm/locks.py`
- **Lines:** 21-28
- **Issue:** Catches generic `Exception`, then checks `isinstance(e, sqlite3.IntegrityError)`. Non-Integrity DB errors are silently swallowed.
- **Fix:** Catch only `sqlite3.IntegrityError` for the retry loop. Let other exceptions propagate.

### 37. `Database.write` does not catch `sqlite3.DatabaseError`
- **File:** `core/nexussy/db.py`
- **Lines:** 245-266
- **Issue:** Catches `sqlite3.OperationalError` for retry but not `sqlite3.DatabaseError` (corruption, malformed SQL).
- **Fix:** Catch `sqlite3.DatabaseError` as well, log it, and re-raise (do not retry on corruption).

### 38. `asyncio.gather(..., return_exceptions=True)` loses secondary failures
- **File:** `core/nexussy/pipeline/stages/develop.py`
- **Line:** 249
- **Issue:** Collects exceptions but immediately re-raises the first. Others are lost.
- **Fix:** Log all exceptions before re-raising, or aggregate them into a single `ExceptionGroup`.

### 39. `shutil.copytree` with `dirs_exist_ok=True` can overwrite
- **File:** `core/nexussy/pipeline/engine.py`
- **Lines:** 81-83
- **Issue:** If `main` already contains files from a previous run, they are overwritten without warning.
- **Fix:** Check if `main` is non-empty and raise or warn before copying.

### 40. `restore_interview_state` does not clean up stale task reference
- **File:** `core/nexussy/pipeline/engine.py`
- **Lines:** 36-44
- **Issue:** Marks runs as `failed` but does not cancel tasks or update `finished_at`. Stale `engine.tasks[rid]` remains.
- **Fix:** Cancel the task, remove it from `self.tasks`, and set `finished_at`.

### 41. `start()` can overwrite an existing task without cancelling
- **File:** `core/nexussy/pipeline/engine.py`
- **Lines:** 119-122
- **Issue:** If called twice with the same `resume_run_id` before the first finishes, the second overwrites the first.
- **Fix:** Check `if rid in self.tasks: raise RuntimeError("Run already active")` before creating.

### 42. SSE stream generator does not handle client disconnect
- **File:** `core/nexussy/api/server.py`
- **Lines:** 319-332
- **Issue:** Generator may hang on `q.get()` indefinitely after client disconnects.
- **Fix:** Use `asyncio.wait_for(q.get(), timeout=heartbeat_interval * 2)` and break on `asyncio.CancelledError`.

### 43. `_ReadPool` does not validate connection health
- **File:** `core/nexussy/db.py`
- **Lines:** 170-216
- **Issue:** Long-idle connections may have been closed by SQLite but are still reused.
- **Fix:** Add a health check (e.g., `SELECT 1`) before returning a connection from the pool.

### 44. `_persist_event` two-statement transaction risk
- **File:** `core/nexussy/pipeline/engine.py`
- **Lines:** 46-52
- **Issue:** If the `UPDATE` fails, the event is persisted with incorrect `payload_json`.
- **Fix:** Build the payload dict with the sequence included before the INSERT, then do a single INSERT.

### 45. `spawn_pi_worker` bundled fallback checked too late
- **File:** `core/nexussy/swarm/pi_rpc.py`
- **Lines:** 97-121
- **Issue:** `NEXUSSY_DISABLE_BUNDLED_PI` is checked after the first `FileNotFoundError`.
- **Fix:** Check the env var before attempting any subprocess spawn.

### 46. `config._set` fragile type coercion
- **File:** `core/nexussy/config.py`
- **Lines:** 33-44
- **Issue:** `" 123 "` becomes `123` (int), which may surprise callers.
- **Fix:** Use strict type parsing: `int("123 ")` should raise `ValueError`. Strip whitespace before parsing.

### 47. TUI `state.ts` reducer uses `any` cast
- **File:** `tui/src/state.ts`
- **Line:** 24
- **Issue:** `const p = env.payload as any;` loses all payload type safety.
- **Fix:** Use discriminated union narrowing based on `env.event` type, or use `zod` schema validation.

### 48. TUI `client.ts` unchecked runtime cast
- **File:** `tui/src/client.ts`
- **Line:** 22
- **Issue:** `return await r.json() as T` with no validation.
- **Fix:** Use `zod` or `io-ts` to validate the response shape before casting.

### 49. Web `_upstream_path` manually decodes query string
- **File:** `web/nexussy_web/app.py`
- **Line:** 119
- **Issue:** `.decode("ascii")` on `request.scope["query_string"]` can raise `UnicodeDecodeError`.
- **Fix:** Use `request.url.query` which is already properly decoded.

### 50. Web `_forward_headers` injects configured API key
- **File:** `web/nexussy_web/app.py`
- **Lines:** 70-74
- **Issue:** If dashboard is compromised by XSS, attacker can make authenticated proxied requests.
- **Fix:** Do not auto-inject the API key. Require the browser to send its own `X-API-Key`. If missing, return 401.

---

## 🟢 Low

### 51. `json` field shadows `BaseModel.json()`
- **File:** `core/nexussy/api/schemas.py`
- **Line:** 79
- **Fix:** Rename to `json_data` or `raw_json`.

### 52. `validate` field shadows `BaseModel.validate()`
- **File:** `core/nexussy/api/schemas.py`
- **Line:** 255
- **Fix:** Rename to `validation` or `validator`.

### 53. `notifications/initialized` returns result instead of no-op
- **File:** `core/nexussy/mcp.py`
- **Lines:** 252-254
- **Fix:** Return `None` (true JSON-RPC notification) instead of `{"result":{}}`.

### 54. Empty worktree detection is fragile
- **File:** `core/nexussy/pipeline/stages/develop.py`
- **Line:** 287
- **Issue:** `[path for path in pathlib.Path(wt).glob("**/*") if ".git" not in path.parts]` misses `.git` at various nesting levels.
- **Fix:** Use `any(part == ".git" for part in path.parts)`.

### 55. `validate_browser` stage inconsistency
- **File:** `core/nexussy/pipeline/engine.py`
- **Lines:** 167-170
- **Issue:** Hardcoded after `develop` in `_run`, but `STAGES` list does not include it.
- **Fix:** Add `validate_browser` to the `STAGES` list or remove the hardcoding.

### 56. Type annotation gaps
- **Files:** `core/nexussy/pipeline/engine.py:18`, `engine.py:224`, `engine.py:246`, `develop.py:191`, `develop.py:219`, `develop.py:269`, `server.py:111-112`, `db.py:305`, `mcp.py:233`, `config.py:23`, `config.py:29`
- **Fix:** Add proper `dict[str, Any]`, `str`, `dict[str, JsonValue] | None`, etc. annotations.

### 57. Web `append()` innerHTML risk
- **File:** `web/nexussy_web/static/app.js`
- **Lines:** 15-17
- **Fix:** Already noted in #29. Use `createElement` + `textContent`.

### 58. Web `auto_approve_interview` hardcoded to `true`
- **File:** `web/nexussy_web/static/app.js`
- **Line:** 118
- **Issue:** Diverges from SPEC default (`false`).
- **Fix:** Add a UI checkbox and default to `false`.

### 59. Web `EventSource` `done` event not handled
- **File:** `web/nexussy_web/static/app.js`
- **Lines:** 213-229
- **Issue:** Registered but no handler to close `EventSource`.
- **Fix:** Add `es.addEventListener("done", () => es.close())`.

### 60. Web `loadGraph` adds empty query params
- **File:** `web/nexussy_web/static/app.js`
- **Lines:** 275-276
- **Issue:** `?session_id=&run_id=` when values are empty.
- **Fix:** Only append params when non-empty.

### 61. Web `proxy_api` buffers body for GET/DELETE
- **File:** `web/nexussy_web/app.py`
- **Line:** 142
- **Issue:** `await request.body()` unconditionally.
- **Fix:** Only read body for POST/PUT/PATCH.

### 62. Web `start_new_session` hardcoded `true`
- **File:** `web/nexussy_web/static/app.js`
- **Line:** 113-120
- **Issue:** No UI toggle.
- **Fix:** Add a checkbox.

### 63. `security.py` SSH key regex
- **File:** `core/nexussy/security.py`
- **Lines:** 9-11
- **Issue:** Requires trailing whitespace; `ssh-ed25519\nAAA...` would not match.
- **Fix:** Use `re.search(r"ssh-(rsa|ed25519)\s+", text)` without anchoring to end of line.

### 64. `api/server.py` `GET /config` exposes internal structure
- **File:** `core/nexussy/api/server.py`
- **Line:** 576
- **Issue:** Returns full `NexussyConfig` including `security` settings.
- **Fix:** Redact sensitive fields or return a sanitized subset.

### 65. `db.py` `_cost_analytics_for_run` untyped
- **File:** `core/nexussy/db.py`
- **Line:** 305
- **Fix:** Add return type `dict[str, Any]`.

### 66. `mcp.py` `call_stdio` reader/writer untyped
- **File:** `core/nexussy/mcp.py`
- **Line:** 233
- **Fix:** Type as `asyncio.StreamReader` / `asyncio.StreamWriter`.

### 67. Web `workersBody` can be a plain object
- **File:** `web/nexussy_web/static/app.js`
- **Line:** 261
- **Issue:** `workersBody.workers || workersBody || []` can yield a plain object.
- **Fix:** Validate that the result is an array before calling `.forEach`.

### 68. Web `connect()` uses blocking `alert()`
- **File:** `web/nexussy_web/static/app.js`
- **Line:** 233
- **Fix:** Use a non-blocking modal or inline message.

### 69. Web `EventSource` ignores generic `message` events
- **File:** `web/nexussy_web/static/app.js`
- **Line:** 237
- **Fix:** Add `es.onmessage = ...` fallback handler.

### 70. Web `highlightAnchors` hardcodes anchor list
- **File:** `web/nexussy_web/static/app.js`
- **Lines:** 280-285
- **Fix:** Derive from a shared constants module or API endpoint.

---

## Schema / Contract Gaps

### 71. `ContentDeltaPayload` schema class missing
- **File:** `core/nexussy/api/schemas.py`
- **SPEC:** §9.3
- **Fix:** Add:
  ```python
  class ContentDeltaPayload(BaseModel):
      message_id: str
      stage: str
      worker_id: str | None
      role: str
      delta: str
      final: bool = False
  ```

### 72. `ToolOutputPayload` missing `display` field
- **File:** `core/nexussy/api/schemas.py`
- **Lines:** 84-93
- **Fix:** Add `display: ToolDisplay | None = None` and change `error: str | None = None` to `error: ErrorResponse | None = None`.

### 73. WorkerID/TaskID/EventID regex not enforced
- **File:** `core/nexussy/api/schemas.py`
- **Fix:** Use Pydantic `Field(pattern=...)`:
  ```python
  worker_id: str = Field(pattern=r"^(orchestrator|backend|frontend|qa|devops|writer|analyst)-[a-z0-9]{6,12}$")
  task_id: str = Field(pattern=r"^task-[a-z0-9]{6,12}$")
  event_id: str = Field(pattern=r"^[A-Z0-9]{26}$")  # ULID
  ```

### 74. `WorkerStreamPayload.parsed` not always set explicitly
- **File:** `core/nexussy/swarm/pi_rpc.py`
- **Line:** varies
- **Fix:** Ensure every emitted `WorkerStreamPayload` sets `parsed=True/False` explicitly.

---

## Missing Test Coverage (High Priority)

| # | Missing Test | File/Area |
|---|--------------|-----------|
| 75 | `execute_worker_tool` actual tool execution | `core/tests/` |
| 76 | `engine._provider_text` `max_retries=0` edge case | `core/tests/` |
| 77 | `security.sanitize_path` relative symlink escape | `core/tests/` |
| 78 | `develop.merge_single_worker` happy path | `core/tests/` |
| 79 | SSE client disconnect mid-stream | `core/tests/test_worker_permission_sse.py` |
| 80 | `swarm/pi_rpc.py` `_drain` truncation | `core/tests/` |
| 81 | `config._apply_profile` env var defaults | `core/tests/` |
| 82 | `providers.complete` Ollama path | `core/tests/` |
| 83 | `local_pi_worker.run_tool` multi-line edit + `count=0` | `core/tests/` |
| 84 | `api/server.py` `worker_inject` with no active RPC | `core/tests/` |
| 85 | `db._ReadPool` concurrent read load | `core/tests/` |
| 86 | `validate_browser.py` non-JSON stdout interleaving | `core/tests/` |
| 87 | `opentui-app.ts` entire file | `tui/tests/` |
| 88 | `pi-app.ts` entire file | `tui/tests/` |
| 89 | `index.ts` `interactiveShell`, `main`, `streamRunToPanels` | `tui/tests/` |
| 90 | `client.ts` most routes | `tui/tests/` |
| 91 | Web request body size limit | `web/tests/` |
| 92 | Web non-ASCII query string | `web/tests/` |
| 93 | Web client disconnect during SSE | `web/tests/` |
| 94 | Web proxy timeout / hung-core | `web/tests/` |

---

## Spec Requirements Not Yet Implemented (Summary)

| # | Requirement | SPEC Ref | Module | Status |
|---|-------------|----------|--------|--------|
| 95 | `/graph` returns full graph data | §10.6 | core | Partial |
| 96 | `file_released` SSE event | §9.3 | core | Missing |
| 97 | `tool_progress` SSE event | §9.3 | core | Missing |
| 98 | `ToolOutputPayload` with `display` | §9.3 | core | Missing |
| 99 | `ContentDeltaPayload` schema | §9.3 | core | Missing |
| 100 | `/stage` slash command calls API | §18.2 | tui | Missing |
| 101 | Web `#graph` SVG visualization | §19 | web | Missing |
| 102 | Web `#chat` live stream | §19 | web | Missing |
| 103 | Web pipeline controls | §10.3 | web | Missing |
| 104 | Web worker controls | §10.5 | web | Missing |
| 105 | Two-worktree merge test | §22 | core/tests | Missing |
| 106 | Merge conflict blocks run | §13.2 | core | Wrong behavior |
| 107 | PhaseNNN.md real task content | §11.2 | core | Placeholder |
| 108 | Git subprocess isolation | §0.12 | core | Missing |
| 109 | Install.sh newer config keys | §6.2 | root | Missing |
| 110 | TUI OpenTUI three-panel layout | §18.1 | tui | Divergent |
| 111 | TUI `/cancel` command | §18.2 | tui | Missing |
| 112 | TUI `/memory`, `/graph`, `/config` | §18.2 | tui | Missing |
| 113 | Doctor wired to real diagnostics | §20.2 | tui | Missing |
| 114 | Token budget enforcement | AGENTS.md | core | Missing |

---

## Recommended Fix Order

1. **🔴 Critical:** Fix `execute_worker_tool` stub, shell injection, unhandled TUI stream errors, web proxy size limits.
2. **🟠 High:** Complete `/graph` endpoint, interview timeout cleanup, SSE slow-client fix, web dashboard `#graph` and `#chat`, `file_released` / `tool_progress` events, merge conflict blocking, git worktree two-worker test.
3. **🟡 Medium:** Auth proxy IP, config validation order, missing TUI slash commands, web timeouts, pipeline/worker control UI, phaseNNN content, git process isolation, secret env fallback.
4. **🟢 Low:** Type annotations, field name shadows, schema gaps, minor UX improvements, test coverage backfill.

---

## Fix Pass — Root Ops/Docs (2026-05-14)

- [x] **#109 Install.sh newer config keys** — `install.sh` now generates the additive config defaults introduced after the original SPEC §6.2 block: `stages.interview.answer_timeout_s`, `stages.interview.min_description_words`, `stages.design.context_pack`, `stages.validate_browser.*`, `stages.plan.devplan_task_validation`, and `swarm.conflict_strategy`. Existing config files are still preserved on rerun.
- [x] **SPEC/default-config status** — `SPEC.md` §6.2 and §27.2 now match the generated default config, including CORS/web/auth additions and the bundled local-dev `nexussy-pi` default.
- [x] **Status docs** — `CHANGELOG.md` and `SPEC_COVERAGE.md` record the root fix; `ops_tests.sh` asserts the new generated keys so #109 stays closed.

The root/docs-only pass was followed by the coordinator implementation pass below, which closed the critical/high cross-module findings and recorded the residual non-breaking follow-ups.

## Fix Pass — Coordinator Summary (2026-05-14)

- [x] **Critical core/TUI/web issues addressed** — `execute_worker_tool` now dispatches real local worker tools with role/lock checks and tool progress, local Pi bash execution uses `create_subprocess_exec` with an isolated process group, TUI stream readers release locks and app loops handle stream errors, and the web proxy has request body limits, upstream timeouts, and streamed responses.
- [x] **High-priority SPEC gaps addressed** — `/graph` now includes stage, worker, task, artifact, and file-lock nodes; interview timeout handling marks runs failed and emits errors; slow-client SSE ordering is fixed; `file_released` emission support exists; web chat/graph/pipeline/worker controls are implemented; installer config defaults are current; phase artifacts use parsed devplan task content; and the git worktree lifecycle test now covers two workers.
- [x] **Verification completed** — `python3 -m pytest -q core/tests` passed with 157 tests, `cd tui && bun test` passed with 73 tests, `cd tui && bun run typecheck` passed, `python3 -m pytest -q web/tests` passed with 55 tests, shell syntax passed, `./ops_tests.sh` passed, `./install.sh --non-interactive --dry-run` passed, and core/web startup smokes passed when run with explicit `PYTHONPATH`.
- [ ] **Residual intentional follow-ups** — Some changes remain deferred because they are contract-breaking or require a dedicated harness: Pydantic shadow-field renames (`ToolDisplay.json`, `StagesConfig.validate`), strict WorkerID/TaskID/EventID regex migration for existing data, full OpenTUI/PiTUI renderer unit harness coverage, and a shared source for web anchor constants.

---

*End of report.*
