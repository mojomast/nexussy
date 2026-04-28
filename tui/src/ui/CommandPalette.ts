export const COMMANDS = ["/help", "/onboarding", "/new", "/resume", "/status", "/stages", "/plan", "/artifacts", "/workers", "/worker", "/dashboard", "/chat", "/pause", "/resume-run", "/skip", "/inject", "/secrets", "/doctor", "/quit"] as const;

export function commandSuggestions(prefix:string): string[] {
  return COMMANDS.filter(cmd => cmd.startsWith(prefix || "/"));
}
