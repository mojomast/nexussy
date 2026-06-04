import { CombinedAutocompleteProvider, Editor, ProcessTerminal, TUI, truncateToWidth, type Component } from "@mariozechner/pi-tui";
import type { CoreClient } from "./client";
import { createState } from "./state";
import { renderApp } from "./ui/App";
import { formatInterviewQuestion, handleComposerSubmit, pendingInterviewFromArtifact } from "./ui/Composer";
import { COMMANDS } from "./ui/CommandPalette";
import { closeOverlay } from "./ui/Overlay";
import { actionableError, reduceChatEvent } from "./ui/Transcript";
import { pauseForNewGate } from "./lib/gateSummary";
import type { ChatUiState } from "./ui/types";

const plain = (text:string) => text;
const editorTheme = {
  borderColor: plain,
  selectList: { selectedPrefix: plain, selectedText: plain, description: plain, scrollInfo: plain, noMatch: plain },
};

function fit(line:string, width:number): string { return truncateToWidth(line, Math.max(0, width)); }

function splitPanel(lines:string[], width:number, height:number): string[] {
  const out = lines.slice(0, height).map(line => fit(line, width));
  while (out.length < height) out.push("");
  return out;
}

export class NexussyPiComponent implements Component {
  constructor(private getState:()=>ChatUiState) {}
  invalidate(): void {}
  render(width:number): string[] {
    return renderApp(this.getState(), width).split("\n").map(line => fit(line, width));
  }
}

export async function runPiTui(client:CoreClient, initial=createState()): Promise<void> {
  const terminal = new ProcessTerminal();
  const tui = new TUI(terminal);
  let state: ChatUiState = { mode:"chat", overlay:"none", app:initial, rawEvents:[], transcript:[], composer:{ text:"", history:[], historyIndex:-1, fileRefs:[], autocompleteOpen:false, autocompleteQuery:"" }, connection:{ connected:false }, statusMessage:"ready" };
  const dashboard = new NexussyPiComponent(() => state);
  const editor = new Editor(tui, editorTheme, { paddingX:1 });
  editor.setAutocompleteProvider(new CombinedAutocompleteProvider(COMMANDS.map(name => ({ name, description:"nexussy command" })), process.cwd()));
  const setStatus = (text:string) => { state = { ...state, statusMessage:text }; tui.requestRender(true); };
  let stopped = false;
  let activeStreamRunId: string | undefined;
  const disposers: Array<() => void> = [];
  const stopTui = () => {
    if (stopped) return;
    stopped = true;
    while (disposers.length) { try { disposers.pop()?.(); } catch {} }
    try { tui.stop(); } catch {}
  };

  async function streamCurrentRun() {
    if (!state.app.runId) return;
    if (activeStreamRunId === state.app.runId) return;
    activeStreamRunId = state.app.runId;
    try {
      setStatus("streaming; composer ready");
      const lastEventId = state.connection.lastEventId ?? state.app.lastEventId;
      for await (const env of client.streamRun(state.app.runId, { retryMs:3000, attempts:0, lastEventId })) {
        if (state.rawEvents.some(event => event.event_id === env.event_id)) continue;
        const previous = state;
        state = reduceChatEvent(state, env);
        state = await pauseForNewGate(client, previous, state);
        if (env.type === "artifact_updated" && (env.payload as any)?.artifact?.kind === "interview" && state.app.sessionId && client.artifact && state.app.stages.interview !== "passed") {
          try {
            const pendingInterview = pendingInterviewFromArtifact(await client.artifact("interview", state.app.sessionId));
            const currentId = state.pendingInterview?.questions[state.pendingInterview.index]?.question_id;
            if (pendingInterview) {
              const first = pendingInterview.questions[0];
              state = { ...state, pendingInterview, transcript:first.question_id === currentId ? state.transcript : [...state.transcript, { kind:"assistant", id:`interview-question-${Date.now()}`, role:"assistant", text:formatInterviewQuestion(first, 0, pendingInterview.questions.length) }] };
            } else {
              state = { ...state, pendingInterview:undefined };
            }
          } catch {}
        }
        tui.requestRender(true);
        if (env.type === "done") break;
      }
      setStatus(`run ${state.app.finalStatus ?? "finished"}`);
    } catch (e) {
      const message = `stream error: ${e instanceof Error ? e.message : String(e)}`;
      const err = actionableError(message);
      state = { ...state, transcript:[...state.transcript, { kind:"error", id:`stream-error-${Date.now()}`, text:err.text, actions:err.actions }] };
      setStatus(message);
    } finally {
      activeStreamRunId = undefined;
    }
  }

  editor.onSubmit = (text:string) => {
    const line = text.trim();
    editor.setText("");
    if (!line && !state.pendingInterview) return;
    if (line === "/quit" || line === "/exit") { stopTui(); return; }
    void (async () => {
      try {
        setStatus("working...");
        const [next, result] = await handleComposerSubmit(client, state, line);
        state = next;
        setStatus(result.message);
        if (result.stream) void streamCurrentRun();
        if (result.exit) stopTui();
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        const err = actionableError(message);
        state = { ...state, transcript:[...state.transcript, { kind:"error", id:`command-error-${Date.now()}`, text:err.text, actions:err.actions }] };
        setStatus(`error: ${message}`);
      }
    })();
  };

  tui.addChild(dashboard);
  tui.addChild(editor);
  tui.setFocus(editor);
  const inputListener = (data:string) => {
    if (data === "\u0003" || data === "\u0004") { stopTui(); return { consume:true }; }
    if (data.includes("\u0003") || data.includes("\u0004")) { stopTui(); return { consume:true }; }
    if (data === "\u001b" && state.overlay !== "none") { state = closeOverlay(state); tui.requestRender(true); return { consume:true }; }
    if (data === "\t") { state = { ...state, overlay: state.overlay === "none" ? "help" : "none" }; tui.requestRender(true); return { consume:true }; }
    return undefined;
  };
  tui.addInputListener(inputListener);
  disposers.push(() => { if (typeof (tui as any).removeInputListener === "function") (tui as any).removeInputListener(inputListener); });
  await new Promise<void>(resolve => {
    const originalStop = tui.stop.bind(tui);
    tui.stop = () => { try { while (disposers.length) { try { disposers.pop()?.(); } catch {} } originalStop(); } finally { resolve(); } };
    tui.start();
  });
}
