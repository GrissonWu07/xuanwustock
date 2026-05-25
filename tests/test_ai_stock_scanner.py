from __future__ import annotations

import os

import pandas as pd

from app.discover.ai_stock_scanner import (
    AIStockScanner,
    AIStockScannerConfig,
    _SectorCandidate,
    _clamp,
    _first_matching,
    _news_items_from_payload,
    _normalize,
    _number,
    _parse_theme_response,
    _score_indicator_frame,
    _stock_code,
    _text,
    _to_frame,
)


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


def test_ai_stock_scanner_injected_history_provider_blocks_market_client_access():
    class FailingMarketClient:
        def get_stock_hist_data(self, symbol, **kwargs):
            raise AssertionError("market client should not be called when history_provider is injected")

    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=1, max_stocks=2, max_candidates_per_sector=2, enable_llm_themes=False),
        ak_api=FakeAkForSectors(),
        market_client=FailingMarketClient(),
        history_provider=lambda code: pd.DataFrame(),
    )

    result = scanner.scan()

    assert list(result["股票代码"]) == ["688111", "000001"]
    assert set(result["technical_reasons"]) == {"technical_data_unavailable"}


def test_ai_stock_scanner_tied_final_scores_keep_original_candidate_order():
    scanner = AIStockScanner(
        AIStockScannerConfig(
            max_stocks=2,
            enable_llm_themes=False,
            weight_sector=0,
            weight_technical=0,
            weight_theme=1,
        ),
        ak_api=FakeAkEmpty(),
        history_provider=lambda code: pd.DataFrame(),
    )
    rows = [
        {
            "股票代码": "688111",
            "股票简称": "金山办公",
            "所属行业": "人工智能",
            "sector_score": 0.5,
            "rank_score": 0.5,
            "price_change_score": 0.5,
            "scanner_score": 0.5,
            "source_reason": "first tied candidate",
        },
        {
            "股票代码": "000001",
            "股票简称": "平安银行",
            "所属行业": "银行",
            "sector_score": 0.5,
            "rank_score": 0.5,
            "price_change_score": 0.5,
            "scanner_score": 0.5,
            "source_reason": "second tied candidate",
        },
    ]

    result = scanner._rank_rows(rows, themes={})

    assert list(result["股票代码"]) == ["688111", "000001"]
    assert result.iloc[0]["scanner_score"] == result.iloc[1]["scanner_score"]
    assert result.iloc[0]["sector_score"] == result.iloc[1]["sector_score"]
    assert result.iloc[0]["technical_score"] == result.iloc[1]["technical_score"]
    assert result.iloc[0]["preliminary_score"] == result.iloc[1]["preliminary_score"]


def test_ai_stock_scanner_tied_final_scores_use_sector_tiebreaker():
    scanner = AIStockScanner(
        AIStockScannerConfig(
            max_stocks=2,
            enable_llm_themes=False,
            weight_sector=0,
            weight_technical=0,
            weight_theme=1,
        ),
        ak_api=FakeAkEmpty(),
        history_provider=lambda code: pd.DataFrame(),
    )
    rows = [
        {
            "股票代码": "000001",
            "股票简称": "平安银行",
            "所属行业": "银行",
            "sector_score": 0.1,
            "scanner_score": 0.5,
            "source_reason": "low sector score",
        },
        {
            "股票代码": "688111",
            "股票简称": "金山办公",
            "所属行业": "人工智能",
            "sector_score": 0.9,
            "scanner_score": 0.5,
            "source_reason": "high sector score",
        },
    ]

    result = scanner._rank_rows(rows, themes={})

    assert list(result["股票代码"]) == ["688111", "000001"]
    assert result.iloc[0]["scanner_score"] == result.iloc[1]["scanner_score"]


def test_ai_stock_scanner_top_sectors_filters_errors_duplicates_and_low_scores():
    class FakeAkNoisySectors:
        def stock_board_concept_name_em(self):
            raise RuntimeError("concept unavailable")

        def stock_board_industry_name_em(self):
            return pd.DataFrame(
                [
                    {"行业名称": "", "涨跌幅": 9.0, "成交额": 20_000_000_000},
                    {"行业名称": "机器人", "涨跌幅": 6.0, "成交额": 20_000_000_000},
                    {"行业名称": "机器人", "涨跌幅": 5.0, "成交额": 19_000_000_000},
                    {"行业名称": "低分行业", "涨跌幅": -5.0, "成交额": 0},
                    {"行业名称": "算力", "涨跌幅": 4.0, "成交额": 10_000_000_000},
                ]
            )

    scanner = AIStockScanner(
        AIStockScannerConfig(top_k_sectors=2, min_sector_score=0.2, enable_llm_themes=False),
        ak_api=FakeAkNoisySectors(),
    )

    sectors = scanner._top_sectors()

    assert [sector.name for sector in sectors] == ["机器人", "算力"]
    assert all(sector.source == "industry" for sector in sectors)


def test_ai_stock_scanner_sector_rows_use_industry_fallback_and_skip_bad_rows():
    class FakeAkIndustryFallback:
        def stock_board_industry_cons_em(self, symbol):
            raise RuntimeError("industry constituents unavailable")

        def stock_board_concept_cons_em(self, symbol):
            return pd.DataFrame(
                [
                    {"代码": "", "名称": "坏数据", "涨跌幅": 10.0},
                    {"代码": "7", "名称": "全新好", "最新价": 8.8, "涨跌幅": 2.0, "总市值": 100.0},
                ]
            )

    scanner = AIStockScanner(AIStockScannerConfig(max_candidates_per_sector=2), ak_api=FakeAkIndustryFallback())

    rows = scanner._sector_stock_rows(
        [_SectorCandidate(name="机器人", source="industry", score=0.8, change_pct=5.0, amount=10_000_000_000)]
    )

    assert len(rows) == 1
    assert rows[0]["股票代码"] == "000007"
    assert rows[0]["股票简称"] == "全新好"
    assert rows[0]["所属行业"] == "机器人"


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
        history_provider=lambda code: pd.DataFrame(),
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


def test_ai_stock_scanner_parses_theme_response_variants():
    themes = _parse_theme_response(
        """
        prefix
        [
          {"name": "AI算力", "weight": 1.2, "keywords": "算力，大模型, GPU", "sentiment": "invalid"},
          {"name": "", "weight": 0.4, "keywords": ["忽略"], "sentiment": "bullish"},
          "bad item"
        ]
        suffix
        """
    )

    assert set(themes) == {"AI算力"}
    assert themes["AI算力"].weight == 1.0
    assert themes["AI算力"].keywords == ("算力", "大模型", "GPU")
    assert themes["AI算力"].sentiment == "neutral"
    assert _parse_theme_response("no json here") == {}
    assert _parse_theme_response("[not-json]") == {}


def test_ai_stock_scanner_extracts_news_items_from_nested_payloads():
    payload = {
        "hot_topics": [
            {"topic": "AI应用", "sources": ["算力需求", "模型升级"]},
            {"title": "新能源", "summary": "产业链新闻"},
        ]
    }
    nested = {
        "data": [
            payload,
            {"title": "直接新闻", "content": "正文", "source": "fixture"},
            {"ignored": "empty"},
        ]
    }

    items = _news_items_from_payload(nested, 3)

    assert [item["title"] for item in items] == ["AI应用", "新能源", "直接新闻"]
    assert items[0]["content"] == "算力需求 模型升级"
    assert _news_items_from_payload(None, 3) == []
    assert _news_items_from_payload({"ignored": "empty"}, 3) == []
    assert _news_items_from_payload([{"title": "A"}, {"title": "B"}], 1) == [
        {"title": "A", "content": "", "source": None}
    ]


def test_ai_stock_scanner_scores_indicator_frame_bullish_and_bearish():
    bullish_rows = []
    bearish_rows = []
    for index in range(21):
        bullish_rows.append(
            {
                "close": 10 + index,
                "ma5": 9 + index,
                "ma20": 8 + index,
                "ma60": 7 + index,
                "ma20_slope": 0.2,
                "dif": 1.2,
                "dea": 0.8,
                "hist": 0.1 + index * 0.01,
                "rsi12": 62,
                "volume_ratio": 1.8,
                "trend": "up",
            }
        )
        bearish_rows.append(
            {
                "close": 30 - index,
                "ma5": 31 - index,
                "ma20": 32 - index,
                "ma60": 33 - index,
                "ma20_slope": -0.2,
                "dif": -1.2,
                "dea": -0.8,
                "hist": -0.1 - index * 0.01,
                "rsi12": 28,
                "volume_ratio": 0.4,
                "trend": "down",
            }
        )

    bullish = _score_indicator_frame(pd.DataFrame(bullish_rows))
    bearish = _score_indicator_frame(pd.DataFrame(bearish_rows))

    assert bullish.score > bearish.score
    assert {"trend=up", "ma_short_up", "macd_bullish", "rsi_healthy"}.issubset(set(bullish.reasons))
    assert {"trend=down", "ma_short_down", "macd_bearish", "rsi_weak"}.issubset(set(bearish.reasons))


def test_ai_stock_scanner_helper_value_normalization():
    row = {
        "总市值[20260507]": "1,234.5",
        "市盈率(pe)[20260507]": "52.6",
        "empty": "",
    }

    assert _first_matching(row, "总市值") == "1,234.5"
    assert _first_matching(row, "市盈率") == "52.6"
    assert _first_matching(row, "missing") is None
    assert _stock_code("1.SZ") == "000001"
    assert _stock_code("") == ""
    assert _number("12.5%") == 12.5
    assert _number("bad", 7.0) == 7.0
    assert _normalize(5, 0, 10) == 0.5
    assert _normalize(5, 10, 10) == 0.0
    assert _clamp("bad") == 0.0
    assert _text(" nan ", "fallback") == "fallback"
    assert _to_frame({"data": [{"code": "000001"}]}).iloc[0]["code"] == "000001"
    assert _to_frame([{"code": "000002"}]).iloc[0]["code"] == "000002"
    assert _to_frame("bad").empty


def test_ai_stock_scanner_uses_injected_tdx_fetcher_for_fallback_history():
    observed = {}

    class FakeTdxFetcher:
        def get_kline_data_range(self, code, **kwargs):
            observed["code"] = code
            observed["kline_type"] = kwargs["kline_type"]
            return rising_history_frame(code)

    scanner = AIStockScanner(
        AIStockScannerConfig(enable_llm_themes=False),
        ak_api=FakeAkEmpty(),
        tdx_fetcher=FakeTdxFetcher(),
    )

    frame = scanner._fallback_history_frame("000001", "20260101", "20260131")

    assert observed == {"code": "000001", "kline_type": "day"}
    assert frame is not None
    assert not frame.empty


def test_ai_stock_scanner_extracts_themes_with_callable_client_and_unavailable_responses():
    scanner = AIStockScanner(
        AIStockScannerConfig(enable_llm_themes=True),
        ak_api=FakeAkEmpty(),
        llm_client=lambda prompt: {
            "content": '[{"name":"机器人","weight":0.8,"keywords":["机器人","自动化"],"sentiment":"bullish"}]'
        },
    )

    themes = scanner._extract_themes_with_llm([{"title": "机器人产业", "content": "自动化设备景气"}])

    assert set(themes) == {"机器人"}
    assert themes["机器人"].sentiment == "bullish"

    scanner._llm_client = object()
    assert scanner._extract_themes_with_llm([{"title": "bad", "content": "bad"}]) == {}

    scanner._llm_client = lambda prompt: "API调用失败: key missing"
    assert scanner._extract_themes_with_llm([{"title": "bad", "content": "bad"}]) == {}


def test_ai_stock_scanner_theme_alignment_handles_empty_and_bearish_context():
    scanner = AIStockScanner(AIStockScannerConfig(enable_llm_themes=True), ak_api=FakeAkEmpty())
    themes = _parse_theme_response(
        '[{"name":"减持","weight":0.7,"keywords":["风险"],"sentiment":"bearish"}]'
    )

    assert scanner._calculate_theme_alignment({}, themes).score == 0.5
    aligned = scanner._calculate_theme_alignment({"股票简称": "风险资产", "所属行业": "测试"}, themes)
    unmatched = scanner._calculate_theme_alignment({"股票简称": "其他", "所属行业": "测试"}, themes)

    assert aligned.score > unmatched.score
    assert aligned.names == ("减持",)


def test_ai_stock_scanner_fallback_history_returns_none_when_fetcher_fails():
    class FailingTdxFetcher:
        def get_kline_data_range(self, code, **kwargs):
            raise RuntimeError("tdx unavailable")

    scanner = AIStockScanner(
        AIStockScannerConfig(enable_llm_themes=False),
        ak_api=FakeAkEmpty(),
        tdx_fetcher=FailingTdxFetcher(),
    )

    assert scanner._fallback_history_frame("000001", "20260101", "20260131") is None
