#!/usr/bin/env python3
"""
华宝油气手动估值计算器
当自动数据源受限时，从Palmmicro网站或其他渠道获取数据后手动计算

使用方法:
    # 命令行参数
    python3 manual_calculator.py --nav 0.965 --xop 2.5 --price 0.98
    
    # 交互式输入
    python3 manual_calculator.py --interactive
    
    # 从Palmmicro页面复制数据
    python3 manual_calculator.py --palmmicro
"""

import argparse
from datetime import datetime
from typing import Optional


class ManualCalculator:
    """手动计算器"""
    
    def __init__(self):
        self.position = 0.95
        self.rate_sensitivity = 0.8
    
    def calculate(self, nav: float, xop_change: float, rate_change: float = 0,
                  market_price: Optional[float] = None) -> dict:
        """计算估值"""
        
        # 基础估算
        base_est = nav * (1 + xop_change * self.position / 100)
        
        # 汇率调整
        rate_adj = base_est * (1 + rate_change * self.rate_sensitivity / 100)
        
        # 最终估算
        final_est = rate_adj
        
        # 溢价计算
        premium = None
        if market_price:
            premium = (market_price - final_est) / final_est * 100
        
        return {
            "nav": nav,
            "xop_change": xop_change,
            "rate_change": rate_change,
            "base_est": round(base_est, 4),
            "rate_adjusted": round(rate_adj, 4),
            "final_est": round(final_est, 4),
            "market_price": market_price,
            "premium": round(premium, 2) if premium is not None else None,
        }
    
    def print_result(self, result: dict):
        """打印结果"""
        print("=" * 60)
        print("华宝油气手动估值计算器")
        print("=" * 60)
        print(f"⏰ 计算时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        print("【输入参数】")
        print(f"  昨日净值: {result['nav']}")
        print(f"  XOP涨跌: {result['xop_change']:+.2f}%")
        print(f"  汇率变化: {result['rate_change']:+.3f}%")
        print()
        
        print("【估值计算】")
        print(f"  基础估算:   {result['base_est']}")
        print(f"  汇率调整:   {result['rate_adjusted']}")
        print(f"  ★ 最终估值: {result['final_est']}")
        print()
        
        if result['market_price']:
            print("【套利分析】")
            print(f"  场内价格: {result['market_price']}")
            print(f"  估算净值: {result['final_est']}")
            print(f"  溢价率:   {result['premium']:+.2f}%")
            
            # 建议
            prem = result['premium']
            if prem > 1.5:
                print(f"  💡 建议: 🔴 溢价套利（申购-卖出）")
            elif prem > 0.15:
                print(f"  💡 建议: 🟡 XOP对冲套利")
            elif prem < -0.5:
                print(f"  💡 建议: 🟢 折价套利（买入-赎回）")
            else:
                print(f"  💡 建议: ⚪ 观望")
            print()
        
        print("=" * 60)
        print("提示: 此计算基于手动输入数据，准确性取决于输入质量")
        print("=" * 60)
    
    def interactive(self):
        """交互式输入"""
        print("=" * 60)
        print("华宝油气估值计算器 - 交互模式")
        print("=" * 60)
        print()
        print("请从以下渠道获取数据后输入:")
        print("  1. Palmmicro网站: https://palmmicro.com/woody/res/sz162411cn.php")
        print("  2. 天天基金APP: 基金详情页")
        print("  3. 券商APP: 美股行情")
        print()
        
        try:
            nav = float(input("昨日净值 (如 0.9650): "))
            xop = float(input("XOP涨跌幅 % (如 2.5): "))
            rate = input("汇率变化 % (默认0): ").strip()
            rate = float(rate) if rate else 0
            price = input("场内价格 (可选): ").strip()
            price = float(price) if price else None
            
            result = self.calculate(nav, xop, rate, price)
            print()
            self.print_result(result)
            
        except ValueError as e:
            print(f"输入错误: {e}")
    
    def from_palmmicro_template(self):
        """Palmmicro数据录入模板"""
        print("=" * 60)
        print("从Palmmicro网站录入数据")
        print("=" * 60)
        print()
        print("请访问: https://palmmicro.com/woody/res/sz162411cn.php")
        print()
        print("页面上有以下关键数据:")
        print("  - 官方EST (T-1)")
        print("  - 参考EST (T)")
        print("  - 实时EST")
        print("  - XOP价格")
        print("  - 汇率")
        print()
        print("请输入Palmmicro页面显示的数据:")
        
        try:
            official_est = float(input("官方EST (昨日估值): "))
            reference_est = float(input("参考EST (今日估值，若无则填官方EST): "))
            xop_price = float(input("XOP当前价格: "))
            xop_prev = float(input("XOP昨收价格: "))
            
            xop_change = (xop_price - xop_prev) / xop_prev * 100
            
            price = input("华宝油气场内价格: ").strip()
            price = float(price) if price else None
            
            # 使用参考EST作为基准
            result = self.calculate(
                nav=official_est,
                xop_change=xop_change,
                rate_change=0,
                market_price=price
            )
            
            print()
            print("【Palmmicro数据验证】")
            print(f"  官方EST:     {official_est}")
            print(f"  参考EST:     {reference_est}")
            print(f"  我们的计算:  {result['final_est']}")
            diff = abs(result['final_est'] - reference_est) / reference_est * 100
            print(f"  差异:        {diff:.2f}%")
            print()
            
            self.print_result(result)
            
        except ValueError as e:
            print(f"输入错误: {e}")


def main():
    parser = argparse.ArgumentParser(description="华宝油气手动估值计算器")
    parser.add_argument("--nav", type=float, help="昨日净值")
    parser.add_argument("--xop", type=float, help="XOP涨跌幅(%)")
    parser.add_argument("--rate", type=float, default=0, help="汇率变化(%)")
    parser.add_argument("--price", type=float, help="场内价格")
    parser.add_argument("--interactive", action="store_true", help="交互式输入")
    parser.add_argument("--palmmicro", action="store_true", help="从Palmmicro录入")
    args = parser.parse_args()
    
    calc = ManualCalculator()
    
    if args.palmmicro:
        calc.from_palmmicro_template()
    elif args.interactive:
        calc.interactive()
    elif args.nav and args.xop:
        result = calc.calculate(args.nav, args.xop, args.rate, args.price)
        calc.print_result(result)
    else:
        parser.print_help()
        print("\n示例:")
        print("  python3 manual_calculator.py --nav 0.965 --xop 2.5 --price 0.98")


if __name__ == "__main__":
    main()
