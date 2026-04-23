#!/usr/bin/env python3
"""
LOF基金实时估值跟踪系统
针对华宝油气(162411)的实时净值估算和套利分析

原理：
1. 华宝油气跟踪SPSIOP指数，XOP是同一指数的美股ETF
2. 通过XOP实时价格变化推算华宝油气净值变化
3. 结合实时汇率进行估值修正

公式：
实时EST = 前一交易日净值 × (1 + XOP涨跌幅 × 仓位比例) × 汇率调整系数

作者参考：https://palmmicro.com/woody/res/sz162411cn.php
"""

import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict

import akshare as ak
import pandas as pd


class LOFRealTimeTracker:
    """LOF基金实时估值跟踪器"""
    
    def __init__(self, fund_code: str = "162411"):
        self.fund_code = fund_code
        self.fund_name = "华宝油气"
        self.index_etf = "XOP"  # 美股ETF
        self.position_ratio = 0.95  # 仓位比例（LOF通常95%）
        
        # 数据缓存
        self.cache = {}
        self.cache_time = {}
        self.cache_duration = 60  # 缓存60秒
        
        # 历史数据保存
        self.data_dir = Path(__file__).parent / "tracking_data"
        self.data_dir.mkdir(exist_ok=True)
        
    def _get_cache(self, key: str) -> Optional[any]:
        """获取缓存数据"""
        if key in self.cache_time:
            if datetime.now() - self.cache_time[key] < timedelta(seconds=self.cache_duration):
                return self.cache[key]
        return None
    
    def _set_cache(self, key: str, value: any):
        """设置缓存数据"""
        self.cache[key] = value
        self.cache_time[key] = datetime.now()
    
    def get_fund_info(self) -> Dict:
        """获取基金基本信息"""
        cache_key = f"fund_info_{self.fund_code}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
            
        try:
            # 获取LOF基金实时行情
            df = ak.fund_etf_hist_em(
                symbol=self.fund_code,
                period="daily",
                start_date=(datetime.now() - timedelta(days=7)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
                adjust=""
            )
            if not df.empty:
                latest = df.iloc[-1]
                info = {
                    "code": self.fund_code,
                    "name": self.fund_name,
                    "latest_price": float(latest["收盘"]),
                    "latest_nav": float(latest.get("净值", latest["收盘"])),  # 如API返回净值
                    "date": latest["日期"],
                    "volume": int(latest["成交量"]),
                }
                self._set_cache(cache_key, info)
                return info
        except Exception as e:
            print(f"获取基金信息失败: {e}")
            
        return {"code": self.fund_code, "name": self.fund_name}
    
    def get_last_nav(self) -> Optional[float]:
        """获取前一交易日净值"""
        cache_key = f"last_nav_{self.fund_code}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
            
        try:
            # 通过东方财富获取基金净值
            df = ak.fund_open_fund_info_em(symbol=self.fund_code, indicator="单位净值走势")
            if not df.empty:
                # 获取最新净值
                latest_nav = float(df.iloc[-1]["单位净值"])
                self._set_cache(cache_key, latest_nav)
                return latest_nav
        except Exception as e:
            print(f"获取净值失败: {e}")
            
        return None
    
    def get_xop_quote(self) -> Dict:
        """获取XOP实时行情（美股）"""
        cache_key = "xop_quote"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
            
        try:
            # 使用akshare获取美股行情
            # XOP在美股市场
            df = ak.stock_us_spot_em()
            xop_data = df[df["名称"].str.contains("SPDR S&P Oil & Gas Explor & Prod", case=False, na=False)]
            
            if not xop_data.empty:
                row = xop_data.iloc[0]
                quote = {
                    "symbol": "XOP",
                    "name": "SPDR S&P Oil & Gas Exploration & Production ETF",
                    "price": float(row["最新价"]),
                    "change": float(row.get("涨跌额", 0)),
                    "change_pct": float(row.get("涨跌幅", 0)),
                    "prev_close": float(row.get("昨收", row["最新价"])),
                    "updated_at": datetime.now().isoformat(),
                }
                self._set_cache(cache_key, quote)
                return quote
        except Exception as e:
            print(f"获取XOP行情失败: {e}")
            
        return {}
    
    def get_usd_cny_rate(self) -> Optional[float]:
        """获取美元兑人民币汇率（中间价）"""
        cache_key = "usd_cny_rate"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
            
        try:
            # 获取外汇行情
            df = ak.currency_boc_sina(symbol="美元")
            if not df.empty:
                # 获取最新汇率
                rate = float(df.iloc[0]["买入价"])  # 使用买入价作为参考
                self._set_cache(cache_key, rate)
                return rate
        except Exception as e:
            print(f"获取汇率失败: {e}")
            
        # 使用默认汇率
        return 7.2
    
    def calculate_realtime_est(self, last_nav: float, xop_change_pct: float, 
                               usd_rate_change: float = 0) -> Dict:
        """
        计算实时估值(EST)
        
        公式:
        EST = 前一交易日净值 × (1 + XOP涨跌幅 × 仓位比例) × (1 + 汇率变化)
        
        Args:
            last_nav: 前一交易日净值
            xop_change_pct: XOP涨跌幅(%)
            usd_rate_change: 美元兑人民币汇率变化(%)
        
        Returns:
            估值结果字典
        """
        # XOP影响（考虑95%仓位）
        xop_impact = xop_change_pct * self.position_ratio / 100
        
        # 汇率影响（简化计算）
        rate_impact = usd_rate_change / 100 if usd_rate_change else 0
        
        # 计算实时估值
        realtime_est = last_nav * (1 + xop_impact) * (1 + rate_impact)
        
        # 三种EST定义
        official_est = last_nav  # 官方估值（基于前一交易日收盘）
        reference_est = realtime_est  # 参考估值（用于套利决策）
        
        return {
            "last_nav": last_nav,
            "official_est": official_est,
            "reference_est": reference_est,
            "realtime_est": realtime_est,
            "xop_change_pct": xop_change_pct,
            "xop_impact": xop_impact * 100,  # 转换为百分比
            "rate_impact": rate_impact * 100,
            "calculated_at": datetime.now().isoformat(),
        }
    
    def get_arbitrage_opportunity(self, realtime_est: float, 
                                   market_price: float) -> Dict:
        """
        分析套利机会
        
        Returns:
            溢价率/折价率及套利建议
        """
        premium = (market_price - realtime_est) / realtime_est * 100
        
        # 套利成本
        subscription_cost = 1.5  # 申购费1.5%（一折后0.15%）
        redemption_cost = 0.5    # 赎回费0.5%
        trading_cost = 0.03      # 交易佣金0.03%
        
        # 套利建议
        suggestion = "观望"
        if premium > 1.5:
            suggestion = "溢价套利机会（申购-卖出）"
        elif premium < -0.8:
            suggestion = "折价套利机会（买入-赎回）"
        elif premium > 0.15:  # 考虑一折申购费
            suggestion = "可考虑XOP对冲套利"
        
        return {
            "market_price": market_price,
            "realtime_est": realtime_est,
            "premium": premium,
            "premium_pct": f"{premium:.2f}%",
            "suggestion": suggestion,
            "subscription_cost": subscription_cost,
            "redemption_cost": redemption_cost,
        }
    
    def track(self) -> Dict:
        """执行一次跟踪"""
        result = {
            "timestamp": datetime.now().isoformat(),
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
        }
        
        # 1. 获取前一交易日净值
        last_nav = self.get_last_nav()
        if not last_nav:
            result["error"] = "无法获取最新净值"
            return result
        result["last_nav"] = last_nav
        
        # 2. 获取XOP实时行情
        xop_quote = self.get_xop_quote()
        if not xop_quote:
            result["warning"] = "无法获取XOP行情，使用昨日数据估算"
            xop_change_pct = 0
        else:
            xop_change_pct = xop_quote.get("change_pct", 0)
            result["xop_quote"] = xop_quote
        
        # 3. 获取汇率
        usd_rate = self.get_usd_cny_rate()
        result["usd_cny_rate"] = usd_rate
        
        # 4. 计算实时估值
        est_result = self.calculate_realtime_est(last_nav, xop_change_pct)
        result["estimation"] = est_result
        
        # 5. 获取场内价格
        fund_info = self.get_fund_info()
        market_price = fund_info.get("latest_price", last_nav)
        result["market_price"] = market_price
        
        # 6. 分析套利机会
        arb_result = self.get_arbitrage_opportunity(
            est_result["realtime_est"], market_price
        )
        result["arbitrage"] = arb_result
        
        # 7. 保存数据
        self._save_data(result)
        
        return result
    
    def _save_data(self, data: Dict):
        """保存跟踪数据到文件"""
        date_str = datetime.now().strftime("%Y%m%d")
        file_path = self.data_dir / f"tracking_{self.fund_code}_{date_str}.jsonl"
        
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    
    def print_report(self, result: Dict):
        """打印跟踪报告"""
        print("=" * 60)
        print(f"LOF实时估值跟踪报告 - {result['fund_name']}({result['fund_code']})")
        print("=" * 60)
        print(f"时间: {result['timestamp']}")
        print()
        
        print("【净值信息】")
        print(f"  前一交易日净值: {result.get('last_nav', 'N/A')}")
        print()
        
        if "xop_quote" in result:
            xop = result["xop_quote"]
            print("【XOP行情】(美股)")
            print(f"  价格: ${xop.get('price', 'N/A')}")
            print(f"  涨跌: {xop.get('change_pct', 'N/A')}%")
            print()
        
        if "estimation" in result:
            est = result["estimation"]
            print("【估值计算】")
            print(f"  官方EST (T-1): {est['official_est']:.4f}")
            print(f"  参考EST (实时): {est['reference_est']:.4f}")
            print(f"  XOP影响: {est['xop_impact']:.2f}%")
            print()
        
        if "arbitrage" in result:
            arb = result["arbitrage"]
            print("【套利分析】")
            print(f"  场内价格: {arb['market_price']:.4f}")
            print(f"  实时估值: {arb['realtime_est']:.4f}")
            print(f"  溢价率: {arb['premium_pct']}")
            print()
            print(f"  💡 建议: {arb['suggestion']}")
        
        print("=" * 60)


def main():
    """主函数"""
    tracker = LOFRealTimeTracker(fund_code="162411")
    
    print("正在获取数据...")
    result = tracker.track()
    
    if "error" in result:
        print(f"错误: {result['error']}")
        return
    
    tracker.print_report(result)
    
    # 保存JSON
    output_file = Path(__file__).parent / "latest_tracking.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n数据已保存到: {output_file}")


if __name__ == "__main__":
    main()
