import { STAGES, type TuiState } from "../state";
import type { StageName, StageRunStatus } from "../types";
import { modelLabel } from "../lib/routing";
import type { PendingGate, PendingInterview } from "./types";

const STATUS: Record<StageRunStatus,string> = { pending:"○", running:"●", passed:"✓", failed:"✗", skipped:"-", blocked:"!", paused:"Ⅱ", retrying:"↻" };
export const GATE_STATUS = "⏸";
export const LABELS: Record<StageName,string> = { interview:"Discover", design:"Design", validate:"Validate", validate_browser:"Browser", plan:"Plan", review:"Review", develop:"Implement" };
export const VERBS: Record<StageName,string> = { interview:"asking", design:"shaping", validate:"checking", validate_browser:"browsing", plan:"slicing", review:"reviewing", develop:"building" };

export function renderPipelineStrip(state:TuiState, gate?:PendingGate, interview?:PendingInterview): string {
  return STAGES.map(stage => {
    const status = state.stages[stage];
    const workers = countWorkersForStage(state, stage);
    const progress = workers ? ` ${workers}w` : "";
    const model = shortModel(modelLabel(state.routing[stage]?.primary));
    if (gate?.nextStage === stage) return `${GATE_STATUS} ${LABELS[stage]} pending confirmation ${model}`;
    return `${STATUS[status] ?? "?"} ${LABELS[stage]} ${stageText(stage, status, interview)}${progress} ${model}`;
  }).join(" | ");
}

export function renderPipelineRows(state:TuiState, gate?:PendingGate, interview?:PendingInterview): string[] {
  return STAGES.map(stage => {
    const route = state.routing[stage];
    const workers = countWorkersForStage(state, stage);
    const statusText = gate?.nextStage === stage ? "pending confirmation" : stageText(stage, state.stages[stage], interview);
    return `${LABELS[stage].padEnd(9)} ${statusText.padEnd(20)} ${modelLabel(route?.primary)} -> ${modelLabel(route?.fallback)} ${route?.workerGroup ?? "orchestrator"}${workers ? ` ${workers} worker(s)` : ""}`;
  });
}

function stageText(stage:StageName, status:StageRunStatus, interview?:PendingInterview): string {
  if (status === "running") return stage === "interview" && interview ? `${VERBS[stage]} (q${interview.index + 1}/${interview.questions.length})` : VERBS[stage];
  if (status === "retrying") return `retrying ${VERBS[stage]}`;
  if (status === "paused") return "waiting for you";
  return status;
}

export function workerStage(worker:{stage?:StageName|null; task_title?:string|null}): StageName|undefined {
  if (worker.stage) return worker.stage;
  const text = (worker.task_title ?? "").toLowerCase();
  return STAGES.find(stage => text.includes(stage) || text.includes(stage.replace("_", " ")));
}

export function countWorkersForStage(state:TuiState, stage:StageName): number {
  return Object.values(state.workers).filter(worker => workerStage(worker) === stage).length;
}

function shortModel(label:string): string {
  return label.replace(/^([^:]+:)?/, "").replace(/\s+\(disabled\)$/, "!").slice(0, 18);
}
