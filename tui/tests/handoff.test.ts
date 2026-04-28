import { expect, test } from "bun:test";
import { runSlash } from "../src/commands";
import { getAnchorBlock } from "../src/lib/anchors";
import { applyCompaction, firstIncompleteStage, generateHandoffDocument, generateLocalHandoffAndPause } from "../src/lib/handoff";
import { renderHandoffModal } from "../src/components/HandoffModal";
import { createState } from "../src/state";

const handoff = ["QUICK_STATUS", "HANDOFF_NOTES", "SUBAGENT_A_ASSIGNMENT", "SUBAGENT_B_ASSIGNMENT", "SUBAGENT_C_ASSIGNMENT", "SUBAGENT_D_ASSIGNMENT"].map(a => `<!-- ${a}_START -->\nold ${a}\n<!-- ${a}_END -->`).join("\n");
const devplan = "<!-- NEXT_TASK_GROUP_START -->\n- [ ] next task\n<!-- NEXT_TASK_GROUP_END -->";

test("generating a handoff populates anchor blocks", () => {
  const state = { ...createState({ contextWindowSize:100, projectName:"demo" }), sessionId:"sess-1", runId:"run-1" };
  state.stages.interview = "passed";
  state.stages.design = "running";
  state.usage.total_tokens = 80;
  state.contextBudget = { totalTokens:80, contextWindowSize:100, fillRatio:0.8, nearLimit:true, atLimit:false };
  state.logs.push({ id:"l1", kind:"system", title:"stage", text:"design started", collapsed:false });
  const doc = generateHandoffDocument({ state, handoffDoc:handoff, devplanDoc:devplan, trigger:"token_warning", now:new Date("2026-04-28T00:00:00Z") });
  for (const anchor of ["QUICK_STATUS", "HANDOFF_NOTES", "SUBAGENT_A_ASSIGNMENT", "SUBAGENT_B_ASSIGNMENT", "SUBAGENT_C_ASSIGNMENT", "SUBAGENT_D_ASSIGNMENT"]) expect(getAnchorBlock(doc, anchor).trim()).not.toBe("");
  expect(getAnchorBlock(doc, "QUICK_STATUS")).toContain("Session: sess-1");
  expect(getAnchorBlock(doc, "QUICK_STATUS")).toContain("80 / 100");
  expect(getAnchorBlock(doc, "QUICK_STATUS")).toContain("80%");
  expect(getAnchorBlock(doc, "QUICK_STATUS")).toContain("token_warning");
  expect(getAnchorBlock(doc, "HANDOFF_NOTES")).toContain("- [ ] next task");
});

test("first incomplete stage is derived locally without mutating the run", () => {
  const state = { ...createState({ projectName:"demo" }), sessionId:"sess-1", runId:"run-1" };
  state.stages.interview = "passed";
  expect(firstIncompleteStage(state)).toBe("design");
});

test("/handoff slash command result is local", async () => {
  const result = await runSlash("/handoff", {} as any, createState());
  expect(result.local).toBe(true);
});

test("compact helper updates token budget and records freed context", async () => {
  const state = { ...createState({ contextWindowSize:100 }), runId:"run-1" };
  state.usage.total_tokens = 90;
  state.contextBudget = { totalTokens:90, contextWindowSize:100, fillRatio:0.9, nearLimit:true, atLimit:true };
  const compacted = applyCompaction(state, 35);
  expect(compacted.usage.total_tokens).toBe(55);
  expect(compacted.contextBudget.atLimit).toBe(false);
  expect(compacted.logs.at(-1)?.title).toBe("compact");
});

test("local handoff pause uses only the contract pause route", async () => {
  const calls:any[] = [];
  const state = { ...createState({ contextWindowSize:100, projectName:"demo" }), sessionId:"sess-1", runId:"run-1" };
  const doc = await generateLocalHandoffAndPause({
    pause(runId:string, reason:string) { calls.push(["pause", runId, reason]); },
  }, { state, handoffDoc:handoff, devplanDoc:devplan, trigger:"token_critical", now:new Date("2026-04-28T00:00:00Z") });
  expect(doc).toContain("Session: sess-1");
  expect(calls).toEqual([["pause", "run-1", "handoff"]]);
});

test("handoff modal does not advertise unwired compact or auto-restart actions", () => {
  const state = createState({ contextWindowSize:100 });
  state.usage.total_tokens = 90;
  state.contextBudget = { totalTokens:90, contextWindowSize:100, fillRatio:0.9, nearLimit:true, atLimit:true };
  const copy = renderHandoffModal(state).join("\n");
  expect(copy).toContain("Copy handoff");
  expect(copy).toContain("Pause");
  expect(copy).not.toContain("Compact -");
  expect(copy).not.toContain("Auto-restart -");
});
