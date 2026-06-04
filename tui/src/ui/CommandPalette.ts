export const COMMANDS = ["/help", "/onboarding", "/new", "/setup", "/setup-openrouter", "/resume", "/status", "/stages", "/pipeline", "/models", "/routing", "/profile", "/stage-chat", "/plan", "/artifacts", "/workers", "/worker", "/dashboard", "/chat", "/pause", "/resume-run", "/cancel", "/skip", "/inject", "/steer", "/secrets", "/doctor", "/quit"] as const;

export function commandSuggestions(prefix:string): string[] {
  return COMMANDS.filter(cmd => cmd.startsWith(prefix || "/"));
}
