import json

from nexussy.swarm.project_graph import build_or_load_project_graph, graph_cache_path, summarize_project_graph


def test_project_graph_contract_and_cache_metadata(tmp_path):
    (tmp_path / "SPEC.md").write_text("# Spec\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import json\nfrom pathlib import Path\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from src import app\n", encoding="utf-8")

    graph = build_or_load_project_graph(tmp_path)
    encoded = json.dumps(graph, sort_keys=True)
    assert "SPEC.md" in encoded
    assert graph["metadata"]["schema_version"] == 1
    assert graph["metadata"]["worktree_root"] == str(tmp_path.resolve())
    assert set(graph["metadata"]["file_hashes"]) == {"SPEC.md", "src/app.py", "tests/test_app.py"}
    assert any("found" in tag for node in graph["nodes"] for tag in node["tags"])
    assert any("inferred" in tag for node in graph["nodes"] for tag in node["tags"])
    assert graph_cache_path(tmp_path).exists()


def test_project_graph_cold_start_creates_missing_cache_directory(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import json\n", encoding="utf-8")
    cache = graph_cache_path(tmp_path)

    assert not cache.parent.exists()
    graph = build_or_load_project_graph(tmp_path)

    assert cache.exists()
    assert set(graph["metadata"]["file_hashes"]) == {"src/app.py"}


def test_project_graph_corrupted_cache_rebuilds_without_crashing(tmp_path):
    (tmp_path / "README.md").write_text("# Recover\n", encoding="utf-8")
    cache = graph_cache_path(tmp_path)
    cache.parent.mkdir(parents=True)
    cache.write_text("{not valid json", encoding="utf-8")

    graph = build_or_load_project_graph(tmp_path)

    assert graph["metadata"]["file_hashes"].keys() == {"README.md"}
    assert json.loads(cache.read_text(encoding="utf-8"))["metadata"]["schema_version"] == 1


def test_project_graph_empty_project_is_safe(tmp_path):
    graph = build_or_load_project_graph(tmp_path)
    summary = summarize_project_graph(graph)

    assert graph["metadata"]["file_hashes"] == {}
    assert graph["nodes"] == []
    assert "files=0" in summary


def test_project_graph_reuses_unchanged_files_and_handles_deletes(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import sys\n", encoding="utf-8")
    first = build_or_load_project_graph(tmp_path)
    a_hash = first["metadata"]["file_hashes"]["a.py"]

    calls = []
    import nexussy.swarm.project_graph as project_graph

    original = project_graph._process_file

    def tracking_process(root, rel):
        calls.append(rel)
        return original(root, rel)

    monkeypatch.setattr(project_graph, "_process_file", tracking_process)
    (tmp_path / "b.py").write_text("import json\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("import pathlib\n", encoding="utf-8")
    (tmp_path / "a.py").unlink()
    second = project_graph.build_or_load_project_graph(tmp_path)

    assert calls == ["b.py", "c.py"]
    assert "a.py" not in second["metadata"]["file_hashes"]
    assert second["metadata"]["file_hashes"].get("a.py") != a_hash


def test_project_graph_skips_binary_oversized_and_corrupt_cache(tmp_path):
    (tmp_path / "README.md").write_text("# Hi\n", encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"abc\x00def")
    (tmp_path / "large.txt").write_text("x" * (300 * 1024), encoding="utf-8")
    cache = graph_cache_path(tmp_path)
    cache.parent.mkdir(parents=True)
    cache.write_text("not json", encoding="utf-8")

    graph = build_or_load_project_graph(tmp_path)
    assert set(graph["metadata"]["file_hashes"]) == {"README.md"}
    skipped = {item["path"]: item["reason"] for item in graph["metadata"]["skipped"]}
    assert skipped["bin.dat"] == "binary"
    assert skipped["large.txt"] == "oversized"


def test_compressed_summary_is_bounded_tagged_and_reduces_large_project(tmp_path):
    raw_listing = []
    for idx in range(240):
        folder = tmp_path / "src" / f"feature_{idx}"
        folder.mkdir(parents=True)
        file_path = folder / f"module_{idx}.py"
        content = "import json\n" + "# implementation details\n" * 20
        file_path.write_text(content, encoding="utf-8")
        raw_listing.append(f"src/feature_{idx}/module_{idx}.py\n{content}")
    (tmp_path / "README.md").write_text("# Large\n", encoding="utf-8")
    graph = build_or_load_project_graph(tmp_path)
    summary = summarize_project_graph(graph)

    assert "[found]" in summary
    assert "[inferred]" in summary
    assert "Project structure" in summary
    assert len(summary) <= 6000
    assert len(summary) <= len("\n".join(raw_listing)) * 0.5
