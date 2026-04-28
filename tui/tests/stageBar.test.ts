import { expect, test } from "bun:test";
import { renderStageBar, renderStageBarFooter } from "../src/components/StageBar";
import { createState, reduceEvent } from "../src/state";
import type { EventEnvelope } from "../src/types";

function envelope(type:any, payload:any, sequence=1): EventEnvelope { return { event_id:`e${sequence}`, sequence, contract_version:"1.0", type, session_id:"s", run_id:"r", ts:"2026-04-28T00:00:00Z", source:"core", payload } as EventEnvelope; }

test("shows all six stages in order", () => {
  const text = renderStageBar(createState());
  expect(text).toContain("interview");
  expect(text.indexOf("interview")).toBeLessThan(text.indexOf("design"));
  expect(text.indexOf("review")).toBeLessThan(text.indexOf("develop"));
});

test("updates stage to running on stage_transition", () => {
  const s = reduceEvent(createState(), envelope("stage_transition", { from_stage:"interview", to_stage:"design", from_status:"passed", to_status:"running", reason:"next" }));
  expect(s.stages.interview).toBe("passed");
  expect(s.stages.design).toBe("running");
});

test("shows retrying on validate to design retry", () => {
  const s = reduceEvent(createState(), envelope("stage_transition", { from_stage:"validate", to_stage:"design", from_status:"failed", to_status:"running", reason:"retry validation" }));
  expect(s.stages.validate).toBe("retrying");
  expect(s.stages.validate).not.toBe("failed");
});

test("shows checkpoint badge", () => {
  const s = reduceEvent(createState(), envelope("checkpoint_saved", { checkpoint_id:"c", stage:"design", path:"p", sha256:"a", created_at:"now" }));
  expect(renderStageBar(s)).toContain("design ✓");
});

test("footer token color changes by threshold", () => {
  expect(renderStageBarFooter({ ...createState({ contextWindowSize:100 }), contextBudget:{ totalTokens:50, contextWindowSize:100, fillRatio:0.5, nearLimit:false, atLimit:false } }).color).toBe("green");
  expect(renderStageBarFooter({ ...createState({ contextWindowSize:100 }), contextBudget:{ totalTokens:75, contextWindowSize:100, fillRatio:0.75, nearLimit:true, atLimit:false } }).color).toBe("amber");
  expect(renderStageBarFooter({ ...createState({ contextWindowSize:100 }), contextBudget:{ totalTokens:90, contextWindowSize:100, fillRatio:0.9, nearLimit:true, atLimit:true } }).color).toBe("red");
});
