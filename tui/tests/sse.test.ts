import { expect, test } from "bun:test";
import { EVENT_TYPES, type EventEnvelope } from "../src/types";
import { applyReconnect, fixtureFrame, minimalPayloadFor, parseEnvelope, parseSSEFrames, reconnectHeaders, SSEParseError } from "../src/sse";

function env(type:any, n=1): EventEnvelope { return { event_id:`01HV${String(n).padStart(22,"0")}`, sequence:n, contract_version:"1.0", type, session_id:"018f0000-0000-4000-8000-000000000001", run_id:"018f0000-0000-4000-8000-000000000002", ts:"2026-04-27T00:00:00Z", source:"core", payload:minimalPayloadFor(type) } as EventEnvelope; }

test("parses every Section 9 event type", () => {
  for (let i=0;i<EVENT_TYPES.length;i++) {
    const frame = parseSSEFrames(fixtureFrame(env(EVENT_TYPES[i], i+1)))[0];
    expect(parseEnvelope(frame).type).toBe(EVENT_TYPES[i]);
  }
});

test("rejects malformed envelopes and forbidden done sentinel", () => {
  expect(() => parseSSEFrames("data only\n\n")).toThrow(SSEParseError);
  expect(() => parseEnvelope({data:"[DONE]"})).toThrow(SSEParseError);
  expect(() => parseEnvelope({id:"x",event:"heartbeat",data:JSON.stringify({...env("heartbeat"),event_id:"y"})})).toThrow(SSEParseError);
  expect(() => parseEnvelope({data:JSON.stringify({...env("heartbeat"),contract_version:"2.0"})})).toThrow(SSEParseError);
  expect(() => parseEnvelope({data:JSON.stringify({...env("content_delta"),payload:{stage:"interview"}})})).toThrow(SSEParseError);
});

test("heartbeat frames are valid no-op liveness envelopes", () => {
  const parsed = parseEnvelope(parseSSEFrames(fixtureFrame(env("heartbeat", 99)))[0]);
  expect(parsed.type).toBe("heartbeat");
  if (parsed.type !== "heartbeat") throw new Error("expected heartbeat");
  expect(parsed.payload.server_status).toBe("ok");
});

test("tracks Last-Event-ID reconnect headers", () => {
  const next = applyReconnect({ retryMs:3000, attempts:3 }, env("heartbeat", 7), 1111);
  expect(next.lastEventId).toBe("01HV0000000000000000000007");
  expect(next.retryMs).toBe(1111);
  expect(reconnectHeaders(next)).toEqual({"Last-Event-ID":"01HV0000000000000000000007"});
});
