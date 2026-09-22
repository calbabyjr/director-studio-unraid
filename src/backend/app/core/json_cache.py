"""Load JSON files with an mtime cache so Comfy graphs are not re-parsed every job."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CACHE: dict[str, tuple[float, Any]] = {}


def load_json_file(path: Path) -> Any:
    key = str(path)
    mtime = path.stat().st_mtime
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    _CACHE[key] = (mtime, data)
    return data
