import { getAnchorBlock, setAnchorBlock } from "../lib/anchors";

export const HANDOFF_BLOCKS = [
  ["QUICK_STATUS", "Current Status", true],
  ["HANDOFF_NOTES", "Notes", true],
  ["SUBAGENT_A_ASSIGNMENT", "Subagent A", false],
  ["SUBAGENT_B_ASSIGNMENT", "Subagent B", false],
  ["SUBAGENT_C_ASSIGNMENT", "Subagent C", false],
  ["SUBAGENT_D_ASSIGNMENT", "Subagent D", false],
] as const;

export interface HandoffCard { anchor:string; label:string; editable:boolean; content:string; }

export function parseHandoffPanel(doc:string): HandoffCard[] {
  return HANDOFF_BLOCKS.map(([anchor,label,editable]) => ({ anchor, label, editable, content:getAnchorBlock(doc, anchor).trim() }));
}

export function saveHandoffBlock(doc:string, anchor:string, content:string): string {
  const entry = HANDOFF_BLOCKS.find(([name]) => name === anchor);
  if (!entry) throw new Error(`Unknown handoff anchor ${anchor}`);
  if (!entry[2]) throw new Error(`Anchor ${anchor} is read-only`);
  return setAnchorBlock(doc, anchor, content);
}
