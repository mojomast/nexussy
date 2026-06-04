import { STAGES, type TuiState } from "../state";
import type { StageName, StageRunStatus } from "../types";
import { modelLabel } from "../lib/routing";

const STATUS: Record<StageRunStatus,string> = { pending:"○", running:"●", passed:"✓", failed:"✗", skipped:"-", blocked:"!", paused:"Ⅱ", retrying:"↻" };
const LABELS: Record<StageName,string> = { interview:"Discover", design:"Design", validate:"Validate", plan:"Plan", review:"Review", develop:"Implement", validate_browser:"Browser" };

export function renderPipelineStrip(state:TuiState): string {
  return STAGES.map(stage => {
    const status = state.stages[stage];
    const workers = countWorkersForStage(state, stage);
    const progress = workers ? ` ${workers}w` : "";
    const model = shortModel(modelLabel(state.routing[stage]?.primary));
    return `${STATUS[status] ?? "?"} ${LABELS[stage]} ${status}${progress} ${model}`;
  }).join(" | ");
}

export function renderPipelineRows(state:TuiState): string[] {
  return STAGES.map(stage => {
    const route = state.routing[stage];
    const workers = countWorkersForStage(state, stage);
    return `${LABELS[stage].padEnd(9)} ${String(state.stages[stage]).padEnd(8)} ${modelLabel(route?.primary)} -> ${modelLabel(route?.fallback)} ${route?.workerGroup ?? "orchestrator"}${workers ? ` ${workers} worker(s)` : ""}`;
  });
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
