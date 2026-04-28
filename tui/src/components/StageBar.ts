import { CRITICAL_THRESHOLD, WARNING_THRESHOLD } from "../lib/contextBudget";
import { STAGES, type TuiState } from "../state";
import type { StageName, StageRunStatus } from "../types";

const ICONS: Record<string,string> = { pending:"○", running:"●", passed:"✓", retrying:"↻", failed:"✗", skipped:"-", blocked:"!", paused:"Ⅱ" };

export function renderStageBar(state:TuiState): string {
  return STAGES.map(stage => renderStage(stage, state.stages[stage], Boolean(state.checkpoints[stage]))).join(" -> ");
}

export function renderStageBarFooter(state:TuiState): { text:string; color:"green"|"amber"|"red" } {
  const b = state.contextBudget;
  const pct = Math.round(b.fillRatio * 100);
  const color = b.fillRatio >= CRITICAL_THRESHOLD ? "red" : b.fillRatio >= WARNING_THRESHOLD ? "amber" : "green";
  return { text:`${b.totalTokens} / ${b.contextWindowSize} tokens (${pct}%)`, color };
}

export function isRetryTransition(from:StageName|undefined|null, to:StageName, reason?:string): boolean {
  if (/retry/i.test(reason ?? "")) return true;
  return (from === "validate" && to === "design") || (from === "review" && to === "plan");
}

function renderStage(stage:StageName, status:StageRunStatus, checkpoint:boolean): string {
  return `${ICONS[status] ?? "?"} ${stage}${checkpoint ? " ✓" : ""}`;
}
