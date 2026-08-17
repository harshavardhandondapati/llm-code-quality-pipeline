"""Environment-based configuration for the pipeline."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from llm_pipeline.schemas import ModelProvider
from llm_pipeline.runtime_tools import bugsinpy_bin_directory, defects4j_bin_directory


class Settings(BaseSettings):
    """Validated application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="PIPELINE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    model_provider: ModelProvider = ModelProvider.MOCK
    model_name: str = Field(default="mock-model", min_length=1)
    api_key: SecretStr | None = None

    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    model_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    model_max_output_tokens: int = Field(default=4096, ge=256, le=32768)
    model_request_timeout_seconds: int = Field(default=120, ge=10, le=600)

    workspace_root: Path = Path("workspaces")
    results_directory: Path = Path("results")
    log_directory: Path = Path("logs")
    bugsinpy_executable_directory: Path | None = None
    defects4j_executable_directory: Path | None = None

    test_timeout_seconds: int = Field(default=300, ge=1, le=86_400)
    max_source_characters: int = Field(default=50_000, ge=1_000)
    max_context_files: int = Field(default=5, ge=1, le=50)
    context_lines_before: int = Field(default=20, ge=0, le=500)
    context_lines_after: int = Field(default=20, ge=0, le=500)
    max_failure_output_characters: int = Field(default=12_000, ge=500)
    context_use_benchmark_hints: bool = False
    human_approval_required: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator(
        "workspace_root",
        "results_directory",
        "log_directory",
        "bugsinpy_executable_directory",
        "defects4j_executable_directory",
        mode="before",
    )
    @classmethod
    def expand_paths(cls, value: str | Path | None) -> Path | None:
        """Expand `~` while preserving relative paths."""
        if value is None or value == "":
            return None
        return Path(value).expanduser()

    def ensure_runtime_directories(self) -> None:
        """Create runtime directories when they do not already exist."""
        for directory in (
            self.workspace_root,
            self.results_directory,
            self.log_directory,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one cached settings instance for the application process.

    When executable directories are not provided explicitly, the pipeline looks
    for benchmark tools in the project-local tools folder first and then in the
    Docker/cloud tools folder. This keeps local and deployed runs consistent.
    """
    settings = Settings()
    if settings.bugsinpy_executable_directory is None:
        settings.bugsinpy_executable_directory = bugsinpy_bin_directory()
    if settings.defects4j_executable_directory is None:
        settings.defects4j_executable_directory = defects4j_bin_directory()
    return settings
