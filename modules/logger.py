"""Timestamped logging to stdout and, once the run folder exists, Generation.log.

Format mirrors the Hazel pipeline logs:
    2026-07-15 14:03:12  Prompt received
"""

import sys
from datetime import datetime
from pathlib import Path


class RunLogger:
    def __init__(self):
        self._file = None
        self._buffer = []  # lines logged before the run folder exists

    def attach_file(self, run_dir: Path):
        """Point the logger at Generation.log inside the run folder and flush
        anything logged before the folder existed."""
        self._file = run_dir / "Generation.log"
        with self._file.open("a", encoding="utf-8") as f:
            for line in self._buffer:
                f.write(line + "\n")
        self._buffer = []

    def log(self, message: str):
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {message}"
        print(line, flush=True)
        if self._file is not None:
            with self._file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            self._buffer.append(line)

    def fail(self, message: str, exit_code: int = 1):
        """Fail loud: log the error and abort."""
        self.log(f"ERROR: {message}")
        sys.exit(exit_code)
