import { getAnchorBlock, setAnchorBlock } from "../lib/anchors";

export interface DevplanView { progressLog:string[]; nextTasks:Array<{title:string; checked:boolean; raw:string}>; }

export function parseDevplan(doc:string): DevplanView {
  return { progressLog:lines(getAnchorBlock(doc, "PROGRESS_LOG")), nextTasks:lines(getAnchorBlock(doc, "NEXT_TASK_GROUP")).map(parseTask) };
}

export function checkDevplanTask(doc:string, taskIndex:number): string {
  const progress = lines(getAnchorBlock(doc, "PROGRESS_LOG"));
  const tasks = lines(getAnchorBlock(doc, "NEXT_TASK_GROUP"));
  const task = tasks[taskIndex];
  if (task === undefined) return doc;
  const title = parseTask(task).title;
  const nextTasks = tasks.filter((_, i) => i !== taskIndex);
  let next = setAnchorBlock(doc, "PROGRESS_LOG", [...progress, `- ✓ ${title}`].join("\n"));
  next = setAnchorBlock(next, "NEXT_TASK_GROUP", nextTasks.join("\n"));
  return next;
}

function parseTask(raw:string): {title:string; checked:boolean; raw:string} {
  const m = /^\s*-\s*\[([^\]]+)\]\s*(.*)$/.exec(raw);
  return { raw, checked:/x|✓|✅/i.test(m?.[1] ?? ""), title:(m?.[2] ?? raw.replace(/^\s*-\s*/, "")).trim() };
}

function lines(s:string): string[] { return s.split(/\r?\n/).map(x => x.trimEnd()).filter(x => x.trim()); }
