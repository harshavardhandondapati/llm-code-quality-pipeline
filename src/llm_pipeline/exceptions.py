"""Domain-specific exceptions used across the pipeline."""


class PipelineError(Exception):
    """Base exception for all controlled pipeline failures."""


class ConfigurationError(PipelineError):
    """Raised when application configuration is invalid or incomplete."""


class DatasetError(PipelineError):
    """Base exception for dataset-related failures."""


class DatasetCheckoutError(DatasetError):
    """Raised when a benchmark bug cannot be checked out."""


class DatasetEnvironmentError(DatasetError):
    """Raised when dataset command-line tools are unavailable or cannot start."""


class DatasetMetadataError(DatasetError):
    """Raised when benchmark metadata is missing or cannot be read."""


class CommandExecutionError(PipelineError):
    """Raised when an external command fails unexpectedly."""


class CommandTimeoutError(CommandExecutionError):
    """Raised when an external command exceeds its configured timeout."""


class WorkspaceError(PipelineError):
    """Raised when a workspace cannot be created, reset, or removed safely."""


class ContextBuildError(PipelineError):
    """Raised when source context cannot be prepared for an LLM."""


class LLMError(PipelineError):
    """Base exception for LLM-provider failures."""


class LLMResponseError(LLMError):
    """Raised when an LLM response cannot be parsed or validated."""


class PatchApplicationError(PipelineError):
    """Raised when a generated patch cannot be validated or applied."""


class ValidationError(PipelineError):
    """Raised when compilation or automated test validation cannot run."""


class ResultRecordingError(PipelineError):
    """Raised when experiment results cannot be persisted."""
