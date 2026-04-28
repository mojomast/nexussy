import type { TuiState } from "../state";

export function renderHandoffModal(state:TuiState): string[] {
  const pct = Math.round(state.contextBudget.fillRatio * 100);
  const model = state.usage.model ?? state.config.model ?? "configured model";
  return [
    `Context Window ${pct}% Full`,
    `You are approaching the limit for ${model}.`,
    "",
    "Options:",
    "Copy handoff - Generate local handoff text for your clipboard/editor",
    "Pause - Call /pipeline/pause after generating the local handoff",
    "Restart manually - Start a new run with /new after you save the handoff",
    state.contextBudget.atLimit ? "Esc Dismiss (not recommended)" : "Esc Dismiss",
  ];
}
