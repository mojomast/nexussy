export function renderOnboarding(): string[] {
  return [
    "Welcome to nexussy. Plain chat stays in Ask mode and will not run the pipeline.",
    "",
    "What it can do:",
    "  ● Interview  clarify requirements and complexity",
    "  ● Design     draft architecture, dependencies, risks, test strategy",
    "  ● Validate   check the design and request corrections",
    "  ● Plan       write devplan, handoff, and phase files",
    "  ● Review     review the plan before implementation",
    "  ● Develop    spawn workers, use worktrees, merge changes, report results",
    "",
    "Start deliberately with a slash command:",
    "  /new Create a FastAPI todo app with SQLite and tests",
    "",
    "Useful commands:",
    "  /new <description>   start a pipeline run",
    "  /status              show compact run status",
    "  /plan                show planning artifacts",
    "  /workers             inspect worker activity",
    "  /dashboard           open the monitoring dashboard",
    "  /help                show all commands",
  ];
}
