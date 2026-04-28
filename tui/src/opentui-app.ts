import {
  BoxRenderable,
  CliRenderEvents,
  InputRenderable,
  InputRenderableEvents,
  ScrollBoxRenderable,
  TextRenderable,
  createCliRenderer,
} from "@opentui/core";
import type { CoreClient } from "./client";
import { createState } from "./state";
import { handleComposerSubmit } from "./ui/Composer";
import { renderOnboarding } from "./ui/Onboarding";
import { closeOverlay } from "./ui/Overlay";
import { renderStatusStrip } from "./ui/StatusStrip";
import { reduceChatEvent, renderTranscriptItem } from "./ui/Transcript";
import type { ChatUiState, TranscriptItem } from "./ui/types";

const WIDE_LAYOUT_MIN_WIDTH = 112;

function clampLine(line:string, width:number): string {
  return line.length > width ? `${line.slice(0, Math.max(0, width - 1))}…` : line;
}

function isMainTranscriptItem(item:TranscriptItem): boolean {
  if (item.kind === "assistant" || item.kind === "run_started" || item.kind === "done" || item.kind === "error") return true;
  if (item.kind === "stage") return item.status === "passed" || item.status === "failed" || item.status === "cancelled";
  if (item.kind === "worker") return /failed|blocked|conflict/i.test(item.text);
  return false;
}

function renderTranscriptText(state:ChatUiState): string {
  const visibleItems = state.transcript.filter(isMainTranscriptItem);
  const lines = visibleItems.length ? visibleItems.flatMap(item => [...renderTranscriptItem(item), ""]).slice(0, -1) : renderOnboarding();
  return lines.join("\n");
}

function renderSidePanel(state:ChatUiState, width:number): string {
  const stages = Object.entries(state.app.stages).map(([stage, status]) => `${stage.padEnd(9)} ${status}`);
  const workers = Object.values(state.app.workers).slice(0, 4).map(w => `${w.role}:${w.status}`);
  const latest = state.transcript.slice().reverse().find(item => item.kind !== "meta" && item.kind !== "artifact");
  const overlay = state.overlay === "none" ? [] : [`Overlay: ${state.overlay}`, "Esc closes overlay"];
  const lines = [
    "Pipeline",
    ...stages,
    "",
    "Workers",
    ...(workers.length ? workers : ["none"]),
    "",
    "Options",
    state.interviewMode ? "interview mode" : "pipeline mode",
    "/help commands",
    "/stages details",
    "/workers agents",
    "/artifacts outputs",
    "/secrets providers",
    "",
    "Activity",
    latest?.text ?? "idle",
    "",
    ...overlay,
  ];
  return lines.map(line => clampLine(line, width)).join("\n");
}

function createInitialChatState(initial=createState()): ChatUiState {
  return {
    mode:"chat",
    overlay:"none",
    app:initial,
    rawEvents:[],
    transcript:[],
    composer:{ text:"", history:[], historyIndex:-1, fileRefs:[], autocompleteOpen:false, autocompleteQuery:"" },
    connection:{ connected:false },
    statusMessage:"ready",
  };
}

export async function runOpenTui(client:CoreClient, initial=createState()): Promise<void> {
  const renderer = await createCliRenderer({
    stdin:process.stdin,
    stdout:process.stdout,
    exitOnCtrlC:false,
    clearOnShutdown:true,
    consoleMode:"disabled",
    screenMode:"alternate-screen",
    useMouse:false,
  });

  let state = createInitialChatState(initial);
  let stopped = false;

  const root = renderer.root;
  root.flexDirection = "column";
  root.paddingX = 1;

  const header = new TextRenderable(renderer, {
    id:"nexussy-header",
    content:"",
    width:"100%",
    height:1,
    fg:"#88c0d0",
  });

  const body = new BoxRenderable(renderer, {
    id:"nexussy-body",
    flexDirection:"row",
    flexGrow:1,
    width:"100%",
    overflow:"hidden",
    columnGap:1,
  });

  const transcriptScroll = new ScrollBoxRenderable(renderer, {
    id:"nexussy-transcript-scroll",
    flexGrow:1,
    flexShrink:1,
    height:"100%",
    stickyScroll:true,
    stickyStart:"bottom",
    viewportCulling:true,
    scrollY:true,
    scrollX:false,
    verticalScrollbarOptions:{ visible:false },
    rootOptions:{ backgroundColor:"#0f1117" },
    viewportOptions:{ backgroundColor:"#0f1117" },
    contentOptions:{ backgroundColor:"#0f1117" },
  });

  const transcript = new TextRenderable(renderer, {
    id:"nexussy-transcript",
    content:"",
    width:"100%",
    wrapMode:"word",
    overflow:"hidden",
    fg:"#d8dee9",
  });

  const sideFrame = new BoxRenderable(renderer, {
    id:"nexussy-side-frame",
    title:"Pipeline",
    border:true,
    borderColor:"#4c566a",
    width:34,
    flexShrink:0,
    height:"100%",
    paddingX:1,
    overflow:"hidden",
  });

  const sidePanel = new TextRenderable(renderer, {
    id:"nexussy-side-panel",
    content:"",
    width:"100%",
    height:"100%",
    wrapMode:"word",
    fg:"#d8dee9",
  });

  const status = new TextRenderable(renderer, {
    id:"nexussy-status",
    content:"",
    width:"100%",
    height:1,
    fg:"#a3be8c",
  });

  const inputFrame = new BoxRenderable(renderer, {
    id:"nexussy-composer-frame",
    border:true,
    borderColor:"#5e81ac",
    focusedBorderColor:"#88c0d0",
    width:"100%",
    height:3,
    paddingX:1,
  });

  const input = new InputRenderable(renderer, {
    id:"nexussy-composer",
    value:"",
    placeholder:"Ask nexussy to build, review, or change something. /help for commands.",
    width:Math.max(20, renderer.terminalWidth - 6),
    backgroundColor:"#2e3440",
    focusedBackgroundColor:"#3b4252",
    textColor:"#eceff4",
    cursorColor:"#88c0d0",
  });

  inputFrame.add(input);
  transcriptScroll.add(transcript);
  sideFrame.add(sidePanel);
  body.add(transcriptScroll);
  body.add(sideFrame);
  root.add(header);
  root.add(body);
  root.add(status);
  root.add(inputFrame);

  const stop = () => {
    if (stopped) return;
    stopped = true;
    renderer.stop();
    renderer.destroy();
  };

  const setStatus = (message:string) => {
    state = { ...state, statusMessage:message };
    render();
  };

  const render = () => {
    state = { ...state, composer:{ ...state.composer, text:input.value } };
    const wide = renderer.terminalWidth >= WIDE_LAYOUT_MIN_WIDTH;
    sideFrame.visible = wide;
    input.width = Math.max(20, renderer.terminalWidth - 6);
    header.content = `nexussy  ${state.app.runId ? `run ${state.app.runId.slice(0, 8)}` : "session ready"}  model: ${state.app.usage.model ?? "configured"}`;
    transcript.content = renderTranscriptText(state);
    status.content = renderStatusStrip(state);
    sidePanel.content = renderSidePanel(state, 30);
    transcriptScroll.scrollTo({ x:0, y:transcriptScroll.scrollHeight });
    renderer.requestRender();
  };

  async function streamCurrentRun() {
    if (!state.app.runId) return;
    for await (const env of client.streamRun(state.app.runId)) {
      state = reduceChatEvent(state, env);
      render();
      if (env.type === "done") break;
    }
    setStatus(`run ${state.app.finalStatus ?? "finished"}`);
  }

  const submit = (text:string) => {
    const line = text.trim();
    input.value = "";
    if (!line) { render(); return; }
    if (line === "/quit" || line === "/exit") { stop(); return; }
    void (async () => {
      try {
        state = { ...state, transcript:[...state.transcript, { kind:"assistant", id:`local-user-${Date.now()}`, role:"user", text:`You: ${line}` }] };
        setStatus("working...");
        const [next, result] = await handleComposerSubmit(client, state, line);
        state = next;
        setStatus(result.message);
        if (result.stream) await streamCurrentRun();
        if (result.exit) stop();
      } catch (e) {
        setStatus(`error: ${e instanceof Error ? e.message : String(e)}`);
      }
    })();
  };

  input.on(InputRenderableEvents.INPUT, () => render());
  input.on(InputRenderableEvents.ENTER, (value:string) => submit(value));
  input.onKeyDown = key => {
    if (key.name === "escape" && state.overlay !== "none") {
      state = closeOverlay(state);
      key.preventDefault();
      render();
      return;
    }
    if (key.name === "tab") {
      state = { ...state, overlay:state.overlay === "none" ? "help" : "none" };
      key.preventDefault();
      render();
    }
  };

  renderer.addInputHandler(sequence => {
    if (sequence.includes("\u0003") || sequence.includes("\u0004")) {
      stop();
      return true;
    }
    return false;
  });

  renderer.on(CliRenderEvents.RESIZE, render);
  renderer.on(CliRenderEvents.DESTROY, () => { stopped = true; });
  input.focus();
  render();
  renderer.start();
  input.focus();

  await new Promise<void>(resolve => renderer.on(CliRenderEvents.DESTROY, resolve));
}
