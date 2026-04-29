# nexussy Operations

This guide is for operator-owned local workstations and small trusted teams on a LAN or private VPN. nexussy is not designed as a SaaS or internet-exposed multi-tenant service.

## State Files

Global state lives under `~/.nexussy/` by default:

| Path | Purpose |
|---|---|
| `~/.nexussy/state.db` | Global SQLite state |
| `~/.nexussy/.env` | Local env-file secrets fallback and runtime overrides |
| `~/.nexussy/nexussy.yaml` | Operator config |
| `~/.nexussy/audit.log` | Append-only local audit log |
| `~/nexussy-projects/<slug>/.nexussy/state.db` | Per-project SQLite state |

Project artifacts and source worktrees live under `~/nexussy-projects/` unless `projects_dir` is changed.

## Snapshot Backup

Preferred online SQLite snapshot:

```bash
sqlite3 ~/.nexussy/state.db "VACUUM INTO '$HOME/.nexussy/backups/state-$(date -u +%Y%m%dT%H%M%SZ).db'"
```

Create the backup directory first if needed:

```bash
mkdir -p ~/.nexussy/backups
```

For the simplest full local snapshot, stop nexussy first and copy the home and project directories:

```bash
./nexussy.sh stop
mkdir -p ~/.nexussy/backups
cp -a ~/.nexussy ~/.nexussy/backups/home-$(date -u +%Y%m%dT%H%M%SZ)
cp -a ~/nexussy-projects ~/.nexussy/backups/projects-$(date -u +%Y%m%dT%H%M%SZ)
```

If you use per-project state heavily, snapshot each project DB too:

```bash
sqlite3 ~/nexussy-projects/<project_slug>/.nexussy/state.db "VACUUM INTO '$HOME/.nexussy/backups/<project_slug>-state.db'"
```

## Restore

Stop services before replacing state:

```bash
./nexussy.sh stop
cp ~/.nexussy/backups/state-YYYYMMDDTHHMMSSZ.db ~/.nexussy/state.db
```

Restore project directories from a filesystem snapshot when project worktrees or artifacts are needed:

```bash
rm -rf ~/nexussy-projects
cp -a ~/.nexussy/backups/projects-YYYYMMDDTHHMMSSZ ~/nexussy-projects
```

Start nexussy after restore:

```bash
./nexussy.sh start
./nexussy.sh status
```

## Schema Versions

The current SQLite schema version constant lives in `core/nexussy/db.py` as `CURRENT_SCHEMA_VERSION`.

Migrations are applied by the database initialization path. A migration should be:

- Sequential: bump `CURRENT_SCHEMA_VERSION` by one.
- Idempotent: safe to run if part of the schema already exists.
- Bounded: executed inside the existing SQLite write discipline.
- Tested: add a core test that initializes an older schema shape and verifies startup upgrades it.

Before changing schema code, snapshot `~/.nexussy/state.db` and any project DBs you care about.

## Backup Frequency

Recommended defaults:

| Context | Frequency |
|---|---|
| Solo local workstation | Daily while actively using nexussy; before upgrades or schema changes |
| Trusted LAN/VPN team | At least daily, plus before upgrades, config/profile changes, or large live provider/Pi runs |

Keep at least a few recent snapshots. If provider runs are expensive or project artifacts are important, back up both `~/.nexussy/` and `~/nexussy-projects/`.

## Audit Log

View local audit entries with:

```bash
./nexussy.sh logs --audit
```

The audit log is plain text and local-only. It records operator-relevant actions without secret values.
