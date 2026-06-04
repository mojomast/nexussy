import { renderPanels } from "../renderer";
import { createState } from "../state";
import { renderOverlay } from "./Overlay";
import { renderOnboarding } from "./Onboarding";
import { renderPipelineStrip } from "./PipelineStrip";
import { composerPrompt, renderStatusStrip } from "./StatusStrip";
import { renderTranscript } from "./Transcript";
import { stageArtifacts } from "../lib/gateSummary";
import type { ChatUiState } from "./types";

export function createDefaultChatState(): ChatUiState {
  return { mode:"chat", overlay:"none", app:createState(), rawEvents:[], transcript:[], composer:{ text:"", history:[], historyIndex:-1, fileRefs:[], autocompleteOpen:false, autocompleteQuery:"" }, connection:{ connected:false } };
}

function clampLine(line:string, width:number): string { return line.length > width ? `${line.slice(0, Math.max(0, width - 1))}…` : line; }

export function renderChat(state:ChatUiState, width=100): string {
  const scope = state.stageChat ? `  stage chat: ${state.stageChat.stage}` : "";
  const header = `nexussy  ${state.app.runId ? `run ${state.app.runId.slice(0,8)}` : "session ready"}  profile: ${state.app.routingProfile}${scope}`;
  const transcript = renderTranscript(state.transcript, state.transcriptFilter?.stage ?? state.stageChat?.stage);
  const interview = renderInterviewBlock(state);
  const gate = renderGateBlock(state);
  const intro = transcript.length ? transcript : renderOnboarding();
  const overlay = renderOverlay(state);
  const rows = [header, renderPipelineStrip(state.app, state.pendingGate, state.pendingInterview), "", ...interview, ...gate, ...intro, ...(overlay.length ? ["", `╭─ ${state.overlay}`, ...overlay.map(x => `│ ${x}`), "╰─"] : []), "", renderStatusStrip(state), `${composerPrompt(state)}${state.composer.text}`];
  return rows.map(row => clampLine(row, width)).join("\n");
}

function renderGateBlock(state:ChatUiState): string[] {
  const gate = state.pendingGate;
  if (!gate) return [];
  const artifacts = stageArtifacts(gate.completedStage, state.app.artifacts).map(artifact => `│ Artifact: ${artifact.path}`);
  return [
    `╭─ Stage complete: ${gate.completedStage} → next: ${gate.nextStage}`,
    `│ Summary: ${gate.summary}`,
    ...artifacts.slice(-3),
    "│ Review the stage output above, or open /artifacts and /pipeline for details.",
    "│ Type yes to approve and advance; type feedback here to iterate; type no to stay paused.",
    "╰─",
    "",
  ];
}

export function renderInterviewBlock(state:ChatUiState): string[] {
  const pending = state.pendingInterview;
  const question = pending?.questions[pending.index ?? 0];
  if (!pending) return [];
  if (!question) return ["╭─ Interview: waiting for next question…", "╰─ Your answer was submitted; the pipeline is preparing the next question.", ""];
  return [
    `╭─ Interview: Question ${pending.index + 1}/${pending.questions.length}`,
    `│ ${question.question}`,
    ...(question.suggested_answer ? [`│ Suggested: ${question.suggested_answer}`] : []),
    `╰─ ${question.suggested_answer ? "Press Enter to accept the suggestion, or type your answer." : "Type your answer."}`,
    "",
  ];
}

export function renderDashboardMode(state:ChatUiState): string {
  const panels = renderPanels(state.app);
  return `${panels.left}\n---\n${panels.center}\n---\n${panels.right}`;
}

export function renderApp(state:ChatUiState, width=100): string {
  return state.mode === "dashboard" ? renderDashboardMode(state) : renderChat(state, width);
}
