"""Factory helpers for selecting a benchmark dataset adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_pipeline.datasets.base import DatasetAdapter
from llm_pipeline.datasets.bugsinpy import BugsInPyAdapter
from llm_pipeline.datasets.defects4j import Defects4JAdapter
from llm_pipeline.utils.command_runner import CommandRunner


SUPPORTED_DATASETS = ("bugsinpy", "defects4j")


def normalise_dataset_name(dataset: str) -> str:
    """Return a stable dataset identifier accepted by the CLI."""
    normalised = dataset.strip().lower().replace("_", "-")
    aliases = {
        "bugs-in-py": "bugsinpy",
        "bugsinpy": "bugsinpy",
        "defects-4j": "defects4j",
        "defects4j": "defects4j",
    }
    try:
        return aliases[normalised]
    except KeyError as error:
        raise ValueError(
            f"Unsupported dataset: {dataset}. Supported datasets are: {', '.join(SUPPORTED_DATASETS)}."
        ) from error


def create_dataset_adapter(
    dataset: str,
    command_runner: CommandRunner,
    settings: Any,
) -> DatasetAdapter:
    """Create the adapter used by the selected dataset/language."""
    selected = normalise_dataset_name(dataset)
    if selected == "bugsinpy":
        return BugsInPyAdapter(
            command_runner,
            executable_directory=settings.bugsinpy_executable_directory,
            timeout_seconds=settings.test_timeout_seconds,
        )
    if selected == "defects4j":
        return Defects4JAdapter(
            command_runner,
            executable_directory=settings.defects4j_executable_directory,
            timeout_seconds=settings.test_timeout_seconds,
        )
    raise AssertionError(f"Unhandled dataset: {selected}")


def candidate_report_file_name(dataset: str) -> str:
    """Return the candidate report name while preserving the existing Python report name."""
    selected = normalise_dataset_name(dataset)
    if selected == "bugsinpy":
        return "bugsinpy_candidate_selection.json"
    return f"{selected}_candidate_selection.json"


def adapter_source_extensions(adapter: DatasetAdapter) -> tuple[str, ...]:
    """Return source extensions used by the selected adapter."""
    value = getattr(adapter, "source_file_extensions", (".py",))
    return tuple(str(item) for item in value)


def adapter_source_file_names(adapter: DatasetAdapter) -> tuple[str, ...]:
    """Return exact build/config file names used by the selected adapter."""
    value = getattr(adapter, "source_file_names", ())
    return tuple(str(item) for item in value)
