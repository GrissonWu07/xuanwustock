"""
智能盯盘 - A股数据获取模块
使用TDX/akshare获取实时行情和技术指标
支持降级到tushare作为备用数据源
"""

from app.console_utils import safe_print as print
import logging
import os
import threading
import time
from app.akshare_client import ak
import pandas as pd
from typing import Dict, Optional
from datetime import datetime, timedelta
from app.data.indicators import TechnicalIndicatorEngine
from app.local_market_data_clients import AkshareLocalClient, TushareLocalClient


class SmartMonitorDataFetcher:
    """A股数据获取器（支持多数据源降级：TDX -> AKShare -> Tushare）"""
    _TDX_CIRCUIT_LOCK = threading.Lock()
    _TDX_CIRCUIT_OPEN_UNTIL = 0.0
    _TDX_CONSECUTIVE_FAILURES = 0
    
    def __init__(
        self,
        use_tdx: bool = None,
        tdx_host: str = None,
        tdx_port: int = None,
        tdx_fallback_hosts: list[str] = None,
        tdx_timeout: int = None,
    ):
        """
        初始化数据获取器
        
        Args:
            use_tdx: 是否使用TDX数据源（可选，从配置读取）
            tdx_host: TDX行情服务器地址（可选，从配置读取）
            tdx_port: TDX行情服务器端口（可选，从配置读取）
            tdx_fallback_hosts: 备用TDX服务器列表（可选，从配置读取）
            tdx_timeout: TDX连接超时（可选，从配置读取）
        """
        self.logger = logging.getLogger(__name__)
        
        # TDX数据源配置
        from app.config import TDX_CONFIG

        if use_tdx is None:
            use_tdx = TDX_CONFIG.get('enabled', False)
        
        if tdx_host is None:
            tdx_host = TDX_CONFIG.get('host')
        if tdx_port is None:
            tdx_port = TDX_CONFIG.get('port', 7709)
        if tdx_timeout is None:
            tdx_timeout = TDX_CONFIG.get('timeout', 5)
        
        self.use_tdx = use_tdx
        self.tdx_fetcher = None
        
        if self.use_tdx:
            try:
                from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher
                self.tdx_fetcher = SmartMonitorTDXDataFetcher(
                    host=tdx_host,
                    port=tdx_port,
                    fallback_hosts=tdx_fallback_hosts,
                    hosts_file=TDX_CONFIG.get('hosts_file'),
                    timeout=tdx_timeout,
                )
                self.logger.info("TDX数据源已启用: pytdx 直连模式")
            except Exception as e:
                self.logger.warning(f"TDX数据源初始化失败: {e}，将使用AKShare")
                self.use_tdx = False
        
        # 初始化Tushare（备用数据源）
        self.ts_pro = None
        tushare_token = os.getenv('TUSHARE_TOKEN', '')
        
        if tushare_token:
            try:
                import tushare as ts
                ts.set_token(tushare_token)
                self.ts_pro = ts.pro_api()
                self.logger.info("Tushare备用数据源初始化成功")
            except Exception as e:
                self.logger.warning(f"Tushare初始化失败: {e}")
        else:
            self.logger.info("未配置Tushare Token，仅使用AKShare数据源")
        self.akshare_client = AkshareLocalClient()
        self.tushare_client = TushareLocalClient(tushare_api=self.ts_pro)

    @classmethod
    def _is_tdx_circuit_open(cls) -> bool:
        with cls._TDX_CIRCUIT_LOCK:
            return time.monotonic() < float(cls._TDX_CIRCUIT_OPEN_UNTIL)

    @classmethod
    def _record_tdx_success(cls) -> None:
        with cls._TDX_CIRCUIT_LOCK:
            cls._TDX_CONSECUTIVE_FAILURES = 0
            cls._TDX_CIRCUIT_OPEN_UNTIL = 0.0

    @classmethod
    def _record_tdx_failure(cls) -> None:
        now = time.monotonic()
        with cls._TDX_CIRCUIT_LOCK:
            cls._TDX_CONSECUTIVE_FAILURES = int(cls._TDX_CONSECUTIVE_FAILURES) + 1
            failures = cls._TDX_CONSECUTIVE_FAILURES
            if failures >= 3:
                cooldown = min(300.0, 20.0 * (2.0 ** min(failures - 3, 5)))
                cls._TDX_CIRCUIT_OPEN_UNTIL = max(float(cls._TDX_CIRCUIT_OPEN_UNTIL), now + cooldown)
    
    def get_realtime_quote(self, stock_code: str, retry: int = 1) -> Optional[Dict]:
        """
        获取实时行情（带重试和降级机制）
        优先使用TDX，失败时降级到AKShare，最后降级到Tushare
        
        Args:
            stock_code: 股票代码（如：600519）
            retry: 重试次数（默认1次，避免IP封禁）
            
        Returns:
            实时行情数据
        """
        import time
        
        # 方法1: 尝试使用TDX（如果启用）
        if self.use_tdx and self.tdx_fetcher and not self._is_tdx_circuit_open():
            try:
                quote = self.tdx_fetcher.get_realtime_quote(stock_code)
                if quote:
                    self._record_tdx_success()
                    return quote
                else:
                    self._record_tdx_failure()
                    self.logger.warning(f"TDX获取失败 {stock_code}，尝试降级到AKShare")
            except Exception as e:
                self._record_tdx_failure()
                self.logger.warning(f"TDX获取异常 {stock_code}: {e}，尝试降级到AKShare")
        elif self.use_tdx and self.tdx_fetcher:
            self.logger.debug(f"TDX熔断生效，跳过TDX直连并直接降级: {stock_code}")
        
        # 方法2: 组合使用AKShare分钟行情 + 基本信息
        for attempt in range(retry):
            try:
                quote = self.akshare_client.get_realtime_quote(stock_code)
                if not quote:
                    self.logger.warning(f"AKShare未找到股票 {stock_code} 的实时行情数据")
                    if attempt < retry - 1:
                        time.sleep(2)
                        continue
                    break

                self.logger.info(f"✅ AKShare成功获取 {stock_code} ({quote.get('name', 'N/A')}) 实时行情")
                return {
                    'code': stock_code,
                    'name': quote.get('name', 'N/A'),
                    'current_price': float(quote.get('current_price') or quote.get('price') or 0),
                    'change_pct': float(quote.get('change_pct') or quote.get('change_percent') or 0),
                    'change_amount': float(quote.get('change_amount') or quote.get('change') or 0),
                    'volume': float(quote.get('volume') or 0),
                    'amount': float(quote.get('amount') or 0),
                    'high': float(quote.get('high') or 0),
                    'low': float(quote.get('low') or 0),
                    'open': float(quote.get('open') or 0),
                    'pre_close': float(quote.get('pre_close') or 0),
                    'turnover_rate': float(quote.get('turnover_rate') or 0),
                    'volume_ratio': float(quote.get('volume_ratio') or 1.0),
                    'update_time': str(quote.get('update_time') or quote.get('quote_time') or datetime.now()),
                    'data_source': 'akshare',
                    'cache_source': quote.get('cache_source'),
                    'cache_status': quote.get('cache_status'),
                }
                
            except Exception as e:
                if attempt < retry - 1:
                    self.logger.warning(f"AKShare获取失败 {stock_code}，第{attempt+1}次重试... 错误: {type(e).__name__}: {str(e)[:50]}")
                    time.sleep(2)  # 等待2秒后重试
                else:
                    self.logger.warning(f"AKShare获取失败 {stock_code}（已重试{retry}次），尝试降级")
        
        # 降级到Tushare
        if self.ts_pro:
            self.logger.info(f"降级到Tushare获取 {stock_code}...")
            return self._get_realtime_quote_from_tushare(stock_code)
        else:
            self.logger.error(f"AKShare失败且未配置Tushare，无法获取 {stock_code} 行情")
            return None
    
    def get_technical_indicators(self, stock_code: str, period: str = 'daily', retry: int = 1) -> Optional[Dict]:
        """
        计算技术指标（带降级机制）
        优先使用TDX，失败时降级到AKShare，最后降级到Tushare
        
        Args:
            stock_code: 股票代码
            period: 周期（daily/weekly/monthly）
            retry: 重试次数（默认1次）
            
        Returns:
            技术指标数据
        """
        import time
        
        # 方法1: 尝试使用TDX（如果启用）
        if self.use_tdx and self.tdx_fetcher and not self._is_tdx_circuit_open():
            try:
                indicators = self.tdx_fetcher.get_technical_indicators(stock_code, period)
                if indicators:
                    self._record_tdx_success()
                    return indicators
                else:
                    self._record_tdx_failure()
                    self.logger.warning(f"TDX计算技术指标失败 {stock_code}，尝试降级到AKShare")
            except Exception as e:
                self._record_tdx_failure()
                self.logger.warning(f"TDX计算技术指标异常 {stock_code}: {e}，尝试降级到AKShare")
        elif self.use_tdx and self.tdx_fetcher:
            self.logger.debug(f"TDX熔断生效，跳过TDX技术指标并直接降级: {stock_code}")
        
        # 方法2: 尝试使用AKShare
        for attempt in range(retry):
            try:
                # 获取历史数据（最近200个交易日，用于计算指标）
                end_date = datetime.now().strftime('%Y%m%d')
                start_date = (datetime.now() - timedelta(days=300)).strftime('%Y%m%d')
                
                df = self.akshare_client.get_stock_hist_data(
                    stock_code,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq",
                    output="akshare",
                )
                
                if df.empty or len(df) < 60:
                    if attempt < retry - 1:
                        self.logger.warning(f"AKShare历史数据不足 {stock_code}，第{attempt+1}次重试...")
                        time.sleep(1)
                        continue
                    else:
                        self.logger.warning(f"AKShare历史数据不足 {stock_code}，尝试降级")
                        break
                
                # 数据充足，计算技术指标
                return self._calculate_all_indicators(df, stock_code)
                
            except Exception as e:
                if attempt < retry - 1:
                    self.logger.warning(f"AKShare获取历史数据失败 {stock_code}，第{attempt+1}次重试... 错误: {type(e).__name__}: {str(e)[:50]}")
                    time.sleep(1)
                else:
                    self.logger.warning(f"AKShare获取历史数据失败 {stock_code}（已重试{retry}次），尝试降级到Tushare")
                    break
        
        # 方法3: 降级到Tushare
        if self.ts_pro:
            self.logger.info(f"降级到Tushare获取 {stock_code} 历史数据...")
            return self._get_technical_indicators_from_tushare(stock_code, period)
        else:
            self.logger.error(f"AKShare失败且未配置Tushare，无法获取 {stock_code} 技术指标")
            return None
    
    def _calculate_all_indicators(self, df: pd.DataFrame, stock_code: str) -> Optional[Dict]:
        """
        根据历史数据计算所有技术指标
        
        Args:
            df: 历史数据DataFrame
            stock_code: 股票代码
            
        Returns:
            技术指标数据
        """
        try:
            if df.empty or len(df) < 60:
                self.logger.warning(f"股票 {stock_code} 历史数据不足")
                return None
            
            indicators = TechnicalIndicatorEngine().calculate(
                df,
                symbol=stock_code,
                source="smart_monitor",
                dataset="hist_daily",
                timeframe="1d",
                provider="akshare",
                strict=False,
            )
            if indicators.empty:
                return None
            latest = indicators.iloc[-1]

            current_price = float(latest['close'])
            ma5 = float(latest['ma5'])
            ma20 = float(latest['ma20'])
            ma60 = float(latest['ma60'])
            
            if current_price > ma5 > ma20 > ma60:
                trend = 'up'
            elif current_price < ma5 < ma20 < ma60:
                trend = 'down'
            else:
                trend = 'sideways'
            
            # 布林带位置
            boll_upper = float(latest['boll_upper'])
            boll_mid = float(latest['boll_mid'])
            boll_lower = float(latest['boll_lower'])
            
            if current_price >= boll_upper:
                boll_position = '上轨附近（超买）'
            elif current_price <= boll_lower:
                boll_position = '下轨附近（超卖）'
            elif current_price > boll_mid:
                boll_position = '中轨上方'
            else:
                boll_position = '中轨下方'
            
            return {
                'ma5': ma5,
                'ma20': ma20,
                'ma10': float(latest['ma10']) if pd.notna(latest['ma10']) else 0.0,
                'ma60': ma60,
                'trend': trend,
                'macd_dif': float(latest['dif']),
                'macd_dea': float(latest['dea']),
                'macd': float(latest['macd']),
                'dif': float(latest['dif']),
                'dea': float(latest['dea']),
                'hist': float(latest['hist']),
                'hist_prev': float(indicators.iloc[-2]['hist']) if len(indicators) >= 2 and pd.notna(indicators.iloc[-2]['hist']) else 0.0,
                'rsi6': float(latest['rsi6']),
                'rsi12': float(latest['rsi12']),
                'rsi14': float(latest['rsi14']),
                'rsi24': float(latest['rsi24']),
                'kdj_k': float(latest['kdj_k']),
                'kdj_d': float(latest['kdj_d']),
                'kdj_j': float(latest['kdj_j']),
                'k': float(latest['kdj_k']),
                'd': float(latest['kdj_d']),
                'j': float(latest['kdj_j']),
                'obv': float(latest['obv']),
                'obv_prev': float(latest['obv_prev']) if pd.notna(latest['obv_prev']) else float(latest['obv']),
                'atr': float(latest['atr']) if pd.notna(latest['atr']) else 0.0,
                'boll_upper': boll_upper,
                'boll_mid': boll_mid,
                'boll_lower': boll_lower,
                'boll_position_value': float(latest['boll_position_value']),
                'boll_position': boll_position,
                'vol_ma5': float(latest['volume_ma5']),
                'vol_ma10': float(latest['volume_ma10']),
                'volume_ratio': float(latest['volume_ratio']) if pd.notna(latest['volume_ratio']) else 1.0,
                'formula_profile': str(latest['formula_profile']),
                'indicator_version': str(latest['indicator_version']),
            }
            
        except Exception as e:
            self.logger.error(f"计算技术指标失败 {stock_code}: {e}")
            return None
    
    def _get_technical_indicators_from_tushare(self, stock_code: str, period: str = 'daily') -> Optional[Dict]:
        """
        使用Tushare本地优先源获取历史数据并计算技术指标
        
        Args:
            stock_code: 股票代码（6位）
            period: 周期（daily/weekly/monthly）
            
        Returns:
            技术指标数据
        """
        try:
            df = self.tushare_client.get_stock_hist_data(
                stock_code,
                start_date=(datetime.now() - timedelta(days=400)).strftime('%Y%m%d'),
                end_date=datetime.now().strftime('%Y%m%d'),
                output="akshare",
            )
            if df is None or df.empty:
                self.logger.error(f"Tushare未返回 {stock_code} 的历史数据")
                return None
            if len(df) < 60:
                self.logger.warning(f"Tushare历史数据不足 {stock_code}（仅{len(df)}条）")
                return None
            self.logger.info(f"✅ Tushare本地优先获取 {stock_code} 历史数据，共{len(df)}条")
            return self._calculate_all_indicators(df, stock_code)
            
        except Exception as e:
            self.logger.error(f"Tushare获取历史数据失败 {stock_code}: {type(e).__name__}: {str(e)}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None
    
    def get_main_force_flow(self, stock_code: str, retry: int = 2) -> Optional[Dict]:
        """
        获取主力资金流向（带重试机制）
        
        Args:
            stock_code: 股票代码
            retry: 重试次数（默认2次）
            
        Returns:
            主力资金数据
        """
        import time
        
        for attempt in range(retry):
            try:
                # 获取个股资金流（新版AKShare API参数调整）
                try:
                    df = ak.stock_individual_fund_flow_rank(market="今日")
                except TypeError:
                    # 如果market参数也不支持，尝试无参数调用
                    try:
                        df = ak.stock_individual_fund_flow_rank()
                    except TypeError as te:
                        self.logger.warning(f"AKShare API参数不兼容: {te}")
                        return None
                
                stock_data = df[df['代码'] == stock_code]
                
                if stock_data.empty:
                    self.logger.warning(f"未找到股票 {stock_code} 的资金流向数据")
                    return None
                
                row = stock_data.iloc[0]
                
                # 主力净额
                main_net = float(row.get('主力净流入-净额', 0)) / 10000  # 转换为万元
                main_net_pct = float(row.get('主力净流入-净占比', 0))
                
                # 判断主力动向
                if main_net > 0 and main_net_pct > 5:
                    trend = '大幅流入'
                elif main_net > 0:
                    trend = '小幅流入'
                elif main_net < 0 and main_net_pct < -5:
                    trend = '大幅流出'
                elif main_net < 0:
                    trend = '小幅流出'
                else:
                    trend = '观望'
                
                return {
                    'main_net': main_net,  # 万元
                    'main_net_pct': main_net_pct,  # 百分比
                    'super_net': float(row.get('超大单净流入-净额', 0)) / 10000,
                    'big_net': float(row.get('大单净流入-净额', 0)) / 10000,
                    'mid_net': float(row.get('中单净流入-净额', 0)) / 10000,
                    'small_net': float(row.get('小单净流入-净额', 0)) / 10000,
                    'trend': trend,
                    'data_source': 'akshare'
                }
                
            except Exception as e:
                if attempt < retry - 1:
                    self.logger.warning(f"AKShare获取资金流向失败 {stock_code}，第{attempt+1}次重试... 错误: {type(e).__name__}")
                    time.sleep(1)  # 等待1秒后重试
                else:
                    self.logger.warning(f"AKShare获取资金流向失败 {stock_code}（已重试{retry}次），尝试降级到Tushare")
                    break
        
        # 降级到Tushare
        if self.ts_pro:
            return self._get_main_force_from_tushare(stock_code)
        else:
            self.logger.error(f"AKShare失败且未配置Tushare，无法获取 {stock_code} 资金流向")
            return None
    
    def get_comprehensive_data(self, stock_code: str) -> Dict:
        """
        获取综合数据（实时行情+技术指标）
        注意：已移除主力资金流向数据，因为该接口不稳定且AI决策不依赖此数据
        
        Args:
            stock_code: 股票代码
            
        Returns:
            综合数据
        """
        result = {}
        
        # 实时行情
        quote = self.get_realtime_quote(stock_code)
        if quote:
            result.update(quote)
        
        # 技术指标
        indicators = self.get_technical_indicators(stock_code)
        if indicators:
            result.update(indicators)
        
        # 主力资金（已禁用 - 接口不稳定）
        # main_force = self.get_main_force_flow(stock_code)
        # if main_force:
        #     result['main_force'] = main_force
        
        return result
    
    # ========== Tushare备用数据源方法 ==========
    
    def _get_realtime_quote_from_tushare(self, stock_code: str) -> Optional[Dict]:
        """
        从Tushare获取实时行情（备用数据源）
        使用免费接口，无需积分
        
        Args:
            stock_code: 股票代码
            
        Returns:
            实时行情数据
        """
        try:
            quote = self.tushare_client.get_realtime_quote(stock_code)
            if not quote:
                self.logger.error(f"Tushare本地优先源未返回 {stock_code} 实时行情")
                return None
            return {
                'code': stock_code,
                'name': quote.get('name', 'N/A'),
                'current_price': float(quote.get('current_price') or quote.get('price') or 0),
                'change_pct': float(quote.get('change_pct') or quote.get('change_percent') or 0),
                'change_amount': float(quote.get('change_amount') or quote.get('change') or 0),
                'volume': float(quote.get('volume') or 0),
                'amount': float(quote.get('amount') or 0),
                'high': float(quote.get('high') or 0),
                'low': float(quote.get('low') or 0),
                'open': float(quote.get('open') or 0),
                'pre_close': float(quote.get('pre_close') or 0),
                'turnover_rate': float(quote.get('turnover_rate') or 0),
                'volume_ratio': float(quote.get('volume_ratio') or 1.0),
                'update_time': str(quote.get('update_time') or quote.get('quote_time') or datetime.now()),
                'data_source': 'tushare',
                'cache_source': quote.get('cache_source'),
                'cache_status': quote.get('cache_status'),
            }
        except Exception as e:
            error_msg = str(e)
            if "权限" in error_msg or "积分" in error_msg:
                self.logger.error(f"Tushare权限不足 {stock_code}: 需要更多积分")
                self.logger.info("💡 获取积分方法：")
                self.logger.info("   1. 完善个人信息 +100积分")
                self.logger.info("   2. 每日签到 +1积分")
                self.logger.info("   3. 参与社区互动")
                self.logger.info("   详情访问: https://tushare.pro/document/1?doc_id=13")
            else:
                self.logger.error(f"Tushare获取失败 {stock_code}: {error_msg[:100]}")
            return None
    
    def _get_main_force_from_tushare(self, stock_code: str) -> Optional[Dict]:
        """
        从Tushare获取主力资金流向（备用数据源）
        注意：资金流向接口需要较高积分
        
        Args:
            stock_code: 股票代码
            
        Returns:
            主力资金数据
        """
        try:
            # 转换股票代码格式
            if stock_code.startswith('6'):
                ts_code = f"{stock_code}.SH"
            elif stock_code.startswith(('0', '3')):
                ts_code = f"{stock_code}.SZ"
            else:
                return None
            
            # 尝试获取资金流向数据（需要120积分）
            today = datetime.now().strftime('%Y%m%d')
            df = self.ts_pro.moneyflow(ts_code=ts_code, start_date=today, end_date=today)
            
            if df.empty:
                # 获取最近一个交易日
                df = self.ts_pro.moneyflow(ts_code=ts_code, end_date=today)
                df = df.head(1)
            
            if df.empty:
                self.logger.warning(f"Tushare未找到股票 {stock_code} 的资金流向数据")
                return None
            
            row = df.iloc[0]
            
            # 计算主力净额（大单+超大单）
            buy_lg_amount = float(row.get('buy_lg_amount', 0))
            buy_elg_amount = float(row.get('buy_elg_amount', 0))
            sell_lg_amount = float(row.get('sell_lg_amount', 0))
            sell_elg_amount = float(row.get('sell_elg_amount', 0))
            
            main_net = (buy_lg_amount + buy_elg_amount - sell_lg_amount - sell_elg_amount) / 10000
            
            # 计算净占比
            net_mf_amount = float(row.get('net_mf_amount', 0))
            main_net_pct = (main_net / net_mf_amount * 100) if net_mf_amount != 0 else 0
            
            # 判断主力动向
            if main_net > 0 and main_net_pct > 5:
                trend = '大幅流入'
            elif main_net > 0:
                trend = '小幅流入'
            elif main_net < 0 and main_net_pct < -5:
                trend = '大幅流出'
            elif main_net < 0:
                trend = '小幅流出'
            else:
                trend = '观望'
            
            self.logger.info(f"✅ Tushare降级成功，获取到 {stock_code} 资金流向")
            
            return {
                'main_net': main_net,
                'main_net_pct': main_net_pct,
                'super_net': (buy_elg_amount - sell_elg_amount) / 10000,
                'big_net': (buy_lg_amount - sell_lg_amount) / 10000,
                'mid_net': float(row.get('buy_md_amount', 0) - row.get('sell_md_amount', 0)) / 10000,
                'small_net': float(row.get('buy_sm_amount', 0) - row.get('sell_sm_amount', 0)) / 10000,
                'trend': trend
            }
            
        except Exception as e:
            error_msg = str(e)
            if "权限" in error_msg or "积分" in error_msg:
                self.logger.warning(f"⚠️ Tushare资金流向接口需要120积分，当前积分不足")
                self.logger.info("💡 获取积分方法：")
                self.logger.info("   1. 完善个人信息 +100积分")
                self.logger.info("   2. 每日签到累积 +30积分（30天）")
                self.logger.info("   3. 参与社区互动获得积分")
                self.logger.info("   详情: https://tushare.pro/document/1?doc_id=13")
                self.logger.info("   智能盯盘会继续运行，仅缺少资金流向数据")
            else:
                self.logger.error(f"Tushare获取资金流向失败 {stock_code}: {error_msg[:100]}")
            return None


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    fetcher = SmartMonitorDataFetcher()
    
    # 测试贵州茅台
    print("测试获取贵州茅台(600519)数据...")
    data = fetcher.get_comprehensive_data('600519')
    
    if data:
        print("\n实时行情:")
        print(f"  当前价: {data.get('current_price')} 元")
        print(f"  涨跌幅: {data.get('change_pct')}%")
        
        print("\n技术指标:")
        print(f"  MA5: {data.get('ma5', 0):.2f}")
        print(f"  MA20: {data.get('ma20', 0):.2f}")
        print(f"  MACD: {data.get('macd', 0):.4f}")
        print(f"  RSI(6): {data.get('rsi6', 0):.2f}")
        
        if 'main_force' in data:
            print("\n主力资金:")
            print(f"  主力净额: {data['main_force']['main_net']:.2f}万")
            print(f"  主力动向: {data['main_force']['trend']}")

