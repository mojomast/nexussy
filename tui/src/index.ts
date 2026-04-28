import { CoreClient, FixtureCoreClient } from "./client";
import { CONTRACT_EVENT_FIXTURES, FIXTURE_RUN_ID } from "./fixtures";
import { createState, reduceEvent } from "./state";
import { loadOptionalPiRuntime, renderPanels } from "./renderer";

export async function main() {
  await loadOptionalPiRuntime();
  const mockMode = process.env.NEXUSSY_TUI_MODE === "mock-fixture" || process.argv.includes("--mock-fixture");
  const client = mockMode ? new FixtureCoreClient(CONTRACT_EVENT_FIXTURES) : new CoreClient({ baseUrl:process.env.NEXUSSY_CORE_URL ?? "http://127.0.0.1:7771", apiKey:process.env.NEXUSSY_API_KEY, mode:"live-core" });
  const state = createState();
  const runId = mockMode ? FIXTURE_RUN_ID : process.argv[2];
  if (!runId) { console.log(renderPanels(state).left + "\n---\n" + renderPanels(state).center + "\n---\n" + renderPanels(state).right); return; }
  let current: typeof state = { ...state, runId };
  for await (const env of client.streamRun(runId)) { current = reduceEvent(current, env); console.clear(); const p=renderPanels(current); console.log(`${p.left}\n---\n${p.center}\n---\n${p.right}`); if(env.type==="done") break; }
}
if (import.meta.main) main().catch(e => { console.error(e); process.exit(1); });
