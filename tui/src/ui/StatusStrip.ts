import type { ChatUiState } from "./types";
import { modelLabel } from "../lib/routing";

export function composerPrompt(state: ChatUiState): string {
  if (state.pendingGate) return "confirm to advance › ";
  if (state.stageChat) return `${state.stageChat.stage} › `;
  if (state.app.paused) return "nexussy paused › ";
  if (state.app.runId && state.app.finalStatus !== "passed" && state.app.finalStatus !== "failed" && state.app.finalStatus !== "cancelled") return "nexussy running › ";
  return "nexussy › ";
}

export function renderStatusStrip(state: ChatUiState): string {
  const run = state.app.runId ? `run: ${state.app.runId.slice(0, 8)}` : "session ready";
  const activeStage = Object.entries(state.app.stages).find(([, status]) => status === "running" || status === "paused")?.[0] ?? "idle";
  const routedModel = activeStage === "idle" ? undefined : modelLabel(state.app.routing[activeStage as keyof typeof state.app.routing]?.primary);
  const model = state.app.usage.model ?? routedModel ?? "configured model";
  const cost = `$${state.app.usage.cost_usd.toFixed(4)}`;
  const budget = state.app.contextBudget;
  const pct = Math.round(budget.fillRatio * 100);
  if (state.pendingGate) return `${state.connection.connected ? "connected" : "offline"}  ${run}  paused at gate: ${state.pendingGate.completedStage} → ${state.pendingGate.nextStage}  (yes to advance | iterate here)  Profile: ${state.app.routingProfile}  tokens: ${budget.totalTokens}/${budget.contextWindowSize} (${pct}%)  cost: ${cost}`;
  const msg = state.statusMessage ? `  ${state.statusMessage}` : "";
  return `${state.connection.connected ? "connected" : "offline"}  ${run}${msg}  stage: ${activeStage}  Profile: ${state.app.routingProfile}  model: ${model}  tokens: ${budget.totalTokens}/${budget.contextWindowSize} (${pct}%)  cost: ${cost}  /models /pipeline /workers /dashboard /help`;
}
