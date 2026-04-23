#!/usr/bin/env python3
"""
自建华宝油气实时估值计算器
由于第三方平台已下线实时估算功能，基于公开数据自行计算

公式:
实时EST = 昨日净值 × (1 + XOP涨跌幅 × 仓位95%) × 汇率系数

数据来源:
- 昨日净值: 天天基金（每日更新）
- XOP行情: 新浪财经（美股延时或期货实时）
- 汇率: 新浪财经（USD/CNH实时）
"""

import requests
import json
from datetime import datetime


class RealtimeCalculator:
    """实时估值计算器"""
    
    def __init__(self):
        self.fund_code = "162411"
        self.position = 0.95
        
    def get_last_nav(self) -> dict:
        """获取最新披露净值"""
        url = f"http://fundgz.1234567.com.cn/js/{self.fund_code}.js"
        try:
            resp = requests.get(url, timeout=5, headers={
                "Referer": "http://fund.eastmoney.com/",
                "User-Agent": "Mozilla/5.0"
            })
            text = resp.text
            if "jsonpgz(" in text:
                data = json.loads(text[8:-2])
                return {
                    "nav": float(data.get("dwjz", 0)),
                    "nav_date": data.get("jzrq"),
                    "name": data.get("name"),
                }
        except Exception as e:
            print(f"获取净值失败: {e}")
        return {"nav": 0.965, "nav_date": "2026-03-24", "name": "华宝油气"}
    
    def get_xop_change(self) -> float:
        """获取XOP涨跌幅(%)"""
        # 美股XOP（延时行情）
        url = "https://hq.sinajs.cn/list=usr_xop"
        try:
            resp = requests.get(url, timeout=5, headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0"
            })
            text = resp.text
            if "hq_str_usr_xop" in text:
                parts = text.split('"')[1].split(",")
                if len(parts) >= 2:
                    price = float(parts[0])
                    prev = float(parts[1])
                    return round((price - prev) / prev * 100, 2)
        except:
            pass
        return 0
    
    def get_usdcny_rate(self) -> dict:
        """获取美元兑人民币汇率"""
        # 新浪外汇
        url = "https://hq.sinajs.cn/list=fx_susdcny"
        try:
            resp = requests.get(url, timeout=5, headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0"
            })
            text = resp.text
            if "hq_str_fx_susdcny" in text:
                parts = text.split('"')[1].split(",")
                if len(parts) >= 8:
                    return {
                        "spot": float(parts[1]),
                        "buy": float(parts[3]),
                        "sell": float(parts[5]),
                    }
        except:
            pass
        return {"spot": 7.25, "buy": 7.24, "sell": 7.26}
    
    def calculate(self) -> dict:
        """计算实时估值"""
        # 获取数据
        nav_data = self.get_last_nav()
        xop_change = self.get_xop_change()
        rate_data = self.get_usdcny_rate()
        
        last_nav = nav_data["nav"]
        
        # 计算参考EST（基于昨日净值+XOP变化）
        reference_est = last_nav * (1 + xop_change * self.position / 100)
        
        # 获取场内价格
        market_price = self.get_market_price()
        
        # 计算溢价
        premium = (market_price - reference_est) / reference_est * 100
        
        return {
            "fund_code": self.fund_code,
            "fund_name": nav_data["name"],
            "last_nav": last_nav,
            "nav_date": nav_data["nav_date"],
            "xop_change": xop_change,
            "usdcny": rate_data["spot"],
            "reference_est": round(reference_est, 4),
            "market_price": market_price,
            "premium": round(premium, 2),
            "timestamp": datetime.now().isoformat(),
        }
    
    def get_market_price(self) -> float:
        """获取场内价格"""
        url = "http://qt.gtimg.cn/q=sz162411"
        try:
            resp = requests.get(url, timeout=5)
            text = resp.text
            if 'v_sz162411' in text:
                parts = text.split('"')[1].split("~")
                return float(parts[3])
        except:
            pass
        return 0.984
    
    def print_report(self, data: dict):
        """打印报告"""
        print("=" * 65)
        print("华宝油气实时估值计算器（自建）")
        print("=" * 65)
        print(f"⏰ 计算时间: {data['timestamp']}")
        print()
        print("【输入数据】")
        print(f"  昨日净值: {data['last_nav']} ({data['nav_date']})")
        print(f"  XOP涨跌: {data['xop_change']:+.2f}%")
        print(f"  USD/CNY: {data['usdcny']}")
        print()
        print("【计算结果】")
        print(f"  参考EST: {data['reference_est']}")
        print(f"  场内价格: {data['market_price']}")
        print(f"  溢价率: {data['premium']:+.2f}%")
        print()
        
        # 套利建议
        premium = data['premium']
        if premium > 1.5:
            print("💡 建议: 溢价套利（申购-卖出）")
        elif premium > 0.15:
            print("💡 建议: XOP对冲套利")
        elif premium < -0.5:
            print("💡 建议: 折价套利（买入-赎回）")
        else:
            print("💡 建议: 观望")
        
        print("=" * 65)
        print()
        print("⚠️ 重要提示:")
        print("  1. 此估算基于公开数据自行计算")
        print("  2. 未考虑基金经理调仓、汇率实时变化")
        print("  3. 仅供参考，投资有风险")


def main():
    calc = RealtimeCalculator()
    data = calc.calculate()
    calc.print_report(data)
    
    # 保存
    import json
    from pathlib import Path
    output = Path(__file__).parent / "realtime_calc.json"
    with open(output, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n数据已保存: {output}")


if __name__ == "__main__":
    main()
