import { expect, test } from "bun:test";
import { runSlash } from "../src/commands";
import { getAnchorBlock } from "../src/lib/anchors";
import { buildAutoRestartRequest, firstIncompleteStage, generateHandoffDocument } from "../src/lib/handoff";
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

test("auto-restart request uses full handoff and first incomplete stage", () => {
  const state = { ...createState({ projectName:"demo" }), sessionId:"sess-1", runId:"run-1" };
  state.stages.interview = "passed";
  expect(firstIncompleteStage(state)).toBe("design");
  const req = buildAutoRestartRequest(state, handoff);
  expect(req.description).toBe(handoff);
  expect(req.metadata?.handoff_from_session).toBe("sess-1");
  expect(req.metadata?.handoff_from_run).toBe("run-1");
  expect(req.start_stage).toBe("design");
});

test("/handoff slash command result is local", async () => {
  const result = await runSlash("/handoff", {} as any, createState());
  expect(result.local).toBe(true);
});
