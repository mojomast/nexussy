import { STAGES, type TuiState } from "../state";
import type { ArtifactRef, StageName } from "../types";
import type { ChatUiState, ClientLike, TranscriptItem } from "../ui/types";

export function buildGateSummary(stage:StageName, transcript:TranscriptItem[]): string {
  const recent = transcript.slice(-40);
  if (stage === "design") {
    const paths = recent.flatMap(item => item.kind === "artifact" && /design|spec/i.test(`${item.artifact.kind} ${item.artifact.path}`) ? [item.artifact.path] : []);
    if (paths.length) return `Design artifacts: ${paths.slice(-3).join(", ")}`;
  }
  if (stage === "validate") {
    const results = recent
      .filter((item): item is TranscriptItem & { kind:"tool" } => item.kind === "tool" && !item.collapsed && /tool output|tool failed|pass|fail|error|success|validated/i.test(`${item.title} ${item.text}`))
      .slice(-2)
      .map(item => `${item.title}: ${item.text.slice(0, 80)}`);
    if (results.length) return results.join("; ");
  }
  if (stage === "plan") {
    const paths = recent.flatMap(item => item.kind === "artifact" && /devplan|plan/i.test(`${item.artifact.kind} ${item.artifact.path}`) ? [item.artifact.path] : []);
    if (paths.length) return `Plan artifact: ${paths.at(-1)}`;
  }
  if (stage === "review") {
    const review = [...recent].reverse().filter(item => item.kind === "assistant").map(item => item.text).find((text:string) => /review|issue|passed|failed/i.test(text));
    if (review) return review.slice(0, 120);
  }
  if (stage === "develop") {
    const workers = new Set(recent.filter(item => item.kind === "worker").map(item => item.worker_id)).size;
    const files = recent.filter(item => item.kind === "file").length;
    if (workers || files) return `${workers} worker(s), ${files} file activity event(s)`;
  }
  if (stage === "interview") {
    const answers = recent.filter(item => item.kind === "stage_control" && item.stage === "interview" && /Submitted answer/i.test(item.text)).length;
    return answers ? `${answers} interview answer(s) submitted` : "Interview answers captured.";
  }
  const fallback = [...recent].reverse().find((item:TranscriptItem) => (item.kind === "assistant" || item.kind === "stage_control") && (item.kind !== "stage_control" || item.stage === stage));
  return fallback ? fallback.text.slice(0, 120) : `${stage} completed. Review artifacts or continue.`;
}

export async function pauseForNewGate(client:Pick<ClientLike, "pause">, previous:ChatUiState, next:ChatUiState): Promise<ChatUiState> {
  if (previous.pendingGate || !next.pendingGate || !next.app.runId) return next;
  await client.pause(next.app.runId, `stage gate: ${next.pendingGate.completedStage} complete; awaiting confirmation for ${next.pendingGate.nextStage}`);
  return { ...next, app:{ ...next.app, paused:true }, statusMessage:`paused at gate: ${next.pendingGate.completedStage} → ${next.pendingGate.nextStage}` };
}

export function pendingGateFromApp(app:TuiState): ChatUiState["pendingGate"]|undefined {
  if (app.config.gateStages === false || !app.paused || app.finalStatus) return undefined;
  const openIndex = STAGES.findIndex(stage => app.stages[stage] !== "passed" && app.stages[stage] !== "skipped");
  if (openIndex <= 0) return undefined;
  const completedStage = [...STAGES.slice(0, openIndex)].reverse().find(stage => app.stages[stage] === "passed");
  const nextStage = STAGES[openIndex];
  if (!completedStage || !nextStage) return undefined;
  return { completedStage, nextStage, summary:summaryFromArtifacts(completedStage, app.artifacts), autoAdvance:false };
}

export function stageArtifacts(stage:StageName, artifacts:ArtifactRef[]): ArtifactRef[] {
  return artifacts.filter(artifact => artifactMatchesStage(stage, artifact));
}

function summaryFromArtifacts(stage:StageName, artifacts:ArtifactRef[]): string {
  const matches = stageArtifacts(stage, artifacts);
  if (matches.length) return `${stage} artifact: ${matches.at(-1)!.path}`;
  return `${stage} completed. Review artifacts or continue.`;
}

function artifactMatchesStage(stage:StageName, artifact:ArtifactRef): boolean {
  const text = `${artifact.kind} ${artifact.path}`;
  if (stage === "interview") return /interview/i.test(text);
  if (stage === "design") return /design/i.test(text);
  if (stage === "validate") return /validat|report/i.test(text);
  if (stage === "plan") return /devplan|plan/i.test(text);
  if (stage === "review") return /review/i.test(text);
  if (stage === "develop") return /develop|merge|changed_files/i.test(text);
  if (stage === "validate_browser") return /browser/i.test(text);
  return false;
}
