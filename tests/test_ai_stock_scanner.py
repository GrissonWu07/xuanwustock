from __future__ import annotations

import os

import pandas as pd

from app.discover.ai_stock_scanner import AIStockScanner, AIStockScannerConfig


class FakeAkForSectors:
    def stock_board_concept_name_em(self):
        return pd.DataFrame(
            [
                {"板块名称": "人工智能", "涨跌幅": 5.0, "成交额": 20_000_000_000},
                {"板块名称": "新能源车", "涨跌幅": 2.0, "成交额": 8_000_000_000},
            ]
        )

    def stock_board_industry_name_em(self):
        return pd.DataFrame()

    def stock_board_concept_cons_em(self, symbol):
        if symbol != "人工智能":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {"代码": "688111", "名称": "金山办公", "最新价": 321.88, "涨跌幅": 4.2, "总市值": 1234.0},
                {"代码": "000001", "名称": "平安银行", "最新价": 10.12, "涨跌幅": 1.1, "总市值": 2000.0},
            ]
        )


class FakeAkEmpty:
    def stock_board_concept_name_em(self):
        return pd.DataFrame()

    def stock_board_industry_name_em(self):
        return pd.DataFrame()


class FakeLlm:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call_api(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self.response


def rising_history_frame(symbol: str = "688111") -> pd.DataFrame:
    rows = []
    for index in range(80):
        close = 10 + index * 0.2
        rows.append(
            {
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=index),
                "symbol": symbol,
                "open": close - 0.08,
                "high": close + 0.18,
                "low": close - 0.18,
                "close": close,
                "volume": 1_000_000 + index * 20_000,
                "amount": close * (1_000_000 + index * 20_000),
            }
        )
    return pd.DataFrame(rows)


def test_ai_stock_scanner_selects_candidates_from_hot_sector_constituents():
    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=1, max_stocks=2, max_candidates_per_sector=2, enable_llm_themes=False),
        ak_api=FakeAkForSectors(),
        history_provider=lambda code: pd.DataFrame(),
    )

    result = scanner.scan()
    repeated = scanner.scan()

    assert list(result["股票代码"]) == ["688111", "000001"]
    assert list(repeated["股票代码"]) == ["688111", "000001"]
    assert result.iloc[0]["股票简称"] == "金山办公"
    assert result.iloc[0]["所属行业"] == "人工智能"
    assert "sector=人工智能" in result.iloc[0]["reason"]


def test_ai_stock_scanner_falls_back_to_wencai_when_sector_data_is_empty():
    def fake_wencai_get(**kwargs):
        assert "热门题材" in kwargs["query"]
        return pd.DataFrame(
            [
                {
                    "股票代码": "600519",
                    "股票简称": "贵州茅台",
                    "所属行业": "白酒",
                    "最新价": 1453.96,
                    "总市值": 18200.0,
                    "市盈率": 26.1,
                    "市净率": 9.8,
                }
            ]
        )

    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=1, max_stocks=1, enable_llm_themes=False),
        ak_api=FakeAkEmpty(),
        wencai_get=fake_wencai_get,
    )

    result = scanner.scan()

    assert list(result["股票代码"]) == ["600519"]
    assert result.iloc[0]["股票简称"] == "贵州茅台"
    assert "main fund flow" in result.iloc[0]["reason"]


def test_ai_stock_scanner_maps_dynamic_wencai_market_columns():
    def fake_wencai_get(**kwargs):
        return pd.DataFrame(
            [
                {
                    "股票代码": "000988.SZ",
                    "股票简称": "华工科技",
                    "所属同花顺行业": "机械设备-自动化设备-激光设备",
                    "收盘价:不复权[20260507]": 133.5,
                    "总市值[20260507]": 134_234_600_000,
                    "市盈率(pe)[20260507]": 52.562,
                    "市净率(pb)[20260507]": 11.485,
                }
            ]
        )

    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=1, max_stocks=1, enable_llm_themes=False),
        ak_api=FakeAkEmpty(),
        wencai_get=fake_wencai_get,
        history_provider=lambda code: pd.DataFrame(),
    )

    result = scanner.scan()

    assert result.iloc[0]["股票代码"] == "000988"
    assert result.iloc[0]["最新价"] == 133.5
    assert result.iloc[0]["总市值"] == 134_234_600_000
    assert result.iloc[0]["市盈率"] == 52.562
    assert result.iloc[0]["市净率"] == 11.485


def test_ai_stock_scanner_uses_project_llm_themes_for_alignment_score():
    llm = FakeLlm(
        """
        [
          {"name": "AI算力", "weight": 0.9, "keywords": ["人工智能", "算力", "大模型"], "sentiment": "bullish"}
        ]
        """
    )
    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=1, max_stocks=2, max_candidates_per_sector=2),
        ak_api=FakeAkForSectors(),
        news_provider=lambda: [{"title": "AI算力需求提升", "content": "人工智能和大模型产业链景气度提升"}],
        llm_client=llm,
        history_provider=lambda code: rising_history_frame(code),
    )

    result = scanner.scan()

    assert llm.calls
    assert list(result["股票代码"])[0] == "688111"
    assert result.iloc[0]["theme_score"] > 0.8
    assert "theme=AI算力" in result.iloc[0]["reason"]


def test_ai_stock_scanner_uses_technical_indicator_score():
    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=1, max_stocks=1, max_candidates_per_sector=1, enable_llm_themes=False),
        ak_api=FakeAkForSectors(),
        history_provider=lambda code: rising_history_frame(code),
    )

    result = scanner.scan()

    assert result.iloc[0]["technical_score"] > 0.6
    assert "technical_score=" in result.iloc[0]["reason"]
    assert "trend" in result.iloc[0]["technical_reasons"]


def test_ai_stock_scanner_continues_when_llm_theme_extraction_fails():
    llm = FakeLlm("API调用失败: 模型未配置（请在设置页配置 AI_API_KEY）")
    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=1, max_stocks=1, max_candidates_per_sector=1),
        ak_api=FakeAkForSectors(),
        news_provider=lambda: [{"title": "AI产业新闻", "content": "大模型进展"}],
        llm_client=llm,
        history_provider=lambda code: pd.DataFrame(),
    )

    result = scanner.scan()

    assert list(result["股票代码"]) == ["688111"]
    assert result.iloc[0]["theme_score"] == 0.5
    assert "theme_score=0.50" in result.iloc[0]["reason"]


def test_ai_stock_scanner_fetches_history_without_proxy_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://broken-proxy")
    observed: dict[str, str | None] = {}

    class FakeMarketClient:
        def get_stock_hist_data(self, symbol, **kwargs):
            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            return rising_history_frame(symbol)

    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=1, max_stocks=1, max_candidates_per_sector=1, enable_llm_themes=False),
        ak_api=FakeAkForSectors(),
        market_client=FakeMarketClient(),
    )

    result = scanner.scan()

    assert observed["HTTP_PROXY"] is None
    assert os.environ["HTTP_PROXY"] == "http://broken-proxy"
    assert result.iloc[0]["technical_score"] > 0.6


def test_ai_stock_scanner_falls_back_to_tdx_history_when_primary_history_fails():
    class FailingMarketClient:
        def get_stock_hist_data(self, symbol, **kwargs):
            raise RuntimeError("akshare unavailable")

    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=1, max_stocks=1, max_candidates_per_sector=1, enable_llm_themes=False),
        ak_api=FakeAkForSectors(),
        market_client=FailingMarketClient(),
        fallback_history_provider=lambda code, start_date, end_date: rising_history_frame(code),
    )

    result = scanner.scan()

    assert result.iloc[0]["technical_score"] > 0.6
    assert "technical_data_unavailable" not in result.iloc[0]["technical_reasons"]
