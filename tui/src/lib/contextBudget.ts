import type { TokenUsage } from "../types";

export interface ContextBudget {
  /** Total tokens consumed so far in this session (input + output + cache). */
  totalTokens: number;
  /** Hard limit for the active provider/model, set from config or a default. */
  contextWindowSize: number;
  /** 0.0-1.0 fill ratio. */
  fillRatio: number;
  /** True when fillRatio >= WARNING_THRESHOLD (default 0.75). */
  nearLimit: boolean;
  /** True when fillRatio >= CRITICAL_THRESHOLD (default 0.90). */
  atLimit: boolean;
}

export const WARNING_THRESHOLD = 0.75;
export const CRITICAL_THRESHOLD = 0.90;

export function computeBudget(usage: TokenUsage, contextWindowSize: number): ContextBudget {
  const totalTokens = usage.total_tokens || ((usage.input_tokens ?? 0) + (usage.output_tokens ?? 0) + (usage.cache_read_tokens ?? 0) + (usage.cache_write_tokens ?? 0));
  const safeWindow = Number.isFinite(contextWindowSize) && contextWindowSize > 0 ? contextWindowSize : defaultContextWindowSize(usage.model ?? "");
  const fillRatio = Math.min(1, Math.max(0, totalTokens / safeWindow));
  return { totalTokens, contextWindowSize:safeWindow, fillRatio, nearLimit:fillRatio >= WARNING_THRESHOLD, atLimit:fillRatio >= CRITICAL_THRESHOLD };
}

export function defaultContextWindowSize(model: string): number {
  const m = model.toLowerCase().replace(/^[^/]+\//, "");
  if (m.startsWith("claude-")) return 200_000;
  if (m.startsWith("gpt-4o")) return 128_000;
  if (m.startsWith("gpt-4-turbo")) return 128_000;
  if (m.startsWith("gpt-3.5")) return 16_385;
  if (m.startsWith("gemini-1.5")) return 1_000_000;
  if (m.startsWith("gemini-2")) return 1_000_000;
  if (m.startsWith("llama") || m.startsWith("mistral")) return 32_768;
  return 32_768;
}
