import type { TranscriptItem } from "./types";

export function renderArtifactLink(item: Extract<TranscriptItem, {kind:"artifact"}>): string {
  return `↳ ${item.artifact.kind}: ${item.artifact.path}`;
}
