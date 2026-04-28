import type { TuiState } from "../state";
import type { ArtifactRef, EventEnvelope, StageName, Worker, WorkerRole } from "../types";

export type UiMode = "chat" | "dashboard";
export type OverlayMode = "none" | "help" | "onboarding" | "status" | "stages" | "plan" | "artifacts" | "workers" | "worker" | "doctor" | "secrets" | "handoff";

export type TranscriptItem =
  | { kind:"run_started"; id:string; text:string }
  | { kind:"stage"; id:string; stage:StageName; status:string; text:string }
  | { kind:"assistant"; id:string; role:string; text:string }
  | { kind:"tool"; id:string; title:string; text:string; collapsed:boolean }
  | { kind:"worker"; id:string; worker_id:string; text:string }
  | { kind:"file"; id:string; text:string }
  | { kind:"artifact"; id:string; artifact:ArtifactRef; text:string }
  | { kind:"error"; id:string; text:string; actions:string[] }
  | { kind:"done"; id:string; status:string; text:string }
  | { kind:"meta"; id:string; text:string };

export interface ComposerState { text:string; history:string[]; historyIndex:number; fileRefs:string[]; autocompleteOpen:boolean; autocompleteQuery:string; }
export interface ConnectionState { connected:boolean; lastEventId?:string; error?:string; }

export interface ChatUiState {
  mode: UiMode;
  overlay: OverlayMode;
  selectedWorkerId?: string;
  app: TuiState;
  rawEvents: EventEnvelope[];
  transcript: TranscriptItem[];
  interviewMode?: boolean;
  pendingAction?: { description:string; command:string };
  composer: ComposerState;
  connection: ConnectionState;
  statusMessage?: string;
}

export interface CommandOutcome { message:string; stream?:boolean; exit?:boolean; html?:string; }

export type ClientLike = {
  startPipeline(body:unknown): Promise<{run_id:string; session_id:string}>|{run_id:string; session_id:string};
  chat(body:{message:string; model?:string|null}): Promise<{message:string; model:string; usage?:unknown}>|{message:string; model:string; usage?:unknown};
  inject(body:{run_id:string; message:string; worker_id?:string|null; stage?:StageName|null}): Promise<unknown>|unknown;
  injectWorker(worker_id:string, body:{run_id:string; worker_id:string; message:string}): Promise<unknown>|unknown;
  pause(run_id:string, reason?:string): Promise<unknown>|unknown;
  resume(run_id:string): Promise<unknown>|unknown;
  skip(run_id:string, stage:StageName, reason:string): Promise<unknown>|unknown;
  spawn(body:{run_id:string; role:WorkerRole; task:string; phase_number?:number|null; model?:string}): Promise<unknown>|unknown;
  secrets(): Promise<unknown>|unknown;
  status(run_id:string): Promise<unknown>|unknown;
  workers(run_id:string): Promise<unknown>|unknown;
  artifacts(session_id:string, run_id?:string): Promise<unknown>|unknown;
  compact?(run_id:string): Promise<{compacted_tokens:number}>|{compacted_tokens:number};
};
