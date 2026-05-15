import { afterEach, beforeEach, expect, mock, test } from "bun:test";
import { createState, type TuiState } from "../src/state";
import type { CoreClient } from "../src/client";

type Listener = (...args:any[]) => void;

class MockNode {
  public children:any[] = [];
  public visible = true;
  public width:any;
  public height:any;
  public content = "";
  public value = "";
  public scrollHeight = 0;
  public readonly listeners = new Map<unknown, Set<Listener>>();
  public onKeyDown?: (key:{name:string; preventDefault:()=>void}) => void;
  constructor(_renderer:any, options:Record<string, unknown> = {}) { Object.assign(this, options); }
  add(child:any) { this.children.push(child); }
  on(event:unknown, listener:Listener) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(listener);
  }
  off(event:unknown, listener:Listener) { this.listeners.get(event)?.delete(listener); }
  emit(event:unknown, ...args:any[]) { for (const listener of this.listeners.get(event) ?? []) listener(...args); }
  focus() { mockState.openTui.focusCalls += 1; }
  scrollTo(pos:{x:number; y:number}) { mockState.openTui.scrolls.push(pos); }
}

class MockInputRenderable extends MockNode {
  constructor(renderer:any, options:Record<string, unknown> = {}) {
    super(renderer, options);
    mockState.openTui.inputs.push(this);
  }
}

class MockRenderer {
  public root = new MockNode(this);
  public terminalWidth = 120;
  public readonly listeners = new Map<unknown, Set<Listener>>();
  public readonly inputHandlers: Array<(sequence:string)=>boolean|undefined> = [];
  public requestRenderCalls = 0;
  public stopCalls = 0;
  public destroyCalls = 0;
  public removedInputHandlers = 0;
  on(event:unknown, listener:Listener) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(listener);
  }
  off(event:unknown, listener:Listener) { this.listeners.get(event)?.delete(listener); }
  emit(event:unknown, ...args:any[]) { for (const listener of [...(this.listeners.get(event) ?? [])]) listener(...args); }
  addInputHandler(handler:(sequence:string)=>boolean|undefined) { this.inputHandlers.push(handler); }
  removeInputHandler(handler:(sequence:string)=>boolean|undefined) {
    this.removedInputHandlers += 1;
    const index = this.inputHandlers.indexOf(handler);
    if (index >= 0) this.inputHandlers.splice(index, 1);
  }
  requestRender() { this.requestRenderCalls += 1; }
  start() { mockState.openTui.started = true; }
  stop() { this.stopCalls += 1; }
  destroy() { this.destroyCalls += 1; this.emit("destroy"); }
}

class MockTerminal {}
class MockTui {
  public children:any[] = [];
  public focus:any;
  public inputListeners: Array<(data:string)=>unknown> = [];
  public requestRenderCalls = 0;
  public stopCalls = 0;
  public removedInputListeners = 0;
  addChild(child:any) { this.children.push(child); }
  setFocus(child:any) { this.focus = child; }
  requestRender(_force?:boolean) { this.requestRenderCalls += 1; }
  addInputListener(listener:(data:string)=>unknown) { this.inputListeners.push(listener); }
  removeInputListener(listener:(data:string)=>unknown) {
    this.removedInputListeners += 1;
    const index = this.inputListeners.indexOf(listener);
    if (index >= 0) this.inputListeners.splice(index, 1);
  }
  start() { mockState.pi.started = true; }
  stop() { this.stopCalls += 1; }
}
class MockEditor {
  public onSubmit?: (text:string) => void;
  public text = "";
  public autocompleteProvider:any;
  constructor(public tui:MockTui) { mockState.pi.editors.push(this); }
  setAutocompleteProvider(provider:any) { this.autocompleteProvider = provider; }
  setText(text:string) { this.text = text; }
}
class MockAutocompleteProvider { constructor(public commands:any[], public cwd:string) {} }

const mockState = {
  openTui: { renderers: [] as MockRenderer[], inputs: [] as MockInputRenderable[], focusCalls: 0, scrolls: [] as Array<{x:number; y:number}>, started:false },
  pi: { tuis: [] as MockTui[], editors: [] as MockEditor[], started:false },
};

mock.module("@opentui/core", () => ({
  CliRenderEvents: { RESIZE:"resize", DESTROY:"destroy" },
  InputRenderableEvents: { INPUT:"input", ENTER:"enter" },
  createCliRenderer: async () => {
    const renderer = new MockRenderer();
    mockState.openTui.renderers.push(renderer);
    return renderer;
  },
  BoxRenderable: MockNode,
  ScrollBoxRenderable: MockNode,
  TextRenderable: MockNode,
  InputRenderable: MockInputRenderable,
}));

mock.module("@mariozechner/pi-tui", () => ({
  ProcessTerminal: MockTerminal,
  TUI: class extends MockTui { constructor(_terminal:any) { super(); mockState.pi.tuis.push(this); } },
  Editor: MockEditor,
  CombinedAutocompleteProvider: MockAutocompleteProvider,
  truncateToWidth: (line:string, width:number) => line.length > width ? line.slice(0, width) : line,
}));

function resetMocks() {
  mockState.openTui.renderers = [];
  mockState.openTui.inputs = [];
  mockState.openTui.focusCalls = 0;
  mockState.openTui.scrolls = [];
  mockState.openTui.started = false;
  mockState.pi.tuis = [];
  mockState.pi.editors = [];
  mockState.pi.started = false;
}

function makeInitial(): TuiState {
  return { ...createState(), sessionId:"sess-1" };
}

function makeClient(streamError = new Error("stream dropped")): CoreClient {
  return {
    async startPipeline() { return { session_id:"sess-1", run_id:"run-12345678", status:"running" }; },
    async *streamRun() { throw streamError; },
  } as unknown as CoreClient;
}

async function tick(times = 1) { for (let i = 0; i < times; i += 1) await new Promise(resolve => setTimeout(resolve, 0)); }

beforeEach(resetMocks);
afterEach(resetMocks);

test("OpenTUI harness renders input state, handles stream errors, and cleans listeners", async () => {
  const { runOpenTui } = await import("../src/opentui-app");
  const running = runOpenTui(makeClient(), makeInitial());
  await tick();

  const renderer = mockState.openTui.renderers[0];
  const input = mockState.openTui.inputs[0];
  expect(mockState.openTui.started).toBe(true);
  expect(mockState.openTui.focusCalls).toBeGreaterThanOrEqual(2);

  input.value = "draft";
  input.emit("input");
  expect(renderer.requestRenderCalls).toBeGreaterThan(1);
  expect(input.value).toBe("draft");
  expect(renderer.root.children[3].children[0]).toBe(input);

  input.emit("enter", "/new build a tiny cli with tests");
  await tick(4);
  expect(renderer.root.children[2].content).toContain("stream error: stream dropped");
  expect(renderer.root.children[0].content).toContain("run run-1234");

  expect(renderer.inputHandlers[0]("\u0003")).toBe(true);
  await running;
  expect(renderer.stopCalls).toBe(1);
  expect(renderer.destroyCalls).toBe(1);
  expect(renderer.removedInputHandlers).toBe(1);
  expect(input.listeners.get("input")?.size ?? 0).toBe(0);
  expect(input.listeners.get("enter")?.size ?? 0).toBe(0);
});

test("Pi TUI harness handles keyboard overlays, stream errors, and input listener cleanup", async () => {
  const { runPiTui } = await import("../src/pi-app");
  const running = runPiTui(makeClient(), makeInitial());
  await tick();

  const tui = mockState.pi.tuis[0];
  const editor = mockState.pi.editors[0];
  expect(mockState.pi.started).toBe(true);
  expect(tui.children.length).toBe(2);
  expect(tui.focus).toBe(editor);
  expect(editor.autocompleteProvider.commands.length).toBeGreaterThan(0);

  expect(tui.inputListeners[0]("\t")).toEqual({ consume:true });
  expect(tui.children[0].render(100).join("\n")).toContain("/steer list");
  expect(tui.inputListeners[0]("\u001b")).toEqual({ consume:true });

  editor.onSubmit?.("/new build a tiny cli with tests");
  await tick(4);
  expect(editor.text).toBe("");
  expect(tui.children[0].render(100).join("\n")).toContain("stream error");

  expect(tui.inputListeners[0]("\u0004")).toEqual({ consume:true });
  await running;
  expect(tui.stopCalls).toBe(1);
  expect(tui.removedInputListeners).toBe(1);
  expect(tui.inputListeners.length).toBe(0);
});
