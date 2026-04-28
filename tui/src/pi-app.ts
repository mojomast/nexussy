import { CombinedAutocompleteProvider, Editor, ProcessTerminal, TUI, truncateToWidth, type Component } from "@mariozechner/pi-tui";
import type { CoreClient } from "./client";
import { createState } from "./state";
import { renderApp } from "./ui/App";
import { handleComposerSubmit } from "./ui/Composer";
import { COMMANDS } from "./ui/CommandPalette";
import { closeOverlay } from "./ui/Overlay";
import { reduceChatEvent } from "./ui/Transcript";
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
  const stopTui = () => {
    if (stopped) return;
    stopped = true;
    try { tui.stop(); } catch {}
  };

  async function streamCurrentRun() {
    if (!state.app.runId) return;
    for await (const env of client.streamRun(state.app.runId)) {
      state = reduceChatEvent(state, env);
      tui.requestRender(true);
      if (env.type === "done") break;
    }
    setStatus(`run ${state.app.finalStatus ?? "finished"}`);
  }

  editor.onSubmit = (text:string) => {
    const line = text.trim();
    editor.setText("");
    if (!line) return;
    if (line === "/quit" || line === "/exit") { stopTui(); return; }
    void (async () => {
      try {
        setStatus("working...");
        const [next, result] = await handleComposerSubmit(client, state, line);
        state = next;
        setStatus(result.message);
        if (result.stream) await streamCurrentRun();
        if (result.exit) stopTui();
      } catch (e) {
        setStatus(`error: ${e instanceof Error ? e.message : String(e)}`);
      }
    })();
  };

  tui.addChild(dashboard);
  tui.addChild(editor);
  tui.setFocus(editor);
  tui.addInputListener(data => {
    if (data === "\u0003" || data === "\u0004") { stopTui(); return { consume:true }; }
    if (data.includes("\u0003") || data.includes("\u0004")) { stopTui(); return { consume:true }; }
    if (data === "\u001b" && state.overlay !== "none") { state = closeOverlay(state); tui.requestRender(true); return { consume:true }; }
    if (data === "\t") { state = { ...state, overlay: state.overlay === "none" ? "help" : "none" }; tui.requestRender(true); return { consume:true }; }
    return undefined;
  });
  await new Promise<void>(resolve => {
    const originalStop = tui.stop.bind(tui);
    tui.stop = () => { try { originalStop(); } finally { resolve(); } };
    tui.start();
  });
}
