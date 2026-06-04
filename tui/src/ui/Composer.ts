import { parseNewCommand, projectNameFromDescription } from "../index";
import { renderPanels } from "../renderer";
import { STAGES, addStageControlNote, reduceArtifactsSnapshot, reduceRoutingProfile, reduceSecrets, reduceStageRoutingModel, reduceStatusSnapshot, reduceWorkersSnapshot, triggerHandoff } from "../state";
import { findModelOption } from "../lib/routing";
import { WORKER_ID_PATTERN } from "../commands";
import type { PipelineStartRequest, RoutingProfileName, StageName, WorkerRole } from "../types";
import { closeOverlay } from "./Overlay";
import type { ChatUiState, ClientLike, CommandOutcome } from "./types";

const greetingPattern = /^(hi|hello|hey|yo|sup|howdy|hiya|what'?s\s+up|whatsg\s+up|what'?s?\s*good)[!.\s]*$/i;
const stages = new Set<string>(STAGES);
const roles = new Set(["orchestrator","backend","frontend","qa","devops","writer","analyst"]);
const profiles = new Set(["default","fast","cheap","strict"]);
const workerFilters = new Set(["all","idle","busy","failed"]);
const steerWorkerPattern = /^[a-z0-9-]+$/;
export type InteractionBucket = "ask" | "command" | "choice-selection" | "confirmation" | "ambiguous";

export function looksLikeProjectRequest(text:string): boolean {
  const trimmed = text.trim();
  if (!trimmed || greetingPattern.test(trimmed)) return false;
  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length < 4) return /\b(build|create|make|implement|add|fix|write|generate|scaffold|plan|review|test)\b/i.test(trimmed) && words.length >= 2;
  return /\b(app|api|cli|site|service|feature|tests?|database|frontend|backend|project|tool|script|library|package|component|endpoint|auth|sqlite|fastapi|react|python|typescript|plan|review|implement|build|create|make|fix|add)\b/i.test(trimmed);
}

export function wantsInterviewFirst(text:string): boolean {
  return /\b(interview|interrogate|question)\b.*\b(me|us)\b|\bask\b.*\b(questions|question)\b|\bhelp\b.*\b(scope|define|figure out)\b/i.test(text.trim());
}

export function classifyInteraction(input:string, state:ChatUiState): InteractionBucket {
  const line = input.trim();
  if (!line) return "ambiguous";
  if (line.startsWith("/")) return "command";
  if (state.pendingAction && /^(1|option\s*1|yes|y|confirm|run it|yes,?\s*run it)$/i.test(line)) return /^(1|option\s*1)$/i.test(line) ? "choice-selection" : "confirmation";
  if (/^(\d+|option\s*\d+|yes|y|no|n|confirm|run it)$/i.test(line)) return "ambiguous";
  if (line.endsWith("?") || /^(can|could|should|would|what|why|how|is|are|do|does|which)\b/i.test(line)) return "ask";
  return "ask";
}

export function idleAssistantText(input:string): string {
  if (greetingPattern.test(input.trim())) return "Hi. Ask for help, describe what you want to build, or run `./nexussy.sh cli --setup` if providers are not configured yet. To build for real, use `/new <description>`.";
  if (wantsInterviewFirst(input)) return "Ask mode: I can help clarify scope here without starting the pipeline. Answer one question: what outcome do you want, and what platform should it target? Use `/new <description>` only when you want nexussy to start a pipeline run.";
  if (looksLikeProjectRequest(input)) return "This looks buildable. Reply `Yes, run it` to start the full pipeline, or keep asking questions here if you want to shape the idea first.";
  return "Ask mode. I can answer questions and explain options here. Use `/new <description>` only when you want interview/design/plan/review/develop to run.";
}

export function createChatUiState(appFactory:()=>ChatUiState["app"]): ChatUiState {
  return { mode:"chat", overlay:"none", app:appFactory(), rawEvents:[], transcript:[], composer:{ text:"", history:[], historyIndex:-1, fileRefs:[], autocompleteOpen:false, autocompleteQuery:"" }, connection:{ connected:false } };
}

export async function startNewRun(client:ClientLike, state:ChatUiState, description:string): Promise<[ChatUiState, CommandOutcome]> {
  const trimmed = description.trim();
  if (!trimmed) throw new Error("description required");
  const parsed = parseNewCommand(trimmed);
  if (!parsed.description) throw new Error("description required");
  const metadata = parsed.designContextPack && parsed.designContextPack !== "none" ? { design_context_pack:parsed.designContextPack } : undefined;
  const model_overrides = selectedModelOverrides(state);
  const request: PipelineStartRequest = { project_name:projectNameFromDescription(parsed.description), description:parsed.description, auto_approve_interview:Boolean(parsed.autoInterview), ...(metadata ? { metadata } : {}), ...(Object.keys(model_overrides).length ? { model_overrides } : {}) };
  const started = await client.startPipeline(request);
  return [{ ...state, pendingAction:undefined, app:{ ...state.app, runId:started.run_id, sessionId:started.session_id, finalStatus:undefined }, statusMessage:`started ${started.run_id.slice(0,8)}` }, { message:`started run ${started.run_id}`, stream:true }];
}

export function selectedModelOverrides(state:ChatUiState): Partial<Record<StageName,string>> {
  return Object.fromEntries(Object.values(state.app.routing).filter(route => route.primary?.configured && route.primary.model && (route.primary.provider === "agentrouter" || route.explicit)).map(route => [route.stage, route.primary!.model])) as Partial<Record<StageName,string>>;
}

export function pendingInterviewFromArtifact(response:unknown): ChatUiState["pendingInterview"] {
  const content = typeof response === "string" ? response : response && typeof response === "object" ? String((response as any).content_text ?? (response as any).content ?? "") : "";
  if (!content.trim()) return undefined;
  let parsed:unknown;
  try { parsed = JSON.parse(content); } catch { return undefined; }
  const questions = Array.isArray((parsed as any)?.questions) ? (parsed as any).questions.map((q:any, index:number) => ({ question_id:String(q.question_id ?? q.id ?? `q${index + 1}`), question:String(q.question ?? q.text ?? ""), answer:typeof q.answer === "string" ? q.answer : undefined, suggested_answer:typeof q.suggested_answer === "string" ? q.suggested_answer : undefined })).filter((q:{question_id:string; question:string; answer?:string}) => q.question && (!q.answer || q.answer === "pending")).map(({ question_id, question, suggested_answer }:{question_id:string; question:string; suggested_answer?:string}) => ({ question_id, question, suggested_answer })) : [];
  return questions.length ? { questions, answers:{}, index:0 } : undefined;
}

export function formatInterviewQuestion(question:{question:string; suggested_answer?:string|null}, index:number, total:number): string {
  return `Interview question ${index + 1}/${total}: ${question.question}${question.suggested_answer ? `\nSuggested default: ${question.suggested_answer}` : ""}`;
}

export async function handleComposerSubmit(client:ClientLike, state:ChatUiState, input:string): Promise<[ChatUiState, CommandOutcome]> {
  const line = input.trim();
  if (!line) return [state, { message:"" }];
  const withHistory = { ...state, composer:{ ...state.composer, history:[...state.composer.history, line], historyIndex:-1 } };
  const bucket = classifyInteraction(line, withHistory);
  if (bucket !== "command") {
    if (withHistory.pendingInterview && withHistory.app.sessionId) return answerPendingInterview(client, withHistory, line);
    if (withHistory.stageChat) {
      if (!withHistory.app.runId) throw new Error("run_id is required for stage chat");
      await client.inject({ run_id:withHistory.app.runId, message:line, stage:withHistory.stageChat.stage });
      return [{ ...withHistory, transcript:[...withHistory.transcript, { kind:"stage_control", id:`stage-chat-${Date.now()}`, stage:withHistory.stageChat.stage, action:"chat", text:line }], statusMessage:`sent to ${withHistory.stageChat.stage}` }, { message:`sent to ${withHistory.stageChat.stage}` }];
    }
    if ((bucket === "choice-selection" || bucket === "confirmation") && withHistory.pendingAction) return handleComposerSubmit(client, { ...withHistory, pendingAction:undefined }, withHistory.pendingAction.command);
    const projectRequest = looksLikeProjectRequest(line);
    let text = bucket === "ambiguous" ? "I will not act on that without a specific command. Choose: `1` ask a question here, or `2` use `/new <description>` to build." : projectRequest ? `${idleAssistantText(line)} Command preview: \`/new ${line}\`.` : idleAssistantText(line);
    if (!projectRequest && bucket === "ask" && !greetingPattern.test(line) && !wantsInterviewFirst(line)) {
      try {
        const reply = await client.chat({ message:line });
        text = reply.message;
      } catch (e) {
        text = `${idleAssistantText(line)} Provider chat is not ready: ${e instanceof Error ? e.message : String(e)}. Run \`./nexussy.sh cli --setup\` to configure API access.`;
      }
    }
    const pendingAction = projectRequest ? { description:`start pipeline for: ${line}`, command:`/new ${line}` } : withHistory.pendingAction;
    return [{ ...withHistory, pendingAction, transcript:[...withHistory.transcript, { kind:"assistant", id:`local-${Date.now()}`, role:"assistant", text }], statusMessage:"ask mode" }, { message:"ask mode" }];
  }
  const [cmd, ...rest] = line.split(/\s+/);
  if (cmd === "/quit") return [withHistory, { message:"bye", exit:true }];
  if (cmd === "/help") return [{ ...withHistory, overlay:"help" }, { message:"help" }];
  if (cmd === "/onboarding") return [{ ...withHistory, overlay:"onboarding" }, { message:"onboarding" }];
  if (cmd === "/dashboard") return [{ ...withHistory, mode:"dashboard" }, { message:"dashboard" }];
  if (cmd === "/chat") return [{ ...withHistory, mode:"chat", overlay:"none", stageChat:undefined, transcriptFilter:undefined }, { message:"chat" }];
  if (cmd === "/pipeline") return hydrateStatusOverlay(client, { ...withHistory, selectedStage:activeStage(withHistory) ?? "plan" }, "pipeline");
  if (cmd === "/models" || cmd === "/routing") { const secrets = await client.secrets() as any; return [{ ...withHistory, app:reduceSecrets(withHistory.app, secrets), overlay:"models" }, { message:"model routing" }]; }
  if (cmd === "/model" || cmd === "/fallback") {
    const stage = rest.shift() as StageName|undefined;
    const model = rest.join(" ").trim();
    if (!stage || !isStage(stage) || !model) throw new Error(`usage: ${cmd} <stage> <provider/model>`);
    const option = findModelOption(withHistory.app.modelOptions, model);
    if (!option) throw new Error(`model is not available from configured providers: ${model}`);
    const app = reduceStageRoutingModel(withHistory.app, stage, option, cmd === "/model" ? "primary" : "fallback");
    return [{ ...withHistory, app, overlay:"models", statusMessage:`${cmd.slice(1)} ${stage} ${option.model}` }, { message:`${cmd.slice(1)} ${stage}` }];
  }
  if (cmd === "/profile") {
    const profile = rest[0] as RoutingProfileName|undefined;
    if (!profile) return [{ ...withHistory, overlay:"profile" }, { message:"profile" }];
    if (!profiles.has(profile)) throw new Error("usage: /profile <default|fast|cheap|strict>");
    return [{ ...withHistory, app:reduceRoutingProfile(withHistory.app, profile), overlay:"profile", statusMessage:`profile ${profile}` }, { message:`profile ${profile}` }];
  }
  if (cmd === "/status") return hydrateStatusOverlay(client, withHistory, "status");
  if (cmd === "/stages") return hydrateStatusOverlay(client, withHistory, "stages");
  if (cmd === "/plan") return [{ ...withHistory, overlay:"plan" }, { message:"plan" }];
  if (cmd === "/artifacts") return hydrateArtifactsOverlay(client, withHistory);
  if (cmd === "/handoff") return [{ ...withHistory, overlay:"handoff", app:triggerHandoff(withHistory.app, "user_command") }, { message:"handoff triggered by user" }];
  if (cmd === "/workers") { const filter = workerFilters.has(rest[0]) ? rest.shift() as ChatUiState["workerFilter"] : undefined; const stage = stages.has(rest[0]) ? rest.shift() as StageName : undefined; return hydrateWorkersOverlay(client, { ...withHistory, workerFilter:filter ?? "all", selectedStage:stage }); }
  if (cmd === "/worker") { const workerId = rest[0]; if (workerId && !WORKER_ID_PATTERN.test(workerId)) throw new Error("invalid worker_id"); return [{ ...withHistory, overlay:"worker", selectedWorkerId:workerId }, { message:"worker" }]; }
  if (cmd === "/doctor") return [{ ...withHistory, overlay:"doctor" }, { message:"doctor fallback" }];
  if (cmd === "/setup" || cmd === "/setup-openrouter") {
    const provider = cmd === "/setup-openrouter" ? "openrouter" : rest[0];
    if (!provider) return [{ ...withHistory, overlay:"setup" }, { message:"setup menu" }];
    const command = provider === "agentrouter" ? "./nexussy.sh cli --setup" : provider === "openrouter" ? "./nexussy.sh cli --setup-openrouter" : "./nexussy.sh cli --setup";
    return [{ ...withHistory, overlay:"setup", transcript:[...withHistory.transcript, { kind:"assistant", id:`setup-${Date.now()}`, role:"assistant", text:`Provider setup for ${provider}: run \`${command}\` for hidden API-key input. Then return here and use /models.` }] }, { message:`setup ${provider}` }];
  }
  if (cmd === "/new") return startNewRun(client, withHistory, rest.join(" "));
  if (cmd === "/resume" && rest[0] && !withHistory.app.runId && !stages.has(rest[0])) { const app = await hydrateRunStatus(client, { ...withHistory.app, runId:rest[0], finalStatus:undefined }); return [{ ...withHistory, app, statusMessage:`resuming ${rest[0].slice(0,8)}` }, { message:`resuming ${rest[0]}`, stream:true }]; }
  if (cmd === "/secrets") { const secrets = await client.secrets() as any; return [{ ...withHistory, app:reduceSecrets(withHistory.app, secrets), overlay:"secrets" }, { message:"provider key status refreshed" }]; }
  if (cmd === "/memory") return dataOverlay(withHistory, "Memory", await requireClientMethod(client.memory, "/memory").call(client, withHistory.app.sessionId), "memory loaded");
  if (cmd === "/graph") return dataOverlay(withHistory, "Graph", await requireClientMethod(client.graph, "/graph").call(client, withHistory.app.sessionId, withHistory.app.runId), "graph loaded");
  if (cmd === "/config") return dataOverlay(withHistory, "Config", await requireClientMethod(client.config, "/config").call(client), "config loaded");
  if (cmd === "/events") {
    if (!withHistory.app.runId) throw new Error("run_id is required for /events");
    return dataOverlay(withHistory, "Events", await requireClientMethod(client.events, "/events").call(client, withHistory.app.runId, 0, 50), "events loaded");
  }
  if (cmd === "/interview-answer") {
    if (!withHistory.app.sessionId) throw new Error("session_id is required for /interview-answer");
    const answers = parseInterviewAnswers(rest);
    if (!Object.keys(answers).length) throw new Error("usage: /interview-answer question_id=answer ...");
    await requireClientMethod(client.interviewAnswer, "/interview-answer").call(client, withHistory.app.sessionId, answers);
    const app = withHistory.app.runId ? await hydrateRunStatus(client, withHistory.app) : withHistory.app;
    return [{ ...withHistory, app, pendingInterview:undefined, statusMessage:"interview answers submitted", transcript:[...withHistory.transcript, { kind:"stage_control", id:`interview-answer-${Date.now()}`, stage:"interview", action:"chat", text:"Submitted interview answers" }] }, { message:"interview answers submitted", stream:Boolean(withHistory.app.runId) }];
  }
  if (cmd === "/export") return [withHistory, { message:"exported displayed session data", html:renderPanels(withHistory.app).html }];
  if (!withHistory.app.runId) throw new Error("start a run first with plain text or /new DESCRIPTION");
  if (cmd === "/pause") return stageControl(client, withHistory, rest, "pause");
  if (cmd === "/resume-run" || cmd === "/resume") return stageControl(client, withHistory, rest, "resume");
  if (cmd === "/cancel") return stageControl(client, withHistory, rest, "cancel");
  if (cmd === "/stage-chat") { const stage = stageFromArg(rest[0]); if (!stage) throw new Error("usage: /stage-chat <stage>"); return [{ ...withHistory, overlay:"stage-chat", stageChat:{ stage }, selectedStage:stage, transcriptFilter:{ stage }, transcript:[...withHistory.transcript, { kind:"stage_control", id:`stage-chat-open-${Date.now()}`, stage, action:"chat", text:`Opened stage chat for ${stage}` }] }, { message:`stage chat ${stage}` }]; }
  if (cmd === "/stage") { const stage = stageFromArg(rest[0]); if (!stage) throw new Error("invalid stage"); return [{ ...withHistory, overlay:"stages", selectedStage:stage, statusMessage:`viewing ${stage}` }, { message:`viewing ${stage}; use /skip ${stage} <reason> to mutate the run` }]; }
  if (cmd === "/skip") { const stage = stageFromArg(rest.shift()); const reason = rest.join(" "); if (!stage || !reason) throw new Error("usage: /skip <stage> <reason>"); await client.skip(withHistory.app.runId, stage, reason); return [{ ...withHistory, statusMessage:`skipped ${stage}` }, { message:`skipped ${stage}` }]; }
  if (cmd === "/spawn") { const role = rest.shift() as WorkerRole; if (!role || !roles.has(role)) throw new Error("invalid role"); const task = rest.join(" "); if (!task) throw new Error("task required"); await client.spawn({ run_id:withHistory.app.runId, role, task }); return [{ ...withHistory, statusMessage:"spawned" }, { message:"spawned" }]; }
  if (cmd === "/inject") { const maybe = rest[0]; const workerId = maybe && WORKER_ID_PATTERN.test(maybe) ? rest.shift() : undefined; const message = rest.join(" "); if (!message) throw new Error("message required"); if (workerId) await client.injectWorker(workerId, { run_id:withHistory.app.runId, worker_id:workerId, message }); else await client.inject({ run_id:withHistory.app.runId, message }); return [{ ...withHistory, statusMessage:"injected" }, { message:"injected" }]; }
  if (cmd === "/steer") return handleSteerCommand(client, withHistory, rest);
  if (cmd === "/escape") return [closeOverlay(withHistory), { message:"overlay closed" }];
  throw new Error(`unknown command ${cmd}`);
}

async function answerPendingInterview(client:ClientLike, state:ChatUiState, text:string): Promise<[ChatUiState, CommandOutcome]> {
  const pending = state.pendingInterview!;
  const question = pending.questions[pending.index];
  if (!question) return [{ ...state, pendingInterview:undefined }, { message:"interview cleared" }];
  const answers = { [question.question_id]:text };
  await requireClientMethod(client.interviewAnswer, "/interview-answer").call(client, state.app.sessionId!, answers);
  const app = state.app.runId ? await hydrateRunStatus(client, state.app) : state.app;
  return [{ ...state, app, pendingInterview:undefined, transcript:[...state.transcript, { kind:"stage_control", id:`interview-submit-${Date.now()}`, stage:"interview", action:"chat", text:`Submitted answer for ${question.question_id}; waiting for the next adaptive question or pipeline work` }], statusMessage:"interview answer submitted" }, { message:"interview answer submitted; composer ready", stream:Boolean(state.app.runId) }];
}

function requireClientMethod<T extends (...args:any[]) => unknown>(method:T|undefined, command:string): T {
  if (!method) throw new Error(`core client does not support ${command}`);
  return method;
}

function dataOverlay(state:ChatUiState, title:string, value:unknown, message:string): [ChatUiState, CommandOutcome] {
  return [{ ...state, overlay:"data", dataPanel:{ title, lines:formatData(value) }, statusMessage:message }, { message }];
}

function formatData(value:unknown): string[] {
  const json = JSON.stringify(value, null, 2) ?? "null";
  return json.split("\n").slice(0, 120);
}

async function handleSteerCommand(client:ClientLike, state:ChatUiState, args:string[]): Promise<[ChatUiState, CommandOutcome]> {
  const runId = state.app.runId;
  if (!runId) throw new Error("run_id is required for /steer");
  if (!client.mcpCall) throw new Error("core client does not support MCP calls");
  const sub = args[0];
  if (sub === "list") {
    const status = await client.mcpCall<{queue_length:number; recent:Array<{target:string; worker_id?:string|null; message:string; priority:string; created_at:string; consumed_at?:string|null}>}>("nexussy_steer_status", { run_id:runId });
    const recent = status.recent.slice(0, 3).map(e => `${e.target}${e.worker_id ? ` ${e.worker_id}` : ""}: ${e.message}`).join("; ") || "none";
    const message = `steer queue: ${status.queue_length}; recent: ${recent}`;
    return [{ ...state, statusMessage:message }, { message }];
  }
  if (sub === "clear") {
    await client.mcpCall("nexussy_steer", { target:"orchestrator", run_id:runId, message:"CLEAR_CONTEXT", priority:"normal" });
    return [{ ...state, statusMessage:"Steering context cleared" }, { message:"Steering context cleared" }];
  }
  if (!args.length) throw new Error("usage: /steer <message> or /steer @<worker-id> <message>");
  const maybeMention = args[0];
  if (maybeMention?.startsWith("@")) {
    const workerId = maybeMention.slice(1);
    if (!steerWorkerPattern.test(workerId)) throw new Error("invalid worker_id");
    let app = state.app;
    if (!app.workers[workerId]) app = reduceWorkersSnapshot(app, await client.workers(runId) as any);
    if (!app.workers[workerId]) throw new Error("worker not found");
    const message = args.slice(1).join(" ").trim();
    if (!message) throw new Error("message required");
    await client.mcpCall("nexussy_steer", { target:"worker", run_id:runId, worker_id:workerId, message, priority:"normal" });
    const toast = `Steering message sent to worker ${workerId}`;
    return [{ ...state, app, statusMessage:toast }, { message:toast }];
  }
  const message = args.join(" ").trim();
  if (!message) throw new Error("message required");
  await client.mcpCall("nexussy_steer", { target:"orchestrator", run_id:runId, message, priority:"normal" });
  return [{ ...state, statusMessage:"Steering message sent to orchestrator" }, { message:"Steering message sent to orchestrator" }];
}

async function hydrateRunStatus(client:ClientLike, app:ChatUiState["app"]): Promise<ChatUiState["app"]> {
  if (!app.runId) return app;
  return reduceStatusSnapshot(app, await client.status(app.runId) as any);
}

async function hydrateStatusOverlay(client:ClientLike, state:ChatUiState, overlay:"status"|"stages"|"pipeline"): Promise<[ChatUiState, CommandOutcome]> {
  const app = state.app.runId ? await hydrateRunStatus(client, state.app) : state.app;
  return [{ ...state, overlay, app }, { message:overlay }];
}

async function hydrateWorkersOverlay(client:ClientLike, state:ChatUiState): Promise<[ChatUiState, CommandOutcome]> {
  const app = state.app.runId ? reduceWorkersSnapshot(state.app, await client.workers(state.app.runId) as any) : state.app;
  return [{ ...state, overlay:"workers", app }, { message:"workers" }];
}

async function hydrateArtifactsOverlay(client:ClientLike, state:ChatUiState): Promise<[ChatUiState, CommandOutcome]> {
  const app = state.app.sessionId ? reduceArtifactsSnapshot(state.app, await client.artifacts(state.app.sessionId, state.app.runId) as any) : state.app;
  return [{ ...state, overlay:"artifacts", app }, { message:"artifacts" }];
}

function parseStageScoped(args:string[], fallback:string): { stage?:StageName; text:string } {
  const stage = stageFromArg(args[0]);
  if (stage) args.shift();
  return { stage, text:args.join(" ").trim() || fallback };
}

function activeStage(state:ChatUiState): StageName|undefined {
  return Object.entries(state.app.stages).find(([, status]) => status === "running" || status === "paused")?.[0] as StageName|undefined;
}

function selectedOrActiveStage(state:ChatUiState): StageName { return state.selectedStage ?? activeStage(state) ?? "plan"; }
function isStage(value:string|undefined): value is StageName { return Boolean(value && stages.has(value)); }
function stageFromArg(value:string|undefined): StageName|undefined { return isStage(value) ? value : undefined; }

async function stageControl(client:ClientLike, state:ChatUiState, args:string[], action:"pause"|"resume"|"cancel"): Promise<[ChatUiState, CommandOutcome]> {
  const { stage, text } = parseStageScoped(args, action === "resume" ? "resumed" : "user");
  const targetStage = stage ?? selectedOrActiveStage(state);
  if (action === "pause") await client.pause(state.app.runId!, text);
  else if (action === "resume") await client.resume(state.app.runId!);
  else await requireClientMethod(client.cancel, "/cancel").call(client, state.app.runId!, text);
  let app = addStageControlNote(state.app, { stage:targetStage, action, reason:text });
  try { app = await hydrateRunStatus(client, app); } catch {}
  return [{ ...state, app, selectedStage:targetStage, transcript:[...state.transcript, { kind:"stage_control", id:`${action}-${Date.now()}`, stage:targetStage, action, text }], statusMessage:`${action} ${targetStage}` }, { message:action === "cancel" ? `cancelled: ${text}` : action === "resume" ? "resumed" : "paused" }];
}

function parseInterviewAnswers(args:string[]): Record<string,string> {
  const answers:Record<string,string> = {};
  let current:string|undefined;
  for (const token of args) {
    const index = token.indexOf("=");
    if (index > 0) {
      const key = token.slice(0, index).trim();
      const value = token.slice(index + 1).trim();
      if (key) {
        current = key;
        answers[current] = value;
      }
      continue;
    }
    if (current) answers[current] = `${answers[current]} ${token}`.trim();
  }
  return answers;
}
