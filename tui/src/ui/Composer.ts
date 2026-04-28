import { projectNameFromDescription } from "../index";
import { renderPanels } from "../renderer";
import { reduceArtifactsSnapshot, reduceSecrets, reduceStatusSnapshot, reduceWorkersSnapshot, triggerHandoff } from "../state";
import { WORKER_ID_PATTERN } from "../commands";
import type { StageName, WorkerRole } from "../types";
import { closeOverlay } from "./Overlay";
import type { ChatUiState, ClientLike, CommandOutcome } from "./types";

const greetingPattern = /^(hi|hello|hey|yo|sup|howdy|hiya|what'?s\s+up|whatsg\s+up|what'?s?\s*good)[!.\s]*$/i;
const stages = new Set(["interview","design","validate","plan","review","develop"]);
const roles = new Set(["orchestrator","backend","frontend","qa","devops","writer","analyst"]);
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
  if (greetingPattern.test(input.trim())) return "Hi. Tell me what you want to build, or use `/new <description>` to start the pipeline. Try: `Create a tiny CLI with tests`.";
  if (wantsInterviewFirst(input)) return "Ask mode: I can help clarify scope here without starting the pipeline. Answer one question: what outcome do you want, and what platform should it target? Use `/new <description>` only when you want nexussy to start a pipeline run.";
  if (looksLikeProjectRequest(input)) return "Ask mode only. I will not start a pipeline from plain text. Use `/new <description>` to start, or ask a question if you want tradeoffs first.";
  return "Ask mode. I can answer questions and explain options here. Use slash commands such as `/new <description>`, `/status`, `/plan`, or `/secrets` when you want an action.";
}

export function createChatUiState(appFactory:()=>ChatUiState["app"]): ChatUiState {
  return { mode:"chat", overlay:"none", app:appFactory(), rawEvents:[], transcript:[], composer:{ text:"", history:[], historyIndex:-1, fileRefs:[], autocompleteOpen:false, autocompleteQuery:"" }, connection:{ connected:false } };
}

export async function startNewRun(client:ClientLike, state:ChatUiState, description:string): Promise<[ChatUiState, CommandOutcome]> {
  const trimmed = description.trim();
  if (!trimmed) throw new Error("description required");
  const started = await client.startPipeline({ project_name:projectNameFromDescription(trimmed), description:trimmed, auto_approve_interview:true });
  return [{ ...state, pendingAction:undefined, app:{ ...state.app, runId:started.run_id, sessionId:started.session_id, finalStatus:undefined }, statusMessage:`started ${started.run_id.slice(0,8)}` }, { message:`started run ${started.run_id}`, stream:true }];
}

export async function handleComposerSubmit(client:ClientLike, state:ChatUiState, input:string): Promise<[ChatUiState, CommandOutcome]> {
  const line = input.trim();
  if (!line) return [state, { message:"" }];
  const withHistory = { ...state, composer:{ ...state.composer, history:[...state.composer.history, line], historyIndex:-1 } };
  const bucket = classifyInteraction(line, withHistory);
  if (bucket !== "command") {
    if ((bucket === "choice-selection" || bucket === "confirmation") && withHistory.pendingAction) return handleComposerSubmit(client, { ...withHistory, pendingAction:undefined }, withHistory.pendingAction.command);
    const projectRequest = looksLikeProjectRequest(line);
    const text = bucket === "ambiguous" ? "I will not act on that without a specific command. Choose: `1` ask a question here, or `2` use a slash command such as `/new <description>`." : projectRequest ? `${idleAssistantText(line)} Reply \`1\` or \`Yes, run it\` to execute \`/new ${line}\`.` : idleAssistantText(line);
    const pendingAction = projectRequest ? { description:`start pipeline for: ${line}`, command:`/new ${line}` } : withHistory.pendingAction;
    return [{ ...withHistory, pendingAction, transcript:[...withHistory.transcript, { kind:"assistant", id:`local-${Date.now()}`, role:"assistant", text }], statusMessage:"ask mode" }, { message:"ask mode" }];
  }
  const [cmd, ...rest] = line.split(/\s+/);
  if (cmd === "/quit") return [withHistory, { message:"bye", exit:true }];
  if (cmd === "/help") return [{ ...withHistory, overlay:"help" }, { message:"help" }];
  if (cmd === "/onboarding") return [{ ...withHistory, overlay:"onboarding" }, { message:"onboarding" }];
  if (cmd === "/dashboard") return [{ ...withHistory, mode:"dashboard" }, { message:"dashboard" }];
  if (cmd === "/chat") return [{ ...withHistory, mode:"chat" }, { message:"chat" }];
  if (cmd === "/status") return hydrateStatusOverlay(client, withHistory, "status");
  if (cmd === "/stages") return hydrateStatusOverlay(client, withHistory, "stages");
  if (cmd === "/plan") return [{ ...withHistory, overlay:"plan" }, { message:"plan" }];
  if (cmd === "/artifacts") return hydrateArtifactsOverlay(client, withHistory);
  if (cmd === "/handoff") return [{ ...withHistory, overlay:"handoff", app:triggerHandoff(withHistory.app, "user_command") }, { message:"handoff triggered by user" }];
  if (cmd === "/workers") return hydrateWorkersOverlay(client, withHistory);
  if (cmd === "/worker") { const workerId = rest[0]; if (workerId && !WORKER_ID_PATTERN.test(workerId)) throw new Error("invalid worker_id"); return [{ ...withHistory, overlay:"worker", selectedWorkerId:workerId }, { message:"worker" }]; }
  if (cmd === "/doctor") return [{ ...withHistory, overlay:"doctor" }, { message:"doctor fallback" }];
  if (cmd === "/new") return startNewRun(client, withHistory, rest.join(" "));
  if (cmd === "/resume" && rest[0]) { const app = await hydrateRunStatus(client, { ...withHistory.app, runId:rest[0], finalStatus:undefined }); return [{ ...withHistory, app, statusMessage:`resuming ${rest[0].slice(0,8)}` }, { message:`resuming ${rest[0]}`, stream:true }]; }
  if (cmd === "/secrets") { const secrets = await client.secrets() as any; return [{ ...withHistory, app:reduceSecrets(withHistory.app, secrets), overlay:"secrets" }, { message:"provider key status refreshed" }]; }
  if (cmd === "/export") return [withHistory, { message:"exported displayed session data", html:renderPanels(withHistory.app).html }];
  if (!withHistory.app.runId) throw new Error("start a run first with plain text or /new DESCRIPTION");
  if (cmd === "/pause") { await client.pause(withHistory.app.runId, rest.join(" ") || "user"); return [{ ...withHistory, app:{ ...withHistory.app, paused:true }, statusMessage:"paused" }, { message:"paused" }]; }
  if (cmd === "/resume-run" || cmd === "/resume") { await client.resume(withHistory.app.runId); return [{ ...withHistory, app:{ ...withHistory.app, paused:false }, statusMessage:"resumed" }, { message:"resumed" }]; }
  if (cmd === "/stage") { const stage = rest[0] as StageName; if (!stages.has(stage)) throw new Error("invalid stage"); return [{ ...withHistory, overlay:"stages", statusMessage:`viewing ${stage}` }, { message:`viewing ${stage}; use /skip ${stage} <reason> to mutate the run` }]; }
  if (cmd === "/skip") { const stage = rest.shift() as StageName; const reason = rest.join(" "); if (!stage || !reason) throw new Error("usage: /skip <stage> <reason>"); await client.skip(withHistory.app.runId, stage, reason); return [{ ...withHistory, statusMessage:`skipped ${stage}` }, { message:`skipped ${stage}` }]; }
  if (cmd === "/spawn") { const role = rest.shift() as WorkerRole; if (!role || !roles.has(role)) throw new Error("invalid role"); const task = rest.join(" "); if (!task) throw new Error("task required"); await client.spawn({ run_id:withHistory.app.runId, role, task }); return [{ ...withHistory, statusMessage:"spawned" }, { message:"spawned" }]; }
  if (cmd === "/inject") { const maybe = rest[0]; const workerId = maybe && WORKER_ID_PATTERN.test(maybe) ? rest.shift() : undefined; const message = rest.join(" "); if (!message) throw new Error("message required"); if (workerId) await client.injectWorker(workerId, { run_id:withHistory.app.runId, worker_id:workerId, message }); else await client.inject({ run_id:withHistory.app.runId, message }); return [{ ...withHistory, statusMessage:"injected" }, { message:"injected" }]; }
  if (cmd === "/escape") return [closeOverlay(withHistory), { message:"overlay closed" }];
  throw new Error(`unknown command ${cmd}`);
}

async function hydrateRunStatus(client:ClientLike, app:ChatUiState["app"]): Promise<ChatUiState["app"]> {
  if (!app.runId) return app;
  return reduceStatusSnapshot(app, await client.status(app.runId) as any);
}

async function hydrateStatusOverlay(client:ClientLike, state:ChatUiState, overlay:"status"|"stages"): Promise<[ChatUiState, CommandOutcome]> {
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
