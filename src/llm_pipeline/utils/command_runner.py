"""Run external commands and return their output in a predictable format."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Mapping, Sequence

from llm_pipeline.exceptions import CommandExecutionError
from llm_pipeline.schemas import CommandResult


class CommandRunner:
    """Execute a command without using a shell and capture its result."""

    TIMEOUT_RETURN_CODE = 124

    def __init__(self, default_timeout_seconds: float = 300) -> None:
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be greater than zero")
        self.default_timeout_seconds = default_timeout_seconds

    def run(
        self,
        command: Sequence[str],
        working_directory: Path | str,
        *,
        timeout_seconds: float | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run one command and return stdout, stderr, status, and duration.

        A non-zero return code is recorded in CommandResult rather than raised as
        an exception. This lets later pipeline stages decide whether a failing
        command is expected, for example when reproducing a known failing test.
        """
        command_list = self._normalise_command(command)
        work_dir = Path(working_directory).expanduser().resolve()
        timeout = self.default_timeout_seconds if timeout_seconds is None else timeout_seconds

        if timeout <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if not work_dir.is_dir():
            raise CommandExecutionError(
                f"Working directory does not exist or is not a directory: {work_dir}"
            )

        process_environment = os.environ.copy()
        if environment:
            process_environment.update(environment)

        started = perf_counter()
        try:
            completed = subprocess.run(
                command_list,
                cwd=work_dir,
                env=process_environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            elapsed = perf_counter() - started
            return CommandResult(
                command=command_list,
                working_directory=work_dir,
                return_code=self.TIMEOUT_RETURN_CODE,
                stdout=self._as_text(error.stdout),
                stderr=self._timeout_message(error.stderr, timeout),
                execution_time_seconds=elapsed,
                timed_out=True,
            )
        except OSError as error:
            raise CommandExecutionError(
                f"Could not start command {command_list[0]!r}: {error}"
            ) from error

        return CommandResult(
            command=command_list,
            working_directory=work_dir,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            execution_time_seconds=perf_counter() - started,
            timed_out=False,
        )

    @staticmethod
    def _normalise_command(command: Sequence[str]) -> list[str]:
        if isinstance(command, (str, bytes)):
            raise TypeError("command must be a sequence of separate arguments")

        command_list = [str(part) for part in command]
        if not command_list:
            raise ValueError("command must contain at least one argument")
        if any(not part for part in command_list):
            raise ValueError("command arguments cannot be empty")
        return command_list

    @staticmethod
    def _as_text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    @classmethod
    def _timeout_message(cls, stderr: str | bytes | None, timeout: float) -> str:
        existing = cls._as_text(stderr).rstrip()
        message = f"Command timed out after {timeout:g} seconds."
        return f"{existing}\n{message}" if existing else message
