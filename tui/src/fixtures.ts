import { minimalPayloadFor } from "./sse";
import { EVENT_TYPES, type EventEnvelope, type SSEEventType } from "./types";

export const FIXTURE_SESSION_ID = "018f0000-0000-4000-8000-000000000001";
export const FIXTURE_RUN_ID = "018f0000-0000-4000-8000-000000000002";

export function fixtureEnvelope(type: SSEEventType, index: number): EventEnvelope {
  return {
    event_id: `01HV${String(index).padStart(22,"0")}`,
    sequence: index,
    contract_version: "1.0",
    type,
    session_id: FIXTURE_SESSION_ID,
    run_id: FIXTURE_RUN_ID,
    ts: "2026-04-27T00:00:00Z",
    source: "core",
    payload: minimalPayloadFor(type),
  } as EventEnvelope;
}

// Explicit mock fixture mode: one valid Section 9 envelope for every event type.
export const CONTRACT_EVENT_FIXTURES: EventEnvelope[] = EVENT_TYPES.map((type, i) => fixtureEnvelope(type, i + 1));
