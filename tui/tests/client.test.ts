import { expect, test } from "bun:test";
import { CoreClient, CoreHttpError, FixtureCoreClient } from "../src/client";
import { fixtureFrame, minimalPayloadFor } from "../src/sse";
import type { EventEnvelope } from "../src/types";

function response(body: unknown, status = 200): Response { return new Response(JSON.stringify(body), { status, headers:{"content-type":"application/json"} }); }
function env(n=1): EventEnvelope { return { event_id:`e${n}`, sequence:n, contract_version:"1.0", type:"heartbeat", session_id:"s", run_id:"r", ts:"2026-04-27T00:00:00Z", source:"core", payload:minimalPayloadFor("heartbeat") } as EventEnvelope; }

test("live-core mode preserves auth headers across HTTP routes used by UI", async () => {
  const seen: Array<{url:string; init:RequestInit}> = [];
  const client = new CoreClient({ mode:"live-core", apiKey:"secret", fetchImpl: (async (url, init) => { seen.push({url:String(url), init:init ?? {}}); return response({ok:true}); }) as typeof fetch });
  await client.health(); await client.status("r"); await client.spawn({run_id:"r", role:"backend", task:"Do it"}); await client.fileLocks("r"); await client.events("r"); await client.mcpCall("nexussy_steer_status", {run_id:"r"}); await client.secrets(); await client.setSecret("OPENAI_API_KEY", "sk-secret"); await client.deleteSecret("OPENAI_API_KEY");
  expect(client.mode).toBe("live-core");
  expect(seen.map(s => new URL(s.url).pathname)).toEqual(["/health","/pipeline/status","/swarm/spawn","/swarm/file-locks","/events","/mcp/call","/secrets","/secrets/OPENAI_API_KEY","/secrets/OPENAI_API_KEY"]);
  expect(JSON.parse(String(seen[5].init.body))).toEqual({name:"nexussy_steer_status", arguments:{run_id:"r"}});
  expect(seen.every(s => (s.init.headers as Record<string,string>)["X-API-Key"] === "secret")).toBe(true);
});

test("contract artifacts route uses session and optional run query", async () => {
  const seen: Array<{url:string; init:RequestInit}> = [];
  const client = new CoreClient({ fetchImpl: (async (url, init) => { seen.push({ url:String(url), init:init ?? {} }); return response({ ok:true, artifacts:[] }); }) as typeof fetch });
  await client.artifacts("sess 1", "run-1");
  const url = new URL(seen[0].url);
  expect(url.pathname).toBe("/pipeline/artifacts");
  expect(url.searchParams.get("session_id")).toBe("sess 1");
  expect(url.searchParams.get("run_id")).toBe("run-1");
  expect(seen[0].init.method).toBe("GET");
});

test("HTTP auth and connection errors are surfaced with core error body", async () => {
  const client = new CoreClient({ fetchImpl: (async () => response({ok:false,error_code:"unauthorized",message:"bad key",request_id:"req",retryable:false}, 401)) as unknown as typeof fetch });
  await expect(client.status("r")).rejects.toBeInstanceOf(CoreHttpError);
  try { await client.status("r"); } catch (e) { expect((e as CoreHttpError).response?.error_code).toBe("unauthorized"); expect((e as Error).message).toBe("bad key"); }
});

test("mock-fixture mode replays after Last-Event-ID assumption", async () => {
  const fixture = [env(1), env(2), env(3)];
  const client = new FixtureCoreClient(fixture);
  const replayed: string[] = [];
  for await (const e of client.streamRun("r", { retryMs:3000, attempts:1, lastEventId:"e1" })) replayed.push(e.event_id);
  expect(client.mode).toBe("mock-fixture");
  expect(replayed).toEqual(["e2","e3"]);
});

test("live SSE reconnect sends Last-Event-ID and streams incrementally", async () => {
  const done = { ...env(2), event_id:"e2", sequence:2, type:"done", payload:minimalPayloadFor("done") } as EventEnvelope;
  const requests: Array<HeadersInit|undefined> = [];
  const client = new CoreClient({ fetchImpl: (async (_url, init) => {
    requests.push(init?.headers);
    const body = requests.length === 1 ? fixtureFrame(env(1)) : fixtureFrame(done);
    return new Response(body, { status:200, headers:{"content-type":"text/event-stream; charset=utf-8"} });
  }) as typeof fetch });
  const seen: string[] = [];
  for await (const event of client.streamRun("r", { retryMs:0, attempts:0 })) seen.push(event.event_id);
  expect(seen).toEqual(["e1", "e2"]);
  expect((requests[1] as Record<string,string>)["Last-Event-ID"]).toBe("e1");
});

test("SSE auth failure surfaces unauthorized error", async () => {
  const client = new CoreClient({ fetchImpl: (async () => new Response("unauthorized", { status:401 })) as unknown as typeof fetch });
  await expect(async () => {
    for await (const _ of client.streamRun("r")) { /* unreachable */ }
  }).toThrow("unauthorized");
});
