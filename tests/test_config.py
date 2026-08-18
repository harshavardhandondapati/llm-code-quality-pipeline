from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_pipeline.config import Settings
from llm_pipeline.schemas import ModelProvider


def test_settings_defaults_are_valid() -> None:
    settings = Settings(_env_file=None)

    assert settings.model_provider is ModelProvider.MOCK
    assert settings.model_name == "mock-model"
    assert settings.test_timeout_seconds == 1200
    assert settings.human_approval_required is True


def test_settings_load_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PIPELINE_MODEL_PROVIDER", "open_model")
    monkeypatch.setenv("PIPELINE_MODEL_NAME", "local-test-model")
    monkeypatch.setenv("PIPELINE_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("PIPELINE_TEST_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("PIPELINE_HUMAN_APPROVAL_REQUIRED", "false")

    settings = Settings(_env_file=None)

    assert settings.model_provider is ModelProvider.OPEN_MODEL
    assert settings.model_name == "local-test-model"
    assert settings.workspace_root == tmp_path / "workspace"
    assert settings.test_timeout_seconds == 120
    assert settings.human_approval_required is False


def test_settings_reject_invalid_timeout() -> None:
    with pytest.raises(ValidationError):
        Settings(test_timeout_seconds=0, _env_file=None)


def test_ensure_runtime_directories_creates_directories(tmp_path: Path) -> None:
    settings = Settings(
        workspace_root=tmp_path / "workspaces",
        results_directory=tmp_path / "results",
        log_directory=tmp_path / "logs",
        _env_file=None,
    )

    settings.ensure_runtime_directories()

    assert settings.workspace_root.is_dir()
    assert settings.results_directory.is_dir()
    assert settings.log_directory.is_dir()


def test_settings_accept_bugsinpy_executable_directory(tmp_path: Path) -> None:
    executable_directory = tmp_path / "BugsInPy" / "framework" / "bin"

    settings = Settings(
        bugsinpy_executable_directory=executable_directory,
        _env_file=None,
    )

    assert settings.bugsinpy_executable_directory == executable_directory


def test_settings_load_source_context_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_MAX_CONTEXT_FILES", "7")
    monkeypatch.setenv("PIPELINE_CONTEXT_LINES_BEFORE", "12")
    monkeypatch.setenv("PIPELINE_CONTEXT_LINES_AFTER", "18")
    monkeypatch.setenv("PIPELINE_MAX_FAILURE_OUTPUT_CHARACTERS", "8000")
    monkeypatch.setenv("PIPELINE_CONTEXT_USE_BENCHMARK_HINTS", "true")

    settings = Settings(_env_file=None)

    assert settings.max_context_files == 7
    assert settings.context_lines_before == 12
    assert settings.context_lines_after == 18
    assert settings.max_failure_output_characters == 8000
    assert settings.context_use_benchmark_hints is True


def test_settings_reject_zero_context_files() -> None:
    with pytest.raises(ValidationError):
        Settings(max_context_files=0, _env_file=None)


def test_settings_accept_openrouter_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("PIPELINE_MODEL_NAME", "openrouter/free")
    monkeypatch.setenv("PIPELINE_OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PIPELINE_MODEL_TEMPERATURE", "0")
    monkeypatch.setenv("PIPELINE_MODEL_MAX_OUTPUT_TOKENS", "2048")

    settings = Settings(_env_file=None)

    assert settings.model_provider is ModelProvider.OPENROUTER
    assert settings.model_name == "openrouter/free"
    assert settings.openrouter_api_key is not None
    assert settings.openrouter_api_key.get_secret_value() == "test-key"
    assert settings.model_max_output_tokens == 2048
