from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

DataMode = Literal["sample", "official_snapshot"]


@dataclass(frozen=True)
class DataContext:
    """The process-wide mode and data root used by every adapter."""

    mode: DataMode
    data_root: Path | None = None
    # Injected for freshness tests; None means the real UTC clock.
    clock: Callable[[], datetime] | None = None

    @classmethod
    def from_env(cls) -> DataContext:
        mode = os.environ.get("TAIWAN_LAB_DATA_MODE", "sample").strip().lower()
        if mode == "sample":
            return cls(mode="sample")
        if mode != "official_snapshot":
            raise ValueError("TAIWAN_LAB_DATA_MODE must be sample or official_snapshot")

        raw_root = os.environ.get("TAIWAN_LAB_DATA_DIR", "").strip()
        if not raw_root:
            raise ValueError("TAIWAN_LAB_DATA_DIR is required for official_snapshot mode")
        data_root = Path(raw_root).expanduser()
        if not data_root.is_dir():
            raise ValueError("TAIWAN_LAB_DATA_DIR must be an existing directory")
        return cls(mode="official_snapshot", data_root=data_root)


def data_context() -> DataContext:
    return DataContext.from_env()
