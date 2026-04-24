"""
数据源管理器
实现akshare和tushare的自动切换机制
"""

from app.console_utils import safe_print as print
import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from contextlib import contextmanager
from dotenv import load_dotenv
from app.local_market_data_clients import AkshareLocalClient, TushareLocalClient

# 加载环境变量
load_dotenv()

PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


def _safe_print(message):
    """Print without failing on consoles that cannot encode emoji."""
    try:
        print(message)
    except UnicodeEncodeError:
        stdout = getattr(sys, "stdout", None)
        if stdout is None:
            return

        encoding = getattr(stdout, "encoding", None) or "utf-8"
        sanitized = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        stdout.write(sanitized + "\n")
        stdout.flush()


@contextmanager
def _without_proxy_env():
    """Temporarily disable proxy env vars for direct AkShare/Eastmoney access."""
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


class DataSourceManager:
    """数据源管理器 - 实现akshare与tushare自动切换"""
    
    def __init__(self):
        self.tushare_token = os.getenv('TUSHARE_TOKEN', '')
        self.tushare_available = False
        self.tushare_api = None
        
        # 初始化tushare
        if self.tushare_token:
            try:
                import tushare as ts
                ts.set_token(self.tushare_token)
                self.tushare_api = ts.pro_api()
                self.tushare_available = True
                _safe_print("✅ Tushare数据源初始化成功")
            except Exception as e:
                _safe_print(f"⚠️ Tushare数据源初始化失败: {e}")
                self.tushare_available = False
        else:
            _safe_print("ℹ️ 未配置Tushare Token，将仅使用Akshare数据源")

        self.akshare_client = AkshareLocalClient()
        self.tushare_client = TushareLocalClient(tushare_api=self.tushare_api)
    
    def get_stock_hist_data(self, symbol, start_date=None, end_date=None, adjust='qfq'):
        """
        获取股票历史数据（优先akshare，失败时使用tushare）
        
        Args:
            symbol: 股票代码（6位数字）
            start_date: 开始日期（格式：'20240101'或'2024-01-01'）
            end_date: 结束日期
            adjust: 复权类型（'qfq'前复权, 'hfq'后复权, ''不复权）
            
        Returns:
            DataFrame: 包含日期、开盘、收盘、最高、最低、成交量等列
        """
        # 标准化日期格式
        if start_date:
            start_date = start_date.replace('-', '')
        if end_date:
            end_date = end_date.replace('-', '')
        else:
            end_date = datetime.now().strftime('%Y%m%d')
        
        # 优先使用本地AKShare缓存；缺失时由客户端回源AKShare并写回本地。
        try:
            _safe_print(f"[Akshare] 正在获取 {symbol} 的历史数据...")
            with _without_proxy_env():
                df = self.akshare_client.get_stock_hist_data(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                )
            if df is not None and not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                _safe_print(f"[Akshare] ✅ 成功获取 {len(df)} 条数据")
                return df
        except Exception as e:
            _safe_print(f"[Akshare] ❌ 获取失败: {e}")
        
        # akshare失败，尝试tushare
        if self.tushare_available:
            try:
                _safe_print(f"[Tushare] 正在获取 {symbol} 的历史数据（备用数据源）...")
                df = self.tushare_client.get_stock_hist_data(
                    symbol,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                )
                if df is not None and not df.empty:
                    df['date'] = pd.to_datetime(df['date'])
                    df = df.sort_values('date')
                    _safe_print(f"[Tushare] ✅ 成功获取 {len(df)} 条数据")
                    return df
            except Exception as e:
                _safe_print(f"[Tushare] ❌ 获取失败: {e}")
        
        # 两个数据源都失败
        _safe_print("❌ 所有数据源均获取失败")
        return None
    
    def get_stock_basic_info(self, symbol):
        """
        获取股票基本信息（优先akshare，失败时使用tushare）
        
        Args:
            symbol: 股票代码
            
        Returns:
            dict: 股票基本信息
        """
        info = {
            "symbol": symbol,
            "name": "未知",
            "industry": "未知",
            "market": "未知"
        }
        
        # 优先使用本地AKShare缓存；缺失时回源AKShare。
        try:
            _safe_print(f"[Akshare] 正在获取 {symbol} 的基本信息...")
            with _without_proxy_env():
                stock_info = self.akshare_client.get_stock_basic_info(symbol)
            if stock_info:
                info.update({key: value for key, value in stock_info.items() if value not in (None, "")})
                _safe_print(f"[Akshare] ✅ 成功获取基本信息")
                return info
        except Exception as e:
            _safe_print(f"[Akshare] ❌ 获取失败: {e}")
        
        # akshare失败，尝试tushare
        if self.tushare_available:
            try:
                _safe_print(f"[Tushare] 正在获取 {symbol} 的基本信息（备用数据源）...")
                stock_info = self.tushare_client.get_stock_basic_info(symbol)
                if stock_info:
                    info.update({key: value for key, value in stock_info.items() if value not in (None, "")})
                    _safe_print(f"[Tushare] ✅ 成功获取基本信息")
                    return info
            except Exception as e:
                _safe_print(f"[Tushare] ❌ 获取失败: {e}")
        
        return info
    
    def get_realtime_quotes(self, symbol):
        """
        获取实时行情数据（优先akshare，失败时使用tushare）
        
        Args:
            symbol: 股票代码
            
        Returns:
            dict: 实时行情数据
        """
        quotes = {}
        
        # 优先使用本地AKShare缓存；缺失或过期时回源AKShare。
        try:
            _safe_print(f"[Akshare] 正在获取 {symbol} 的实时行情...")
            with _without_proxy_env():
                quotes = self.akshare_client.get_realtime_quote(symbol) or {}
            if quotes:
                quotes.setdefault('symbol', symbol)
                quotes.setdefault('price', quotes.get('current_price'))
                quotes.setdefault('change_percent', quotes.get('change_pct'))
                quotes.setdefault('change', quotes.get('change_amount'))
                _safe_print(f"[Akshare] ✅ 成功获取实时行情")
                return quotes
        except Exception as e:
            _safe_print(f"[Akshare] ❌ 获取失败: {e}")
        
        # akshare失败，尝试tushare
        if self.tushare_available:
            try:
                _safe_print(f"[Tushare] 正在获取 {symbol} 的实时行情（备用数据源）...")
                quotes = self.tushare_client.get_realtime_quote(symbol) or {}
                if quotes:
                    quotes.setdefault('symbol', symbol)
                    quotes.setdefault('price', quotes.get('current_price'))
                    quotes.setdefault('change_percent', quotes.get('change_pct'))
                    _safe_print(f"[Tushare] ✅ 成功获取实时行情")
                    return quotes
            except Exception as e:
                _safe_print(f"[Tushare] ❌ 获取失败: {e}")
        
        return quotes
    
    def get_financial_data(self, symbol, report_type='income'):
        """
        获取财务数据（优先akshare，失败时使用tushare）
        
        Args:
            symbol: 股票代码
            report_type: 报表类型（'income'利润表, 'balance'资产负债表, 'cashflow'现金流量表）
            
        Returns:
            DataFrame: 财务数据
        """
        # 优先使用本地AKShare缓存；缺失时回源AKShare。
        try:
            _safe_print(f"[Akshare] 正在获取 {symbol} 的财务数据...")
            with _without_proxy_env():
                df = self.akshare_client.get_financial_data(symbol, report_type=report_type)
            if df is not None and not df.empty:
                _safe_print(f"[Akshare] ✅ 成功获取财务数据")
                return df
        except Exception as e:
            _safe_print(f"[Akshare] ❌ 获取失败: {e}")
        
        # akshare失败，尝试tushare
        if self.tushare_available:
            try:
                _safe_print(f"[Tushare] 正在获取 {symbol} 的财务数据（备用数据源）...")
                df = self.tushare_client.get_financial_data(symbol, report_type=report_type)
                if df is not None and not df.empty:
                    _safe_print(f"[Tushare] ✅ 成功获取财务数据")
                    return df
            except Exception as e:
                _safe_print(f"[Tushare] ❌ 获取失败: {e}")
        
        return None
    
    def _convert_to_ts_code(self, symbol):
        """
        将6位股票代码转换为tushare格式（带市场后缀）
        
        Args:
            symbol: 6位股票代码
            
        Returns:
            str: tushare格式代码（如：000001.SZ）
        """
        if not symbol or len(symbol) != 6:
            return symbol
        
        # 根据代码判断市场
        if symbol.startswith('6'):
            # 上海主板
            return f"{symbol}.SH"
        elif symbol.startswith('0') or symbol.startswith('3'):
            # 深圳主板和创业板
            return f"{symbol}.SZ"
        elif symbol.startswith('8') or symbol.startswith('4'):
            # 北交所
            return f"{symbol}.BJ"
        else:
            # 默认深圳
            return f"{symbol}.SZ"
    
    def _convert_from_ts_code(self, ts_code):
        """
        将tushare格式代码转换为6位代码
        
        Args:
            ts_code: tushare格式代码（如：000001.SZ）
            
        Returns:
            str: 6位股票代码
        """
        if '.' in ts_code:
            return ts_code.split('.')[0]
        return ts_code


# 全局数据源管理器实例
data_source_manager = DataSourceManager()

