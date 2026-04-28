import type { TranscriptItem } from "./types";

export function renderWorkerCard(item: Extract<TranscriptItem, {kind:"worker"}>): string {
  return `◇ ${item.text}`;
}
