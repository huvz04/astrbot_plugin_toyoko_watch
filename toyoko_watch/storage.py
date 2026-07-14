"""Atomic JSON persistence for plugin runtime data."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonStore:
    """Load and atomically persist one JSON document."""

    def __init__(self, path: Path, default_factory: Callable[[], Any]):
        self.path = Path(path)
        self.default_factory = default_factory

    def load(self) -> Any:
        """Load JSON, backing up corrupt content before resetting it."""
        if not self.path.exists():
            value = self.default_factory()
            self.save(value)
            return value
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}.bak")
            shutil.copy2(self.path, backup)
            value = self.default_factory()
            self.save(value)
            return value

    def save(self, value: Any) -> None:
        """Write JSON through a sibling temporary file and atomic replace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
