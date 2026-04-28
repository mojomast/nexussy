import type { ChatUiState } from "./types";

export function composerPrompt(state: ChatUiState): string {
  if (state.app.paused) return "nexussy paused › ";
  if (state.app.runId && state.app.finalStatus !== "passed" && state.app.finalStatus !== "failed" && state.app.finalStatus !== "cancelled") return "nexussy running › ";
  return "nexussy › ";
}

export function renderStatusStrip(state: ChatUiState): string {
  const model = state.app.usage.model ?? "configured model";
  const run = state.app.runId ? `run: ${state.app.runId.slice(0, 8)}` : "session ready";
  const cost = `$${state.app.usage.cost_usd.toFixed(4)}`;
  const msg = state.statusMessage ? `  ${state.statusMessage}` : "";
  return `${run}  model: ${model}  tokens: ${state.app.usage.total_tokens}  cost: ${cost}${msg}`;
}
