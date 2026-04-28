import type { TranscriptItem } from "./types";

export function renderToolCard(item: Extract<TranscriptItem, {kind:"tool"}>): string[] {
  const prefix = item.collapsed ? "▸" : "▾";
  const rows = [`${prefix} ${item.title}`];
  if (!item.collapsed && item.text) rows.push(...item.text.split("\n").map(x => `  └─ ${x}`));
  return rows;
}
