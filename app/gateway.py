from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.gateway_api import UIApiContext, create_app

__all__ = ["UIApiContext", "create_app", "main"]


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - runtime convenience only
        raise RuntimeError("uvicorn is required to run the backend API") from exc

    uvicorn.run(
        create_app(),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8501")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":  # pragma: no cover - runtime convenience only
    main()
