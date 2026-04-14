"""Application package root for business code."""

from importlib import import_module


def __getattr__(name: str):
    if name == "main":
        return import_module("app.gateway").main
    if name in {
        "StockDataFetcher",
        "get_stock_data",
        "calculate_key_indicators",
        "build_indicator_explanations",
        "build_indicator_summary",
        "analyze_single_stock_for_batch",
    }:
        return getattr(import_module("app.stock_analysis_service"), name)
    try:
        return import_module(f"app.{name}")
    except ModuleNotFoundError as exc:
        if exc.name == f"app.{name}":
            raise AttributeError(name) from exc
        raise
