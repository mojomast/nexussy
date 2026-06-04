import type { ModelOption, RoutingProfileName, RoutingTable, SecretSummary, StageName, StageRouting } from "../types";

export const routingProfiles: RoutingProfileName[] = ["default", "fast", "cheap", "strict"];

export const providerModelCatalog: Array<{provider:string; secretName:string; models:string[]; agents:string[]}> = [
  { provider:"agentrouter", secretName:"AGENTROUTER_API_KEY", models:["openai/deepseek-v4-flash", "openai/gpt-5.4", "anthropic/claude-sonnet-4"], agents:["orchestrator", "worker"] },
  { provider:"openrouter", secretName:"OPENROUTER_API_KEY", models:["openrouter/openai/gpt-4o-mini", "openrouter/anthropic/claude-sonnet-4", "openrouter/google/gemini-2.5-pro"], agents:["orchestrator"] },
  { provider:"openai", secretName:"OPENAI_API_KEY", models:["openai/gpt-5.5-fast", "openai/gpt-4o-mini"], agents:["orchestrator", "worker"] },
  { provider:"anthropic", secretName:"ANTHROPIC_API_KEY", models:["anthropic/claude-sonnet-4", "anthropic/claude-3-5-haiku-latest"], agents:["orchestrator", "worker"] },
];

export function discoverModelOptions(secrets:SecretSummary[]): ModelOption[] {
  const configured = new Set(secrets.filter(secret => secret.configured).map(secret => secret.name));
  return providerModelCatalog.flatMap(provider => {
    const ready = configured.has(provider.secretName) || (provider.provider === "agentrouter" && configured.has("AGENT_ROUTER_TOKEN"));
    return provider.models.map(model => ({
      provider:provider.provider,
      model,
      label:`${provider.provider}/${model.replace(/^[^/]+\//, "")}`,
      configured:ready,
      disabledReason:ready ? undefined : `${provider.secretName} is not configured`,
      agent:provider.agents.join(","),
    }));
  });
}

export function defaultRoutingForStages(stages:StageName[], options:ModelOption[], profile:RoutingProfileName="default"): RoutingTable {
  const available = options.filter(option => option.configured);
  const primary = available[0] ?? options[0];
  const fallback = available[1] ?? options.find(option => option.provider !== primary?.provider && option.configured);
  return Object.fromEntries(stages.map(stage => [stage, stageRouting(stage, primary, fallback, profile)])) as RoutingTable;
}

export function stageRouting(stage:StageName, primary:ModelOption|undefined, fallback:ModelOption|undefined, profile:RoutingProfileName): StageRouting {
  return {
    stage,
    primary,
    fallback,
    profile,
    workerGroup:stage === "develop" ? "swarm" : "orchestrator",
    notes:primary?.configured === false ? primary.disabledReason : undefined,
  };
}

export function setStageRoutingModel(table:RoutingTable, stage:StageName, option:ModelOption, slot:"primary"|"fallback"): RoutingTable {
  const current = table[stage];
  return { ...table, [stage]:{ ...current, stage, [slot]:option, explicit:true, notes:option.configured ? current?.notes : option.disabledReason } };
}

export function findModelOption(options:ModelOption[], value:string): ModelOption|undefined {
  const needle = value.trim().toLowerCase();
  return options.find(option => option.model.toLowerCase() === needle || `${option.provider}/${option.model}`.toLowerCase() === needle || option.label.toLowerCase() === needle);
}

export function switchRoutingProfile(table:RoutingTable, profile:RoutingProfileName): RoutingTable {
  return Object.fromEntries(Object.entries(table).map(([stage, route]) => [stage, { ...route, profile }])) as RoutingTable;
}

export function modelLabel(option:ModelOption|undefined): string {
  if (!option) return "unassigned";
  const suffix = option.configured ? "" : " (disabled)";
  return `${option.provider}:${option.model.replace(/^[^/]+\//, "")}${suffix}`;
}
