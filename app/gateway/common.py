from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any

from app.watchlist_selector_integration import normalize_stock_code


RESEARCH_MARKDOWN_TEXT_LIMIT = 2000
RESEARCH_MODULE_TIMEOUT_SECONDS = int(os.getenv("RESEARCH_MODULE_TIMEOUT_SECONDS", "600"))
RESEARCH_MODULE_MAX_PARALLEL = max(1, int(os.getenv("RESEARCH_MODULE_MAX_PARALLEL", "2")))


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def p(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def txt(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def dict_value(obj: Any, key: str, default: Any = None) -> Any:
    if not isinstance(obj, dict):
        return default
    return obj.get(key, default)


def num(value: Any, digits: int = 2, default: str = "0.00") -> str:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return default


def pct(value: Any, digits: int = 2, default: str = "0.00%") -> str:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return default


def float_value(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def int_value(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or (isinstance(value, str) and not str(value).strip()):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def metric(label: str, value: Any) -> dict[str, Any]:
    return {"label": label, "value": txt(value, "0")}


def insight(title: str, body: str, tone: str | None = None) -> dict[str, Any]:
    item = {"title": title, "body": body}
    if tone:
        item["tone"] = tone
    return item


def timeline(time: str, title: str, body: str) -> dict[str, str]:
    return {"time": time, "title": title, "body": body}


def table(columns: list[str], rows: list[dict[str, Any]], empty_label: str) -> dict[str, Any]:
    return {"columns": columns, "rows": rows, "emptyLabel": empty_label}


def snippet(value: Any, limit: int = 80, default: str = "") -> str:
    # 保留兼容函数签名，但后端不再做文本截断。
    _ = limit
    return txt(value, default)


def looks_like_stock_code(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().upper()
    return bool(re.fullmatch(r"\d{6}(?:\.[A-Z]{2,6})?", text))


def payload_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def code_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("code", "stockCode", "stock_code", "id", "symbol"):
            code = normalize_stock_code(payload.get(key))
            if code:
                return code
        return ""
    code = normalize_stock_code(payload)
    if code:
        return code
    return ""


def normalize_codes(payload: Any) -> list[str]:
    if isinstance(payload, list):
        return [normalize_stock_code(item) for item in payload if normalize_stock_code(item)]
    if isinstance(payload, dict):
        for key in ("codes", "stockCodes", "stock_codes", "rows", "ids"):
            if key in payload:
                return normalize_codes(payload[key])
        code = code_from_payload(payload)
        return [code] if code else []
    if payload is None:
        return []
    code = normalize_stock_code(payload)
    return [code] if code else []


def first_non_empty(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        return value
    return None


__all__ = [
    "RESEARCH_MARKDOWN_TEXT_LIMIT",
    "RESEARCH_MODULE_TIMEOUT_SECONDS",
    "code_from_payload",
    "dict_value",
    "first_non_empty",
    "float_value",
    "insight",
    "int_value",
    "looks_like_stock_code",
    "metric",
    "normalize_codes",
    "now",
    "num",
    "p",
    "payload_dict",
    "pct",
    "snippet",
    "table",
    "timeline",
    "txt",
]
