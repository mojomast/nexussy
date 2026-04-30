import { applyReconnect, parseEnvelope, parseSSEFrames, reconnectHeaders, type ReconnectState } from "./sse";
import type { ErrorResponse, EventEnvelope, PipelineStatusResponse, RunStartResponse, SecretSummary, StageName, WorkerRole } from "./types";

export type ClientMode = "live-core"|"mock-fixture";
export interface CoreClientOptions { baseUrl?: string; apiKey?: string; mode?: ClientMode; fetchImpl?: typeof fetch; }
export class CoreHttpError extends Error { constructor(public status:number, public response:ErrorResponse|undefined, message:string) { super(message); } }

export class CoreClient {
  public readonly mode: ClientMode;
  private readonly fetchImpl: typeof fetch;
  constructor(baseUrlOrOptions: string|CoreClientOptions = "http://127.0.0.1:7771", apiKey?: string) {
    const options = typeof baseUrlOrOptions === "string" ? { baseUrl:baseUrlOrOptions, apiKey, mode:"live-core" as const } : baseUrlOrOptions;
    this.baseUrl = options.baseUrl ?? "http://127.0.0.1:7771";
    this.apiKey = options.apiKey;
    this.mode = options.mode ?? "live-core";
    this.fetchImpl = options.fetchImpl ?? fetch;
  }
  public baseUrl: string;
  private apiKey?: string;
  private headers(extra: HeadersInit = {}): HeadersInit { return { "Content-Type":"application/json", ...(this.apiKey ? {"X-API-Key":this.apiKey} : {}), ...extra }; }
  private url(path:string, query?:Record<string,string|number|boolean|undefined|null>): string { const u=new URL(path,this.baseUrl); for(const [k,v] of Object.entries(query??{})) if(v!==undefined&&v!==null) u.searchParams.set(k,String(v)); return u.toString(); }
  private async json<T>(method:string,path:string,body?:unknown,query?:Record<string,string|number|boolean|undefined|null>): Promise<T> { const r=await this.fetchImpl(this.url(path,query),{method,headers:this.headers(),body:body===undefined?undefined:JSON.stringify(body)}); if(!r.ok) { let err:ErrorResponse|undefined; try { err = await r.json() as ErrorResponse; } catch {} throw new CoreHttpError(r.status, err, err?.message ?? `${method} ${path} failed ${r.status}`); } return await r.json() as T; }
  health(){ return this.json("GET","/health"); }
  createSession(body:unknown){ return this.json("POST","/sessions",body); }
  listSessions(limit=50,offset=0){ return this.json("GET","/sessions",undefined,{limit,offset}); }
  getSession(sessionId:string){ return this.json("GET",`/sessions/${encodeURIComponent(sessionId)}`); }
  deleteSession(sessionId:string,delete_files=false){ return this.json("DELETE",`/sessions/${encodeURIComponent(sessionId)}`,undefined,{delete_files}); }
  startPipeline(body:unknown){ return this.json<RunStartResponse>("POST","/pipeline/start",body); }
  mcpCall<T=unknown>(name:string, args:Record<string, unknown>){ return this.json<T>("POST","/mcp/call",{name, arguments:args}); }
  chat(body:{message:string;model?:string|null}){ return this.json<{ok:boolean;message:string;model:string;usage?:unknown}>("POST","/assistant/reply",body); }
  status(run_id:string){ return this.json<PipelineStatusResponse>("GET","/pipeline/status",undefined,{run_id}); }
  inject(body:{run_id:string;message:string;worker_id?:string|null;stage?:StageName|null}){ return this.json("POST","/pipeline/inject",body); }
  pause(run_id:string, reason="user"){ return this.json("POST","/pipeline/pause",{run_id,reason}); }
  resume(run_id:string){ return this.json("POST","/pipeline/resume",{run_id}); }
  skip(run_id:string, stage:StageName, reason:string){ return this.json("POST","/pipeline/skip",{run_id,stage,reason}); }
  cancel(run_id:string, reason:string){ return this.json("POST","/pipeline/cancel",{run_id,reason}); }
  artifacts(session_id:string, run_id?:string){ return this.json("GET","/pipeline/artifacts",undefined,{session_id,run_id}); }
  artifact(kind:string, session_id:string, phase_number?:number){ return this.json("GET",`/pipeline/artifacts/${kind}`,undefined,{session_id,phase_number}); }
  workers(run_id:string){ return this.json("GET","/swarm/workers",undefined,{run_id}); }
  worker(worker_id:string, run_id:string){ return this.json("GET",`/swarm/workers/${worker_id}`,undefined,{run_id}); }
  spawn(body:{run_id:string;role:WorkerRole;task:string;phase_number?:number|null;model?:string}){ return this.json("POST","/swarm/spawn",body); }
  assign(body:{run_id:string;worker_id:string;task_id?:string;task:string;phase_number?:number|null}){ return this.json("POST","/swarm/assign",body); }
  injectWorker(worker_id:string, body:{run_id:string;worker_id:string;message:string}){ return this.json("POST",`/swarm/workers/${worker_id}/inject`,body); }
  stopWorker(worker_id:string, run_id:string, reason:string){ return this.json("POST",`/swarm/workers/${worker_id}/stop`,{run_id,reason}); }
  fileLocks(run_id:string){ return this.json("GET","/swarm/file-locks",undefined,{run_id}); }
  config(){ return this.json("GET","/config"); }
  updateConfig(body:unknown){ return this.json("PUT","/config",body); }
  secrets(){ return this.json<SecretSummary[]>("GET","/secrets"); }
  setSecret(name:string,value:string){ return this.json<SecretSummary>("PUT",`/secrets/${encodeURIComponent(name)}`,{value}); }
  deleteSecret(name:string){ return this.json("DELETE",`/secrets/${encodeURIComponent(name)}`); }
  memory(session_id?:string){ return this.json("GET","/memory",undefined,{session_id}); }
  createMemory(body:unknown){ return this.json("POST","/memory",body); }
  deleteMemory(memory_id:string){ return this.json("DELETE",`/memory/${memory_id}`); }
  graph(session_id?:string, run_id?:string){ return this.json("GET","/graph",undefined,{session_id,run_id}); }
  events(run_id:string, after_sequence=0, limit=500){ return this.json<EventEnvelope[]>("GET","/events",undefined,{run_id,after_sequence,limit}); }
  async *streamRun(runId:string, state:ReconnectState={retryMs:3000,attempts:0}): AsyncGenerator<EventEnvelope> { yield* this.stream(`/pipeline/runs/${runId}/stream`, state); }
  async *streamWorker(workerId:string, runId:string, state:ReconnectState={retryMs:3000,attempts:0}): AsyncGenerator<EventEnvelope> { yield* this.stream(`/swarm/workers/${workerId}/stream?run_id=${encodeURIComponent(runId)}`, state); }
  private async *stream(path:string,state:ReconnectState): AsyncGenerator<EventEnvelope> {
    let reconnect = state;
    while (true) {
      const r=await this.fetchImpl(this.url(path),{headers:this.headers(reconnectHeaders(reconnect))});
      if(!r.ok||!r.body) throw new CoreHttpError(r.status, undefined, r.status === 401 ? "unauthorized" : `SSE failed ${r.status}`);
      const retryHeader = Number(r.headers.get("retry") ?? reconnect.retryMs);
      let sawDone = false;
      if ((r.body as ReadableStream<Uint8Array>).getReader) {
        const reader=(r.body as ReadableStream<Uint8Array>).getReader();
        const decoder=new TextDecoder();
        let buffer="";
        while (true) {
          const {done,value}=await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream:true });
          const split = buffer.split(/\n\n+/);
          buffer = split.pop() ?? "";
          for (const raw of split) {
            for (const frame of parseSSEFrames(raw + "\n\n")) {
              const env=parseEnvelope(frame); reconnect=applyReconnect(reconnect, env, frame.retry ?? retryHeader); yield env; if(env.type==="done") sawDone=true;
            }
          }
        }
        buffer += decoder.decode();
        for (const frame of parseSSEFrames(buffer)) { const env=parseEnvelope(frame); reconnect=applyReconnect(reconnect, env, frame.retry ?? retryHeader); yield env; if(env.type==="done") sawDone=true; }
      } else {
        const text=await r.text();
        for(const f of parseSSEFrames(text)) { const env=parseEnvelope(f); reconnect=applyReconnect(reconnect, env, f.retry ?? retryHeader); yield env; if(env.type==="done") sawDone=true; }
      }
      if (sawDone) return;
      reconnect = { ...reconnect, attempts: reconnect.attempts + 1 };
      await new Promise(resolve => setTimeout(resolve, reconnect.retryMs));
    }
  }
}

export class FixtureCoreClient extends CoreClient {
  public readonly eventsFixture: EventEnvelope[];
  constructor(eventsFixture: EventEnvelope[]) { super({ baseUrl:"mock://fixture", mode:"mock-fixture" }); this.eventsFixture = eventsFixture; }
  override async *streamRun(_runId:string, state:ReconnectState={retryMs:3000,attempts:0}): AsyncGenerator<EventEnvelope> {
    const start = state.lastEventId ? this.eventsFixture.findIndex(e => e.event_id === state.lastEventId) + 1 : 0;
    for (const env of this.eventsFixture.slice(Math.max(0,start))) yield env;
  }
  override chat(body:{message:string;model?:string|null}){ return Promise.resolve({ ok:true, message:`mock assistant reply: ${body.message}`, model:body.model ?? "mock/model" }); }
}
