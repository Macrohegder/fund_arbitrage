#!/usr/bin/env python3
"""
IB实时行情演示脚本 - IB专用版
============================
演示如何使用IB实时行情功能，仅使用IB数据源

Usage:
    python demo_ib_quote.py
    python demo_ib_quote.py --forecast    # 仅显示A股开盘预估
"""

import sys
import argparse


def print_trading_hours():
    """打印交易时段信息"""
    try:
        from ib_realtime_client import TradingHours
        
        print("\n" + "=" * 70)
        print("美股交易时段 (北京时间)")
        print("=" * 70)
        print(TradingHours.format_beijing_trading_hours())
        
        print("\n当前状态:")
        info = TradingHours.get_session_info()
        for key, value in info.items():
            print(f"  {key}: {value}")
    except ImportError:
        print("❌ 模块未找到")


def demo_quote_manager():
    """演示行情管理器"""
    print("\n" + "=" * 70)
    print("演示1: 行情管理器 (QuoteManager - IB专用版)")
    print("=" * 70)
    
    try:
        from quote_manager import QuoteManager, TradingHours
        
        # 打印当前时段
        print_trading_hours()
        
        # 创建行情管理器
        print("\n🔌 初始化行情管理器...")
        print("  注意: 本系统仅使用IB数据源，无降级机制")
        qm = QuoteManager(auto_connect=True)
        
        # 检查IB连接状态
        status = qm.get_connection_status()
        session = status.get('trading_session', {})
        
        print(f"\n📊 连接状态:")
        print(f"  IB连接: {'✅' if status['ib_connected'] else '❌'}")
        print(f"  当前时段: {session.get('session', 'unknown')}")
        print(f"  距A股开盘: {session.get('hours_to_a_share_open', 'N/A')}小时")
        
        if not status['ib_connected']:
            print("\n❌ IB未连接，系统无法获取数据")
            print("💡 建议: 启动IB Gateway后再运行本系统")
            qm.close()
            return
        
        # 获取XOP行情
        print("\n📈 获取 XOP 行情...")
        xop = qm.get_quote("XOP")
        if xop:
            icons = {
                "pre_market": "🌅",
                "regular": "☀️",
                "after_hours": "🌙",
                "closed": "🌑"
            }
            session_icon = icons.get(xop.session, "❓")
            rt_marker = "⚡实时" if xop.is_realtime else "⏱️延时"
            ah_marker = "🌙盘后" if xop.is_extended_hours else ""
            
            print(f"  {session_icon} 时段: {xop.session}")
            print(f"  💰 价格: ${xop.price:.2f}")
            print(f"  📊 涨跌: {xop.change_pct:+.2f}%")
            print(f"  📡 数据源: {xop.source} {rt_marker} {ah_marker}")
            print(f"  ⏱️ 延迟: {xop.latency_ms:.0f}ms")
            if xop.bid and xop.ask:
                print(f"  📋 买卖: {xop.bid} / {xop.ask}")
        else:
            print("  ❌ IB获取失败，建议不交易")
        
        # 获取盘后参考价
        print("\n🌙 获取盘后收盘参考价...")
        ah = qm.get_after_hours_reference("XOP")
        if ah:
            print(f"  盘后价格: ${ah.price:.2f}")
            print(f"  盘后涨跌: {ah.change_pct:+.2f}%")
            print(f"  数据来源: {ah.source}")
            print(f"  数据时间: {ah.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print("  暂无盘后数据（IB未提供或还未到盘后时段）")
        
        # 获取A股开盘预估
        print("\n🇨🇳 获取A股开盘预估...")
        forecast = qm.get_a_share_open_forecast("XOP")
        if forecast:
            print(f"  📊 美股常规收盘: ${forecast['regular_close']:.2f}")
            print(f"  🌙 美股盘后收盘: ${forecast['after_hours_price']:.2f}")
            print(f"  📈 盘后涨跌幅: {forecast['after_hours_change_pct']:+.2f}%")
            print(f"  🎯 预估净值变化: {forecast['forecast_nav_change']:+.2f}%")
            
            rel_icons = {"high": "🟢", "medium": "🟡", "low": "🔴"}
            rel_icon = rel_icons.get(forecast['reliability'], "⚪")
            print(f"  {rel_icon} 数据可靠性: {forecast['reliability']}")
            print(f"  ⏰ 数据时间: {forecast['data_time']}")
        else:
            print("  无法获取预估数据（IB盘后数据不可用）")
        
        # 获取汇率
        print("\n💱 获取 USD/CNY 汇率...")
        rate = qm.get_usd_cny_rate()
        if rate:
            print(f"  汇率: {rate:.4f}")
        else:
            print("  IB获取汇率失败")
        
        # 统计
        print("\n📈 统计信息:")
        stats = qm.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        qm.close()
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


def demo_lof_tracker():
    """演示LOF跟踪器"""
    print("\n" + "=" * 70)
    print("演示2: LOF跟踪器 (LOFTrackerIB - IB专用版)")
    print("=" * 70)
    
    try:
        from lof_tracker_ib import LOFTrackerIB
        
        print("\n🔌 初始化LOF跟踪器...")
        print("  注意: 本系统仅使用IB数据源")
        tracker = LOFTrackerIB(
            fund_code="162411",
            use_ib=True
        )
        
        # 检查IB连接
        if not tracker.quote_manager or not tracker.quote_manager._ib_connected:
            print("\n❌ IB未连接，跟踪器无法正常运行")
            print("💡 建议: 启动IB Gateway后再运行本系统")
            return
        
        print("\n📊 执行一次跟踪...")
        result = tracker.track()
        
        print("\n📋 结果摘要:")
        print(f"  基金: {result.fund_name}({result.fund_code})")
        print(f"  时间: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  美股时段: {result.trading_session.get('session', 'unknown')}")
        print(f"  净值: {result.last_nav}")
        
        if result.xop_quote:
            xop = result.xop_quote
            icons = {"pre_market": "🌅", "regular": "☀️", "after_hours": "🌙", "closed": "🌑"}
            icon = icons.get(xop.get('session'), "❓")
            print(f"  XOP: {icon} ${xop['price']:.2f} ({xop['change_pct']:+.2f}%)")
        else:
            print("  XOP: ❌ IB获取失败")
        
        print(f"  估值: {result.estimation['realtime_est']:.4f}")
        print(f"  溢价: {result.arbitrage['premium_pct']}")
        
        if result.a_share_forecast:
            print(f"  A股开盘预估: {result.a_share_forecast['forecast_nav_change']:+.2f}%")
        
        # 打印完整报告
        print("\n" + "-" * 70)
        print("完整报告:")
        print("-" * 70)
        tracker.print_report(result)
        
        tracker.quote_manager.close()
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


def demo_forecast():
    """仅演示A股开盘预估"""
    print("\n" + "=" * 70)
    print("A股开盘预估演示 (基于IB盘后数据)")
    print("=" * 70)
    
    try:
        from lof_tracker_ib import LOFTrackerIB
        
        tracker = LOFTrackerIB(use_ib=True)
        
        if not tracker.quote_manager or not tracker.quote_manager._ib_connected:
            print("❌ IB未连接，无法获取A股开盘预估")
            return
        
        tracker.print_forecast_only()
        tracker.quote_manager.close()
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="IB实时行情功能演示 - IB专用版")
    parser.add_argument("--forecast", action="store_true", help="仅显示A股开盘预估")
    parser.add_argument("--session", action="store_true", help="仅显示交易时段信息")
    args = parser.parse_args()
    
    if args.session:
        print_trading_hours()
        return
    
    if args.forecast:
        demo_forecast()
        return
    
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 18 + "IB实时行情功能演示 (IB专用版)" + " " * 19 + "║")
    print("║" + " " * 15 + "仅使用IB数据源，无降级机制" + " " * 18 + "║")
    print("╚" + "═" * 68 + "╝")
    
    # 演示1: 行情管理器
    demo_quote_manager()
    
    # 演示2: LOF跟踪器
    demo_lof_tracker()
    
    print("\n" + "=" * 70)
    print("演示完成！")
    print("=" * 70)
    print("\n提示:")
    print("  • 本系统仅使用IB数据源，IB失败时不会降级到其他数据源")
    print("  • 使用 ./start_ib_tracker.sh 启动持续跟踪")
    print("  • 使用 python demo_ib_quote.py --forecast 查看A股开盘预估")
    print("  • 查看 IB_QUOTE_README.md 获取完整文档")
    print("")


if __name__ == "__main__":
    main()
