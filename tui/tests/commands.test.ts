import { expect, test } from "bun:test";
import { runSlash } from "../src/commands";
import { createState } from "../src/state";

class MockClient { calls:any[]=[]; secretsState=[{name:"OPENAI_API_KEY",source:"keyring",configured:true}]; pause(...a:any[]){this.calls.push(["POST","/pipeline/pause",...a]);} resume(...a:any[]){this.calls.push(["POST","/pipeline/resume",...a]);} skip(...a:any[]){this.calls.push(["POST","/pipeline/skip",...a]);} spawn(...a:any[]){this.calls.push(["POST","/swarm/spawn",...a]);} inject(...a:any[]){this.calls.push(["POST","/pipeline/inject",...a]);} injectWorker(id:string,...a:any[]){this.calls.push(["POST",`/swarm/workers/${id}/inject`,...a]);} secrets(){this.calls.push(["GET","/secrets"]); return this.secretsState;} deleteSecret(name:string){this.calls.push(["DELETE",`/secrets/${name}`]); this.secretsState=[];} }
const state = { ...createState(), runId:"run-1", sessionId:"sess-1" };

test("slash commands map to exact Section 18.2 endpoints", async () => {
  const c = new MockClient() as any;
  expect((await runSlash("/pause operator reason", c, state)).endpoint).toBe("/pipeline/pause");
  expect((await runSlash("/resume", c, state)).endpoint).toBe("/pipeline/resume");
  expect((await runSlash("/stage plan", c, state)).local).toBe(true);
  expect((await runSlash("/skip plan explicit reason", c, state)).endpoint).toBe("/pipeline/skip");
  expect((await runSlash("/spawn backend build API", c, state)).endpoint).toBe("/swarm/spawn");
  expect((await runSlash("/inject hello all", c, state)).endpoint).toBe("/pipeline/inject");
  expect((await runSlash("/inject backend-abc123 hello one", c, state)).endpoint).toBe("/swarm/workers/backend-abc123/inject");
  expect((await runSlash("/export", c, state)).local).toBe(true);
  expect(c.calls.map((x: any[])=>x[1])).toEqual(["/pipeline/pause","/pipeline/resume","/pipeline/skip","/swarm/spawn","/pipeline/inject","/swarm/workers/backend-abc123/inject"]);
  expect(c.calls[0][2]).toBe("run-1");
  expect(c.calls[0][3]).toBe("operator reason");
  expect(c.calls[2][2]).toBe("run-1");
  expect(c.calls[2][3]).toBe("plan");
  expect(c.calls[2][4]).toBe("explicit reason");
  expect(c.calls[3][2]).toEqual({run_id:"run-1", role:"backend", task:"build API"});
  expect(c.calls[4][2]).toEqual({run_id:"run-1", message:"hello all"});
  expect(c.calls[5][2]).toEqual({run_id:"run-1", worker_id:"backend-abc123", message:"hello one"});
});

test("secret slash commands show status without accepting visible secret values", async () => {
  const c = new MockClient() as any;
  const s = createState();
  expect((await runSlash("/secrets", c, s)).endpoint).toBe("/secrets");
  expect(s.secrets[0].name).toBe("OPENAI_API_KEY");
  await expect(runSlash("/set-key OPENAI_API_KEY sk-secret", c, s)).rejects.toThrow("do not type secrets");
  expect((await runSlash("/set-key OPENAI_API_KEY", c, s)).message).toContain("--set-key OPENAI_API_KEY");
  expect((await runSlash("/setup-openrouter", c, s)).message).toContain("--setup");
  expect((await runSlash("/delete-key OPENAI_API_KEY", c, s)).method).toBe("DELETE");
  expect(JSON.stringify(s)).not.toContain("sk-secret");
});
