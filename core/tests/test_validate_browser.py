import pytest
from pydantic import ValidationError

from nexussy.api.schemas import NexussyConfig, ValidateBrowserStageConfig
from nexussy.config import load_config


def test_validate_browser_config_defaults_disabled(monkeypatch):
    for key in (
        "NEXUSSY_VALIDATE_BROWSER_ENABLED",
        "NEXUSSY_VALIDATE_BROWSER_COMMAND",
        "NEXUSSY_VALIDATE_BROWSER_TARGET_URL",
        "NEXUSSY_VALIDATE_BROWSER_TIMEOUT_S",
        "NEXUSSY_VALIDATE_BROWSER_FAILURE_POLICY",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = load_config()

    assert cfg.stages.validate_browser.enabled is False
    assert cfg.stages.validate_browser.command is None
    assert cfg.stages.validate_browser.target_url is None
    assert cfg.stages.validate_browser.timeout_s == 60
    assert cfg.stages.validate_browser.failure_policy == "skip"


def test_validate_browser_config_accepts_safe_values():
    cfg = NexussyConfig.model_validate(
        {
            "stages": {
                "validate_browser": {
                    "enabled": True,
                    "command": "browser-harness",
                    "target_url": "http://127.0.0.1:7772/",
                    "timeout_s": 30,
                    "failure_policy": "fail",
                }
            }
        }
    )

    assert cfg.stages.validate_browser.enabled is True
    assert cfg.stages.validate_browser.command == "browser-harness"
    assert cfg.stages.validate_browser.target_url == "http://127.0.0.1:7772/"
    assert cfg.stages.validate_browser.timeout_s == 30
    assert cfg.stages.validate_browser.failure_policy == "fail"


def test_validate_browser_config_rejects_extra_and_unsafe_values():
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"enabled": False, "unexpected": True})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"command": "   "})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"target_url": ""})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"timeout_s": 0})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"timeout_s": 601})
    with pytest.raises(ValidationError):
        ValidateBrowserStageConfig.model_validate({"failure_policy": "warn"})


def test_validate_browser_config_env_overrides(monkeypatch):
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_ENABLED", "true")
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_COMMAND", "browser-harness")
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_TARGET_URL", "http://127.0.0.1:7772/")
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_TIMEOUT_S", "45")
    monkeypatch.setenv("NEXUSSY_VALIDATE_BROWSER_FAILURE_POLICY", "fail")

    cfg = load_config()

    assert cfg.stages.validate_browser.enabled is True
    assert cfg.stages.validate_browser.command == "browser-harness"
    assert cfg.stages.validate_browser.target_url == "http://127.0.0.1:7772/"
    assert cfg.stages.validate_browser.timeout_s == 45
    assert cfg.stages.validate_browser.failure_policy == "fail"
