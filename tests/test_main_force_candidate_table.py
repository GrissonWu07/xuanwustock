import pandas as pd
import pytest

from main_force_ui import build_main_force_candidate_display_df


def test_build_main_force_candidate_display_df_normalizes_candidate_columns():
    raw_df = pd.DataFrame(
        [
            {
                "股票代码": "002824.SZ",
                "股票简称": "和胜股份",
                "所属同花顺行业": "有色金属-工业金属-铝",
                "区间主力资金流向[20260112-20260410]": 26297734.3,
                "区间涨跌幅:前复权[20260112-20260410]": 29.6562,
                "总市值[20260410]": 7863490000,
                "市盈率(pe)[20260410]": 58.8091,
                "市净率(pb)[20260410]": 3.4946,
                "最新价": 22.97,
            }
        ]
    )

    candidate_df = build_main_force_candidate_display_df(raw_df)

    assert list(candidate_df.columns) == [
        "加入关注池",
        "股票代码",
        "股票简称",
        "所属行业",
        "最新价",
        "主力资金(亿)",
        "区间涨跌幅(%)",
        "总市值(亿)",
        "市盈率",
        "市净率",
    ]
    row = candidate_df.iloc[0].to_dict()
    assert row["加入关注池"] is False
    assert row["股票代码"] == "002824.SZ"
    assert row["股票简称"] == "和胜股份"
    assert row["所属行业"] == "有色金属-工业金属-铝"
    assert row["最新价"] == 22.97
    assert row["主力资金(亿)"] == pytest.approx(0.262977343)
    assert row["区间涨跌幅(%)"] == 29.6562
    assert row["总市值(亿)"] == 78.6349
    assert row["市盈率"] == 58.8091
    assert row["市净率"] == 3.4946
