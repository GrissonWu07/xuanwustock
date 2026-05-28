"""Local seed extraction for unified stock refresh.

The refresh scheduler uses these seeds only to enrich local runtime entries
before remote refresh runs. They are not decision facts.
"""

from __future__ import annotations

from typing import Any

from app.discover.candidate_artifact import load_discovery_candidate_artifact
from app.selector_result_store import load_latest_result
from app.watchlist_selector_integration import normalize_stock_code


def _txt(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _metric_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "").replace("亿", ""))
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _price(value: Any) -> float | None:
    number = _metric_float(value)
    if number is None or number <= 0:
        return None
    return number


def _first_metric_by_keyword(mapping: dict[str, Any], keywords: tuple[str, ...]) -> float | None:
    for key, value in mapping.items():
        key_text = _txt(key).lower()
        if any(keyword.lower() in key_text for keyword in keywords):
            number = _metric_float(value)
            if number is not None:
                return number
    return None


def _valid_name(value: Any) -> str:
    text = _txt(value)
    if not text or text in {"--", "-", "N/A", "None", "null", "未知"}:
        return ""
    return text


def _resolved_stock_name(value: Any, stock_code: str) -> str:
    name = _valid_name(value)
    code = normalize_stock_code(stock_code)
    if not name or name.upper() == code.upper():
        return ""
    return name


def _runtime_stock_code(value: Any) -> str:
    code = normalize_stock_code(value)
    if code.isdigit() and len(code) < 6:
        return code.zfill(6)
    return code


def _valid_sector(value: Any) -> str:
    text = _txt(value)
    if not text or text in {"--", "-", "N/A", "None", "null", "未知"}:
        return ""
    return text


def collect_local_seed_entries(context: Any) -> dict[str, dict[str, Any]]:
    seeds: dict[str, dict[str, Any]] = {}
    for row in _local_selector_seed_rows(context):
        _add_local_seed_entry(seeds, row)
    try:
        artifact = load_discovery_candidate_artifact(base_dir=context.selector_result_dir)
    except Exception:
        artifact = {}
    rows = artifact.get("rows") if isinstance(artifact, dict) else None
    if isinstance(rows, list):
        for row in rows:
            _add_local_seed_entry(seeds, row)
    return seeds


def _local_selector_seed_rows(context: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selector_keys = ("main_force", "low_price_bull", "small_cap", "profit_growth", "value_stock")
    for key in selector_keys:
        try:
            payload = load_latest_result(key, base_dir=context.selector_result_dir)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        result = payload.get("result")
        if isinstance(result, dict):
            recommendations = result.get("final_recommendations")
            if isinstance(recommendations, list):
                for item in recommendations:
                    if isinstance(item, dict):
                        stock_data = item.get("stock_data")
                        merged = dict(stock_data) if isinstance(stock_data, dict) else {}
                        merged.update(item)
                        rows.append(merged)
        frame = payload.get("stocks_df")
        if frame is not None and hasattr(frame, "to_dict"):
            try:
                frame_rows = frame.to_dict("records")
            except Exception:
                frame_rows = []
            rows.extend(item for item in frame_rows if isinstance(item, dict))
    return rows


def _add_local_seed_entry(seeds: dict[str, dict[str, Any]], row: Any) -> None:
    if not isinstance(row, dict):
        return
    code = ""
    for key in ("股票代码", "symbol", "stock_code", "code", "id"):
        code = _runtime_stock_code(row.get(key))
        if code:
            break
    if not code:
        return
    seed: dict[str, Any] = {"stock_code": code}
    name = _resolved_stock_name(
        row.get("stock_name")
        or row.get("name")
        or row.get("股票简称")
        or row.get("股票名称")
        or row.get("证券简称")
        or row.get("名称"),
        code,
    )
    if name:
        seed["stock_name"] = name
    sector = (
        _valid_sector(row.get("industry"))
        or _valid_sector(row.get("sector"))
        or _valid_sector(row.get("所属行业"))
        or _valid_sector(row.get("所属同花顺行业"))
        or _valid_sector(row.get("板块"))
    )
    if sector:
        seed["sector"] = sector
    latest_price = _price(row.get("latest_price")) or _price(row.get("latestPrice")) or _price(row.get("price")) or _price(row.get("最新价"))
    if latest_price is not None:
        seed["latest_price"] = latest_price
        seed["price"] = latest_price
    _add_seed_metrics(seed, row)
    if len(seed) > 1:
        seeds[code] = merge_runtime_seed(seeds.get(code), seed, code)


def _add_seed_metrics(seed: dict[str, Any], row: dict[str, Any]) -> None:
    metric_aliases = {
        "market_cap": ("market_cap", "marketCap", "total_market_cap", "总市值", "市值"),
        "pe_ratio": ("pe_ratio", "peRatio", "pe", "PE", "市盈率", "市盈率TTM"),
        "pb_ratio": ("pb_ratio", "pbRatio", "pb", "PB", "市净率"),
    }
    metric_keywords = {
        "market_cap": ("总市值", "market_cap", "marketcap"),
        "pe_ratio": ("市盈率", "pe_ratio", "pe"),
        "pb_ratio": ("市净率", "pb_ratio", "pb"),
    }
    for target, aliases in metric_aliases.items():
        for alias in aliases:
            value = _metric_float(row.get(alias))
            if value is not None:
                seed[target] = value
                break
        if target not in seed:
            value = _first_metric_by_keyword(row, metric_keywords[target])
            if value is not None:
                seed[target] = value


def merge_runtime_seed(existing: dict[str, Any] | None, seed: dict[str, Any], stock_code: str) -> dict[str, Any]:
    if not isinstance(seed, dict) or not seed:
        return dict(existing or {})
    result = dict(existing or {})
    code = normalize_stock_code(stock_code or result.get("stock_code") or seed.get("stock_code"))
    result.setdefault("stock_code", code)
    seed_name = _resolved_stock_name(seed.get("stock_name"), code)
    if seed_name and not _resolved_stock_name(result.get("stock_name"), code):
        result["stock_name"] = seed_name
    if _valid_sector(seed.get("sector")) and not _valid_sector(result.get("sector")):
        result["sector"] = _valid_sector(seed.get("sector"))
    for key in ("latest_price", "price"):
        if _price(result.get(key)) is None and _price(seed.get(key)) is not None:
            result[key] = _price(seed.get(key))
    for key in ("market_cap", "pe_ratio", "pb_ratio"):
        if _metric_float(result.get(key)) is None and _metric_float(seed.get(key)) is not None:
            result[key] = _metric_float(seed.get(key))
    return result
