import type { SessionSummary } from "../types";
import type { TranscriptItem } from "./types";

export function latestResumableSession(response:unknown): SessionSummary|undefined {
  const sessions = response && typeof response === "object" && Array.isArray((response as any).sessions) ? (response as any).sessions as SessionSummary[] : [];
  return sessions.find(session => Boolean(session.last_run_id) && !["passed", "failed", "cancelled"].includes(session.status));
}

export function resumePromptItem(session:SessionSummary, id=`resume-prompt-${Date.now()}`): TranscriptItem {
  return { kind:"assistant", id, role:"assistant", text:`Previous run found: ${session.project_name} (${session.status}${session.current_stage ? `, ${session.current_stage}` : ""}). Reply yes to resume ${session.last_run_id?.slice(0, 8)}, or no to start fresh.` };
}
