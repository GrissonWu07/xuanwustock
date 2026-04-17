#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
低估值选股模块
使用pywencai获取低估值优质股票
"""

from app.console_utils import safe_print as print
import os
from contextlib import contextmanager
import pandas as pd
import pywencai
from datetime import datetime
from typing import Tuple, Optional
import time


PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


class ValueStockSelector:
    """低估值选股类"""

    def __init__(self):
        self.raw_data = None
        self.selected_stocks = None

    def get_value_stocks(self, top_n: int = 10) -> Tuple[bool, Optional[pd.DataFrame], str]:
        """
        获取低估值优质股票

        选股策略：
        - 市盈率 ≤ 20
        - 市净率 ≤ 1.5
        - 股息率 ≥ 1%
        - 资产负债率 ≤ 30%
        - 非ST
        - 非科创板
        - 非创业板
        - 按流通市值由小到大排名

        Args:
            top_n: 返回前N只股票

        Returns:
            (success, dataframe, message)
        """
        try:
            print(f"\n{'='*60}")
            print(f"💎 低估值选股 - 数据获取中")
            print(f"{'='*60}")
            print(f"策略: PE≤20 + PB≤1.5 + 股息率≥1% + 资产负债率≤30%")
            print(f"排除: ST、科创板、创业板")
            print(f"排序: 按流通市值由小到大")
            print(f"目标: 筛选前{top_n}只股票")

            # 构建问财查询语句
            query = (
                "市盈率小于等于20，"
                "市净率小于等于1.5，"
                "股息率大于等于1%，"
                "资产负债率小于等于30%，"
                "非st，"
                "非科创板，"
                "非创业板，"
                "按流通市值由小到大排名"
            )

            print(f"\n查询语句: {query}")
            print(f"正在调用问财接口...")

            # 调用pywencai（增加重试与退避，避免偶发空响应）
            result = None
            failures = []
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    with self._without_proxy_env():
                        result = pywencai.get(query=query, loop=True, retry=1, sleep=0)
                    if result is None:
                        raise ValueError("问财接口返回空结果")
                    break
                except Exception as exc:
                    failure_message = self._format_query_error(exc)
                    failures.append(f"第{attempt}次: {failure_message}")
                    if attempt < max_attempts:
                        wait_seconds = attempt
                        print(f"⚠️ 问财查询失败（{failure_message}），{wait_seconds}s后重试...")
                        time.sleep(wait_seconds)

            if result is None:
                latest = failures[-1] if failures else "问财接口返回None，请检查网络或稍后重试"
                return False, None, f"问财查询失败，{latest}"

            # 转换为DataFrame
            df_result = self._convert_to_dataframe(result)

            if df_result is None or df_result.empty:
                return False, None, "未获取到符合条件的股票数据"
            if not self._is_valid_stock_dataframe(df_result):
                return False, None, "问财返回的数据格式异常，未识别到股票代码/简称字段"

            print(f"✅ 成功获取 {len(df_result)} 只股票")

            # 显示获取到的列名
            print(f"\n获取到的数据字段:")
            for col in df_result.columns[:15]:
                print(f"  - {col}")
            if len(df_result.columns) > 15:
                print(f"  ... 还有 {len(df_result.columns) - 15} 个字段")

            # 保存原始数据
            self.raw_data = df_result

            # 取前N只
            if len(df_result) > top_n:
                selected = df_result.head(top_n)
                print(f"\n从 {len(df_result)} 只股票中选出前 {top_n} 只")
            else:
                selected = df_result
                print(f"\n共 {len(df_result)} 只符合条件的股票")

            self.selected_stocks = selected

            # 显示选中的股票
            print(f"\n✅ 选中的股票:")
            for idx, row in selected.iterrows():
                code = row.get('股票代码', 'N/A')
                name = row.get('股票简称', 'N/A')
                pe = row.get('市盈率', row.get('市盈率(动态)', 'N/A'))
                pb = row.get('市净率', 'N/A')
                div_rate = row.get('股息率', 'N/A')
                debt_ratio = row.get('资产负债率', 'N/A')
                cap = row.get('流通市值', 'N/A')
                print(f"  {idx+1}. {code} {name} - PE:{pe} PB:{pb} 股息率:{div_rate}% 负债率:{debt_ratio}% 流通市值:{cap}")

            print(f"{'='*60}\n")

            return True, selected, f"成功筛选出{len(selected)}只低估值优质股票"

        except Exception as e:
            error_msg = f"获取数据失败: {str(e)}"
            print(f"❌ {error_msg}")
            return False, None, error_msg

    @staticmethod
    @contextmanager
    def _without_proxy_env():
        """Temporarily disable proxy env vars for pywencai direct access."""
        original_env = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}
        try:
            for key in PROXY_ENV_KEYS:
                os.environ.pop(key, None)
            yield
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    @staticmethod
    def _format_query_error(error: Exception) -> str:
        message = str(error).strip() or error.__class__.__name__
        if "NoneType" in message and "get" in message:
            return "问财响应为空（未返回有效data字段）"
        return message

    def _convert_to_dataframe(self, result) -> Optional[pd.DataFrame]:
        """将pywencai返回结果转换为DataFrame"""
        try:
            if isinstance(result, pd.DataFrame):
                return result
            elif isinstance(result, dict):
                if 'data' in result:
                    return pd.DataFrame(result['data'])
                elif 'result' in result:
                    return pd.DataFrame(result['result'])
                else:
                    return pd.DataFrame(result)
            elif isinstance(result, list):
                return pd.DataFrame(result)
            else:
                print(f"⚠️ 未知的数据格式: {type(result)}")
                return None
        except Exception as e:
            print(f"转换DataFrame失败: {e}")
            return None

    @staticmethod
    def _is_valid_stock_dataframe(df: pd.DataFrame) -> bool:
        required_column_markers = ("股票代码", "股票简称")
        return all(
            any(marker in str(column) for column in df.columns)
            for marker in required_column_markers
        )

    def get_stock_codes(self) -> list:
        """
        获取选中股票的代码列表（去掉市场后缀）

        Returns:
            股票代码列表
        """
        if self.selected_stocks is None or self.selected_stocks.empty:
            return []

        codes = []
        for code in self.selected_stocks['股票代码'].tolist():
            if isinstance(code, str):
                clean_code = code.split('.')[0] if '.' in code else code
                codes.append(clean_code)
            else:
                codes.append(str(code))

        return codes


# 测试
if __name__ == "__main__":
    print("=" * 60)
    print("测试低估值选股模块")
    print("=" * 60)

    selector = ValueStockSelector()
    success, df, msg = selector.get_value_stocks(top_n=10)
    print(f"\n结果: {msg}")
    if success and df is not None:
        print(f"共 {len(df)} 只股票")
