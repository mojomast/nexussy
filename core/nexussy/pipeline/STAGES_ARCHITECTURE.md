# Pipeline Stages Architecture

`engine.py` owns orchestration, events, run/session DB writes, retry loops, provider calls, checkpoints, interview state, and worker/tool persistence.

`helpers.py` owns pure parsing, text shaping, path validation, complexity scoring, and provider startup exceptions.

`stages/*.py` own stage prompt construction, artifact shaping, and stage-specific parse decisions.

The develop stage owns worker orchestration, worker RPC execution, worktree creation, merge sequencing, and develop/merge/changed-file artifacts.

Stages receive `engine` as a service object and call existing engine methods such as `_provider_text()`, `_save_art()`, `emit()`, and `db`.

To add a stage, create `stages/{name}.py`, implement `async def run(engine, req, detail, rid, cp, root, selected_models, allow_mock, **kwargs)`, then register it in `Engine._STAGE_HANDLERS`.
