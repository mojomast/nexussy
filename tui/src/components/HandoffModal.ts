import type { TuiState } from "../state";

export function renderHandoffModal(state:TuiState): string[] {
  const pct = Math.round(state.contextBudget.fillRatio * 100);
  const model = state.usage.model ?? state.config.model ?? "configured model";
  return [
    `Context Window ${pct}% Full`,
    `You are approaching the limit for ${model}.`,
    "",
    "Options:",
    "Compact - Summarise and compress this context window",
    "Handoff - Generate handoff.md and pause here",
    "Auto-restart - Generate handoff.md, then start a new run from it",
    state.contextBudget.atLimit ? "Esc Dismiss (not recommended)" : "Esc Dismiss",
  ];
}
