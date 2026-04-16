from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_LOCALES_DIR = Path(__file__).resolve().parent / "locales"
_DEFAULT_LOCALE = (os.getenv("APP_LOCALE") or "en-US").strip() or "en-US"
_FALLBACK_LOCALE = "en-US"


def _normalize_locale(locale: str | None) -> str:
    raw = (locale or _DEFAULT_LOCALE).strip()
    if not raw:
        return _DEFAULT_LOCALE
    lowered = raw.lower().replace("_", "-")
    if lowered in {"zh", "zh-cn", "zh-hans", "zh-hans-cn"}:
        return "zh-CN"
    if lowered in {"en", "en-us"}:
        return "en-US"
    return raw


@lru_cache(maxsize=8)
def _load_messages(locale: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{locale}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def t(key: str, default: str | None = None, locale: str | None = None, **kwargs: Any) -> str:
    normalized_locale = _normalize_locale(locale)
    messages = _load_messages(normalized_locale)
    fallback_messages = _load_messages(_FALLBACK_LOCALE)
    text = messages.get(key) or fallback_messages.get(key) or default or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def current_locale() -> str:
    return _normalize_locale(None)


__all__ = ["current_locale", "t"]
