import { getAnchorBlock, setAnchorBlock } from "./anchors";
import { STAGES, type HandoffPrompt, type TuiState } from "../state";
import type { StageName, Worker } from "../types";

export type HandoffTrigger = HandoffPrompt["trigger"];

export interface HandoffInputs {
  state: TuiState;
  handoffDoc: string;
  devplanDoc: string;
  trigger: HandoffTrigger;
  worker?: Worker;
  now?: Date;
}

export interface HandoffClient {
  pause?(runId:string, reason:string): Promise<unknown>|unknown;
}

export function generateHandoffDocument(input:HandoffInputs): string {
  const { state, trigger } = input;
  const now = (input.now ?? new Date()).toISOString();
  const lastCompleted = [...STAGES].reverse().find(stage => state.stages[stage] === "passed") ?? "none";
  const currentStage = STAGES.find(stage => state.stages[stage] === "running" || state.stages[stage] === "retrying") ?? "none";
  const nextTaskGroup = getAnchorBlock(input.devplanDoc, "NEXT_TASK_GROUP").trim();
  const quickStatus = [
    `Session: ${state.sessionId ?? "unknown"}`,
    `Run: ${state.runId ?? "unknown"}`,
    `Stage reached: ${lastCompleted}`,
    `Tokens used: ${state.contextBudget.totalTokens} / ${state.contextBudget.contextWindowSize} (${Math.round(state.contextBudget.fillRatio * 100)}%)`,
    `Generated: ${now}`,
    `Trigger: ${trigger}`,
  ].join("\n");
  const completed = STAGES.filter(stage => state.stages[stage] === "passed").map(stage => `- ${stage}: ${artifactsForStage(state, stage).join(", ") || "passed"}`);
  const workerTask = input.worker?.task_title ? `${input.worker.worker_id}: ${input.worker.task_title}` : undefined;
  const notes = [
    "What was completed",
    ...(completed.length ? completed : ["- No stages completed yet"]),
    "",
    "What is in progress",
    `- ${workerTask ?? currentStage}`,
    "",
    "What comes next",
    nextTaskGroup || "- No unchecked next task group found",
    "",
    "Context to carry forward",
    ...state.logs.slice(-5).map(row => `- ${row.title}: ${firstLine(row.text)}`),
  ].join("\n");
  let doc = setAnchorBlock(input.handoffDoc, "QUICK_STATUS", quickStatus);
  doc = setAnchorBlock(doc, "HANDOFF_NOTES", notes);
  const worker = input.worker;
  if (worker) {
    const slot = slotForWorker(worker.worker_id) ?? slotForRole(worker.role);
    if (slot) doc = setAnchorBlock(doc, slot, [
      `Worker: ${worker.worker_id}`,
      `Role: ${worker.role}`,
      `Status: ${worker.status}`,
      `Last task: ${worker.task_title ?? "none"}`,
      `Completed at: ${now}`,
    ].join("\n"));
  }
  return doc;
}

export function firstIncompleteStage(state:TuiState): StageName {
  return STAGES.find(stage => state.stages[stage] !== "passed") ?? "develop";
}

export function applyCompaction(state:TuiState, compactedTokens:number): TuiState {
  const total = Math.max(0, state.usage.total_tokens - compactedTokens);
  const usage = { ...state.usage, total_tokens:total };
  const fillRatio = Math.min(1, total / state.contextBudget.contextWindowSize);
  return { ...state, usage, contextBudget:{ ...state.contextBudget, totalTokens:total, fillRatio, nearLimit:fillRatio >= 0.75, atLimit:fillRatio >= 0.90 }, logs:[...state.logs, { id:`compact-${state.logs.length + 1}`, kind:"system", title:"compact", text:`Context compacted - ${compactedTokens} tokens freed`, collapsed:false }] };
}

export async function generateLocalHandoffAndPause(client:HandoffClient, input:HandoffInputs): Promise<string> {
  if (!input.state.sessionId || !input.state.runId) throw new Error("session_id and run_id are required for handoff");
  const doc = generateHandoffDocument(input);
  if (client.pause) await client.pause(input.state.runId, "handoff");
  else throw new Error("client does not support pausing runs");
  return doc;
}

function artifactsForStage(state:TuiState, stage:StageName): string[] {
  const byStage:Record<StageName,string[]> = {
    interview:["interview","complexity_profile"], design:["design_draft"], validate:["validated_design","validation_report"], plan:["devplan","handoff","phase"], review:["review_report"], develop:["develop_report","merge_report","changed_files"],
  };
  return state.artifacts.filter(a => byStage[stage].includes(a.kind)).map(a => a.path);
}

function slotForWorker(workerId:string): string | undefined {
  const m = /^subagent[_-]?([a-d])\b/i.exec(workerId);
  return m ? `SUBAGENT_${m[1].toUpperCase()}_ASSIGNMENT` : undefined;
}

function slotForRole(role:string): string | undefined {
  const map:Record<string,string> = { backend:"SUBAGENT_A_ASSIGNMENT", frontend:"SUBAGENT_B_ASSIGNMENT", qa:"SUBAGENT_B_ASSIGNMENT", devops:"SUBAGENT_D_ASSIGNMENT", writer:"SUBAGENT_D_ASSIGNMENT", analyst:"SUBAGENT_C_ASSIGNMENT" };
  return map[role];
}

function firstLine(text:string): string { return text.split(/\r?\n/).find(Boolean) ?? ""; }
