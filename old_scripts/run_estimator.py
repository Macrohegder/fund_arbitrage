#!/usr/bin/env python3
"""
华宝油气估值系统统一入口
根据环境自动选择最佳估值方案

使用方式:
    python3 run_estimator.py              # 自动选择最佳方案
    python3 run_estimator.py --mode auto  # 同上
    python3 run_estimator.py --mode manual --nav 0.965 --xop 1.5
    python3 run_estimator.py --mode palmmicro
    python3 run_estimator.py --watch      # 持续监控
"""

import argparse
import sys
import time
from datetime import datetime


def check_data_source():
    """检查数据源可用性"""
    import requests
    
    results = {}
    
    # 检查天天基金
    try:
        resp = requests.get("http://fundgz.1234567.com.cn/js/162411.js", 
                          headers={"Referer": "http://fund.eastmoney.com/"},
                          timeout=5)
        results["tiantian"] = resp.status_code == 200
    except:
        results["tiantian"] = False
    
    # 检查腾讯行情
    try:
        resp = requests.get("http://qt.gtimg.cn/q=sz162411", timeout=5)
        results["tencent"] = "v_sz162411" in resp.text
    except:
        results["tencent"] = False
    
    # 检查新浪
    try:
        resp = requests.get("https://hq.sinajs.cn/list=usr_xop",
                          headers={"Referer": "https://finance.sina.com.cn"},
                          timeout=5)
        results["sina"] = "hq_str_usr_xop" in resp.text
    except:
        results["sina"] = False
    
    return results


def auto_mode(args):
    """自动选择模式"""
    print("=" * 70)
    print("华宝油气估值系统 - 自动模式")
    print("=" * 70)
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 检查数据源
    print("正在检测数据源可用性...")
    sources = check_data_source()
    
    available = sum(sources.values())
    total = len(sources)
    
    print(f"  天天基金API: {'✓' if sources['tiantian'] else '✗'}")
    print(f"  腾讯行情:    {'✓' if sources['tencent'] else '✗'}")
    print(f"  新浪财经:    {'✓' if sources['sina'] else '✗'}")
    print(f"\n数据源可用率: {available}/{total}")
    print()
    
    # 根据可用性选择模式
    if available >= 2:
        print("✅ 数据源充足，使用增强自动模式\n")
        from enhanced_estimator import EnhancedEstimator
        est = EnhancedEstimator()
        result = est.estimate()
        est.print_report(result)
        est.save(result)
        
    elif available >= 1:
        print("⚠️  数据源有限，使用基础模式\n")
        from lof_tracker import LOFTracker
        tracker = LOFTracker()
        result = tracker.track()
        tracker.print_report(result)
        
    else:
        print("❌ 自动数据源不可用，切换到手动模式\n")
        print("请使用以下命令手动输入数据:")
        print("  python3 run_estimator.py --mode manual --interactive")
        print("  或")
        print("  python3 run_estimator.py --mode palmmicro")
        return False
    
    return True


def manual_mode(args):
    """手动模式"""
    from manual_calculator import ManualCalculator
    
    calc = ManualCalculator()
    
    if args.interactive or (args.nav is None and args.xop is None):
        calc.interactive()
    elif args.nav and args.xop:
        result = calc.calculate(args.nav, args.xop, args.rate or 0, args.price)
        calc.print_result(result)
    else:
        print("手动模式需要 --nav 和 --xop 参数，或使用 --interactive")
        return False
    
    return True


def palmmicro_mode(args):
    """Palmmicro录入模式"""
    from manual_calculator import ManualCalculator
    calc = ManualCalculator()
    calc.from_palmmicro_template()
    return True


def watch_mode(args):
    """持续监控模式"""
    print(f"启动持续监控，间隔 {args.interval} 秒...")
    print("按 Ctrl+C 停止\n")
    
    try:
        while True:
            print(f"\n{'='*70}")
            print(f"监控时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print('='*70)
            
            success = auto_mode(args)
            
            if success and args.alert:
                # 检查是否需要报警
                import json
                from pathlib import Path
                
                latest = Path("enhanced_latest.json")
                if latest.exists():
                    with open(latest) as f:
                        data = json.load(f)
                    premium = data.get("premium", 0)
                    
                    if abs(premium) > args.alert:
                        print(f"\n🔔 提醒: 溢价率达到 {premium:.2f}%!")
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\n\n监控已停止")


def main():
    parser = argparse.ArgumentParser(description="华宝油气估值系统")
    parser.add_argument("--mode", choices=["auto", "manual", "palmmicro"], 
                       default="auto", help="运行模式")
    parser.add_argument("--nav", type=float, help="昨日净值(手动模式)")
    parser.add_argument("--xop", type=float, help="XOP涨跌幅%(手动模式)")
    parser.add_argument("--rate", type=float, default=0, help="汇率变化%(手动模式)")
    parser.add_argument("--price", type=float, help="场内价格(手动模式)")
    parser.add_argument("--interactive", action="store_true", help="交互式输入")
    parser.add_argument("--watch", action="store_true", help="持续监控")
    parser.add_argument("--interval", type=int, default=60, help="监控间隔(秒)")
    parser.add_argument("--alert", type=float, help="溢价超过N%时提醒")
    args = parser.parse_args()
    
    # 根据模式执行
    if args.watch:
        watch_mode(args)
    elif args.mode == "auto":
        auto_mode(args)
    elif args.mode == "manual":
        manual_mode(args)
    elif args.mode == "palmmicro":
        palmmicro_mode(args)


if __name__ == "__main__":
    main()
