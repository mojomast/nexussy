const $ = (selector) => document.querySelector(selector);
const ANCHORS = Object.freeze(Array.isArray(globalThis.NEXUSSY_ANCHORS) ? [...globalThis.NEXUSSY_ANCHORS] : []);
const POLL_MS = 5000;
const API_TIMEOUT_MS = 10000;
let source = null;
let sessionOffset = 0;
let activeRunId = localStorage.getItem('nexussy.runId') || '';
let activeSessionId = localStorage.getItem('nexussy.sessionId') || '';
let interviewQuestions = [];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function append(id, html) {
  const el = document.createElement('div');
  el.className = 'event';
  const text = String(html ?? '');
  el.textContent = text;
  // Keep older DOM smoke fakes observable while never appending raw markup.
  el.innerHTML = escapeHtml(text);
  $(id).prepend(el);
}

function clear(el) {
  if (typeof el.replaceChildren === 'function') {
    el.replaceChildren();
  } else if (typeof el.removeChild === 'function') {
    while (el.firstChild) el.removeChild(el.firstChild);
  } else if (Array.isArray(el.children)) {
    el.children.length = 0;
  }
  el.textContent = '';
  el.innerHTML = '';
}

function reportError(scope, error) {
  const msg = (error && error.message) || String(error || 'unknown');
  $('#error-banner').textContent = `${scope}: ${msg}`;
  append('#stream-log', `<b>${escapeHtml(scope)}</b> <span class="muted">${escapeHtml(msg)}</span>`);
}

async function api(path, options = {}) {
  const controller = typeof AbortController === 'function' ? new AbortController() : null;
  const canTimeout = typeof setTimeout === 'function' && typeof clearTimeout === 'function';
  const timeoutId = canTimeout && controller ? setTimeout(() => controller.abort(), API_TIMEOUT_MS) : null;
  let response;
  try {
    const fetchOptions = controller ? { ...options, signal: options.signal || controller.signal } : options;
    response = await fetch('/api' + path, fetchOptions);
  } catch (error) {
    if (error && error.name === 'AbortError') throw new Error('request timed out');
    throw error;
  } finally {
    if (canTimeout) clearTimeout(timeoutId);
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.error_code ? `${body.error_code}: ${body.message}` : JSON.stringify(body);
    } catch (_) {}
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function activateTabs() {
  const hash = location.hash || '#artifacts';
  document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', '#' + tab.id === hash));
  document.querySelectorAll('nav a').forEach((link) => link.classList.toggle('active', link.hash === hash));
}

async function refreshHealth() {
  try {
    const health = await api('/health');
    $('#health').textContent = `core: ${health.status || 'ok'} contract ${health.contract_version || '?'}`;
  } catch (error) {
    $('#health').textContent = 'core: unavailable';
    reportError('core unavailable', error);
  }
}

function normalizeSessions(body) {
  if (Array.isArray(body)) return body;
  return body.sessions || body.items || body.rows || [];
}

function normalizeStatus(body) {
  const status = body.status && typeof body.status === 'object' ? body.status : body;
  const run = status.run || body.run || {};
  return {
    raw: body,
    status,
    run,
    run_id: run.run_id || status.run_id || body.run_id || activeRunId,
    session_id: run.session_id || status.session_id || body.session_id || activeSessionId,
    state: run.status || status.status || body.status || 'unknown',
    current_stage: run.current_stage || status.current_stage || body.current_stage || '',
    stages: status.stages || status.stage_statuses || body.stages || body.stage_statuses || [],
    pause_state: status.pause_state || body.pause_state || run.pause_state || null,
    workers: status.workers || body.workers || [],
    file_locks: status.file_locks || status.locks || body.file_locks || body.locks || [],
  };
}

async function loadSessions() {
  const rows = normalizeSessions(await api(`/sessions?limit=12&offset=${sessionOffset}`));
  clear($('#session-list'));
  rows.forEach((session) => {
    const id = session.session_id || session.id || '';
    const runId = session.last_run_id || session.run_id || session.latest_run_id || '';
    const card = document.createElement('button');
    card.className = 'card';
    card.innerHTML = `<b>${escapeHtml(session.project_name || session.name || id)}</b><p>${escapeHtml(session.status || '')} ${escapeHtml(session.current_stage || '')}</p><small>${escapeHtml(id)}</small>`;
    card.onclick = () => selectSession(id, runId);
    $('#session-list').append(card);
  });
}

function selectSession(sessionId, runId = '') {
  if (sessionId) {
    activeSessionId = sessionId;
    localStorage.setItem('nexussy.sessionId', sessionId);
  }
  if (runId) {
    activeRunId = runId;
    $('#run-id').value = runId;
    localStorage.setItem('nexussy.runId', runId);
  }
}

function projectNameFromDescription(description) {
  const words = String(description || '').trim().split(/\s+/).filter(Boolean).slice(0, 6).join(' ');
  return words || 'nexussy run';
}

async function startPipelineFromForm(event) {
  event.preventDefault();
  const description = $('#start-description').value.trim();
  if (!description) return reportError('pipeline start failed', 'Describe what nexussy should build.');
  const pack = $('#design-context-pack').value;
  const body = {
    project_name: $('#start-project-name').value.trim() || projectNameFromDescription(description),
    description,
    auto_approve_interview: $('#auto-approve-interview').checked === true,
    start_new_session: $('#start-new-session').checked !== false,
  };
  if (pack && pack !== 'none') body.metadata = { design_context_pack: pack };
  const started = await api('/pipeline/start', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  selectSession(started.session_id, started.run_id);
  $('#pipeline-summary').textContent = `started ${started.run_id || ''}`.trim();
  connect();
}

function stage(payload) {
  const name = payload.stage || payload.name;
  if (!name) return;
  let el = document.getElementById('stage-' + name);
  if (!el) {
    el = document.createElement('div');
    el.id = 'stage-' + name;
    $('#stages').append(el);
  }
  const status = payload.status || 'pending';
  el.className = 'card stage ' + status;
  el.innerHTML = `<h3>${escapeHtml(name)}</h3><p>${escapeHtml(status)} attempt ${escapeHtml(payload.attempt || 0)}/${escapeHtml(payload.max_attempts || 0)}</p>`;
}

function transition(payload) {
  append('#transitions', `${escapeHtml(payload.from_stage || 'start')} → <b>${escapeHtml(payload.to_stage || '')}</b> ${escapeHtml(payload.reason || '')}`);
}

function worker(payload) {
  const id = payload.worker_id;
  if (!id) return;
  let el = document.getElementById('worker-' + id);
  if (!el) {
    el = document.createElement('div');
    el.id = 'worker-' + id;
    $('#worker-grid').append(el);
  }
  el.className = 'card worker';
  el.innerHTML = `<b>${escapeHtml(id)}</b><p>${escapeHtml(payload.role || '')} / ${escapeHtml(payload.status || '')}</p><p>${escapeHtml(payload.task_title || 'idle')}</p><small>${escapeHtml(payload.worktree_path || '')}</small>`;
  const controls = document.createElement('div');
  controls.className = 'row';
  const inject = document.createElement('button');
  inject.textContent = 'Inject';
  inject.onclick = () => injectWorker(id);
  const stop = document.createElement('button');
  stop.textContent = 'Stop';
  stop.onclick = () => stopWorker(id);
  controls.append(inject);
  controls.append(stop);
  el.append(controls);
}

function toolRow(type, payload) {
  const el = document.createElement('div');
  el.className = 'card tool';
  el.innerHTML = `<b>${escapeHtml(type)}</b> ${escapeHtml(payload.tool_name || payload.message || payload.call_id || '')}<pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
  el.onclick = () => el.classList.toggle('open');
  $('#tool-rows').prepend(el);
}

function lock(type, payload) {
  append('#file-lock-feed', `<b>${escapeHtml(type)}</b> ${escapeHtml(payload.path || '')} by ${escapeHtml(payload.worker_id || '')}`);
}

function renderFileLocks(rows = []) {
  $('#file-lock-feed').innerHTML = '';
  rows.forEach((row) => lock(row.status || row.type || 'file_lock', row));
}

function questionCandidates(payload = {}) {
  if (Array.isArray(payload.questions) && payload.questions.length) return payload.questions;
  if (Array.isArray(payload.pending_questions) && payload.pending_questions.length) return payload.pending_questions;
  if (payload.question || payload.prompt || payload.reason || payload.question_id) return [payload];
  return [];
}

function showInterview(payload = {}) {
  const paused = payload.paused === true || payload.status === 'paused';
  const form = $('#interview-form');
  const fields = $('#interview-fields');
  form.classList.toggle('hidden', !paused);
  if (!paused) {
    interviewQuestions = [];
    fields.innerHTML = '';
    return;
  }
  if (payload.session_id) selectSession(payload.session_id, payload.run_id || activeRunId);
  interviewQuestions = questionCandidates(payload).map((question, index) => ({
    ...question,
    question_id: question.question_id || question.id || `question-${index + 1}`,
    question: question.question || question.prompt || payload.reason || 'Run is paused for interview input.',
    answerElement: null,
  }));
  fields.innerHTML = '';
  interviewQuestions.forEach((question) => {
    const label = document.createElement('label');
    label.textContent = question.question;
    const textarea = document.createElement('textarea');
    textarea.name = question.question_id;
    textarea.rows = 3;
    textarea.placeholder = 'Answer this interview question';
    question.answerElement = textarea;
    fields.append(label);
    fields.append(textarea);
  });
}

function handleEvent(ev) {
  let data = {};
  try { data = JSON.parse(ev.data || '{}'); } catch (_) { reportError('malformed SSE', 'could not parse event JSON'); }
  const type = ev.type || data.type;
  const payload = data.payload || data;
  append('#stream-log', `<b>${escapeHtml(type)}</b> <span class="muted">${escapeHtml(ev.lastEventId || '')}</span><pre>${escapeHtml(ev.data || '')}</pre>`);
  renderChatEvent(type, payload, ev.lastEventId || '');
  if (payload.session_id) selectSession(payload.session_id, payload.run_id || data.run_id || activeRunId);
  if (data.run_id || payload.run_id) selectSession(activeSessionId, data.run_id || payload.run_id);
  if (type === 'cost_update') {
    const total = '$' + Number(payload.cost_usd || payload.total_cost_usd || 0).toFixed(4);
    $('#cost').textContent = total;
    $('#chat-cost').textContent = total;
  }
  if (['tool_call', 'tool_output', 'tool_progress'].includes(type)) toolRow(type, payload);
  if (type === 'stage_transition') transition(payload);
  if (type === 'stage_status') stage(payload);
  if (type === 'worker_spawned' || type === 'worker_status') worker(payload);
  if (['file_claimed', 'file_released', 'file_lock_waiting'].includes(type)) lock(type, payload);
  if (type === 'git_event') append('#worktree-status', `${escapeHtml(payload.action || 'git')} ${escapeHtml(payload.message || '')}`);
  if (type === 'pause_state_changed') showInterview(payload);
}

function connect() {
  const runId = $('#run-id').value.trim() || activeRunId;
  if (!runId) return reportError('stream connect failed', 'enter run id');
  selectSession(activeSessionId, runId);
  if (source) source.close();
  source = new EventSource('/api/pipeline/runs/' + encodeURIComponent(runId) + '/stream');
  ['heartbeat','run_started','content_delta','tool_call','tool_output','tool_progress','stage_transition','stage_status','checkpoint_saved','artifact_updated','worker_spawned','worker_status','worker_task','worker_stream','file_claimed','file_released','file_lock_waiting','git_event','blocker_created','blocker_resolved','cost_update','pause_state_changed','pipeline_error','done'].forEach((type) => source.addEventListener(type, handleEvent));
  source.onmessage = handleEvent;
  source.addEventListener('done', () => source.close());
  source.onerror = () => reportError('stream unavailable/auth/malformed SSE', 'EventSource reconnecting; core will replay according to browser Last-Event-ID handling.');
}

function renderChatEvent(type, payload, eventId) {
  const important = ['content_delta', 'tool_call', 'tool_output', 'tool_progress', 'artifact_updated', 'pipeline_error', 'cost_update', 'worker_stream'];
  if (!important.includes(type)) return;
  const row = document.createElement('div');
  row.className = 'event chat-event ' + type;
  const label = document.createElement('b');
  label.textContent = type;
  const meta = document.createElement('span');
  meta.className = 'muted';
  meta.textContent = eventId ? ' ' + eventId : '';
  const body = document.createElement('pre');
  body.textContent = payload.delta || payload.text || payload.message || payload.tool_name || JSON.stringify(payload, null, 2);
  row.append(label);
  row.append(meta);
  row.append(body);
  $('#chat-log').prepend(row);
}

async function refreshPipelineStatus() {
  const runId = $('#run-id').value.trim() || activeRunId;
  if (!runId) return;
  try {
    const status = normalizeStatus(await api('/pipeline/status?run_id=' + encodeURIComponent(runId)));
    $('#pipeline-summary').textContent = `${status.state || 'unknown'} ${status.current_stage || ''}`.trim();
    selectSession(status.session_id || activeSessionId, status.run_id || runId);
    status.stages.forEach(stage);
    status.workers.forEach(worker);
    if (status.file_locks.length) renderFileLocks(status.file_locks);
    if (status.pause_state) showInterview({ ...status.pause_state, session_id: status.session_id, run_id: status.run_id || runId });
    await refreshSwarmState(status.run_id || runId);
  } catch (error) {
    reportError('pipeline status failed', error);
  }
}

async function refreshSwarmState(runId = activeRunId) {
  if (!runId) return;
  try {
    const workersBody = await api('/swarm/workers?run_id=' + encodeURIComponent(runId));
    const workerRows = workersBody.workers || workersBody.items || workersBody.rows || workersBody || [];
    (Array.isArray(workerRows) ? workerRows : []).forEach(worker);
  } catch (_) {}
  try {
    const locksBody = await api('/swarm/file-locks?run_id=' + encodeURIComponent(runId));
    const rows = locksBody.file_locks || locksBody.locks || locksBody.items || locksBody.rows || locksBody || [];
    if (Array.isArray(rows)) renderFileLocks(rows);
  } catch (_) {}
}

async function loadGraph() {
  const sid = activeSessionId || prompt('session_id?');
  const rid = $('#run-id').value.trim() || activeRunId;
  const query = new URLSearchParams();
  if (sid) query.set('session_id', sid);
  if (rid) query.set('run_id', rid);
  renderGraph(await api('/graph' + (query.toString() ? '?' + query.toString() : '')));
}

function renderGraph(data) {
  const viewer = $('#graph-viewer');
  clear(viewer);
  const svgEl = (name) => (typeof document.createElementNS === 'function' ? document.createElementNS('http://www.w3.org/2000/svg', name) : document.createElement(name));
  const attr = (el, key, value) => { if (typeof el.setAttribute === 'function') el.setAttribute(key, String(value)); else el[key] = String(value); };
  const nodes = Array.isArray(data.nodes) ? data.nodes : [];
  const edges = Array.isArray(data.edges) ? data.edges : [];
  const width = Math.max(640, viewer.clientWidth || 800);
  const height = 480;
  const svg = svgEl('svg');
  attr(svg, 'viewBox', `0 0 ${width} ${height}`);
  attr(svg, 'width', '100%');
  attr(svg, 'height', String(height));
  const summary = document.createElement('p');
  summary.className = 'muted';
  summary.textContent = `nodes:${nodes.length} edges:${edges.length}`;
  viewer.textContent = summary.textContent;
  viewer.append(summary);
  const positions = new Map();
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.36;
  nodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1);
    positions.set(node.id, { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius });
  });
  edges.forEach((edge) => {
    const from = positions.get(edge.source || edge.from);
    const to = positions.get(edge.target || edge.to);
    if (!from || !to) return;
    const line = svgEl('line');
    attr(line, 'x1', from.x); attr(line, 'y1', from.y); attr(line, 'x2', to.x); attr(line, 'y2', to.y);
    attr(line, 'stroke', '#58a6ff'); attr(line, 'stroke-opacity', '0.55');
    svg.append(line);
  });
  nodes.forEach((node) => {
    const pos = positions.get(node.id) || { x: cx, y: cy };
    const group = svgEl('g');
    const circle = svgEl('circle');
    attr(circle, 'cx', pos.x); attr(circle, 'cy', pos.y); attr(circle, 'r', '14'); attr(circle, 'fill', '#7ee787');
    const label = svgEl('text');
    attr(label, 'x', pos.x + 18); attr(label, 'y', pos.y + 4); attr(label, 'fill', '#e6edf3');
    label.textContent = node.label || node.id || node.type || 'node';
    group.append(circle); group.append(label); svg.append(group);
  });
  viewer.append(svg);
}

function currentRunId() { return $('#run-id').value.trim() || activeRunId; }

async function controlRun(action, extra = {}) {
  const runId = currentRunId();
  if (!runId) return reportError(action + ' failed', 'enter run id');
  const body = { run_id: runId, ...extra };
  return api('/pipeline/' + action, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
}

async function injectWorker(workerId) {
  const runId = currentRunId();
  const message = prompt('Message for ' + workerId + '?');
  if (!runId || !message) return;
  await api('/swarm/workers/' + encodeURIComponent(workerId) + '/inject', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ run_id: runId, message }) });
}

async function stopWorker(workerId) {
  const runId = currentRunId();
  if (!runId) return;
  await api('/swarm/workers/' + encodeURIComponent(workerId) + '/stop', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ run_id: runId, reason: 'stopped from web dashboard' }) });
}

function highlightAnchors(text) {
  let safe = escapeHtml(text);
  ANCHORS.forEach((anchor) => { safe = safe.replaceAll('&lt;!-- ' + anchor + ' --&gt;', `<span class="anchor">&lt;!-- ${anchor} --&gt;</span>`); });
  return safe;
}

$('#prev-sessions').onclick = () => { sessionOffset = Math.max(0, sessionOffset - 12); loadSessions().catch((e) => reportError('sessions failed', e)); };
$('#next-sessions').onclick = () => { sessionOffset += 12; loadSessions().catch((e) => reportError('sessions failed', e)); };
$('#connect-stream').onclick = connect;
$('#clear-log').onclick = () => { $('#stream-log').innerHTML = ''; };
$('#run-id').value = activeRunId;
$('#run-id').onchange = () => selectSession(activeSessionId, $('#run-id').value.trim());
$('#pipeline-start-form').onsubmit = (event) => startPipelineFromForm(event).catch((e) => reportError('pipeline start failed', e));
$('#pause-run').onclick = () => controlRun('pause', { reason: 'paused from web dashboard' }).catch((e) => reportError('pause failed', e));
$('#resume-run').onclick = () => controlRun('resume').catch((e) => reportError('resume failed', e));
$('#skip-stage').onclick = () => controlRun('skip', { stage: prompt('Stage to skip?') || '' }).catch((e) => reportError('skip failed', e));
$('#cancel-run').onclick = () => controlRun('cancel', { reason: prompt('Cancel reason?') || 'cancelled from web dashboard' }).catch((e) => reportError('cancel failed', e));
$('#inject-run').onclick = () => controlRun('inject', { message: $('#inject-message').value.trim() }).catch((e) => reportError('inject failed', e));
$('#load-artifact').onclick = async () => { try { const sid = activeSessionId || prompt('session_id?'); if (!sid) return; const kind = $('#artifact-kind').value; const body = await api('/pipeline/artifacts/' + kind + '?session_id=' + encodeURIComponent(sid)); $('#artifact-viewer').textContent = body.content_text || JSON.stringify(body, null, 2); if (kind === 'review_report') $('#review-report').textContent = $('#artifact-viewer').textContent; } catch (e) { reportError('artifact load failed', e); } };
$('#load-devplan').onclick = async () => { const sid = activeSessionId || prompt('session_id?'); if (!sid) return; const body = await api('/pipeline/artifacts/devplan?session_id=' + encodeURIComponent(sid)); $('#devplan-content').innerHTML = highlightAnchors(body.content_text || ''); };
$('#load-graph').onclick = () => loadGraph().catch((e) => reportError('graph load failed', e));
$('#load-config').onclick = async () => { $('#config-editor').value = JSON.stringify(await api('/config'), null, 2); };
$('#save-config').onclick = async () => { $('#config-editor').value = JSON.stringify(await api('/config', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: $('#config-editor').value }), null, 2); };
async function loadSecrets() { const rows = await api('/secrets'); $('#secret-list').innerHTML = ''; rows.forEach((secret) => append('#secret-list', `<b>${escapeHtml(secret.name)}</b> ${secret.configured ? 'configured' : 'missing'} <span class="muted">${escapeHtml(secret.source)}</span>`)); }
$('#load-secrets').onclick = loadSecrets;
$('#set-secret').onclick = async () => { await api('/secrets/' + encodeURIComponent($('#secret-name').value), { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ value: $('#secret-value').value }) }); await loadSecrets(); };
$('#delete-secret').onclick = async () => { await api('/secrets/' + encodeURIComponent($('#secret-name').value), { method: 'DELETE' }); await loadSecrets(); };
$('#interview-form').onsubmit = async (event) => {
  event.preventDefault();
  const sid = activeSessionId || prompt('session_id?');
  if (!sid) return;
  const answers = {};
  for (const question of interviewQuestions) {
    const answer = (question.answerElement?.value || '').trim();
    if (!answer) {
      alert('Answer all interview questions before submitting.');
      return;
    }
    answers[question.question_id] = answer;
  }
  await api('/pipeline/' + encodeURIComponent(sid) + '/interview/answer', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ answers }) });
  interviewQuestions = [];
  $('#interview-fields').innerHTML = '';
  $('#interview-form').classList.add('hidden');
};

['interview','design','validate','plan','review','develop'].forEach((name) => stage({ stage: name, status: 'pending' }));
addEventListener('hashchange', activateTabs);
activateTabs();
refreshHealth();
loadSessions().catch((e) => reportError('sessions failed', e));
loadSecrets().catch(() => {});
refreshPipelineStatus();
setInterval(loadSessions, POLL_MS);
setInterval(refreshPipelineStatus, POLL_MS);
setInterval(refreshHealth, 15000);
