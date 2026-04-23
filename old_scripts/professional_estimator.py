#!/usr/bin/env python3
"""
华宝油气专业实时估值系统 v2.0
多数据源融合 + 实时计算 + 置信度评估

核心算法:
实时EST = 昨日净值 × [1 + (XOP涨跌幅 × 仓位比例) + (汇率变化 × 汇率敏感度)] × 期货调整系数

数据源:
- 基金净值: 天天基金网
- XOP行情: 新浪财经(延时) / Yahoo Finance(尝试)
- 汇率: 新浪财经 USD/CNY 实时
- 原油期货CL: 新浪财经（作为领先指标）
- SPSIOP指数期货: 若有（最准确）

置信度评估:
- A级: 数据完整，延时<15分钟
- B级: 部分数据延时或缺失
- C级: 关键数据缺失，仅供参考
"""

import requests
import json
import time
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List
import statistics

# yfinance for XOP data
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


@dataclass
class DataSource:
    """数据源状态"""
    name: str
    value: float
    timestamp: datetime
    latency_ms: int
    is_realtime: bool
    reliability: float  # 0-1


@dataclass
class EstimationResult:
    """估值结果"""
    timestamp: str
    fund_code: str
    fund_name: str
    
    # 输入数据
    last_nav: float
    nav_date: str
    
    # 多源数据
    xop_sources: List[DataSource]
    rate_source: DataSource
    cl_source: Optional[DataSource]
    
    # 计算结果
    base_est: float          # 基础估算（仅XOP）
    rate_adjusted_est: float # 汇率调整
    final_est: float         # 最终估算
    confidence: str          # A/B/C
    confidence_score: float  # 0-1
    
    # 市场数据
    market_price: float
    premium: float
    
    # 元数据
    calculation_method: str
    warnings: List[str]


class ProfessionalEstimator:
    """专业估值器"""
    
    # 基金配置
    FUND_CONFIG = {
        "162411": {
            "name": "华宝油气",
            "benchmark": "SPSIOP",
            "proxy": "XOP",
            "position_ratio": 0.95,
            "rate_sensitivity": 0.8,  # 汇率敏感度（QDII基金）
            "futures_lead": 0.3,      # 期货领先系数
        },
        "161127": {
            "name": "标普生物科技",
            "benchmark": "S&P Biotech",
            "proxy": "XBI",
            "position_ratio": 0.95,
            "rate_sensitivity": 0.8,
            "futures_lead": 0.0,      # 生物科技无直接期货对冲
        }
    }
    
    def __init__(self, fund_code: str = "162411"):
        self.fund_code = fund_code
        self.config = self.FUND_CONFIG[fund_code]
        self.data_dir = Path(__file__).parent / "estimation_data"
        self.data_dir.mkdir(exist_ok=True)
        
        # 缓存
        self._cache = {}
        self._cache_ttl = 30  # 30秒缓存
        
    def _fetch(self, url: str, headers: dict = None, timeout: int = 10) -> Optional[str]:
        """通用HTTP获取"""
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        if headers:
            default_headers.update(headers)
        
        try:
            start = time.time()
            resp = requests.get(url, headers=default_headers, timeout=timeout)
            latency = int((time.time() - start) * 1000)
            
            if resp.status_code == 200:
                return resp.text, latency
        except Exception as e:
            print(f"请求失败 {url}: {e}")
        return None, 0
    
    def get_last_nav(self) -> Dict:
        """获取最新净值和天天基金估算（已停止实时更新）"""
        cache_key = "last_nav"
        if cache_key in self._cache:
            if time.time() - self._cache[cache_key]["time"] < self._cache_ttl:
                return self._cache[cache_key]["data"]
        
        url = f"http://fundgz.1234567.com.cn/js/{self.fund_code}.js"
        text, latency = self._fetch(url, headers={"Referer": "http://fund.eastmoney.com/"})
        
        if text and "jsonpgz(" in text:
            try:
                data = json.loads(text[8:-2])
                result = {
                    "nav": float(data.get("dwjz", 0)),
                    "nav_date": data.get("jzrq"),
                    "name": data.get("name"),
                    "source": "天天基金",
                    "latency_ms": latency,
                    # 监管已叫停实时估值，以下数据为收盘时点估算，不再实时更新
                    "tiantian_est": float(data.get("gsz", 0)) if data.get("gsz") else None,
                    "tiantian_change": data.get("gszzl"),
                    "tiantian_time": data.get("gztime"),
                    "tiantian_note": "监管已叫停实时估值，此数据为历史收盘估算",
                }
                self._cache[cache_key] = {"data": result, "time": time.time()}
                return result
            except:
                pass
        
        # 默认值
        return {"nav": 0.965, "nav_date": "2026-03-24", "name": "华宝油气", "source": "默认", "latency_ms": 0}
    
    def get_xop_sina(self) -> Optional[DataSource]:
        """从新浪获取XOP"""
        url = "https://hq.sinajs.cn/list=usr_xop"
        text, latency = self._fetch(url, headers={"Referer": "https://finance.sina.com.cn"})
        
        if text and "hq_str_usr_xop" in text:
            try:
                parts = text.split('"')[1].split(",")
                price = float(parts[0])
                prev = float(parts[1])
                change_pct = (price - prev) / prev * 100
                
                # 判断是否为实时（美股开盘时间）
                now = datetime.now()
                ny_time = now - timedelta(hours=12)  # 简化计算
                is_realtime = 9 <= ny_time.hour <= 16
                
                return DataSource(
                    name="新浪财经-XOP",
                    value=round(change_pct, 2),
                    timestamp=now,
                    latency_ms=latency,
                    is_realtime=is_realtime,
                    reliability=0.7 if is_realtime else 0.5
                )
            except:
                pass
        return None
    
    def get_xop_alternative(self) -> Optional[DataSource]:
        """备用XOP数据源（腾讯）"""
        url = "http://qt.gtimg.cn/q=usr_xop"
        text, latency = self._fetch(url)
        
        if text and "v_usr_xop" in text:
            try:
                parts = text.split('"')[1].split("~")
                price = float(parts[3])
                prev = float(parts[4])
                change_pct = (price - prev) / prev * 100
                
                return DataSource(
                    name="腾讯财经-XOP",
                    value=round(change_pct, 2),
                    timestamp=datetime.now(),
                    latency_ms=latency,
                    is_realtime=False,  # 通常为延时
                    reliability=0.5
                )
            except:
                pass
        return None
    
    def get_xop_yfinance(self) -> Optional[DataSource]:
        """使用yfinance获取XOP数据（Yahoo Finance）"""
        if not YFINANCE_AVAILABLE:
            return None
        
        try:
            start = time.time()
            ticker = yf.Ticker("XOP")
            
            # 获取今日数据（1分钟粒度）
            today_data = ticker.history(period="1d", interval="1m")
            
            if today_data.empty:
                return None
            
            # 获取最新价格和前收盘价
            latest_price = today_data['Close'].iloc[-1]
            
            # 获取前收盘价（使用历史数据）
            hist = ticker.history(period="5d")
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]  # 昨日收盘价
            else:
                prev_close = today_data['Open'].iloc[0]  # fallback到今日开盘价
            
            # 计算涨跌幅
            change_pct = (latest_price - prev_close) / prev_close * 100
            latency = int((time.time() - start) * 1000)
            
            # 判断是否为实时数据（美股交易时间：9:30-16:00 ET）
            now = datetime.now()
            ny_time = now - timedelta(hours=12)  # 简化计算（ET ≈ UTC-4/5）
            is_realtime = 9 <= ny_time.hour <= 16  # 美股交易时间
            
            return DataSource(
                name="Yahoo Finance-XOP",
                value=round(change_pct, 2),
                timestamp=now,
                latency_ms=latency,
                is_realtime=is_realtime,
                reliability=0.85 if is_realtime else 0.75  # Yahoo数据通常较可靠
            )
        except Exception as e:
            # 静默失败，不打印错误（避免污染输出）
            return None
    
    def get_xop_yahoo_api(self) -> Optional[DataSource]:
        """直接调用Yahoo Finance API获取XOP数据"""
        try:
            start = time.time()
            
            # Yahoo Finance API endpoint (非官方，但广泛使用)
            url = "https://query1.finance.yahoo.com/v8/finance/chart/XOP"
            params = {
                "interval": "1m",
                "range": "1d",
                "includePrePost": "true"
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            
            if not result:
                return None
            
            meta = result.get("meta", {})
            
            # 获取最新价格
            timestamps = result.get("timestamp", [])
            prices = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            
            if not prices or not timestamps:
                return None
            
            # 过滤None值获取最新有效价格
            valid_prices = [(t, p) for t, p in zip(timestamps, prices) if p is not None]
            if not valid_prices:
                return None
            
            latest_price = valid_prices[-1][1]
            
            # 获取前收盘价
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
            if not prev_close:
                # fallback: 使用第一个有效价格作为参考
                prev_close = valid_prices[0][1]
            
            change_pct = (latest_price - prev_close) / prev_close * 100
            latency = int((time.time() - start) * 1000)
            
            # 判断实时性
            now = datetime.now()
            ny_time = now - timedelta(hours=12)
            is_realtime = 9 <= ny_time.hour <= 16
            
            return DataSource(
                name="Yahoo API-XOP",
                value=round(change_pct, 2),
                timestamp=now,
                latency_ms=latency,
                is_realtime=is_realtime,
                reliability=0.8 if is_realtime else 0.7
            )
        except Exception:
            return None
    
    def get_etf_nasdaq(self, symbol: str) -> Optional[DataSource]:
        """从NASDAQ API获取ETF数据（通用）"""
        try:
            start = time.time()
            
            url = f"https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=etf"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
            
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            if data.get("status", {}).get("rCode") != 200:
                return None
            
            primary = data.get("data", {}).get("primaryData", {})
            
            # 解析涨跌幅字符串 (例如: "+0.77%")
            pct_str = primary.get("percentageChange", "0%").replace("%", "")
            change_pct = float(pct_str)
            
            # 解析市场状态
            market_status = data.get("data", {}).get("marketStatus", "Unknown")
            is_realtime = market_status == "Open"
            
            latency = int((time.time() - start) * 1000)
            
            return DataSource(
                name=f"NASDAQ-{symbol}",
                value=round(change_pct, 2),
                timestamp=datetime.now(),
                latency_ms=latency,
                is_realtime=is_realtime,
                reliability=0.9 if is_realtime else 0.85
            )
        except Exception:
            return None
    
    def get_xop_nasdaq(self) -> Optional[DataSource]:
        """从NASDAQ API获取XOP数据"""
        return self.get_etf_nasdaq("XOP")
    
    def get_xbi_nasdaq(self) -> Optional[DataSource]:
        """从NASDAQ API获取XBI数据"""
        return self.get_etf_nasdaq("XBI")
    
    def get_cl_futures(self) -> Optional[DataSource]:
        """获取美油期货CL（作为领先指标）"""
        # 新浪财经期货API
        url = "https://hq.sinajs.cn/list=hf_CL"
        text, latency = self._fetch(url, headers={"Referer": "https://finance.sina.com.cn"})
        
        if text and "hf_CL" in text:
            try:
                parts = text.split('"')[1].split(",")
                # 期货数据格式: 买入价, 卖出价, 最新价, 涨跌, 涨跌幅...
                if len(parts) >= 8:
                    change_pct = float(parts[8])
                    return DataSource(
                        name="新浪财经-CL期货",
                        value=round(change_pct, 2),
                        timestamp=datetime.now(),
                        latency_ms=latency,
                        is_realtime=True,
                        reliability=0.6  # 期货与ETF有差异
                    )
            except:
                pass
        return None
    
    def get_usdcny_rate(self) -> DataSource:
        """获取USD/CNY汇率"""
        url = "https://hq.sinajs.cn/list=fx_susdcny"
        text, latency = self._fetch(url, headers={"Referer": "https://finance.sina.com.cn"})
        
        if text and "fx_susdcny" in text:
            try:
                parts = text.split('"')[1].split(",")
                spot = float(parts[1])
                prev = float(parts[3])  # 昨收
                change_pct = (spot - prev) / prev * 100
                
                return DataSource(
                    name="新浪财经-USD/CNY",
                    value=round(change_pct, 2),
                    timestamp=datetime.now(),
                    latency_ms=latency,
                    is_realtime=True,
                    reliability=0.85
                )
            except:
                pass
        
        # 默认值
        return DataSource(
            name="默认汇率",
            value=0.0,
            timestamp=datetime.now(),
            latency_ms=0,
            is_realtime=False,
            reliability=0.3
        )
    
    def get_market_price(self) -> float:
        """获取场内实时价格"""
        exchange = "sz" if self.fund_code.startswith("16") else "sh"
        url = f"http://qt.gtimg.cn/q={exchange}{self.fund_code}"
        text, _ = self._fetch(url)
        
        var_name = f'v_{exchange}{self.fund_code}'
        if text and var_name in text:
            try:
                parts = text.split('"')[1].split("~")
                return float(parts[3])
            except:
                pass
        return 0.0
    
    def calculate_estimation(self, nav: float, xop_sources: List[DataSource], 
                            rate: DataSource, cl: Optional[DataSource]) -> tuple:
        """
        计算估值
        
        算法:
        1. 基础估算 = NAV × (1 + XOP_change × position)
        2. 汇率调整 = 基础 × (1 + rate_change × rate_sensitivity)
        3. 期货调整 = 汇率调整 × (1 + CL_change × lead_coefficient)
        """
        warnings = []
        
        # 1. XOP数据融合（加权平均）
        if not xop_sources:
            xop_change = 0
            warnings.append("XOP数据缺失")
        else:
            # 按可靠性加权
            total_weight = sum(s.reliability for s in xop_sources)
            weighted_sum = sum(s.value * s.reliability for s in xop_sources)
            xop_change = weighted_sum / total_weight if total_weight > 0 else 0
        
        # 基础估算
        base_est = nav * (1 + xop_change * self.config["position_ratio"] / 100)
        
        # 2. 汇率调整
        rate_adjusted = base_est * (1 + rate.value * self.config["rate_sensitivity"] / 100)
        
        # 3. 期货调整（如果有）
        final_est = rate_adjusted
        if cl:
            # CL期货作为领先指标，权重较小
            final_est = rate_adjusted * (1 + cl.value * self.config["futures_lead"] / 100)
        
        return round(base_est, 4), round(rate_adjusted, 4), round(final_est, 4), warnings
    
    def calculate_confidence(self, xop_sources: List[DataSource], 
                            rate: DataSource, cl: Optional[DataSource],
                            warnings: List[str]) -> tuple:
        """计算置信度"""
        score = 1.0
        
        # XOP数据源质量
        if len(xop_sources) == 0:
            score -= 0.4
        elif len(xop_sources) == 1:
            score -= 0.1
        
        for src in xop_sources:
            if not src.is_realtime:
                score -= 0.1
            if src.reliability < 0.6:
                score -= 0.05
        
        # 汇率数据质量
        if not rate.is_realtime:
            score -= 0.1
        
        # 警告扣分
        score -= len(warnings) * 0.05
        
        # 确定等级
        if score >= 0.85:
            level = "A"
        elif score >= 0.7:
            level = "B"
        else:
            level = "C"
        
        return level, max(0, score)
    
    def estimate(self) -> EstimationResult:
        """执行完整估算"""
        now = datetime.now()
        
        # 1. 获取净值
        nav_data = self.get_last_nav()
        
        # 2. 获取多源Proxy ETF数据
        etf_sources = []
        proxy_etf = self.config.get("proxy", "XOP")
        
        if proxy_etf == "XBI":
            # XBI数据源
            nasdaq_xbi = self.get_xbi_nasdaq()
            if nasdaq_xbi:
                etf_sources.append(nasdaq_xbi)
        else:
            # XOP数据源（默认）
            # 优先使用NASDAQ API（最可靠）
            nasdaq_xop = self.get_xop_nasdaq()
            if nasdaq_xop:
                etf_sources.append(nasdaq_xop)
            
            # 备用: Yahoo Finance（多种方式）
            # 方式1: yfinance库
            yf_xop = self.get_xop_yfinance()
            if yf_xop:
                etf_sources.append(yf_xop)
            
            # 方式2: 直接Yahoo API
            yahoo_api_xop = self.get_xop_yahoo_api()
            if yahoo_api_xop:
                etf_sources.append(yahoo_api_xop)
            
            # 备用：新浪财经
            sina_xop = self.get_xop_sina()
            if sina_xop:
                etf_sources.append(sina_xop)
            
            # 备用：腾讯财经
            tencent_xop = self.get_xop_alternative()
            if tencent_xop:
                etf_sources.append(tencent_xop)
        
        # 3. 获取汇率
        rate = self.get_usdcny_rate()
        
        # 4. 获取期货
        cl = self.get_cl_futures()
        
        # 5. 计算估值
        base_est, rate_adj_est, final_est, warnings = self.calculate_estimation(
            nav_data["nav"], etf_sources, rate, cl
        )
        
        # 6. 计算置信度
        confidence, score = self.calculate_confidence(etf_sources, rate, cl, warnings)
        
        # 7. 获取场内价格
        market_price = self.get_market_price()
        premium = (market_price - final_est) / final_est * 100 if final_est > 0 else 0
        
        # 8. 确定计算方法
        method = "多源融合"
        if cl:
            method += "+期货调整"
        
        return EstimationResult(
            timestamp=now.isoformat(),
            fund_code=self.fund_code,
            fund_name=nav_data["name"],
            last_nav=nav_data["nav"],
            nav_date=nav_data["nav_date"],
            xop_sources=etf_sources,
            rate_source=rate,
            cl_source=cl,
            base_est=base_est,
            rate_adjusted_est=rate_adj_est,
            final_est=final_est,
            confidence=confidence,
            confidence_score=round(score, 2),
            market_price=market_price,
            premium=round(premium, 2),
            calculation_method=method,
            warnings=warnings
        )
    
    def print_report(self, result: EstimationResult, nav_data: Dict = None):
        """打印专业报告"""
        print("=" * 70)
        print(f"📊 {result.fund_name}({result.fund_code}) 专业实时估值报告")
        print("=" * 70)
        print(f"⏰ 计算时间: {result.timestamp}")
        print(f"🎯 置信等级: {result.confidence} (得分: {result.confidence_score})")
        print(f"🔧 计算方法: {result.calculation_method}")
        print()
        
        print("【输入数据】")
        print(f"  昨日净值: {result.last_nav} ({result.nav_date})")
        print()
        
        print("【多源行情】")
        for src in result.xop_sources:
            rt_status = "实时" if src.is_realtime else "延时"
            print(f"  {src.name}: {src.value:+.2f}% [{rt_status}] (可靠度:{src.reliability})")
        
        if result.cl_source:
            cl = result.cl_source
            print(f"  {cl.name}: {cl.value:+.2f}% [领先指标]")
        
        rate = result.rate_source
        print(f"  {rate.name}: {rate.value:+.3f}%")
        print()
        
        print("【估值计算】")
        print(f"  基础估算(XOP):     {result.base_est}")
        print(f"  汇率调整后:        {result.rate_adjusted_est}")
        print(f"  ★ 最终估算:       {result.final_est}")
        print()
        
        # 显示天天基金估算对比（如果可用）
        if nav_data and nav_data.get("tiantian_est"):
            print("【与天天基金对比】")
            print(f"  ⚠️  注: 监管已叫停实时估值，天天基金数据不再更新")
            print(f"  天天基金估算: {nav_data['tiantian_est']} ({nav_data.get('tiantian_change', 'N/A')}%)")
            print(f"  估算时间: {nav_data.get('tiantian_time', 'N/A')} [已过时]")
            tt_premium = (result.market_price - nav_data['tiantian_est']) / nav_data['tiantian_est'] * 100
            print(f"  按天天基金算溢价: {tt_premium:+.2f}%")
            print(f"  按我们的系统算: {result.premium:+.2f}%")
            diff = abs(result.premium - tt_premium)
            if diff > 0.5:
                print(f"  ⚠️  差异: {diff:.2f}% (较大，以我们的估算为准)")
            print()
        
        print("【套利分析】")
        print(f"  场内价格: {result.market_price}")
        print(f"  估算净值: {result.final_est}")
        print(f"  溢价率: {result.premium:+.2f}%")
        
        # 套利建议
        if result.premium > 1.5:
            print(f"  💡 建议: 🔴 溢价套利（申购-卖出）")
        elif result.premium > 0.15:
            print(f"  💡 建议: 🟡 XOP对冲套利（需美股账户）")
        elif result.premium < -0.5:
            print(f"  💡 建议: 🟢 折价套利（买入-赎回）")
        else:
            print(f"  💡 建议: ⚪ 观望")
        print()
        
        if result.warnings:
            print("【警告】")
            for w in result.warnings:
                print(f"  ⚠️  {w}")
            print()
        
        print("=" * 70)
        print("【免责声明】")
        print("  本估算基于公开数据，仅供参考，不构成投资建议")
        print("  QDII基金受汇率、时差、调仓等因素影响，估算存在误差")
        print("=" * 70)
    
    def save_result(self, result: EstimationResult):
        """保存结果"""
        date_str = datetime.now().strftime("%Y%m%d")
        file_path = self.data_dir / f"prof_{self.fund_code}_{date_str}.jsonl"
        
        # 转换为可序列化的字典
        data = asdict(result)
        # DataSource对象转字典
        data["xop_sources"] = [asdict(s) if hasattr(s, '__dataclass_fields__') else s for s in result.xop_sources]
        data["rate_source"] = asdict(result.rate_source) if hasattr(result.rate_source, '__dataclass_fields__') else result.rate_source
        if result.cl_source:
            data["cl_source"] = asdict(result.cl_source) if hasattr(result.cl_source, '__dataclass_fields__') else result.cl_source
        
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")


def main():
    print("正在获取多源数据，请稍候...\n")
    
    estimator = ProfessionalEstimator(fund_code="162411")
    result = estimator.estimate()
    
    # 获取nav_data用于对比
    nav_data = estimator.get_last_nav()
    estimator.print_report(result, nav_data)
    estimator.save_result(result)
    
    # 同时输出JSON供其他程序使用
    output_file = Path(__file__).parent / "professional_est.json"
    with open(output_file, "w", encoding="utf-8") as f:
        data = asdict(result)
        data["xop_sources"] = [asdict(s) for s in result.xop_sources]
        data["rate_source"] = asdict(result.rate_source)
        if result.cl_source:
            data["cl_source"] = asdict(result.cl_source)
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n✅ 数据已保存: {output_file}")


if __name__ == "__main__":
    main()
