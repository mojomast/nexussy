import type { CoreClient } from "./client";
import type { TuiState } from "./state";
import { renderPanels } from "./renderer";
import type { StageName, WorkerRole } from "./types";

export type CommandResult = { local?:true; endpoint?:string; method?:"GET"|"POST"|"DELETE"; message:string; html?:string };
const stages = new Set(["interview","design","validate","plan","review","develop"]);
const roles = new Set(["orchestrator","backend","frontend","qa","devops","writer","analyst"]);
const providerSecrets = new Set(["OPENAI_API_KEY","ANTHROPIC_API_KEY","OPENROUTER_API_KEY","GROQ_API_KEY","GEMINI_API_KEY","MISTRAL_API_KEY","TOGETHER_API_KEY","FIREWORKS_API_KEY","XAI_API_KEY","GLM_API_KEY","ZAI_API_KEY","REQUESTY_API_KEY","AETHER_API_KEY","OLLAMA_BASE_URL"]);

export async function runSlash(input:string, client:CoreClient, state:TuiState): Promise<CommandResult> {
  const [cmd, ...rest] = input.trim().split(/\s+/);
  const run_id = state.runId;
  if (cmd === "/export") return { local:true, message:"exported displayed session data", html:renderPanels(state).html };
  if (cmd === "/handoff") return { local:true, message:"handoff triggered by user" };
  if (cmd === "/secrets" || cmd === "/keys") { state.secrets = await client.secrets(); return { endpoint:"/secrets", method:"GET", message:"provider key status refreshed" }; }
  if (cmd === "/set-key") {
    const name=rest[0];
    if(!name || !providerSecrets.has(name)) throw new Error("invalid provider key name");
    if(rest.length > 1) throw new Error("do not type secrets into slash commands; run `bun run start -- --set-key NAME` for hidden input");
    return { local:true, message:`run hidden setup: bun run start -- --set-key ${name}` };
  }
  if (cmd === "/setup" || cmd === "/setup-openrouter") return { local:true, message:"run guided setup: bun run start -- --setup" };
  if (cmd === "/delete-key") { const name=rest[0]; if(!name || !providerSecrets.has(name)) throw new Error("invalid provider key name"); await client.deleteSecret(name); state.secrets = await client.secrets(); return { endpoint:`/secrets/${name}`, method:"DELETE", message:`deleted ${name}` }; }
  if (!run_id) throw new Error("run_id is required for remote slash commands");
  if (cmd === "/pause") { const reason=rest.join(" ")||"user"; await client.pause(run_id, reason); return {endpoint:"/pipeline/pause",method:"POST",message:reason}; }
  if (cmd === "/resume") { await client.resume(run_id); return {endpoint:"/pipeline/resume",method:"POST",message:"resumed"}; }
  if (cmd === "/stage") { const stage=rest[0]; if(!stages.has(stage)) throw new Error("invalid stage"); await client.skip(run_id, stage as StageName, "user slash stage skip"); return {endpoint:"/pipeline/skip",method:"POST",message:`stage ${stage}`}; }
  if (cmd === "/spawn") { const role=rest.shift(); if(!role||!roles.has(role)) throw new Error("invalid role"); const task=rest.join(" "); if(!task) throw new Error("task required"); await client.spawn({run_id, role:role as WorkerRole, task}); return {endpoint:"/swarm/spawn",method:"POST",message:task}; }
  if (cmd === "/inject") { const maybe=rest[0]; const workerId = maybe && /^[a-z]+-[a-z0-9]{6,12}$/.test(maybe) ? rest.shift() : undefined; const message=rest.join(" "); if(!message) throw new Error("message required"); if(workerId){ await client.injectWorker(workerId,{run_id,worker_id:workerId,message}); return {endpoint:`/swarm/workers/${workerId}/inject`,method:"POST",message}; } await client.inject({run_id,message}); return {endpoint:"/pipeline/inject",method:"POST",message}; }
  throw new Error(`unknown command ${cmd}`);
}
