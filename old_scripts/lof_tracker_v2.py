#!/usr/bin/env python3
"""
LOF基金实时估值跟踪系统 V2
使用新浪财经等直接API，更快速可靠

核心公式:
实时净值(EST) = 前一交易日净值 × (1 + XOP涨跌幅 × 95%仓位) × 汇率系数

套利原则:
- 溢价 > 1.5% : 申购-卖出套利
- 折价 < -0.5% : 买入-赎回套利
- 溢价 > 0.15% + XOP对冲 : 无风险套利
"""

import json
import time
import asyncio
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Tuple


class LOFTrackerV2:
    """LOF实时估值跟踪器V2"""
    
    def __init__(self):
        self.fund_code = "162411"
        self.fund_name = "华宝油气"
        self.xop_symbol = "XOP"
        
        # 配置参数
        self.position_ratio = 0.95  # 仓位95%
        self.subscription_fee = 0.15  # 一折申购费0.15%
        self.redemption_fee = 0.5     # 赎回费0.5%
        self.trading_fee = 0.03       # 交易佣金0.03%
        
        # 数据目录
        self.data_dir = Path(__file__).parent / "tracking_data"
        self.data_dir.mkdir(exist_ok=True)
        
        # 缓存
        self._cache = {}
        self._cache_time = {}
        
    def _get(self, url: str, cache_key: str = None, cache_ttl: int = 30) -> Optional[Dict]:
        """带缓存的HTTP GET"""
        if cache_key and cache_key in self._cache_time:
            if time.time() - self._cache_time[cache_key] < cache_ttl:
                return self._cache[cache_key]
        
        try:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            resp.raise_for_status()
            data = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            
            if cache_key:
                self._cache[cache_key] = data
                self._cache_time[cache_key] = time.time()
            
            return data
        except Exception as e:
            print(f"请求失败 {url}: {e}")
            return None
    
    def get_fund_quote(self) -> Dict:
        """
        获取华宝油气场内实时行情
        使用新浪财经API
        """
        # 新浪基金API
        url = f"https://quotes.sina.cn/cn/api/quotes.php?symbol=sz{self.fund_code}&_={int(time.time()*1000)}"
        
        try:
            resp = requests.get(url, timeout=10, headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0"
            })
            # 新浪返回格式: var _ FundCode_ = {...}
            text = resp.text
            if "=" in text:
                json_str = text.split("=", 1)[1].strip().rstrip(";")
                data = json.loads(json_str)
                
                return {
                    "code": self.fund_code,
                    "name": data.get("name", self.fund_name),
                    "price": float(data.get("price", 0)),
                    "open": float(data.get("open", 0)),
                    "high": float(data.get("high", 0)),
                    "low": float(data.get("low", 0)),
                    "prev_close": float(data.get("prevclose", 0)),
                    "volume": int(data.get("volume", 0)),
                    "updated_at": datetime.now().isoformat(),
                }
        except Exception as e:
            print(f"获取基金行情失败: {e}")
        
        return {}
    
    def get_fund_nav(self) -> Optional[float]:
        """
        获取基金最新净值
        使用东方财富API
        """
        # 东方财富基金净值API
        url = f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo?pageIndex=1&pageSize=1&appType=ttjj&product=EFund&plat=Android&deviceid=123&Version=1&Fcodes={self.fund_code}"
        
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            
            if data.get("Datas") and len(data["Datas"]) > 0:
                fund_data = data["Datas"][0]
                nav = float(fund_data.get("NAV", 0))  # 单位净值
                return nav
        except Exception as e:
            print(f"获取净值失败: {e}")
        
        return None
    
    def get_xop_quote(self) -> Dict:
        """
        获取XOP实时行情
        XOP在美股交易，需要获取延时行情或前一个交易日数据
        """
        # 使用新浪财经的美股API
        url = f"https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var_XOP=/US_MN/us_list.php?symbol=XOP&_={int(time.time()*1000)}"
        
        try:
            resp = requests.get(url, timeout=10)
            text = resp.text
            
            # 解析JSONP
            if "=" in text:
                json_str = text.split("=", 1)[1].strip().rstrip(";")
                data = json.loads(json_str)
                
                if data and len(data) > 0:
                    stock = data[0]
                    price = float(stock.get("price", 0))
                    prev_close = float(stock.get("prevclose", price))
                    change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
                    
                    return {
                        "symbol": "XOP",
                        "price": price,
                        "prev_close": prev_close,
                        "change": price - prev_close,
                        "change_pct": change_pct,
                        "updated_at": datetime.now().isoformat(),
                    }
        except Exception as e:
            print(f"获取XOP行情失败: {e}")
        
        return {}
    
    def get_spsiop_index(self) -> Dict:
        """
        获取SPSIOP指数（华宝油气跟踪的指数）
        如果直接获取不到，用XOP替代
        """
        # SPSIOP是S&P Oil & Gas Exploration & Production Select Industry Index
        # 通常可以用XOP作为代理
        return self.get_xop_quote()
    
    def get_usd_cny_rate(self) -> Dict:
        """
        获取美元兑人民币汇率
        """
        # 新浪财经外汇API
        url = f"https://hq.sinajs.cn/list=fx_susdcny?_={int(time.time()*1000)}"
        
        try:
            resp = requests.get(url, timeout=10, headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0"
            })
            text = resp.text
            
            # 解析: var hq_str_fx_susdcny="美元/人民币,7.2345,..."
            if "=" in text:
                parts = text.split("=")[1].strip().strip('";').split(",")
                if len(parts) >= 5:
                    return {
                        "pair": "USD/CNY",
                        "spot": float(parts[1]),  # 即期汇率
                        "buy": float(parts[3]),   # 买入价
                        "sell": float(parts[5]),  # 卖出价
                        "updated_at": datetime.now().isoformat(),
                    }
        except Exception as e:
            print(f"获取汇率失败: {e}")
        
        # 返回默认值
        return {"pair": "USD/CNY", "spot": 7.25, "buy": 7.24, "sell": 7.26}
    
    def calculate_est(self, last_nav: float, xop_change_pct: float, 
                      usd_rate_change_pct: float = 0) -> Dict:
        """
        计算实时估值
        
        三种EST:
        1. 官方EST - 基于T-1收盘数据
        2. 参考EST - 基于官方EST + T日汇率变化
        3. 实时EST - 基于参考EST + XOP实时变化
        """
        # 官方EST (T-1数据)
        official_est = last_nav
        
        # XOP影响 (95%仓位)
        xop_impact = xop_change_pct * self.position_ratio
        
        # 汇率影响
        rate_impact = usd_rate_change_pct
        
        # 参考EST (官方EST + 汇率调整)
        reference_est = official_est * (1 + rate_impact / 100)
        
        # 实时EST (参考EST + XOP变化)
        realtime_est = reference_est * (1 + xop_impact / 100)
        
        return {
            "official_est": round(official_est, 4),
            "reference_est": round(reference_est, 4),
            "realtime_est": round(realtime_est, 4),
            "xop_change_pct": round(xop_change_pct, 2),
            "xop_impact": round(xop_impact, 2),
            "rate_change_pct": round(usd_rate_change_pct, 2),
            "rate_impact": round(rate_impact, 2),
        }
    
    def analyze_arbitrage(self, realtime_est: float, market_price: float) -> Dict:
        """
        分析套利机会
        """
        premium = (market_price - realtime_est) / realtime_est * 100
        premium_amount = market_price - realtime_est
        
        # 套利成本
        arb_cost = self.subscription_fee + self.trading_fee  # 溢价套利成本
        discount_cost = self.trading_fee + self.redemption_fee  # 折价套利成本
        
        # 套利建议
        suggestion = "观望"
        action = None
        
        if premium > 1.5:
            suggestion = "🔴 溢价套利机会"
            action = "场内申购 → T+2卖出"
            expected_return = premium - arb_cost
        elif premium > 0.15:
            suggestion = "🟡 XOP对冲套利"
            action = "申购 + 做空XOP"
            expected_return = premium - self.subscription_fee
        elif premium < -0.5:
            suggestion = "🟢 折价套利机会"
            action = "场内买入 → 赎回"
            expected_return = abs(premium) - discount_cost
        else:
            expected_return = 0
        
        return {
            "market_price": round(market_price, 4),
            "realtime_est": round(realtime_est, 4),
            "premium": round(premium, 2),
            "premium_pct": f"{premium:+.2f}%",
            "premium_amount": round(premium_amount, 4),
            "suggestion": suggestion,
            "action": action,
            "expected_return": round(expected_return, 2),
            "costs": {
                "subscription": self.subscription_fee,
                "redemption": self.redemption_fee,
                "trading": self.trading_fee,
            }
        }
    
    def track(self) -> Dict:
        """执行跟踪"""
        result = {
            "timestamp": datetime.now().isoformat(),
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
        }
        
        print("📊 正在获取数据...")
        
        # 1. 获取基金净值
        print("  - 获取基金净值...")
        last_nav = self.get_fund_nav()
        if not last_nav:
            result["error"] = "无法获取基金净值"
            return result
        result["last_nav"] = last_nav
        
        # 2. 获取场内价格
        print("  - 获取场内行情...")
        fund_quote = self.get_fund_quote()
        result["fund_quote"] = fund_quote
        market_price = fund_quote.get("price", last_nav)
        
        # 3. 获取XOP行情
        print("  - 获取XOP行情...")
        xop_quote = self.get_xop_quote()
        result["xop_quote"] = xop_quote
        xop_change_pct = xop_quote.get("change_pct", 0)
        
        # 4. 获取汇率
        print("  - 获取汇率...")
        rate_data = self.get_usd_cny_rate()
        result["rate"] = rate_data
        
        # 5. 计算估值
        est = self.calculate_est(last_nav, xop_change_pct)
        result["estimation"] = est
        
        # 6. 套利分析
        arb = self.analyze_arbitrage(est["realtime_est"], market_price)
        result["arbitrage"] = arb
        
        # 7. 保存数据
        self._save(result)
        
        return result
    
    def _save(self, data: Dict):
        """保存数据"""
        date_str = datetime.now().strftime("%Y%m%d")
        file_path = self.data_dir / f"tracking_v2_{self.fund_code}_{date_str}.jsonl"
        
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    
    def print_report(self, result: Dict):
        """打印报告"""
        print("\n" + "=" * 70)
        print(f"📈 {result['fund_name']}({result['fund_code']}) 实时估值报告")
        print("=" * 70)
        print(f"⏰ 时间: {result['timestamp']}")
        print()
        
        print("【净值信息】")
        print(f"  最新净值: {result.get('last_nav', 'N/A')}")
        if result.get("fund_quote"):
            q = result["fund_quote"]
            print(f"  场内价格: {q.get('price', 'N/A')}")
            print(f"  成交量: {q.get('volume', 'N/A')}")
        print()
        
        if result.get("xop_quote"):
            x = result["xop_quote"]
            print("【XOP行情】(美股)")
            print(f"  价格: ${x.get('price', 'N/A')}")
            print(f"  涨跌: {x.get('change_pct', 0):+.2f}%")
            print()
        
        if result.get("estimation"):
            e = result["estimation"]
            print("【估值计算】")
            print(f"  官方EST: {e['official_est']}")
            print(f"  参考EST: {e['reference_est']}")
            print(f"  实时EST: {e['realtime_est']}")
            print(f"  XOP影响: {e['xop_impact']:+.2f}%")
            print()
        
        if result.get("arbitrage"):
            a = result["arbitrage"]
            print("【套利分析】")
            print(f"  场内价格: {a['market_price']}")
            print(f"  实时估值: {a['realtime_est']}")
            print(f"  溢价率: {a['premium_pct']}")
            print()
            print(f"  💡 {a['suggestion']}")
            if a.get("action"):
                print(f"  📝 操作建议: {a['action']}")
            if a.get("expected_return"):
                print(f"  💰 预期收益: {a['expected_return']:.2f}%")
            print()
        
        print("=" * 70)
        
        # 核心原则提醒
        print("\n【套利原则】")
        print("  📌 折价不申购，溢价不赎回")
        print("  📌 上涨赚净值，下跌赚溢价")
        print("  📌 不要怂，就是干！（但要计算好成本）")
        print()


def main():
    tracker = LOFTrackerV2()
    
    try:
        result = tracker.track()
        
        if result.get("error"):
            print(f"❌ 错误: {result['error']}")
            return
        
        tracker.print_report(result)
        
        # 保存JSON
        output_file = Path(__file__).parent / "latest_tracking.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 数据已保存: {output_file}")
        
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
