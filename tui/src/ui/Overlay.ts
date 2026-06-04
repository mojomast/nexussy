import type { ChatUiState } from "./types";
import { STAGES } from "../state";
import { renderOnboarding } from "./Onboarding";
import { renderHandoffModal } from "../components/HandoffModal";
import { modelLabel, routingProfiles } from "../lib/routing";
import { renderPipelineRows, workerStage } from "./PipelineStrip";

export function renderOverlay(state: ChatUiState): string[] {
  if (state.overlay === "none") return [];
  if (state.overlay === "help") return [...gateHelp(state), "/help", "/onboarding", "/new <description>", "/new --auto-interview <description>", "/interview-answer q1=answer q2=answer", "/pipeline", "/models", "/routing", "/model <stage> <provider/model>", "/fallback <stage> <provider/model>", "/profile <name>", "/status", "/stages", "/plan", "/artifacts", "/workers [all|idle|busy|failed] [stage]", "/worker <id>", "/dashboard", "/chat", "/pause [stage] <reason>", "/resume [stage] [comment]", "/cancel [stage] <reason>", "/stage-chat <stage>", "/skip <stage> <reason>", "/inject [worker_id] <message>", "/compact", "/steer <message>", "/steer @<worker-id> <message>", "/steer list", "/steer clear", "/memory", "/graph", "/config", "/events", "/secrets", "/doctor", "/quit"];
  if (state.overlay === "onboarding") return renderOnboarding();
  if (state.overlay === "setup") return ["Provider Setup", "Choose a provider setup flow with hidden secret input:", "1. AgentRouter  /setup agentrouter", "2. OpenRouter   /setup openrouter", "3. OpenAI       /setup openai", "4. Anthropic    /setup anthropic", "", "The visible TUI composer never accepts API keys.", "Run the shown command in this terminal, or exit and run ./nexussy.sh cli --setup.", "After setup, use /secrets or /models to refresh provider status."];
  if (state.overlay === "status") return ["Status", `run: ${state.app.runId ?? "none"}`, `paused: ${state.app.paused ? "yes" : "no"}`, `final: ${state.app.finalStatus ?? "-"}`, `tokens: ${state.app.usage.total_tokens}`];
  if (state.overlay === "stages") return ["Stages", ...Object.entries(state.app.stages).map(([k,v]) => `${k}: ${v}`)];
  if (state.overlay === "pipeline") return ["Pipeline", ...pipelineGateLines(state), `selected: ${state.selectedStage ?? "none"}`, "Stage      Status               Primary -> Fallback Worker", ...renderPipelineRows(state.app, state.pendingGate, state.pendingInterview).map((row, index) => `${STAGES[index] === state.selectedStage ? ">" : " "} ${row}`), "", "Focused controls: arrows/1-7 select stage; P pause, R resume, X cancel, C chat", "Slash: /pause <stage>, /resume <stage>, /cancel <stage>, /stage-chat <stage>"];
  if (state.overlay === "models") return ["Model Routing", `Profile: ${state.app.routingProfile} Gate: ${state.app.config.gateStages === false ? "off" : "on"} (use /profile fast for auto-advance)`, "Stage      Primary Provider/Model              Fallback Provider/Model             Notes", ...Object.values(state.app.routing).map(route => `${route.stage.padEnd(16)} ${modelLabel(route.primary).padEnd(35)} ${modelLabel(route.fallback).padEnd(35)} ${route.notes ?? ""}`), "", "Edit commands:", "  /model <stage> <provider/model>", "  /fallback <stage> <provider/model>", "", "Available options:", ...state.app.modelOptions.map(option => `  ${option.configured ? " " : "x"} ${modelLabel(option)} ${option.agent ? `[${option.agent}]` : ""}${option.disabledReason ? ` - ${option.disabledReason}` : ""}`)];
  if (state.overlay === "profile") return ["Profiles", ...routingProfiles.map(profile => `${profile === state.app.routingProfile ? "*" : " "} ${profile}`), "Use /profile <name> to switch."];
  if (state.overlay === "stage-chat") return ["Stage Chat", `stage: ${state.stageChat?.stage ?? state.selectedStage ?? "none"}`, "Plain text now injects guidance into this stage only.", "Use /chat or Esc to return to global chat."];
  if (state.overlay === "workers") { const workers = filteredWorkers(state); return ["Workers", `filter: ${state.workerFilter ?? "all"}${state.selectedStage ? ` stage:${state.selectedStage}` : ""}`, ...workers.map(w => `${w.worker_id} ${w.role} ${w.status}${w.task_title ? ` - ${w.task_title}` : ""}`), ...(workers.length ? [] : ["(none)"])]; }
  if (state.overlay === "worker") { const w = state.selectedWorkerId ? state.app.workers[state.selectedWorkerId] : undefined; return w ? ["Worker", `${w.worker_id}`, `${w.role} ${w.status}`, w.task_title ?? ""] : ["Worker", "not found"]; }
  if (state.overlay === "plan") return ["Plan", ...(state.app.devplan.length ? state.app.devplan : ["No devplan updates yet."])];
  if (state.overlay === "artifacts") return ["Artifacts", ...(state.app.artifacts.length ? state.app.artifacts.map(a => `${a.kind}: ${a.path}`) : ["No artifacts yet."])];
  if (state.overlay === "secrets") return ["Provider Keys", ...(state.app.secrets.length ? state.app.secrets.map(s => `${s.configured ? "configured" : "missing"} ${s.name}${s.configured ? ` (${s.source})` : ""}`) : ["Run /secrets to refresh provider-key status."])];
  if (state.overlay === "handoff") return renderHandoffModal(state.app);
  if (state.overlay === "data") return [state.dataPanel?.title ?? "Data", ...(state.dataPanel?.lines ?? ["No data loaded."])];
  if (state.overlay === "doctor") return ["Doctor", "Core/web diagnostics are not exposed by a core route yet.", "Fallback: use ./nexussy.sh doctor in another terminal.", `provider summaries: ${state.app.secrets.filter(s => s.configured).length} configured`];
  return [];
}

function gateHelp(state:ChatUiState): string[] {
  const gate = state.pendingGate;
  return gate ? [`Stage gate: ${gate.completedStage} complete → next: ${gate.nextStage}`, "Type yes to advance | iterate here to steer | no to stay paused", "/artifacts /plan /workers for details", ""] : [];
}

function pipelineGateLines(state:ChatUiState): string[] {
  const gate = state.pendingGate;
  return gate ? [`⏸ Gate: ${gate.completedStage} → ${gate.nextStage}`, gate.summary, "Type yes to advance | iterate here | no to stay paused", ""] : [];
}

export function closeOverlay(state: ChatUiState): ChatUiState { return { ...state, overlay:"none", selectedWorkerId:undefined, ...(state.overlay === "stage-chat" ? { stageChat:undefined, transcriptFilter:undefined } : {}) }; }

function filteredWorkers(state:ChatUiState) {
  const filter = state.workerFilter ?? "all";
  return Object.values(state.app.workers).filter(worker => {
    if (state.selectedStage && workerStage(worker) !== state.selectedStage) return false;
    if (filter === "idle") return worker.status === "idle";
    if (filter === "busy") return ["starting", "assigned", "running", "paused"].includes(worker.status);
    if (filter === "failed") return ["failed", "blocked", "stopped"].includes(worker.status);
    return true;
  });
}
