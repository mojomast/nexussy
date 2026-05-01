from __future__ import annotations

import argparse
import asyncio
import json
import sys

from nexussy.config import load_config
from nexussy.db import Database


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze nexussy token and cost usage by run and stage.")
    parser.add_argument("run_id", nargs="?", help="Run id to analyze. Defaults to the latest run.")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit deterministic JSON output.")
    parser.add_argument("--all", action="store_true", help="Analyze every run in the configured database.")
    return parser


def _fmt_int(value: int | float) -> str:
    return str(int(value or 0))


def _fmt_cost(value: int | float) -> str:
    return f"{float(value or 0):.6f}"


def _human(data: dict) -> str:
    rows = []
    for run in data["runs"]:
        for stage in run["stages"]:
            rows.append(
                [
                    run["run_id"],
                    stage["stage"],
                    _fmt_int(stage["input_tokens"]),
                    _fmt_int(stage["output_tokens"]),
                    _fmt_int(stage["cache_read_tokens"]),
                    _fmt_int(stage["cache_write_tokens"]),
                    _fmt_int(stage["total_tokens"]),
                    _fmt_cost(stage["cost_usd"]),
                    stage.get("provider") or "-",
                    stage.get("model") or "-",
                ]
            )
        total = run["run_total"]
        rows.append(
            [
                run["run_id"],
                "TOTAL",
                _fmt_int(total["input_tokens"]),
                _fmt_int(total["output_tokens"]),
                _fmt_int(total["cache_read_tokens"]),
                _fmt_int(total["cache_write_tokens"]),
                _fmt_int(total["total_tokens"]),
                _fmt_cost(total["cost_usd"]),
                total.get("provider") or "-",
                total.get("model") or "-",
            ]
        )
    headers = ["run", "stage", "input", "output", "cache_read", "cache_write", "tokens", "cost_usd", "provider", "model"]
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    lines = ["  ".join(h.ljust(widths[idx]) for idx, h in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend("  ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row)) for row in rows)
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    if args.run_id and args.all:
        print("error: run_id cannot be combined with --all", file=sys.stderr)
        return 2
    config = load_config()
    db = Database(config.database.global_path, config.database.busy_timeout_ms, config.database.write_retry_count, config.database.write_retry_base_ms)
    try:
        data = await db.cost_analytics(args.run_id, all_runs=args.all)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()
    if args.json_output:
        print(json.dumps(data, sort_keys=True, separators=(",", ":")))
    else:
        print(_human(data))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
