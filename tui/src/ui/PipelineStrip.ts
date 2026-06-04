import { STAGES, type TuiState } from "../state";
import type { StageName, StageRunStatus } from "../types";
import { modelLabel } from "../lib/routing";

const STATUS: Record<StageRunStatus,string> = { pending:"○", running:"●", passed:"✓", failed:"✗", skipped:"-", blocked:"!", paused:"Ⅱ", retrying:"↻" };
const LABELS: Record<StageName,string> = { interview:"Discover", design:"Design", validate:"Validate", plan:"Plan", review:"Review", develop:"Implement" };

export function renderPipelineStrip(state:TuiState): string {
  return STAGES.map(stage => {
    const status = state.stages[stage];
    const workers = Object.values(state.workers).filter(worker => worker.task_title && stage === "develop").length;
    const progress = workers ? ` ${workers}w` : "";
    const model = shortModel(modelLabel(state.routing[stage]?.primary));
    return `${STATUS[status] ?? "?"} ${LABELS[stage]} ${status}${progress} ${model}`;
  }).join(" | ");
}

export function renderPipelineRows(state:TuiState): string[] {
  return STAGES.map(stage => {
    const route = state.routing[stage];
    const workers = Object.values(state.workers).filter(worker => stage === "develop" || worker.task_title?.toLowerCase().includes(stage)).length;
    return `${LABELS[stage].padEnd(9)} ${String(state.stages[stage]).padEnd(8)} ${modelLabel(route?.primary)} -> ${modelLabel(route?.fallback)} ${route?.workerGroup ?? "orchestrator"}${workers ? ` ${workers} worker(s)` : ""}`;
  });
}

function shortModel(label:string): string {
  return label.replace(/^([^:]+:)?/, "").replace(/\s+\(disabled\)$/, "!").slice(0, 18);
}
