from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _git_output(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


@lru_cache(maxsize=1)
def get_version_info() -> dict[str, Any]:
    revision = os.getenv("APP_REVISION") or os.getenv("GIT_REVISION") or _git_output("rev-parse", "--short", "HEAD")
    tag = os.getenv("APP_VERSION_TAG") or os.getenv("GIT_TAG") or _git_output("describe", "--tags", "--abbrev=0")
    describe = os.getenv("APP_VERSION") or os.getenv("GIT_DESCRIBE") or _git_output("describe", "--tags", "--always", "--dirty")
    dirty = describe.endswith("-dirty") if describe else False

    revision = revision or "unknown"
    tag = tag or "unknown"
    describe = describe or revision
    display = describe if describe != "unknown" else revision

    return {
        "version": display,
        "display": display,
        "tag": tag,
        "revision": revision,
        "describe": describe,
        "dirty": dirty,
    }
