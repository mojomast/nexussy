"""Pytest fixtures providing isolated temp-dir environments for all tests.

Every test that touches Engine, Database, or the Starlette app gets a
throwaway directory so tests never read from or write to ~/.nexussy/.
"""
import pathlib

import pytest

from nexussy.api import server as _server_module
from nexussy.config import load_config
from nexussy.db import Database
from nexussy.pipeline.engine import Engine


@pytest.fixture()
def tmp_home(tmp_path_factory: pytest.TempPathFactory):
    """A temporary home directory that replaces ~/.nexussy for the duration of a test."""
    return tmp_path_factory.mktemp("nexussy_home")


@pytest.fixture()
def isolated_config(tmp_home, monkeypatch):
    """Load a NexussyConfig that points entirely at tmp_home."""
    monkeypatch.setenv("NEXUSSY_HOME", str(tmp_home))
    monkeypatch.setenv("NEXUSSY_PROJECTS_DIR", str(tmp_home / "projects"))
    monkeypatch.setenv("NEXUSSY_DATABASE_PATH", str(tmp_home / "nexussy.db"))
    return load_config()


@pytest.fixture()
async def isolated_db(isolated_config):
    """An initialized Database in the temp directory."""
    db = Database(isolated_config.database.global_path)
    await db.init()
    return db


@pytest.fixture()
async def isolated_engine(isolated_db, isolated_config):
    """An Engine wired to the isolated database."""
    return Engine(isolated_db, isolated_config)


@pytest.fixture(autouse=True)
async def _reset_server_globals(isolated_config, isolated_db, isolated_engine, monkeypatch):
    """
    Reset server.py module-level globals before each test so tests
    don't share state or touch the real ~/.nexussy database.
    """
    monkeypatch.setattr(_server_module, "config", isolated_config)
    monkeypatch.setattr(_server_module, "db", isolated_db)
    monkeypatch.setattr(_server_module, "engine", isolated_engine)
    _server_module.app.middleware_stack = None
    yield
    monkeypatch.setattr(_server_module, "config", None)
    monkeypatch.setattr(_server_module, "db", None)
    monkeypatch.setattr(_server_module, "engine", None)
    _server_module.app.middleware_stack = None
