const STAGES = ["interview", "design", "validate", "plan", "review", "develop"];
const EVENT_TYPES = [
  "heartbeat", "run_started", "content_delta", "tool_call", "tool_output", "tool_progress",
  "stage_transition", "stage_status", "checkpoint_saved", "artifact_updated", "worker_spawned",
  "worker_status", "worker_task", "worker_stream", "file_claimed", "file_released",
  "file_lock_waiting", "git_event", "blocker_created", "blocker_resolved", "cost_update",
  "pause_state_changed", "pipeline_error", "interview_questions", "done"
];

let state = { sessionId: null, runId: null, es: null, paused: false, stages: [], workers: [], blockers: [], pollTimer: null };

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const key = localStorage.getItem("NEXUSSY_API_KEY") || window.NEXUSSY_API_KEY;
  if (key) headers.set("X-Api-Key", key);
  const res = await fetch(path, { ...options, headers });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const message = data && data.message ? data.message : `${res.status} ${res.statusText}`;
    throw new Error(message);
  }
  return data;
}

function toast(message, tone = "error") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast ${tone}`;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add("hidden"), 4000);
}

function fmt(value) {
  if (!value) return "-";
  try { return new Date(value).toLocaleString(); } catch { return String(value); }
}

function badge(status) {
  const value = status || "created";
  return `<span class="badge ${value}">${value}</span>`;
}

async function init() {
  bindEvents();
  renderStageStepper();
  await loadHealth();
  await loadSessions();
}

function bindEvents() {
  $("refreshSessions").addEventListener("click", () => loadSessions().catch(showError));
  $("newPipelineBtn").addEventListener("click", openModal);
  $("closeModalBtn").addEventListener("click", closeModal);
  $("modalOverlay").addEventListener("click", (event) => { if (event.target.id === "modalOverlay") closeModal(); });
  $("newPipelineForm").addEventListener("submit", submitNewPipeline);
  $("pauseBtn").addEventListener("click", () => controlRun("pause"));
  $("resumeBtn").addEventListener("click", () => controlRun("resume"));
  $("cancelBtn").addEventListener("click", () => controlRun("cancel"));
  $("clearEvents").addEventListener("click", () => { $("eventsLog").textContent = ""; });
}

async function loadHealth() {
  try {
    const health = await api("/health");
    $("versionBadge").textContent = `v${health.version || "unknown"}`;
  } catch (error) {
    $("versionBadge").textContent = "offline";
    showError(error);
  }
}

async function loadSessions() {
  const sessions = await api("/sessions");
  const list = $("sessions");
  if (!sessions.length) {
    list.innerHTML = `<p class="empty">No sessions yet.</p>`;
    return;
  }
  list.innerHTML = sessions.map((session) => `
    <button class="session-item" type="button" data-session="${escapeHtml(session.session_id)}">
      <span><strong>${escapeHtml(session.project_name)}</strong><small>${escapeHtml(session.session_id)}</small></span>
      ${badge(session.status)}
    </button>
  `).join("");
  list.querySelectorAll(".session-item").forEach((button) => {
    button.addEventListener("click", () => selectSession(button.dataset.session).catch(showError));
  });
}

async function selectSession(sessionId) {
  const detail = await api(`/sessions/${encodeURIComponent(sessionId)}`);
  state.sessionId = sessionId;
  const runs = detail.runs || [];
  const run = runs[runs.length - 1];
  if (run && run.run_id) selectRun(run.run_id, sessionId);
  else toast("Session has no runs yet.", "info");
}

function selectRun(runId, sessionId) {
  if (state.es) state.es.close();
  if (state.pollTimer) clearInterval(state.pollTimer);
  state = { ...state, runId, sessionId, es: null, paused: false, stages: [], workers: [], blockers: [] };
  $("eventsLog").textContent = "";
  updateControls();
  pollStatus().catch(showError);
  const streamPath = `/pipeline/runs/${encodeURIComponent(runId)}/stream`;
  const es = new EventSource(streamPath);
  state.es = es;
  EVENT_TYPES.forEach((type) => es.addEventListener(type, handleSse));
  es.onmessage = handleSse;
  es.onerror = () => appendEvent({ type: "stream", payload: "disconnected" });
  state.pollTimer = setInterval(() => pollStatus().catch(showError), 5000);
}

function handleSse(event) {
  let envelope;
  try { envelope = JSON.parse(event.data); } catch { appendEvent({ type: event.type || "message", payload: event.data }); return; }
  const type = envelope.type || event.type;
  if (type !== "heartbeat") appendEvent(envelope);
  switch (type) {
    case "stage_transition":
    case "stage_status":
      mergeStageEvent(envelope.payload || {});
      renderStageStepper();
      break;
    case "worker_spawned":
    case "worker_status":
      upsertWorker(envelope.payload || {});
      renderWorkers();
      break;
    case "blocker_created":
      upsertBlocker(envelope.payload || {});
      renderBlockers();
      break;
    case "blocker_resolved":
      markBlockerResolved(envelope.payload || {});
      renderBlockers();
      break;
    case "pause_state_changed":
      state.paused = Boolean(envelope.payload && envelope.payload.paused);
      updateControls();
      break;
    case "interview_questions":
      renderInterview(envelope.payload && envelope.payload.questions ? envelope.payload.questions : []);
      break;
    case "checkpoint_saved":
    case "artifact_updated":
      maybeLoadInterviewFromArtifact(envelope).catch(() => {});
      break;
    case "done":
      toast(`Run finished: ${(envelope.payload && envelope.payload.final_status) || "done"}`, "success");
      if (state.es) state.es.close();
      if (state.pollTimer) clearInterval(state.pollTimer);
      pollStatus().catch(() => {});
      break;
    case "heartbeat":
      break;
    default:
      break;
  }
}

function appendEvent(envelope) {
  const log = $("eventsLog");
  log.textContent += `${JSON.stringify(envelope, null, 2)}\n`;
  log.scrollTop = log.scrollHeight;
}

async function pollStatus() {
  if (!state.runId) return;
  const status = await api(`/pipeline/status?run_id=${encodeURIComponent(state.runId)}`);
  state.sessionId = status.run.session_id;
  state.stages = status.stages || [];
  state.workers = status.workers || [];
  state.blockers = (status.blockers || []).filter((blocker) => !blocker.resolved);
  state.paused = Boolean(status.paused);
  renderStatus(status.run || {});
  renderStageStepper();
  renderWorkers();
  renderBlockers();
  updateControls();
}

function renderStatus(run) {
  $("runTitle").textContent = run.run_id ? `Run ${run.status || "created"}` : "No active run";
  $("runBadge").className = `badge ${run.status || "created"}`;
  $("runBadge").textContent = run.status || "idle";
  $("runIdValue").textContent = run.run_id || "-";
  $("stageValue").textContent = run.current_stage || "-";
  $("startedValue").textContent = fmt(run.started_at);
  $("finishedValue").textContent = fmt(run.finished_at);
  const usage = run.usage || {};
  $("tokensValue").textContent = usage.total_tokens || 0;
  $("costValue").textContent = `$${Number(usage.cost_usd || 0).toFixed(4)}`;
}

function renderStageStepper() {
  const byName = new Map((state.stages || []).map((stage) => [stage.stage, stage]));
  $("stageStepper").innerHTML = STAGES.map((name) => {
    const stage = byName.get(name) || { stage: name, status: "pending" };
    const status = stage.status || "pending";
    const mark = status === "passed" ? "✓" : status === "failed" ? "✗" : STAGES.indexOf(name) + 1;
    return `<div class="stage-step ${status}"><span class="stage-dot">${mark}</span><span>${name}</span></div>`;
  }).join("");
}

function mergeStageEvent(payload) {
  const stageName = payload.to_stage || payload.stage;
  if (!stageName) return;
  const status = payload.to_status || payload.status || "running";
  const existing = state.stages.find((stage) => stage.stage === stageName);
  if (existing) existing.status = status;
  else state.stages.push({ stage: stageName, status });
}

function upsertWorker(worker) {
  if (!worker.worker_id) return;
  const idx = state.workers.findIndex((item) => item.worker_id === worker.worker_id);
  if (idx >= 0) state.workers[idx] = { ...state.workers[idx], ...worker };
  else state.workers.push(worker);
}

function renderWorkers() {
  const rows = state.workers || [];
  $("workersBody").innerHTML = rows.length ? rows.map((worker) => `
    <tr>
      <td>${escapeHtml(worker.worker_id || "-")}</td>
      <td>${escapeHtml(worker.role || "-")}</td>
      <td>${badge(worker.status || "idle")}</td>
      <td>${escapeHtml(worker.task_title || worker.task_id || "-")}</td>
      <td>${escapeHtml(worker.model || "-")}</td>
    </tr>
  `).join("") : `<tr><td colspan="5" class="empty">No workers yet.</td></tr>`;
}

function upsertBlocker(blocker) {
  if (!blocker.blocker_id) return;
  const idx = state.blockers.findIndex((item) => item.blocker_id === blocker.blocker_id);
  if (idx >= 0) state.blockers[idx] = { ...state.blockers[idx], ...blocker };
  else state.blockers.push(blocker);
}

function markBlockerResolved(blocker) {
  state.blockers = state.blockers.filter((item) => item.blocker_id !== blocker.blocker_id);
}

function renderBlockers() {
  const blockers = (state.blockers || []).filter((blocker) => !blocker.resolved);
  $("blockersPanel").classList.toggle("hidden", blockers.length === 0);
  $("blockersList").innerHTML = blockers.map((blocker) => `
    <div class="blocker-row">
      <div><strong>${escapeHtml(blocker.stage || "run")}</strong><p>${escapeHtml(blocker.message || "blocked")}</p></div>
      <button class="btn btn-ghost" type="button" data-blocker="${escapeHtml(blocker.blocker_id)}">Resolve</button>
    </div>
  `).join("");
  $("blockersList").querySelectorAll("[data-blocker]").forEach((button) => {
    button.addEventListener("click", () => resolveBlocker(button.dataset.blocker).catch(showError));
  });
}

async function resolveBlocker(blockerId) {
  if (!state.runId) return;
  await api("/pipeline/blockers/resolve", { method: "POST", body: JSON.stringify({ run_id: state.runId, blocker_id: blockerId, reason: "resolved from web UI" }) });
  state.blockers = state.blockers.filter((blocker) => blocker.blocker_id !== blockerId);
  renderBlockers();
  toast("Blocker resolved.", "success");
}

function renderInterview(questions) {
  if (!questions || !questions.length) return;
  const panel = $("interviewPanel");
  const form = $("interviewForm");
  panel.classList.remove("hidden");
  form.innerHTML = questions.map((question) => {
    const id = question.id || question.question_id;
    return `<label>${escapeHtml(question.question || id)}${question.required ? " *" : ""}<textarea name="${escapeHtml(id)}" rows="3" required></textarea></label>`;
  }).join("") + `<button class="btn btn-primary" type="submit">Submit Interview Answers</button>`;
  form.onsubmit = submitInterview;
}

async function maybeLoadInterviewFromArtifact(envelope) {
  const payload = envelope.payload || {};
  const artifact = payload.artifact || {};
  if (artifact.kind !== "interview" || !state.sessionId) return;
  const data = await api(`/pipeline/artifacts/interview?session_id=${encodeURIComponent(state.sessionId)}`);
  const parsed = JSON.parse(data.content_text || "{}");
  const pending = (parsed.questions || []).filter((question) => question.answer === "pending");
  if (pending.length) renderInterview(pending.map((question) => ({ id: question.question_id, question: question.question, required: true })));
}

async function submitInterview(event) {
  event.preventDefault();
  if (!state.sessionId) return;
  const form = new FormData(event.currentTarget);
  const answers = {};
  for (const [key, value] of form.entries()) answers[key] = String(value).trim();
  await api(`/pipeline/${encodeURIComponent(state.sessionId)}/interview/answer`, { method: "POST", body: JSON.stringify({ answers }) });
  $("interviewPanel").classList.add("hidden");
  toast("Interview answers submitted.", "success");
}

async function controlRun(action) {
  if (!state.runId) return;
  await api(`/pipeline/${action}`, { method: "POST", body: JSON.stringify({ run_id: state.runId, reason: `web ${action}` }) });
  toast(`Run ${action} requested.`, "success");
  await pollStatus();
}

function updateControls() {
  const hasRun = Boolean(state.runId);
  $("pauseBtn").disabled = !hasRun || state.paused;
  $("resumeBtn").disabled = !hasRun || !state.paused;
  $("cancelBtn").disabled = !hasRun;
}

function openModal() { $("modalOverlay").classList.remove("hidden"); $("projectName").focus(); }
function closeModal() { $("modalOverlay").classList.add("hidden"); $("newPipelineForm").reset(); }

async function submitNewPipeline(event) {
  event.preventDefault();
  const projectName = $("projectName").value.trim();
  const description = $("projectDescription").value.trim();
  const model = $("modelOverride").value.trim();
  const model_overrides = model ? Object.fromEntries(STAGES.map((stage) => [stage, model])) : {};
  const started = await api("/pipeline/start", { method: "POST", body: JSON.stringify({ project_name: projectName, description, model_overrides }) });
  closeModal();
  await loadSessions();
  selectRun(started.run_id, started.session_id);
  toast("Pipeline started.", "success");
}

function showError(error) {
  console.error(error);
  toast(error.message || String(error));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

document.addEventListener("DOMContentLoaded", () => init().catch(showError));
