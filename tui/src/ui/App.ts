import { renderPanels } from "../renderer";
import { createState } from "../state";
import { renderOverlay } from "./Overlay";
import { renderOnboarding } from "./Onboarding";
import { composerPrompt, renderStatusStrip } from "./StatusStrip";
import { renderTranscript } from "./Transcript";
import type { ChatUiState } from "./types";

export function createDefaultChatState(): ChatUiState {
  return { mode:"chat", overlay:"none", app:createState(), rawEvents:[], transcript:[], composer:{ text:"", history:[], historyIndex:-1, fileRefs:[], autocompleteOpen:false, autocompleteQuery:"" }, connection:{ connected:false } };
}

function clampLine(line:string, width:number): string { return line.length > width ? `${line.slice(0, Math.max(0, width - 1))}…` : line; }

export function renderChat(state:ChatUiState, width=100): string {
  const header = `nexussy  ${state.app.runId ? `run ${state.app.runId.slice(0,8)}` : "session ready"}  model: ${state.app.usage.model ?? "configured"}`;
  const transcript = renderTranscript(state.transcript);
  const intro = transcript.length ? transcript : renderOnboarding();
  const overlay = renderOverlay(state);
  const rows = [header, "", ...intro, ...(overlay.length ? ["", `╭─ ${state.overlay}`, ...overlay.map(x => `│ ${x}`), "╰─"] : []), "", renderStatusStrip(state), `${composerPrompt(state)}${state.composer.text}`];
  return rows.map(row => clampLine(row, width)).join("\n");
}

export function renderDashboardMode(state:ChatUiState): string {
  const panels = renderPanels(state.app);
  return `${panels.left}\n---\n${panels.center}\n---\n${panels.right}`;
}

export function renderApp(state:ChatUiState, width=100): string {
  return state.mode === "dashboard" ? renderDashboardMode(state) : renderChat(state, width);
}
