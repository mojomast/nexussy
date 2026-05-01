from __future__ import annotations

import hashlib
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1
CACHE_RELATIVE_PATH = pathlib.Path(".nexussy") / "graph_cache" / "graph.json"
MAX_FILE_BYTES = 256 * 1024
SUMMARY_CHAR_LIMIT = 6000

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "target",
    "coverage",
}
IMPORTANT_NAMES = {"spec.md", "agents.md", "readme.md", "package.json", "pyproject.toml", "setup.py", "requirements.txt", "cargo.toml", "go.mod", "dockerfile"}
SOURCE_ROOTS = {"src", "lib", "app", "core", "server", "client", "web", "tui", "nexussy"}
TEST_ROOTS = {"test", "tests", "spec", "specs", "__tests__"}
ENTRYPOINT_NAMES = {"main.py", "app.py", "server.py", "index.js", "index.ts", "main.ts", "main.js", "cli.py"}


def graph_cache_path(root: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(root) / CACHE_RELATIVE_PATH


def build_or_load_project_graph(root: str | pathlib.Path) -> dict[str, Any]:
    """Build a deterministic, stdlib-only graph and reuse unchanged file nodes."""
    root_path = pathlib.Path(root).resolve()
    files = _discover_files(root_path)
    hashes = {rel: _sha256(root_path / rel) for rel in files}
    old = _load_cache(root_path)
    previous_files = _previous_file_nodes(old)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for rel in sorted(files):
        if old and old.get("metadata", {}).get("file_hashes", {}).get(rel) == hashes[rel] and rel in previous_files:
            entry = previous_files[rel]
            nodes.extend(entry.get("nodes", []))
            edges.extend(entry.get("edges", []))
            continue
        entry = _process_file(root_path, rel)
        nodes.extend(entry["nodes"])
        edges.extend(entry["edges"])

    nodes.extend(_directory_nodes(files))
    edges.extend(_directory_edges(files))
    graph = {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "worktree_root": str(root_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "file_hashes": {k: hashes[k] for k in sorted(hashes)},
            "skipped": _skipped_files(root_path),
        },
        "nodes": _dedupe_sorted(nodes, "id"),
        "edges": _dedupe_sorted(edges, "id"),
    }
    graph["communities"] = _communities(graph)
    _write_cache(root_path, graph)
    return graph


def summarize_project_graph(graph: dict[str, Any], *, max_chars: int = SUMMARY_CHAR_LIMIT) -> str:
    """Return a bounded prompt summary with explicit found/inferred confidence tags."""
    nodes = sorted(graph.get("nodes", []), key=lambda n: (n.get("priority", 99), n.get("id", "")))
    edges = sorted(graph.get("edges", []), key=lambda e: (e.get("priority", 99), e.get("id", "")))
    communities = sorted(graph.get("communities", []), key=lambda c: (c.get("priority", 99), c.get("id", "")))
    metadata = graph.get("metadata", {})
    lines = [
        "Project graph context (compressed; use as hints, not as raw source):",
        f"- Cache: schema={metadata.get('schema_version')} files={len(metadata.get('file_hashes', {}))} [found]",
    ]
    important = [n for n in nodes if n.get("type") == "file" and n.get("priority", 99) <= 20][:25]
    if important:
        lines.append("- Important files [found]: " + ", ".join(n["path"] for n in important))
    roots = [n for n in nodes if n.get("type") == "directory" and n.get("kind") in {"source_root", "test_root"}][:20]
    if roots:
        lines.append("- Project structure: " + "; ".join(f"{n['path']}={n['kind']} [inferred]" for n in roots))
    entrypoints = [n for n in nodes if n.get("kind") == "entrypoint"][:20]
    if entrypoints:
        lines.append("- Entry points [inferred]: " + ", ".join(n["path"] for n in entrypoints))
    imports = [e for e in edges if e.get("kind") in {"imports", "requires"}][:30]
    if imports:
        lines.append("- Relationships [found]: " + "; ".join(f"{e['source']} -> {e['target']}" for e in imports))
    if communities:
        lines.append("- Communities: " + "; ".join(f"{c['name']} ({c['tag']})" for c in communities[:15]))
    skipped = metadata.get("skipped") or []
    if skipped:
        lines.append(f"- Skipped files [found]: {len(skipped)} binary/oversized/ignored files omitted from prompt context")
    summary = "\n".join(lines) + "\n"
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 80].rstrip() + "\n- Summary truncated to bounded prompt budget [found]\n"


def graph_summary_for_worktree(root: str | pathlib.Path) -> str:
    try:
        return summarize_project_graph(build_or_load_project_graph(root))
    except Exception as exc:  # Defensive: RAG should never block interview startup.
        return f"Project graph context unavailable; proceeding with project description only. [inferred] reason={type(exc).__name__}\n"


def _discover_files(root: pathlib.Path) -> list[str]:
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS for part in rel_parts) or rel_parts[:2] == (".nexussy", "graph_cache"):
            continue
        if path.is_file() and not _skip_file(path):
            files.append(path.relative_to(root).as_posix())
    return files


def _skipped_files(root: pathlib.Path) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS for part in rel_parts) or rel_parts[:2] == (".nexussy", "graph_cache"):
            continue
        if path.is_file():
            reason = _skip_reason(path)
            if reason:
                skipped.append({"path": path.relative_to(root).as_posix(), "reason": reason})
    return skipped[:100]


def _skip_file(path: pathlib.Path) -> bool:
    return _skip_reason(path) is not None


def _skip_reason(path: pathlib.Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return "oversized"
        chunk = path.read_bytes()[:2048]
    except OSError:
        return "unreadable"
    if b"\x00" in chunk:
        return "binary"
    return None


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _process_file(root: pathlib.Path, rel: str) -> dict[str, list[dict[str, Any]]]:
    path = root / rel
    text = path.read_text(encoding="utf-8", errors="replace")
    name = pathlib.Path(rel).name.lower()
    kind = "important" if name in IMPORTANT_NAMES else "entrypoint" if name in ENTRYPOINT_NAMES else "file"
    priority = 5 if name in {"spec.md", "agents.md", "readme.md"} else 10 if kind != "file" else 50
    node = {"id": f"file:{rel}", "type": "file", "path": rel, "kind": kind, "priority": priority, "tags": ["found:file"]}
    edges: list[dict[str, Any]] = []
    for target in sorted(_imports(text, rel))[:20]:
        edges.append({"id": f"edge:{rel}:imports:{target}", "source": rel, "target": target, "kind": "imports", "priority": 15, "tags": ["found:relationship"]})
    return {"nodes": [node], "edges": edges}


def _imports(text: str, rel: str) -> set[str]:
    suffix = pathlib.Path(rel).suffix.lower()
    found: set[str] = set()
    if suffix == ".py":
        for match in re.finditer(r"(?m)^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", text):
            found.add((match.group(1) or match.group(2)).split(".")[0])
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for match in re.finditer(r"(?:from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))", text):
            found.add(match.group(1) or match.group(2))
    elif pathlib.Path(rel).name.lower() == "package.json":
        try:
            data = json.loads(text)
            for key in ("dependencies", "devDependencies"):
                if isinstance(data.get(key), dict):
                    found.update(data[key].keys())
        except json.JSONDecodeError:
            pass
    return {item for item in found if item and not item.startswith(".")}


def _directory_nodes(files: list[str]) -> list[dict[str, Any]]:
    seen = {pathlib.Path(rel).parts[0] for rel in files if len(pathlib.Path(rel).parts) > 1}
    nodes = []
    for name in sorted(seen):
        kind = "source_root" if name in SOURCE_ROOTS else "test_root" if name in TEST_ROOTS or name.startswith("test") else "directory"
        if kind != "directory":
            nodes.append({"id": f"dir:{name}", "type": "directory", "path": name, "kind": kind, "priority": 25, "tags": ["inferred:structure"]})
    return nodes


def _directory_edges(files: list[str]) -> list[dict[str, Any]]:
    edges = []
    for rel in sorted(files):
        parts = pathlib.Path(rel).parts
        if len(parts) > 1 and (parts[0] in SOURCE_ROOTS or parts[0] in TEST_ROOTS or parts[0].startswith("test")):
            edges.append({"id": f"edge:{parts[0]}:contains:{rel}", "source": parts[0], "target": rel, "kind": "contains", "priority": 40, "tags": ["inferred:structure"]})
    return edges


def _communities(graph: dict[str, Any]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for node in graph.get("nodes", []):
        if node.get("type") == "file":
            top = pathlib.Path(node["path"]).parts[0] if pathlib.Path(node["path"]).parts else "."
            counts[top] = counts.get(top, 0) + 1
    return [
        {"id": f"community:{name}", "name": name, "files": count, "tag": "inferred:community", "priority": 20 if name in SOURCE_ROOTS | TEST_ROOTS else 60}
        for name, count in sorted(counts.items())
    ]


def _load_cache(root: pathlib.Path) -> dict[str, Any] | None:
    try:
        data = json.loads(graph_cache_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    meta = data.get("metadata", {}) if isinstance(data, dict) else {}
    if meta.get("schema_version") != SCHEMA_VERSION or meta.get("worktree_root") != str(root):
        return None
    return data


def _previous_file_nodes(graph: dict[str, Any] | None) -> dict[str, dict[str, list[dict[str, Any]]]]:
    entries: dict[str, dict[str, list[dict[str, Any]]]] = {}
    if not graph:
        return entries
    for node in graph.get("nodes", []):
        if node.get("type") == "file" and node.get("path"):
            entries[node["path"]] = {"nodes": [node], "edges": []}
    for edge in graph.get("edges", []):
        source = edge.get("source")
        if source in entries:
            entries[source]["edges"].append(edge)
    return entries


def _write_cache(root: pathlib.Path, graph: dict[str, Any]) -> None:
    cache = graph_cache_path(root)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(graph, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(cache)


def _dedupe_sorted(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    unique = {str(item.get(key)): item for item in items if item.get(key)}
    return [unique[k] for k in sorted(unique)]
