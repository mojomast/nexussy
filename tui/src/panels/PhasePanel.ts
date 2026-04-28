import { getAnchorBlock, setAnchorBlock } from "../lib/anchors";
import type { ArtifactRef } from "../types";

export interface PhaseView { artifact:ArtifactRef; tasks:Array<{title:string; checked:boolean; raw:string}>; progress:string[]; }

export function phaseArtifacts(artifacts:ArtifactRef[]): ArtifactRef[] {
  return artifacts.filter(a => a.kind === "phase").sort((a,b) => (a.phase_number ?? phaseNumber(a.path)) - (b.phase_number ?? phaseNumber(b.path)));
}

export function parsePhase(artifact:ArtifactRef, doc:string): PhaseView {
  return { artifact, tasks:lines(getAnchorBlock(doc, "PHASE_TASKS")).map(parseTask), progress:lines(getAnchorBlock(doc, "PHASE_PROGRESS")) };
}

export function checkPhaseTask(doc:string, taskIndex:number): string {
  const tasks = lines(getAnchorBlock(doc, "PHASE_TASKS"));
  const progress = lines(getAnchorBlock(doc, "PHASE_PROGRESS"));
  const raw = tasks[taskIndex];
  if (raw === undefined) return doc;
  const title = parseTask(raw).title;
  const updated = tasks.map((line, i) => i === taskIndex ? line.replace(/^\s*-\s*\[[^\]]*\]/, "- [x]") : line);
  let next = setAnchorBlock(doc, "PHASE_TASKS", updated.join("\n"));
  next = setAnchorBlock(next, "PHASE_PROGRESS", [...progress, `- completed: ${title}`].join("\n"));
  return next;
}

function parseTask(raw:string): {title:string; checked:boolean; raw:string} {
  const m = /^\s*-\s*\[([^\]]+)\]\s*(.*)$/.exec(raw);
  return { raw, checked:/x|✓|✅/i.test(m?.[1] ?? ""), title:(m?.[2] ?? raw.replace(/^\s*-\s*/, "")).trim() };
}

function lines(s:string): string[] { return s.split(/\r?\n/).map(x => x.trimEnd()).filter(x => x.trim()); }
function phaseNumber(path:string): number { return Number(/phase(\d+)/i.exec(path)?.[1] ?? 0); }
