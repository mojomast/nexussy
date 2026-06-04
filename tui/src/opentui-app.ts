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
import { STAGES, createState } from "./state";
import { formatInterviewQuestion, handleComposerSubmit, pendingInterviewFromArtifact } from "./ui/Composer";
import { renderOnboarding } from "./ui/Onboarding";
import { closeOverlay } from "./ui/Overlay";
import { renderStatusStrip } from "./ui/StatusStrip";
import { actionableError, reduceChatEvent, renderTranscriptItem } from "./ui/Transcript";
import { modelLabel } from "./lib/routing";
import type { ChatUiState, TranscriptItem } from "./ui/types";

const WIDE_LAYOUT_MIN_WIDTH = 112;

function clampLine(line:string, width:number): string {
  const clean = line.replace(/\x1b\[[0-9;]*[A-Za-z]/g, "").replace(/[\r\n\t]+/g, " ").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "");
  return clean.length > width ? `${clean.slice(0, Math.max(0, width - 1))}…` : clean;
}

function isMainTranscriptItem(item:TranscriptItem): boolean {
  if (item.kind === "assistant" || item.kind === "run_started" || item.kind === "done" || item.kind === "error") return true;
  if (item.kind === "stage") return true;
  if (item.kind === "stage_control") return true;
  if (item.kind === "worker") return true;
  if (item.kind === "tool") return !item.collapsed || /failed|error/i.test(item.text);
  if (item.kind === "artifact") return /devplan|design|review|develop|changed_files|interview/i.test(item.text);
  return false;
}

function renderTranscriptText(state:ChatUiState): string {
  const visibleItems = state.transcript.filter(item => (!state.stageChat || item.kind === "stage_control" || item.kind === "assistant" || item.kind === "error") && isMainTranscriptItem(item));
  const lines = visibleItems.length ? visibleItems.flatMap(item => [...renderTranscriptItem(item), ""]).slice(0, -1) : renderOnboarding();
  return lines.slice(-80).join("\n");
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
    "Routing",
    `profile ${state.app.routingProfile}`,
    ...Object.values(state.app.routing).slice(0, 3).map(route => `${route.stage}:${modelLabel(route.primary).slice(0, 20)}`),
    "",
    "Workers",
    ...(workers.length ? workers : ["none"]),
    "",
    "Options",
    state.pendingInterview ? "interview: answer prompt" : state.app.runId ? "pipeline active" : "ask mode",
    state.pendingInterview ? "plain text answers" : "plain text asks",
    "build request -> confirm",
    "./nexussy.sh cli --setup",
    "/help commands",
    "/stages details",
    "/workers agents",
    "/artifacts outputs",
    "/secrets providers",
    "",
    "Activity",
    latest?.text ?? "idle",
    "",
    "DevPlan",
    ...(state.app.devplan.length ? state.app.devplan.slice(-3) : ["no anchors yet"]),
    "",
    "Usage",
    `${state.app.usage.total_tokens} tok  $${state.app.usage.cost_usd.toFixed(4)}`,
    "",
    "Files",
    ...(state.app.locks.length ? state.app.locks.slice(-3).map(lock => `${lock.worker_id}: ${lock.path}`) : ["no file activity"]),
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
  let activeStreamRunId: string | undefined;
  const disposers: Array<() => void> = [];
  let resolveDone: () => void = () => {};
  const done = new Promise<void>(resolve => { resolveDone = resolve; });

  const trackListener = (target:any, event:unknown, listener:unknown) => {
    disposers.push(() => {
      if (typeof target.off === "function") target.off(event, listener);
      else if (typeof target.removeListener === "function") target.removeListener(event, listener);
    });
  };

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
    while (disposers.length) {
      try { disposers.pop()?.(); } catch {}
    }
    renderer.stop();
    renderer.destroy();
    resolveDone();
  };

  const setStatus = (message:string) => {
    state = { ...state, statusMessage:message };
    render();
    input.focus();
  };

  const render = () => {
    state = { ...state, composer:{ ...state.composer, text:input.value } };
    const wide = renderer.terminalWidth >= WIDE_LAYOUT_MIN_WIDTH;
    sideFrame.visible = wide;
    input.width = Math.max(20, renderer.terminalWidth - 6);
    header.content = `nexussy  ${state.app.runId ? `run ${state.app.runId.slice(0, 8)}` : "session ready"}  model: ${state.app.usage.model ?? "configured"}`;
    transcript.content = renderTranscriptText(state);
    status.content = clampLine(renderStatusStrip(state), renderer.terminalWidth - 2);
    sidePanel.content = renderSidePanel(state, 30);
    transcriptScroll.scrollTo({ x:0, y:transcriptScroll.scrollHeight });
    renderer.requestRender();
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
        state = reduceChatEvent(state, env);
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
        render();
        input.focus();
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
      input.focus();
    }
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
        if (result.stream) void streamCurrentRun();
        if (result.exit) stop();
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        const err = actionableError(message);
        state = { ...state, transcript:[...state.transcript, { kind:"error", id:`command-error-${Date.now()}`, text:err.text, actions:err.actions }] };
        setStatus(`error: ${message}`);
      } finally {
        input.focus();
      }
    })();
  };

  const onInput = () => render();
  const onEnter = (value:string) => submit(value);
  input.on(InputRenderableEvents.INPUT, onInput);
  input.on(InputRenderableEvents.ENTER, onEnter);
  trackListener(input, InputRenderableEvents.INPUT, onInput);
  trackListener(input, InputRenderableEvents.ENTER, onEnter);
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
      return;
    }
    if (state.overlay === "pipeline") {
      const currentIndex = Math.max(0, STAGES.indexOf(state.selectedStage ?? "plan"));
      if (/^[1-9]$/.test(key.name) && Number(key.name) <= STAGES.length) {
        state = { ...state, selectedStage:STAGES[Number(key.name) - 1] };
        key.preventDefault();
        render();
        return;
      }
      if (key.name === "left" || key.name === "up" || key.name === "h" || key.name === "k") {
        state = { ...state, selectedStage:STAGES[Math.max(0, currentIndex - 1)] };
        key.preventDefault();
        render();
        return;
      }
      if (key.name === "right" || key.name === "down" || key.name === "l" || key.name === "j") {
        state = { ...state, selectedStage:STAGES[Math.min(STAGES.length - 1, currentIndex + 1)] };
        key.preventDefault();
        render();
        return;
      }
    }
    if (state.overlay === "pipeline" && state.selectedStage && ["p", "r", "x", "c"].includes(key.name)) {
      const stage = state.selectedStage;
      if (key.name === "c") submit(`/stage-chat ${stage}`);
      else {
        const command = key.name === "p" ? `/pause ${stage} ` : key.name === "r" ? `/resume ${stage} ` : `/cancel ${stage} `;
        input.value = command;
        input.focus();
        render();
      }
      key.preventDefault();
    }
  };

  const inputHandler = (sequence:string) => {
    if (sequence.includes("\u0003") || sequence.includes("\u0004")) {
      stop();
      return true;
    }
    return false;
  };
  renderer.addInputHandler(inputHandler);
  disposers.push(() => { if (typeof (renderer as any).removeInputHandler === "function") (renderer as any).removeInputHandler(inputHandler); });

  renderer.on(CliRenderEvents.RESIZE, render);
  trackListener(renderer, CliRenderEvents.RESIZE, render);
  const onDestroy = () => { stopped = true; while (disposers.length) { try { disposers.pop()?.(); } catch {} } resolveDone(); };
  renderer.on(CliRenderEvents.DESTROY, onDestroy);
  trackListener(renderer, CliRenderEvents.DESTROY, onDestroy);
  input.focus();
  render();
  renderer.start();
  input.focus();

  await done;
}
