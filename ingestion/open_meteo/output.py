"""The run output file: its folder, its name and the all-or-nothing write."""

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any


def prepare_output_dir(path: Path) -> None:
    """Create `path` with any missing parents and check that files can be written into it."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"output directory {path} cannot be created: {exc}") from exc
    if not os.access(path, os.W_OK):
        raise OSError(f"output directory {path} is not writable")


def output_file_name(mode: str, retrieved_at: datetime, run_id: str) -> str:
    return f"open_meteo_{mode}_{retrieved_at:%Y%m%dT%H%M%SZ}_{run_id}.jsonl"


def write_records_atomically(
    records: Sequence[Mapping[str, Any]], directory: Path, file_name: str
) -> Path:
    """Write `records` as JSON Lines so the final file appears complete or not at all."""
    final_path = directory / file_name
    temp_path = directory / f".{file_name}.tmp"
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            file.flush()
            os.fsync(file.fileno())
        # Unlike a rename, a hard link fails when the final name exists, so nothing is overwritten.
        os.link(temp_path, final_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return final_path
