const $ = (id) => document.getElementById(id);
let currentSessionId = "";
let currentRunId = "";
let events = null;

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

async function loadSessions() {
  const sessions = await api("/sessions");
  $("sessions").innerHTML = sessions.map((s) => `<button data-session="${s.session_id}" data-run="${s.last_run_id || ""}">${s.project_name}<span>${s.status}</span></button>`).join("") || "<p>No sessions yet.</p>";
  $("sessions").querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
    currentSessionId = btn.dataset.session;
    if (btn.dataset.run) {
      $("runId").value = btn.dataset.run;
      watchRun(btn.dataset.run);
    }
  }));
}

async function pollStatus() {
  if (!currentRunId) return;
  const status = await api(`/pipeline/status?run_id=${encodeURIComponent(currentRunId)}`);
  currentSessionId = status.run.session_id;
  $("status").textContent = JSON.stringify(status, null, 2);
}

function watchRun(runId) {
  currentRunId = runId;
  if (events) events.close();
  $("events").textContent = "";
  pollStatus().catch((err) => $("status").textContent = err.message);
  events = new EventSource(`/pipeline/runs/${encodeURIComponent(runId)}/stream`);
  events.onmessage = (event) => appendEvent(event.data);
  events.addEventListener("pause_state_changed", (event) => {
    appendEvent(event.data);
    const parsed = JSON.parse(event.data);
    if (parsed.payload && parsed.payload.paused) $("interviewPanel").classList.remove("hidden");
  });
  events.onerror = () => appendEvent("[stream disconnected]");
}

function appendEvent(text) {
  $("events").textContent += `${text}\n`;
  $("events").scrollTop = $("events").scrollHeight;
}

async function submitAnswers() {
  const answers = Object.fromEntries($("answers").value.split("\n").filter(Boolean).map((line) => {
    const [key, ...rest] = line.split("=");
    return [key.trim(), rest.join("=").trim()];
  }));
  await api(`/pipeline/${encodeURIComponent(currentSessionId)}/interview/answer`, { method: "POST", body: JSON.stringify({ answers }) });
  $("interviewPanel").classList.add("hidden");
}

$("refreshSessions").addEventListener("click", () => loadSessions().catch((err) => $("sessions").textContent = err.message));
$("watchRun").addEventListener("click", () => watchRun($("runId").value.trim()));
$("submitAnswers").addEventListener("click", () => submitAnswers().catch((err) => alert(err.message)));
loadSessions().catch((err) => $("sessions").textContent = err.message);
setInterval(() => pollStatus().catch(() => {}), 3000);
