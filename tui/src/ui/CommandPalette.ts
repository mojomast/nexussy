export const COMMANDS = ["/help", "/onboarding", "/new", "/interview-answer", "/setup", "/setup-openrouter", "/resume", "/status", "/stages", "/pipeline", "/models", "/routing", "/model", "/fallback", "/profile", "/stage-chat", "/plan", "/artifacts", "/workers", "/worker", "/dashboard", "/chat", "/pause", "/resume-run", "/cancel", "/skip", "/inject", "/compact", "/steer", "/memory", "/graph", "/config", "/events", "/secrets", "/doctor", "/quit"] as const;

export function commandSuggestions(prefix:string): string[] {
  return COMMANDS.filter(cmd => cmd.startsWith(prefix || "/"));
}
