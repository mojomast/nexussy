import { expect, test } from "bun:test";
import { checkDevplanTask, parseDevplan } from "../src/panels/DevplanPanel";
import { checkPhaseTask, parsePhase, phaseArtifacts } from "../src/panels/PhasePanel";
import { parseHandoffPanel, saveHandoffBlock } from "../src/panels/HandoffPanel";
import type { ArtifactRef } from "../src/types";

const devplan = `# Plan
<!-- PROGRESS_LOG_START -->
- old progress
<!-- PROGRESS_LOG_END -->
<!-- NEXT_TASK_GROUP_START -->
- [ ] task one
- [x] task two
<!-- NEXT_TASK_GROUP_END -->`;

const phase = `# Phase 001
<!-- PHASE_TASKS_START -->
- [ ] build panel tests
<!-- PHASE_TASKS_END -->
<!-- PHASE_PROGRESS_START -->
- started
<!-- PHASE_PROGRESS_END -->`;

const handoff = ["QUICK_STATUS", "HANDOFF_NOTES", "SUBAGENT_A_ASSIGNMENT", "SUBAGENT_B_ASSIGNMENT", "SUBAGENT_C_ASSIGNMENT", "SUBAGENT_D_ASSIGNMENT"].map(anchor => `<!-- ${anchor}_START -->\nold ${anchor}\n<!-- ${anchor}_END -->`).join("\n");

test("DevPlan panel parses tasks and edits anchored task groups", () => {
  const view = parseDevplan(devplan);
  expect(view.progressLog).toEqual(["- old progress"]);
  expect(view.nextTasks.map(task => [task.title, task.checked])).toEqual([["task one", false], ["task two", true]]);
  const updated = checkDevplanTask(devplan, 0);
  expect(parseDevplan(updated).progressLog.at(-1)).toBe("- ✓ task one");
  expect(parseDevplan(updated).nextTasks.map(task => task.title)).toEqual(["task two"]);
});

test("Phase panel parses sorted phase artifacts and completion edits", () => {
  const artifacts = [
    { kind:"phase", path:"phase010.md", phase_number:10 },
    { kind:"phase", path:"phase002.md", phase_number:2 },
    { kind:"devplan", path:"devplan.md" },
  ] as ArtifactRef[];
  expect(phaseArtifacts(artifacts).map(a => a.path)).toEqual(["phase002.md", "phase010.md"]);
  const view = parsePhase(artifacts[1], phase);
  expect(view.tasks[0].title).toBe("build panel tests");
  const updated = checkPhaseTask(phase, 0);
  expect(parsePhase(artifacts[1], updated).tasks[0].checked).toBe(true);
  expect(parsePhase(artifacts[1], updated).progress.at(-1)).toBe("- completed: build panel tests");
});

test("Handoff panel allows only editable anchor saves", () => {
  const cards = parseHandoffPanel(handoff);
  expect(cards.find(card => card.anchor === "QUICK_STATUS")?.editable).toBe(true);
  expect(cards.find(card => card.anchor === "SUBAGENT_B_ASSIGNMENT")?.editable).toBe(false);
  const updated = saveHandoffBlock(handoff, "QUICK_STATUS", "new status");
  expect(parseHandoffPanel(updated).find(card => card.anchor === "QUICK_STATUS")?.content).toBe("new status");
  expect(() => saveHandoffBlock(handoff, "SUBAGENT_B_ASSIGNMENT", "edit")).toThrow("read-only");
});
