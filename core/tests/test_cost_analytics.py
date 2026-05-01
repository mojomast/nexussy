import json

import pytest

from nexussy.cli import costs
from nexussy.db import Database


async def _seed_run(db: Database, *, run_id="run-1", usage=True, events=True):
    await db.init()
    await db.write(
        lambda con: con.execute(
            "INSERT INTO runs(run_id, session_id, status, current_stage, started_at, finished_at, usage_json) VALUES(?,?,?,?,?,?,?)",
            (
                run_id,
                "session-1",
                "passed",
                "review",
                "2026-05-01T00:00:00+00:00",
                "2026-05-01T00:03:00+00:00",
                json.dumps({"input_tokens": 7, "output_tokens": 5, "cost_usd": 0.12, "provider": "mock", "model": "m1"}) if usage else None,
            ),
        )
    )
    for stage, started, finished in (
        ("interview", "2026-05-01T00:00:00+00:00", "2026-05-01T00:01:00+00:00"),
        ("design", "2026-05-01T00:01:00+00:00", "2026-05-01T00:02:00+00:00"),
        ("review", "2026-05-01T00:02:00+00:00", "2026-05-01T00:03:00+00:00"),
    ):
        await db.write(
            lambda con, s=stage, a=started, b=finished: con.execute(
                "INSERT INTO stage_runs(run_id, stage, status, attempt, started_at, finished_at, error_json) VALUES(?,?,?,?,?,?,?)",
                (run_id, s, "passed", 1, a, b, None),
            )
        )
    if events:
        for seq, stage, created, payload in (
            (1, "interview", "2026-05-01T00:00:10+00:00", {"input_tokens": 2, "output_tokens": 3, "cost_usd": 0.05, "provider": "openrouter", "model": "a"}),
            (2, "design", "2026-05-01T00:01:10+00:00", {"input_tokens": 4, "output_tokens": 1, "cost_usd": 0.07, "provider": "openrouter", "model": "b"}),
        ):
            envelope = {"type": "cost_update", "run_id": run_id, "payload": payload}
            await db.write(
                lambda con, n=seq, p=envelope, c=created: con.execute(
                    "INSERT INTO events(event_id, run_id, sequence, type, payload_json, created_at) VALUES(?,?,?,?,?,?)",
                    (f"evt-{run_id}-{n}", run_id, n, "cost_update", json.dumps(p), c),
                )
            )


@pytest.mark.asyncio
async def test_cost_analytics_groups_usage_events_by_stage(tmp_path):
    db = Database(str(tmp_path / "state.db"))
    await _seed_run(db)
    data = await db.cost_analytics("run-1")
    stages = {row["stage"]: row for row in data["runs"][0]["stages"]}
    assert stages["interview"]["total_tokens"] == 5
    assert stages["design"]["cost_usd"] == 0.07
    assert stages["review"]["total_tokens"] == 0
    assert data["runs"][0]["run_total"]["total_tokens"] == 12
    db.close()


@pytest.mark.asyncio
async def test_cost_analytics_no_events_keeps_zero_stages_with_run_total(tmp_path):
    db = Database(str(tmp_path / "state.db"))
    await _seed_run(db, events=False)
    data = await db.cost_analytics("run-1")
    assert all(stage["total_tokens"] == 0 for stage in data["runs"][0]["stages"])
    assert data["runs"][0]["run_total"]["cost_usd"] == 0.12
    db.close()


@pytest.mark.asyncio
async def test_cost_analytics_validates_single_run_and_aggregates(tmp_path):
    db = Database(str(tmp_path / "state.db"))
    await _seed_run(db, run_id="run-1")
    await _seed_run(db, run_id="run-2", events=False)
    with pytest.raises(ValueError, match="run not found"):
        await db.cost_analytics("missing")
    data = await db.cost_analytics(all_runs=True)
    assert [run["run_id"] for run in data["runs"]] == ["run-1", "run-2"]
    assert data["totals"]["total_tokens"] == 24
    db.close()


def test_cost_cli_json_and_argument_validation(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "state.db"
    db = Database(str(db_path))
    import asyncio

    asyncio.run(_seed_run(db))
    db.close()
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(db_path))
    rc = costs.main(["run-1", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["runs"][0]["run_id"] == "run-1"
    assert costs.main(["run-1", "--all"]) == 2
