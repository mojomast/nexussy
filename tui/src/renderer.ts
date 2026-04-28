import type { TuiState } from "./state";
import { STAGES } from "./state";

export interface RenderedPanels { left:string; center:string; right:string; html:string; }

export interface PiRuntimeAvailability { tui:boolean; ai:boolean; agentCore:boolean; missing:string[]; }
export type RuntimeImporter = (name:string) => Promise<unknown>;

export async function loadOptionalPiRuntime(importer:RuntimeImporter = (name) => import(name)): Promise<PiRuntimeAvailability> {
  const packages = ["@mariozechner/pi-tui", "@mariozechner/pi-ai", "@mariozechner/pi-agent-core"] as const;
  const result:PiRuntimeAvailability = { tui:false, ai:false, agentCore:false, missing:[] };
  for (const pkg of packages) {
    try { await importer(pkg); }
    catch { result.missing.push(pkg); continue; }
    if (pkg.endsWith("pi-tui")) result.tui = true;
    else if (pkg.endsWith("pi-ai")) result.ai = true;
    else result.agentCore = true;
  }
  return result;
}

export function renderPanels(state:TuiState): RenderedPanels {
  const left = [`Agents (${Object.keys(state.workers).length})`, ...Object.values(state.workers).map(w=>`${w.role} ${w.worker_id} ${w.status}${w.task_title?` — ${w.task_title}`:""}`), "", "Stages", ...STAGES.map(x=>`${x}: ${state.stages[x]}`), "", `Paused: ${state.paused ? "yes" : "no"}`, state.finalStatus ? `Final: ${state.finalStatus}` : ""].filter(Boolean).join("\n");
  const center = ["Stream", state.connectionError ? `! connection: ${state.connectionError}` : "", state.authError ? `! auth: ${state.authError}` : "", ...state.logs.map(r => `${r.kind === "tool" ? (r.collapsed ? "▸" : "▾") : "•"} ${r.title}${r.collapsed ? "" : `\n${r.text}`}`), "", "Input: /spawn /inject /pause /resume /stage /export"].filter(Boolean).join("\n");
  const activeBlockers = Object.values(state.blockers).filter(b=>!b.resolved);
  const right = ["DevPlan", ...(state.devplan.length?state.devplan:["(no devplan updates)"]), "", `Tokens: ${state.usage.total_tokens}  Cost: $${state.usage.cost_usd.toFixed(4)}`, "", "Files", ...state.locks.map(l=>`${l.status} ${l.path} by ${l.worker_id}`), "", "Git", ...state.gitEvents.map(g=>`${g.action}: ${g.message}`), "", "Artifacts", ...state.artifacts.map(a=>`${a.kind}: ${a.path}`), "", "Blockers", ...(activeBlockers.length?activeBlockers.map(b=>`${b.severity}: ${b.message}`):["(none)"])].join("\n");
  return { left, center, right, html: exportHtml(left, center, right) };
}

export function exportHtml(left:string, center:string, right:string): string {
  const esc=(s:string)=>s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]!));
  return `<!doctype html><meta charset="utf-8"><title>nexussy export</title><style>body{font-family:monospace;display:grid;grid-template-columns:1fr 2fr 1fr;gap:1rem;background:#111;color:#eee}pre{border:1px solid #555;padding:1rem;white-space:pre-wrap}</style><pre>${esc(left)}</pre><pre>${esc(center)}</pre><pre>${esc(right)}</pre>`;
}
