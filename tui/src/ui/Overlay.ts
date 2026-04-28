import type { ChatUiState } from "./types";
import { renderOnboarding } from "./Onboarding";
import { renderHandoffModal } from "../components/HandoffModal";

export function renderOverlay(state: ChatUiState): string[] {
  if (state.overlay === "none") return [];
  if (state.overlay === "help") return ["/help", "/onboarding", "/new <description>", "/status", "/stages", "/plan", "/artifacts", "/workers", "/worker <id>", "/dashboard", "/chat", "/pause", "/resume-run", "/skip <stage> <reason>", "/inject [worker_id] <message>", "/secrets", "/doctor", "/quit"];
  if (state.overlay === "onboarding") return renderOnboarding();
  if (state.overlay === "status") return ["Status", `run: ${state.app.runId ?? "none"}`, `paused: ${state.app.paused ? "yes" : "no"}`, `final: ${state.app.finalStatus ?? "-"}`, `tokens: ${state.app.usage.total_tokens}`];
  if (state.overlay === "stages") return ["Stages", ...Object.entries(state.app.stages).map(([k,v]) => `${k}: ${v}`)];
  if (state.overlay === "workers") return ["Workers", ...Object.values(state.app.workers).map(w => `${w.worker_id} ${w.role} ${w.status}${w.task_title ? ` - ${w.task_title}` : ""}`), ...(Object.keys(state.app.workers).length ? [] : ["(none)"])];
  if (state.overlay === "worker") { const w = state.selectedWorkerId ? state.app.workers[state.selectedWorkerId] : undefined; return w ? ["Worker", `${w.worker_id}`, `${w.role} ${w.status}`, w.task_title ?? ""] : ["Worker", "not found"]; }
  if (state.overlay === "plan") return ["Plan", ...(state.app.devplan.length ? state.app.devplan : ["No devplan updates yet."])];
  if (state.overlay === "artifacts") return ["Artifacts", ...(state.app.artifacts.length ? state.app.artifacts.map(a => `${a.kind}: ${a.path}`) : ["No artifacts yet."])];
  if (state.overlay === "secrets") return ["Provider Keys", ...(state.app.secrets.length ? state.app.secrets.map(s => `${s.configured ? "configured" : "missing"} ${s.name}${s.configured ? ` (${s.source})` : ""}`) : ["Run /secrets to refresh provider-key status."])];
  if (state.overlay === "handoff") return renderHandoffModal(state.app);
  if (state.overlay === "doctor") return ["Doctor", "Core/web diagnostics are not exposed by a core route yet.", "Fallback: use ./nexussy.sh doctor in another terminal.", `provider summaries: ${state.app.secrets.filter(s => s.configured).length} configured`];
  return [];
}

export function closeOverlay(state: ChatUiState): ChatUiState { return { ...state, overlay:"none", selectedWorkerId:undefined }; }
