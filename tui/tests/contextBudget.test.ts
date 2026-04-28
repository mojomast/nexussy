import { expect, test } from "bun:test";
import { CRITICAL_THRESHOLD, WARNING_THRESHOLD, computeBudget, defaultContextWindowSize } from "../src/lib/contextBudget";
import { renderHandoffModal } from "../src/components/HandoffModal";
import { createState, reduceEvent } from "../src/state";
import type { EventEnvelope } from "../src/types";

function costEvent(total_tokens:number, n=1): EventEnvelope {
  return { event_id:`e${n}`, sequence:n, contract_version:"1.0", type:"cost_update", session_id:"s", run_id:"r", ts:"2026-04-28T00:00:00Z", source:"core", payload:{ input_tokens:0, output_tokens:0, total_tokens, cost_usd:0, model:"test/model" } } as EventEnvelope;
}

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

test("cost updates trigger warning and blocking critical handoff prompts", () => {
  let state = createState({ contextWindowSize:100 });
  state = reduceEvent(state, costEvent(75, 1));
  expect(state.handoffPrompt).toEqual({ trigger:"token_warning", blocking:false });
  state = reduceEvent(state, costEvent(90, 2));
  expect(state.handoffPrompt).toEqual({ trigger:"token_critical", blocking:true });
  const modal = renderHandoffModal(state).join("\n");
  expect(modal).toContain("Context Window 90% Full");
  expect(modal).toContain("Esc Dismiss (not recommended)");
});
