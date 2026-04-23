#!/usr/bin/env python3
"""
LOF基金实时估值跟踪系统 - 最终版
华宝油气(162411)实时套利分析工具

数据源:
- 基金净值/估算: 天天基金网
- 场内价格: 新浪财经
- XOP行情: 新浪财经
- 汇率: 新浪财经

核心公式:
实时溢价率 = (场内价格 - 实时估算净值) / 实时估算净值 × 100%

套利策略:
1. 溢价套利: 场内价格 > 净值 + 成本 (约1.8%)
2. 折价套利: 场内价格 < 净值 - 成本 (约0.8%)
3. XOP对冲: 溢价 > 0.15%时，申购+XOP做空

使用方法:
    python3 lof_tracker.py              # 单次查询
    python3 lof_tracker.py --watch      # 持续监控
    python3 lof_tracker.py --notify 1   # 溢价>1%时通知
"""

import json
import time
import argparse
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


class LOFTracker:
    """LOF基金实时估值跟踪器"""
    
    # 基金配置
    FUNDS = {
        "162411": {
            "name": "华宝油气",
            "index": "SPSIOP",
            "etf": "XOP",
            "position": 0.95,
            "exchange": "sz",
        },
        "161130": {
            "name": "纳指LOF",
            "index": "NDX",
            "etf": "QQQ",
            "position": 0.95,
            "exchange": "sz",
        },
        "161128": {
            "name": "标普科技LOF",
            "index": "SPX",
            "etf": "XLK",
            "position": 0.95,
            "exchange": "sz",
        },
    }
    
    # 套利成本
    COSTS = {
        "subscription": 0.15,   # 一折申购费 0.15%
        "redemption": 0.5,      # 赎回费 0.5%
        "trading": 0.03,        # 交易佣金 0.03%
    }
    
    def __init__(self, fund_code: str = "162411"):
        self.fund_code = fund_code
        self.config = self.FUNDS.get(fund_code, self.FUNDS["162411"])
        self.data_dir = Path(__file__).parent / "tracking_data"
        self.data_dir.mkdir(exist_ok=True)
    
    def get_fund_data(self) -> Optional[Dict]:
        """
        获取基金净值和估算数据
        来源: 天天基金网
        """
        url = f"http://fundgz.1234567.com.cn/js/{self.fund_code}.js"
        
        try:
            resp = requests.get(url, timeout=10, headers={
                "Referer": "http://fund.eastmoney.com/",
                "User-Agent": "Mozilla/5.0"
            })
            
            # 解析JSONP: jsonpgz({...})
            text = resp.text
            if text.startswith("jsonpgz("):
                json_str = text[8:].rstrip(");")
                data = json.loads(json_str)
                
                return {
                    "code": data.get("fundcode"),
                    "name": data.get("name"),
                    "nav_date": data.get("jzrq"),           # 净值日期
                    "nav": float(data.get("dwjz", 0)),      # 单位净值
                    "est_nav": float(data.get("gsz", 0)),   # 估算净值
                    "est_change": data.get("gszzl"),        # 估算涨跌幅
                    "est_time": data.get("gztime"),         # 估算时间
                    "source": "天天基金",
                    "updated_at": datetime.now().isoformat(),
                }
        except Exception as e:
            print(f"获取基金数据失败: {e}")
        
        return None
    
    def get_market_price(self) -> Optional[Dict]:
        """
        获取场内实时价格
        来源: 腾讯财经
        """
        exchange = self.config["exchange"]
        url = f"http://qt.gtimg.cn/q={exchange}{self.fund_code}"
        
        try:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0"
            })
            
            # 解析: v_sz162411="51~华宝油气LOF~162411~0.984~0.951~0.969~..."
            text = resp.text
            var_name = f'v_{exchange}{self.fund_code}'
            if var_name in text:
                parts = text.split('"')[1].split("~")
                if len(parts) >= 10:
                    return {
                        "name": parts[1],
                        "code": parts[2],
                        "price": float(parts[3]),       # 当前价格
                        "prev_close": float(parts[4]),  # 昨收
                        "open": float(parts[5]),        # 开盘价
                        "volume": int(parts[6]),        # 成交量
                        "high": float(parts[33]),       # 最高价
                        "low": float(parts[34]),        # 最低价
                        "updated_at": datetime.now().isoformat(),
                    }
        except Exception as e:
            print(f"获取场内价格失败: {e}")
        
        return None
    
    def get_xop_data(self) -> Optional[Dict]:
        """
        获取XOP行情(美股)
        """
        url = "https://hq.sinajs.cn/list=usr_xop"
        
        try:
            resp = requests.get(url, timeout=10, headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0"
            })
            
            text = resp.text
            if "hq_str_usr_xop" in text:
                parts = text.split('"')[1].split(",")
                if len(parts) >= 5:
                    price = float(parts[0])
                    prev_close = float(parts[1])
                    change_pct = (price - prev_close) / prev_close * 100
                    
                    return {
                        "symbol": "XOP",
                        "price": price,
                        "prev_close": prev_close,
                        "change_pct": round(change_pct, 2),
                        "updated_at": datetime.now().isoformat(),
                    }
        except Exception as e:
            print(f"获取XOP数据失败: {e}")
        
        return None
    
    def calculate_premium(self, market_price: float, est_nav: float) -> Dict:
        """
        计算溢价率和套利分析
        """
        premium = (market_price - est_nav) / est_nav * 100
        premium_amount = market_price - est_nav
        
        # 套利成本
        premium_cost = self.COSTS["subscription"] + self.COSTS["trading"]
        discount_cost = self.COSTS["trading"] + self.COSTS["redemption"]
        
        # 分析套利机会
        if premium > 1.5:
            opportunity = {
                "type": "premium",
                "action": "申购-卖出",
                "profit": round(premium - premium_cost, 2),
                "risk": "T+2期间净值下跌风险",
            }
        elif premium > 0.15:
            opportunity = {
                "type": "hedge",
                "action": "申购+XOP做空",
                "profit": round(premium - self.COSTS["subscription"], 2),
                "risk": "XOP基差风险",
            }
        elif premium < -0.5:
            opportunity = {
                "type": "discount",
                "action": "买入-赎回",
                "profit": round(abs(premium) - discount_cost, 2),
                "risk": "T+1赎回资金占用",
            }
        else:
            opportunity = None
        
        return {
            "market_price": round(market_price, 4),
            "est_nav": round(est_nav, 4),
            "premium": round(premium, 2),
            "premium_pct": f"{premium:+.2f}%",
            "premium_amount": round(premium_amount, 4),
            "opportunity": opportunity,
            "costs": self.COSTS,
        }
    
    def track(self) -> Dict:
        """执行跟踪"""
        result = {
            "timestamp": datetime.now().isoformat(),
            "fund_code": self.fund_code,
            "fund_name": self.config["name"],
        }
        
        # 1. 获取基金数据
        fund_data = self.get_fund_data()
        if not fund_data:
            result["error"] = "无法获取基金数据"
            return result
        result["fund"] = fund_data
        
        # 2. 获取场内价格
        market_data = self.get_market_price()
        if not market_data:
            result["error"] = "无法获取场内价格"
            return result
        result["market"] = market_data
        
        # 3. 获取XOP数据(可选)
        xop_data = self.get_xop_data()
        if xop_data:
            result["xop"] = xop_data
        
        # 4. 计算溢价率
        premium_data = self.calculate_premium(
            market_data["price"],
            fund_data["est_nav"]
        )
        result["premium"] = premium_data
        
        # 5. 保存数据
        self._save(result)
        
        return result
    
    def _save(self, data: Dict):
        """保存跟踪数据"""
        date_str = datetime.now().strftime("%Y%m%d")
        file_path = self.data_dir / f"{self.fund_code}_{date_str}.jsonl"
        
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    
    def print_report(self, result: Dict):
        """打印报告"""
        print("\n" + "=" * 65)
        print(f"📊 {result['fund_name']}({result['fund_code']}) 实时估值报告")
        print("=" * 65)
        print(f"⏰ {result['timestamp']}")
        print()
        
        # 基金数据
        if "fund" in result:
            f = result["fund"]
            print("【基金净值】")
            print(f"  最新净值: {f['nav']} ({f['nav_date']})")
            print(f"  估算净值: {f['est_nav']} ({f['est_change']}%)")
            print(f"  估算时间: {f['est_time']}")
            print()
        
        # 场内价格
        if "market" in result:
            m = result["market"]
            print("【场内交易】")
            print(f"  当前价格: {m['price']}")
            print(f"  开盘价: {m['open']}")
            print(f"  最高价: {m['high']}")
            print(f"  最低价: {m['low']}")
            print(f"  成交量: {m['volume']:,}")
            print()
        
        # XOP数据
        if "xop" in result:
            x = result["xop"]
            print("【XOP行情】(参考)")
            print(f"  价格: ${x['price']}")
            print(f"  涨跌: {x['change_pct']:+.2f}%")
            print()
        
        # 溢价分析
        if "premium" in result:
            p = result["premium"]
            print("【套利分析】")
            print(f"  场内价格: {p['market_price']}")
            print(f"  估算净值: {p['est_nav']}")
            print(f"  溢价率: {p['premium_pct']}")
            print()
            
            if p.get("opportunity"):
                opp = p["opportunity"]
                print(f"  🎯 套利机会: {opp['type'].upper()}")
                print(f"  📝 操作建议: {opp['action']}")
                print(f"  💰 预期收益: {opp['profit']:.2f}%")
                print(f"  ⚠️  风险提示: {opp['risk']}")
            else:
                print("  ⏸️  当前无明显套利机会")
            print()
        
        print("=" * 65)
        print("\n【套利原则】")
        print("  📌 折价不申购，溢价不赎回")
        print("  📌 上涨赚净值，下跌赚溢价")
        print("  📌 赢了会所嫩模，输了下海挖沙！")
        print()


def main():
    parser = argparse.ArgumentParser(description="LOF基金实时估值跟踪")
    parser.add_argument("--code", default="162411", help="基金代码(默认:162411)")
    parser.add_argument("--watch", action="store_true", help="持续监控模式")
    parser.add_argument("--interval", type=int, default=60, help="监控间隔(秒)")
    parser.add_argument("--notify", type=float, help="溢价超过N%时通知")
    args = parser.parse_args()
    
    tracker = LOFTracker(fund_code=args.code)
    
    if args.watch:
        print(f"开始持续监控 {tracker.config['name']}({args.code})...")
        print(f"刷新间隔: {args.interval}秒")
        print("按 Ctrl+C 停止\n")
        
        try:
            while True:
                result = tracker.track()
                
                if result.get("error"):
                    print(f"❌ {result['error']}")
                else:
                    tracker.print_report(result)
                    
                    # 通知检查
                    if args.notify and "premium" in result:
                        premium = result["premium"]["premium"]
                        if abs(premium) > args.notify:
                            print(f"\n🔔 提醒: 溢价率达到 {premium:.2f}%!")
                
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\n监控已停止")
    else:
        # 单次查询
        result = tracker.track()
        
        if result.get("error"):
            print(f"❌ 错误: {result['error']}")
            return
        
        tracker.print_report(result)
        
        # 保存JSON
        output_file = Path(__file__).parent / f"{args.code}_latest.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 数据已保存: {output_file}")


if __name__ == "__main__":
    main()
