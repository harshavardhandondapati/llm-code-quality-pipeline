"""LLM-assisted code quality pipeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("llm-code-quality-pipeline")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = ["__version__"]
