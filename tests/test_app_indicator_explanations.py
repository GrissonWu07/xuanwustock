import app.stock_analysis_service as app_module


def test_build_indicator_explanations_returns_human_readable_labels():
    explanations = app_module.build_indicator_explanations(
        {
            "rsi": 78.2,
            "ma20": 14.8,
            "volume_ratio": 2.1,
            "macd": -0.1532,
        },
        current_price=13.9,
    )

    assert explanations["RSI"]["state"] == "偏热"
    assert "高于 70" in explanations["RSI"]["summary"]
    assert explanations["MA20"]["state"] == "弱于中期趋势"
    assert "当前价低于 MA20" in explanations["MA20"]["summary"]
    assert explanations["量比"]["state"] == "明显放量"
    assert "大于 1.5" in explanations["量比"]["summary"]
    assert explanations["MACD"]["state"] == "空头动能"
    assert "MACD 小于 0" in explanations["MACD"]["summary"]


def test_build_indicator_summary_concatenates_indicator_takeaways():
    summary = app_module.build_indicator_summary(
        {
            "RSI": {"state": "中性", "summary": "RSI 位于 30-70 之间，暂未进入极端区间。"},
            "MA20": {"state": "强于中期趋势", "summary": "当前价高于 MA20，中期趋势仍偏强。"},
            "量比": {"state": "正常成交", "summary": "量比接近 1，成交活跃度没有明显异常。"},
            "MACD": {"state": "多头动能", "summary": "MACD 大于 0，价格动能偏强。"},
        }
    )

    assert "RSI：中性" in summary
    assert "MA20：强于中期趋势" in summary
    assert "MACD：多头动能" in summary
