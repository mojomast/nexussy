import { expect, test } from "bun:test";
import { CRITICAL_THRESHOLD, WARNING_THRESHOLD, computeBudget, defaultContextWindowSize } from "../src/lib/contextBudget";

test("computeBudget returns fillRatio 0 for zero tokens", () => {
  expect(computeBudget({ input_tokens:0, output_tokens:0, total_tokens:0, cost_usd:0 }, 100).fillRatio).toBe(0);
});

test("computeBudget sets nearLimit at warning threshold", () => {
  const b = computeBudget({ input_tokens:0, output_tokens:0, total_tokens:75, cost_usd:0 }, 100);
  expect(b.fillRatio).toBe(WARNING_THRESHOLD);
  expect(b.nearLimit).toBe(true);
});

test("computeBudget sets atLimit at critical threshold", () => {
  const b = computeBudget({ input_tokens:0, output_tokens:0, total_tokens:90, cost_usd:0 }, 100);
  expect(b.fillRatio).toBe(CRITICAL_THRESHOLD);
  expect(b.atLimit).toBe(true);
});

test("defaultContextWindowSize returns model defaults", () => {
  expect(defaultContextWindowSize("claude-3-5-sonnet")).toBe(200000);
  expect(defaultContextWindowSize("gpt-4o-mini")).toBe(128000);
  expect(defaultContextWindowSize("unknown-model-xyz")).toBe(32768);
});
