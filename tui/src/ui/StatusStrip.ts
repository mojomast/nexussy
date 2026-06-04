import type { ChatUiState } from "./types";

export function composerPrompt(state: ChatUiState): string {
  if (state.stageChat) return `${state.stageChat.stage} › `;
  if (state.app.paused) return "nexussy paused › ";
  if (state.app.runId && state.app.finalStatus !== "passed" && state.app.finalStatus !== "failed" && state.app.finalStatus !== "cancelled") return "nexussy running › ";
  return "nexussy › ";
}

export function renderStatusStrip(state: ChatUiState): string {
  const model = state.app.usage.model ?? "configured model";
  const run = state.app.runId ? `run: ${state.app.runId.slice(0, 8)}` : "session ready";
  const activeStage = Object.entries(state.app.stages).find(([, status]) => status === "running" || status === "paused")?.[0] ?? "idle";
  const cost = `$${state.app.usage.cost_usd.toFixed(4)}`;
  const budget = state.app.contextBudget;
  const pct = Math.round(budget.fillRatio * 100);
  const msg = state.statusMessage ? `  ${state.statusMessage}` : "";
  return `${state.connection.connected ? "connected" : "offline"}  ${run}${msg}  stage: ${activeStage}  Profile: ${state.app.routingProfile}  model: ${model}  tokens: ${budget.totalTokens}/${budget.contextWindowSize} (${pct}%)  cost: ${cost}  /models /pipeline /workers /dashboard /help`;
}
