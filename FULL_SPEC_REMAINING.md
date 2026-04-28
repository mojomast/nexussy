# Full Spec Remaining Checklist

`SPEC_COVERAGE.md` currently has no `missing`, `partial`, or `implemented-untested` rows.

## Blocked External Rows

- R-073: Live provider call requires real provider credentials. Production provider path is implemented and tested with deterministic fake provider; missing-provider gate is tested.
- R-074: Live Pi CLI execution requires installed Pi CLI. Production subprocess path is implemented and tested with fake Pi.
- R-079: Live Pi subprocess path with real Pi requires installed Pi CLI. Fake Pi exercises the same subprocess adapter.
- R-081: `shellcheck` is unavailable. Shell syntax and user-space ops tests pass.
