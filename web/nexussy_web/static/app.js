const $ = (selector) => document.querySelector(selector);
const POLL_MS = 5000;
let source = null;
let sessionOffset = 0;
let activeRunId = localStorage.getItem('nexussy.runId') || '';
let activeSessionId = localStorage.getItem('nexussy.sessionId') || '';

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function append(id, html) {
  const el = document.createElement('div');
  el.className = 'event';
  el.innerHTML = html;
  $(id).prepend(el);
}

function reportError(scope, error) {
  const msg = (error && error.message) || String(error || 'unknown');
  $('#error-banner').textContent = `${scope}: ${msg}`;
  append('#stream-log', `<b>${escapeHtml(scope)}</b> <span class="muted">${escapeHtml(msg)}</span>`);
}

async function api(path, options = {}) {
  const response = await fetch('/api' + path, options);
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

async function loadSessions() {
  const rows = normalizeSessions(await api(`/sessions?limit=12&offset=${sessionOffset}`));
  $('#session-list').innerHTML = '';
  rows.forEach((session) => {
    const id = session.session_id || session.id || '';
    const runId = session.run_id || session.latest_run_id || '';
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

function showInterview(payload = {}) {
  const paused = payload.paused === true || payload.status === 'paused';
  $('#interview-form').classList.toggle('hidden', !paused);
  if (!paused) return;
  if (payload.session_id) selectSession(payload.session_id, payload.run_id || activeRunId);
  $('#interview-question').textContent = payload.question || payload.prompt || payload.reason || 'Run is paused for interview input.';
}

function handleEvent(ev) {
  let data = {};
  try { data = JSON.parse(ev.data || '{}'); } catch (_) { reportError('malformed SSE', 'could not parse event JSON'); }
  const type = ev.type || data.type;
  const payload = data.payload || data;
  append('#stream-log', `<b>${escapeHtml(type)}</b> <span class="muted">${escapeHtml(ev.lastEventId || '')}</span><pre>${escapeHtml(ev.data || '')}</pre>`);
  if (payload.session_id) selectSession(payload.session_id, payload.run_id || data.run_id || activeRunId);
  if (data.run_id || payload.run_id) selectSession(activeSessionId, data.run_id || payload.run_id);
  if (type === 'cost_update') $('#cost').textContent = '$' + Number(payload.cost_usd || 0).toFixed(4);
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
  if (!runId) return alert('enter run id');
  selectSession(activeSessionId, runId);
  if (source) source.close();
  source = new EventSource('/api/pipeline/runs/' + encodeURIComponent(runId) + '/stream');
  ['heartbeat','run_started','content_delta','tool_call','tool_output','tool_progress','stage_transition','stage_status','checkpoint_saved','artifact_updated','worker_spawned','worker_status','worker_task','worker_stream','file_claimed','file_released','file_lock_waiting','git_event','blocker_created','blocker_resolved','cost_update','pause_state_changed','pipeline_error','done'].forEach((type) => source.addEventListener(type, handleEvent));
  source.onerror = () => reportError('stream unavailable/auth/malformed SSE', 'EventSource reconnecting; core will replay according to browser Last-Event-ID handling.');
}

async function refreshPipelineStatus() {
  const runId = $('#run-id').value.trim() || activeRunId;
  if (!runId) return;
  try {
    const status = await api('/pipeline/status?run_id=' + encodeURIComponent(runId));
    $('#pipeline-summary').textContent = `${status.status || 'unknown'} ${status.current_stage || ''}`.trim();
    selectSession(status.session_id || activeSessionId, status.run_id || runId);
    (status.stages || status.stage_statuses || []).forEach(stage);
    if (status.pause_state) showInterview({ ...status.pause_state, session_id: status.session_id, run_id: status.run_id || runId });
  } catch (error) {
    reportError('pipeline status failed', error);
  }
}

const anchors = ['PROGRESS_LOG_START','PROGRESS_LOG_END','NEXT_TASK_GROUP_START','NEXT_TASK_GROUP_END','PHASE_TASKS_START','PHASE_TASKS_END','PHASE_PROGRESS_START','PHASE_PROGRESS_END','QUICK_STATUS_START','QUICK_STATUS_END','HANDOFF_NOTES_START','HANDOFF_NOTES_END','SUBAGENT_A_ASSIGNMENT_START','SUBAGENT_A_ASSIGNMENT_END','SUBAGENT_B_ASSIGNMENT_START','SUBAGENT_B_ASSIGNMENT_END','SUBAGENT_C_ASSIGNMENT_START','SUBAGENT_C_ASSIGNMENT_END','SUBAGENT_D_ASSIGNMENT_START','SUBAGENT_D_ASSIGNMENT_END'];
function highlightAnchors(text) {
  let safe = escapeHtml(text);
  anchors.forEach((anchor) => { safe = safe.replaceAll('&lt;!-- ' + anchor + ' --&gt;', `<span class="anchor">&lt;!-- ${anchor} --&gt;</span>`); });
  return safe;
}

$('#prev-sessions').onclick = () => { sessionOffset = Math.max(0, sessionOffset - 12); loadSessions().catch((e) => reportError('sessions failed', e)); };
$('#next-sessions').onclick = () => { sessionOffset += 12; loadSessions().catch((e) => reportError('sessions failed', e)); };
$('#connect-stream').onclick = connect;
$('#clear-log').onclick = () => { $('#stream-log').innerHTML = ''; };
$('#run-id').value = activeRunId;
$('#run-id').onchange = () => selectSession(activeSessionId, $('#run-id').value.trim());
$('#load-artifact').onclick = async () => { try { const sid = activeSessionId || prompt('session_id?'); if (!sid) return; const kind = $('#artifact-kind').value; const body = await api('/pipeline/artifacts/' + kind + '?session_id=' + encodeURIComponent(sid)); $('#artifact-viewer').textContent = body.content_text || JSON.stringify(body, null, 2); if (kind === 'review_report') $('#review-report').textContent = $('#artifact-viewer').textContent; } catch (e) { reportError('artifact load failed', e); } };
$('#load-devplan').onclick = async () => { const sid = activeSessionId || prompt('session_id?'); if (!sid) return; const body = await api('/pipeline/artifacts/devplan?session_id=' + encodeURIComponent(sid)); $('#devplan-content').innerHTML = highlightAnchors(body.content_text || ''); };
$('#load-config').onclick = async () => { $('#config-editor').value = JSON.stringify(await api('/config'), null, 2); };
$('#save-config').onclick = async () => { $('#config-editor').value = JSON.stringify(await api('/config', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: $('#config-editor').value }), null, 2); };
async function loadSecrets() { const rows = await api('/secrets'); $('#secret-list').innerHTML = ''; rows.forEach((secret) => append('#secret-list', `<b>${escapeHtml(secret.name)}</b> ${secret.configured ? 'configured' : 'missing'} <span class="muted">${escapeHtml(secret.source)}</span>`)); }
$('#load-secrets').onclick = loadSecrets;
$('#set-secret').onclick = async () => { await api('/secrets/' + encodeURIComponent($('#secret-name').value), { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ value: $('#secret-value').value }) }); await loadSecrets(); };
$('#delete-secret').onclick = async () => { await api('/secrets/' + encodeURIComponent($('#secret-name').value), { method: 'DELETE' }); await loadSecrets(); };
$('#interview-form').onsubmit = async (event) => { event.preventDefault(); const sid = activeSessionId || prompt('session_id?'); if (!sid) return; await api('/pipeline/' + encodeURIComponent(sid) + '/interview/answer', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ answer: $('#interview-answer').value }) }); $('#interview-answer').value = ''; $('#interview-form').classList.add('hidden'); };

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
