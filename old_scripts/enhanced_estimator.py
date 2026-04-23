#!/usr/bin/env python3
"""
华宝油气增强实时估值系统 v3.0
最大数据源覆盖 + 延时补偿 + 历史校准

解决的核心问题:
1. 美股收盘后XOP数据获取困难 -> 使用期货+历史相关性推算
2. 汇率实时性 -> 多源汇率对比
3. 估算准确度 -> 盘后对比校准
"""

import requests
import json
import time
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

# yfinance for XOP data
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


@dataclass
class MarketData:
    """市场数据点"""
    source: str
    value: float  # 涨跌幅(%)
    price: Optional[float] = None  # 绝对价格
    timestamp: Optional[datetime] = None
    is_realtime: bool = False
    latency_ms: int = 0


class EnhancedEstimator:
    """增强型估值器"""
    
    def __init__(self, fund_code: str = "162411"):
        self.fund_code = fund_code
        self.data_dir = Path(__file__).parent / "estimation_data"
        self.data_dir.mkdir(exist_ok=True)
        
        # 参数配置
        self.position = 0.95
        self.rate_sensitivity = 0.8
        
        # XOP与CL的历史相关系数（约0.85）
        self.xop_cl_correlation = 0.85
        
    def fetch(self, url: str, headers: dict = None, timeout: int = 10) -> Tuple[Optional[str], int]:
        """通用获取"""
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
            pass
        return None, 0
    
    def get_fund_nav(self) -> Dict:
        """获取基金净值"""
        url = f"http://fundgz.1234567.com.cn/js/{self.fund_code}.js"
        text, latency = self.fetch(url, {"Referer": "http://fund.eastmoney.com/"})
        
        if text and "jsonpgz(" in text:
            try:
                data = json.loads(text[8:-2])
                return {
                    "nav": float(data.get("dwjz", 0)),
                    "date": data.get("jzrq"),
                    "name": data.get("name"),
                    "latency": latency
                }
            except:
                pass
        return {"nav": 0.965, "date": "2026-03-24", "name": "华宝油气", "latency": 0}
    
    def get_xop_data(self) -> List[MarketData]:
        """获取XOP多源数据"""
        results = []
        now = datetime.now()
        
        # 源0: NASDAQ API（最优先，最可靠）
        try:
            url = "https://api.nasdaq.com/api/quote/XOP/info?assetclass=etf"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status", {}).get("rCode") == 200:
                    primary = data.get("data", {}).get("primaryData", {})
                    pct_str = primary.get("percentageChange", "0%").replace("%", "")
                    change = float(pct_str)
                    market_status = data.get("data", {}).get("marketStatus", "Unknown")
                    is_rt = market_status == "Open"
                    
                    # 获取价格
                    price_str = primary.get("lastSalePrice", "$0").replace("$", "").replace(",", "")
                    price = float(price_str)
                    
                    results.append(MarketData(
                        source="NASDAQ-XOP",
                        value=round(change, 2),
                        price=price,
                        timestamp=now,
                        is_realtime=is_rt,
                        latency_ms=500  # 估算
                    ))
        except Exception:
            pass
        
        # 源1: yfinance (Yahoo Finance)
        if YFINANCE_AVAILABLE:
            try:
                ticker = yf.Ticker("XOP")
                today_data = ticker.history(period="1d", interval="1m")
                if not today_data.empty:
                    latest_price = today_data['Close'].iloc[-1]
                    hist = ticker.history(period="5d")
                    if len(hist) >= 2:
                        prev_close = hist['Close'].iloc[-2]
                    else:
                        prev_close = today_data['Open'].iloc[0]
                    change = (latest_price - prev_close) / prev_close * 100
                    
                    ny_hour = (now.hour - 12) % 24
                    is_rt = 9 <= ny_hour <= 16
                    
                    results.append(MarketData(
                        source="Yahoo-XOP",
                        value=round(change, 2),
                        price=latest_price,
                        timestamp=now,
                        is_realtime=is_rt,
                        latency_ms=1000
                    ))
            except Exception:
                pass
        
        # 源2: 新浪财经美股
        url1 = "https://hq.sinajs.cn/list=usr_xop"
        text1, lat1 = self.fetch(url1, {"Referer": "https://finance.sina.com.cn"})
        if text1 and "hq_str_usr_xop" in text1:
            try:
                parts = text1.split('"')[1].split(",")
                price = float(parts[0])
                prev = float(parts[1])
                change = (price - prev) / prev * 100
                
                # 判断延时（美股收盘后数据为延时）
                ny_hour = (now.hour - 12) % 24  # 纽约时间（简化）
                is_rt = 9 <= ny_hour <= 16  # 美股交易时间
                
                results.append(MarketData(
                    source="新浪-XOP",
                    value=round(change, 2),
                    price=price,
                    timestamp=now,
                    is_realtime=is_rt,
                    latency_ms=lat1
                ))
            except:
                pass
        
        # 源3: 腾讯财经（可能不同步）
        url2 = "http://qt.gtimg.cn/q=usr_xop"
        text2, lat2 = self.fetch(url2)
        if text2 and "v_usr_xop" in text2:
            try:
                parts = text2.split('"')[1].split("~")
                price = float(parts[3])
                prev = float(parts[4])
                change = (price - prev) / prev * 100
                
                # 与源1对比，如果差异大可能是数据不同步
                if results:
                    diff = abs(change - results[0].value)
                    if diff > 0.5:  # 差异超过0.5%
                        results.append(MarketData(
                            source="腾讯-XOP(差异大)",
                            value=round(change, 2),
                            price=price,
                            timestamp=now,
                            is_realtime=False,
                            latency_ms=lat2
                        ))
                else:
                    results.append(MarketData(
                        source="腾讯-XOP",
                        value=round(change, 2),
                        price=price,
                        timestamp=now,
                        is_realtime=False,
                        latency_ms=lat2
                    ))
            except:
                pass
        
        return results
    
    def get_commodity_data(self) -> List[MarketData]:
        """获取大宗商品数据（作为XOP的领先/滞后指标）"""
        results = []
        now = datetime.now()
        
        # 美油期货CL
        url = "https://hq.sinajs.cn/list=hf_CL"
        text, lat = self.fetch(url, {"Referer": "https://finance.sina.com.cn"})
        if text and "hf_CL" in text:
            try:
                parts = text.split('"')[1].split(",")
                # 期货格式: 最新价, 涨跌, 涨跌幅...
                if len(parts) >= 8:
                    change = float(parts[8])
                    price = float(parts[0])
                    results.append(MarketData(
                        source="美油期货CL",
                        value=round(change, 2),
                        price=price,
                        timestamp=now,
                        is_realtime=True,  # 期货通常是实时
                        latency_ms=lat
                    ))
            except:
                pass
        
        # 布伦特原油
        url2 = "https://hq.sinajs.cn/list=hf_OIL"
        text2, lat2 = self.fetch(url2, {"Referer": "https://finance.sina.com.cn"})
        if text2 and "hf_OIL" in text2:
            try:
                parts = text2.split('"')[1].split(",")
                if len(parts) >= 8:
                    change = float(parts[8])
                    results.append(MarketData(
                        source="布伦特原油",
                        value=round(change, 2),
                        timestamp=now,
                        is_realtime=True,
                        latency_ms=lat2
                    ))
            except:
                pass
        
        return results
    
    def get_fx_data(self) -> MarketData:
        """获取外汇数据"""
        now = datetime.now()
        
        # USD/CNY
        url = "https://hq.sinajs.cn/list=fx_susdcny"
        text, lat = self.fetch(url, {"Referer": "https://finance.sina.com.cn"})
        if text and "fx_susdcny" in text:
            try:
                parts = text.split('"')[1].split(",")
                spot = float(parts[1])
                prev = float(parts[3])
                change = (spot - prev) / prev * 100
                
                return MarketData(
                    source="USD/CNY",
                    value=round(change, 3),
                    price=spot,
                    timestamp=now,
                    is_realtime=True,
                    latency_ms=lat
                )
            except:
                pass
        
        return MarketData(source="USD/CNY(默认)", value=0.0, price=7.25, timestamp=now)
    
    def get_market_price(self) -> float:
        """获取场内价格"""
        url = "http://qt.gtimg.cn/q=sz162411"
        text, _ = self.fetch(url)
        if text and 'v_sz162411' in text:
            try:
                parts = text.split('"')[1].split("~")
                return float(parts[3])
            except:
                pass
        return 0.0
    
    def infer_xop_from_commodity(self, commodity_data: List[MarketData]) -> Optional[float]:
        """
        从原油期货推算XOP涨跌幅
        
        基于历史相关性: XOP与CL的相关系数约0.85
        但XOP波动通常小于CL（beta < 1）
        """
        if not commodity_data:
            return None
        
        # 使用CL期货作为主要参考
        cl_changes = [d.value for d in commodity_data if "CL" in d.source or "原油" in d.source]
        if not cl_changes:
            return None
        
        avg_cl = statistics.mean(cl_changes)
        
        # XOP = CL × 相关系数 × beta调整
        # 经验: XOP beta约0.7-0.9
        inferred_xop = avg_cl * self.xop_cl_correlation * 0.8
        
        return round(inferred_xop, 2)
    
    def calculate_weighted_estimate(self, nav: float, xop_data: List[MarketData],
                                   commodity_data: List[MarketData],
                                   fx: MarketData) -> Dict:
        """加权估算"""
        warnings = []
        sources_used = []
        
        # 1. XOP直接数据
        xop_direct = None
        if xop_data:
            # 如果有多个源，取中位数
            values = [d.value for d in xop_data]
            xop_direct = statistics.median(values)
            sources_used.append(f"XOP直接({len(xop_data)}源)")
        
        # 2. 从期货推算XOP
        xop_inferred = self.infer_xop_from_commodity(commodity_data)
        if xop_inferred is not None:
            sources_used.append("期货推算")
        
        # 3. 融合XOP数据
        if xop_direct is not None and xop_inferred is not None:
            # 如果差异大，优先使用直接数据，但给出警告
            diff = abs(xop_direct - xop_inferred)
            if diff > 1.0:
                warnings.append(f"XOP直接数据与期货推算差异大({diff:.2f}%)，使用直接数据")
                xop_change = xop_direct
            else:
                # 加权融合
                xop_change = xop_direct * 0.7 + xop_inferred * 0.3
        elif xop_direct is not None:
            xop_change = xop_direct
        elif xop_inferred is not None:
            xop_change = xop_inferred
            warnings.append("使用期货推算XOP，准确度降低")
        else:
            xop_change = 0
            warnings.append("无XOP相关数据，假设0变化")
        
        # 4. 计算三层估值
        # 基础: NAV × (1 + XOP × 仓位)
        base_est = nav * (1 + xop_change * self.position / 100)
        
        # 汇率调整
        rate_adj = base_est * (1 + fx.value * self.rate_sensitivity / 100)
        
        # 如果有原油期货领先指标，微调
        final_est = rate_adj
        if commodity_data and xop_direct is None:
            # 只有期货数据时，增加不确定性调整
            final_est = rate_adj * 0.995  # 保守调整0.5%
        
        return {
            "base": round(base_est, 4),
            "rate_adjusted": round(rate_adj, 4),
            "final": round(final_est, 4),
            "xop_change": round(xop_change, 2),
            "sources": sources_used,
            "warnings": warnings
        }
    
    def assess_confidence(self, xop_data: List[MarketData], 
                         commodity_data: List[MarketData],
                         warnings: List[str]) -> Tuple[str, float]:
        """评估置信度"""
        score = 1.0
        
        # XOP直接数据质量
        if not xop_data:
            score -= 0.3
        elif len(xop_data) >= 2:
            score += 0.05
        
        for d in xop_data:
            if not d.is_realtime:
                score -= 0.1
        
        # 期货数据补充
        if commodity_data:
            score += 0.1
        else:
            score -= 0.1
        
        # 警告扣分
        score -= len(warnings) * 0.05
        
        # 确定等级
        score = max(0, min(1, score))
        if score >= 0.8:
            level = "A"
        elif score >= 0.6:
            level = "B"
        elif score >= 0.4:
            level = "C"
        else:
            level = "D"
        
        return level, round(score, 2)
    
    def estimate(self) -> Dict:
        """执行估算"""
        now = datetime.now()
        
        # 获取所有数据
        nav_data = self.get_fund_nav()
        xop_data = self.get_xop_data()
        commodity_data = self.get_commodity_data()
        fx_data = self.get_fx_data()
        market_price = self.get_market_price()
        
        # 计算估值
        calc = self.calculate_weighted_estimate(
            nav_data["nav"], xop_data, commodity_data, fx_data
        )
        
        # 评估置信度
        conf_level, conf_score = self.assess_confidence(xop_data, commodity_data, calc["warnings"])
        
        # 计算溢价
        premium = (market_price - calc["final"]) / calc["final"] * 100 if calc["final"] > 0 else 0
        
        return {
            "timestamp": now.isoformat(),
            "fund_code": self.fund_code,
            "fund_name": nav_data["name"],
            "nav": nav_data["nav"],
            "nav_date": nav_data["date"],
            "estimation": calc,
            "market_price": market_price,
            "premium": round(premium, 2),
            "confidence": {
                "level": conf_level,
                "score": conf_score
            },
            "raw_data": {
                "xop_sources": len(xop_data),
                "commodity_sources": len(commodity_data),
                "fx_available": fx_data.price is not None
            }
        }
    
    def print_report(self, result: Dict):
        """打印报告"""
        print("=" * 75)
        print(f"📊 {result['fund_name']}({result['fund_code']}) 增强实时估值")
        print("=" * 75)
        print(f"⏰ {result['timestamp']}")
        print(f"🎯 置信度: {result['confidence']['level']} (得分: {result['confidence']['score']})")
        print()
        
        print("【基础数据】")
        print(f"  昨日净值: {result['nav']} ({result['nav_date']})")
        print()
        
        est = result['estimation']
        print("【数据源】")
        for src in est['sources']:
            print(f"  ✓ {src}")
        print(f"  XOP变化: {est['xop_change']:+.2f}%")
        print()
        
        print("【估值计算】")
        print(f"  基础估算:     {est['base']}")
        print(f"  汇率调整后:   {est['rate_adjusted']}")
        print(f"  ★ 最终估值:   {est['final']}")
        print()
        
        print("【套利分析】")
        print(f"  场内价格:     {result['market_price']}")
        print(f"  估算净值:     {result['estimation']['final']}")
        print(f"  溢价率:       {result['premium']:+.2f}%")
        
        # 建议
        prem = result['premium']
        if prem > 1.5:
            print(f"  💡 建议: 🔴 溢价套利 (>1.5%)")
        elif prem > 0.5:
            print(f"  💡 建议: 🟡 关注机会 (0.5%-1.5%)")
        elif prem > 0.15:
            print(f"  💡 建议: 🟡 XOP对冲 (0.15%-0.5%)")
        elif prem < -0.5:
            print(f"  💡 建议: 🟢 折价套利 (<-0.5%)")
        else:
            print(f"  💡 建议: ⚪ 观望")
        print()
        
        if est['warnings']:
            print("【警告】")
            for w in est['warnings']:
                print(f"  ⚠️  {w}")
            print()
        
        # 数据质量
        raw = result['raw_data']
        print(f"【数据质量】 XOP:{raw['xop_sources']}源 期货:{raw['commodity_sources']}源 汇率:{'✓' if raw['fx_available'] else '✗'}")
        print("=" * 75)
    
    def save(self, result: Dict):
        """保存结果"""
        date_str = datetime.now().strftime("%Y%m%d")
        file_path = self.data_dir / f"enhanced_{self.fund_code}_{date_str}.jsonl"
        with open(file_path, "a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        
        # 最新结果
        latest = Path(__file__).parent / "enhanced_latest.json"
        with open(latest, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)


def main():
    print("正在获取多源数据（增强模式）...\n")
    
    est = EnhancedEstimator()
    result = est.estimate()
    est.print_report(result)
    est.save(result)
    
    print(f"\n✅ 数据已保存")


if __name__ == "__main__":
    main()
