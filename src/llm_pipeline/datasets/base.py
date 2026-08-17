"""Common interface for benchmark datasets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from llm_pipeline.schemas import (
    BaselineReproductionResult,
    BugVersion,
    CommandResult,
    DatasetCheckoutResult,
)
from llm_pipeline.workspace.manager import WorkspacePaths


class DatasetAdapter(ABC):
    """Describe the small set of operations the pipeline needs from a dataset."""

    @abstractmethod
    def validate_environment(self, working_directory: Path | str) -> CommandResult:
        """Check that the dataset command-line tools can be started."""

    @abstractmethod
    def checkout_bug(
        self,
        project: str,
        bug_id: str,
        workspace: WorkspacePaths,
        *,
        version: BugVersion = BugVersion.BUGGY,
    ) -> DatasetCheckoutResult:
        """Check out one benchmark bug into the supplied workspace."""

    @abstractmethod
    def compile_project(self, checkout: DatasetCheckoutResult) -> CommandResult:
        """Prepare the checked-out project and install its required dependencies."""

    @abstractmethod
    def run_triggering_tests(self, checkout: DatasetCheckoutResult) -> CommandResult:
        """Run the tests associated with the selected benchmark bug."""

    @abstractmethod
    def reproduce_baseline(
        self,
        project: str,
        bug_id: str,
        workspace: WorkspacePaths,
    ) -> BaselineReproductionResult:
        """Check out a buggy version, compile it, and run its relevant tests."""
