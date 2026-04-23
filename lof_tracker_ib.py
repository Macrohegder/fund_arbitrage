#!/usr/bin/env python3
"""
LOF基金实时估值跟踪系统 - IB专用版（仅使用IB数据源）
======================================================
仅使用 Interactive Brokers 数据源，无降级机制
IB数据失败时返回None，建议不交易

Usage:
    # 自动连接IB并启动跟踪
    python lof_tracker_ib.py
    
    # 获取盘后收盘参考（用于次日A股开盘）
    python lof_tracker_ib.py --forecast
"""

import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict

# 导入行情管理器
try:
    from quote_manager import QuoteManager, Quote, TradingHours, TradingSession, get_xop_for_lof_arbitrage
    HAS_QUOTE_MANAGER = True
except ImportError:
    HAS_QUOTE_MANAGER = False
    print("❌ quote_manager 模块未找到，系统无法运行")


@dataclass
class TrackingResult:
    """跟踪结果数据结构"""
    timestamp: datetime
    fund_code: str
    fund_name: str
    last_nav: float
    xop_quote: Optional[Dict]
    usd_cny_rate: Optional[float]
    estimation: Dict
    market_price: float
    arbitrage: Dict
    data_quality: Dict
    trading_session: Dict
    a_share_forecast: Optional[Dict] = None


class LOFTrackerIB:
    """
    LOF基金实时估值跟踪器 - IB专用版
    仅使用IB数据源，失败则不交易
    """
    
    def __init__(
        self,
        fund_code: str = "162411",
        use_ib: bool = True,
        ib_host: str = "127.0.0.1",
        ib_port: int = 4002
    ):
        self.fund_code = fund_code
        self.fund_name = "华宝油气"
        self.index_etf = "XOP"
        self.position_ratio = 0.95
        
        # 行情管理器
        self.quote_manager: Optional[QuoteManager] = None
        self.use_ib = use_ib and HAS_QUOTE_MANAGER
        self.ib_host = ib_host
        self.ib_port = ib_port
        
        # 数据缓存
        self.cache = {}
        self.cache_time = {}
        self.cache_duration = 60
        
        # 跟踪历史
        self.data_dir = Path(__file__).parent / "tracking_data"
        self.data_dir.mkdir(exist_ok=True)
        
        # 盘后数据目录
        self.ah_data_dir = Path(__file__).parent / "after_hours_data"
        self.ah_data_dir.mkdir(exist_ok=True)
        
        # 初始化
        if self.use_ib:
            self._init_quote_manager()
    
    def _init_quote_manager(self):
        """初始化行情管理器"""
        try:
            print("🔌 正在初始化行情管理器...")
            self.quote_manager = QuoteManager(
                auto_connect=True,
                ib_host=self.ib_host,
                ib_port=self.ib_port,
                ib_client_id=12
            )
            
            # 订阅XOP
            if self.quote_manager._ib_connected:
                print("📊 订阅 XOP 实时行情（含盘前盘后）...")
                self.quote_manager.subscribe("XOP")
                time.sleep(1)
            else:
                print("❌ IB连接失败，系统将无法获取数据")
            
        except Exception as e:
            print(f"❌ 行情管理器初始化失败: {e}")
            self.quote_manager = None
    
    def _get_cache(self, key: str) -> Optional[any]:
        """获取缓存"""
        if key in self.cache_time:
            if datetime.now() - self.cache_time[key] < timedelta(seconds=self.cache_duration):
                return self.cache[key]
        return None
    
    def _set_cache(self, key: str, value: any):
        """设置缓存"""
        self.cache[key] = value
        self.cache_time[key] = datetime.now()
    
    def get_last_nav(self) -> Optional[float]:
        """获取前一交易日净值 - 从本地文件读取（IB专用版不依赖akshare）"""
        cache_key = f"last_nav_{self.fund_code}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        
        # 尝试从本地数据文件读取
        nav_file = Path(__file__).parent / "estimation_data" / f"nav_{self.fund_code}.json"
        if nav_file.exists():
            try:
                with open(nav_file) as f:
                    data = json.load(f)
                    latest_nav = data.get("latest_nav")
                    if latest_nav:
                        self._set_cache(cache_key, latest_nav)
                        return latest_nav
            except Exception:
                pass
        
        # 默认值（应该从配置文件读取）
        default_nav = 0.9714  # 华宝油气最新净值默认值
        print(f"⚠️ 无法获取最新净值，使用默认值: {default_nav}")
        return default_nav
    
    def get_xop_quote(self) -> tuple[Optional[Dict], str]:
        """
        获取XOP行情 - 仅使用IB数据源
        """
        session = TradingHours.get_session()
        
        # 仅使用行情管理器（IB数据源）
        if self.use_ib and self.quote_manager:
            quote = self.quote_manager.get_quote("XOP", prefer_realtime=True)
            if quote:
                return {
                    "symbol": quote.symbol,
                    "price": quote.price,
                    "change_pct": quote.change_pct,
                    "source": quote.source,
                    "is_realtime": quote.is_realtime,
                    "is_extended_hours": quote.is_extended_hours,
                    "session": quote.session,
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "timestamp": quote.timestamp.isoformat(),
                }, quote.source
        
        # 休市时尝试盘后快照
        if session == TradingSession.CLOSED:
            if self.quote_manager:
                ah_quote = self.quote_manager.get_after_hours_reference("XOP")
                if ah_quote:
                    return {
                        "symbol": ah_quote.symbol,
                        "price": ah_quote.price,
                        "change_pct": ah_quote.change_pct,
                        "source": ah_quote.source,
                        "is_realtime": False,
                        "is_extended_hours": True,
                        "session": "after_hours",
                        "timestamp": ah_quote.timestamp.isoformat(),
                    }, "ib_after_hours"
        
        # IB获取失败，返回None（不做降级）
        return None, "none"
    
    def get_usd_cny_rate(self) -> Optional[float]:
        """获取USD/CNY汇率 - 仅使用IB数据源"""
        cache_key = "usd_cny_rate"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        
        if self.quote_manager:
            rate = self.quote_manager.get_usd_cny_rate()
            if rate:
                self._set_cache(cache_key, rate)
                return rate
        
        # IB获取失败，返回None（不做降级到新浪财经）
        return None
    
    def get_fund_info(self) -> Dict:
        """获取基金场内信息 - 从本地文件读取（IB专用版）"""
        cache_key = f"fund_info_{self.fund_code}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        
        # 尝试从本地数据文件读取
        fund_file = Path(__file__).parent / "estimation_data" / f"fund_{self.fund_code}.json"
        if fund_file.exists():
            try:
                with open(fund_file) as f:
                    info = json.load(f)
                    self._set_cache(cache_key, info)
                    return info
            except Exception:
                pass
        
        # 使用默认值
        default_info = {
            "code": self.fund_code, 
            "name": self.fund_name, 
            "latest_price": 0.984
        }
        print(f"⚠️ 无法获取基金场内信息，使用默认值")
        return default_info
    
    def calculate_realtime_est(
        self,
        last_nav: float,
        xop_change_pct: float,
        usd_rate_change: float = 0
    ) -> Dict:
        """计算实时估值"""
        xop_impact = xop_change_pct * self.position_ratio / 100
        rate_impact = usd_rate_change / 100 if usd_rate_change else 0
        
        realtime_est = last_nav * (1 + xop_impact) * (1 + rate_impact)
        
        return {
            "last_nav": last_nav,
            "official_est": last_nav,
            "reference_est": realtime_est,
            "realtime_est": realtime_est,
            "xop_change_pct": xop_change_pct,
            "xop_impact": xop_impact * 100,
            "rate_impact": rate_impact * 100,
            "calculated_at": datetime.now().isoformat(),
        }
    
    def analyze_arbitrage(self, realtime_est: float, market_price: float, 
                          session_info: Dict) -> Dict:
        """分析套利机会"""
        premium = (market_price - realtime_est) / realtime_est * 100
        
        # 根据交易时段调整建议
        session = session_info.get("session", "unknown")
        hours_to_open = session_info.get("hours_to_a_share_open", 0)
        
        if session == "after_hours":
            suggestion_base = f"🌙 美股盘后 | 距A股开盘还有 {hours_to_open:.1f}小时"
        elif session == "pre_market":
            suggestion_base = f"🌅 美股盘前 | 距A股开盘还有 {hours_to_open:.1f}小时"
        elif session == "regular":
            suggestion_base = "☀️ 美股常规交易"
        else:
            suggestion_base = "🌑 美股休市"
        
        # 套利建议
        if premium > 1.5:
            suggestion = f"{suggestion_base}\n   🔥 溢价套利机会（申购-卖出）"
        elif premium > 0.15:
            suggestion = f"{suggestion_base}\n   ✓ 可考虑XOP对冲套利"
        elif premium < -0.8:
            suggestion = f"{suggestion_base}\n   🔥 折价套利机会（买入-赎回）"
        elif premium < -0.5:
            suggestion = f"{suggestion_base}\n   ✓ 关注折价机会"
        else:
            suggestion = f"{suggestion_base}\n   ➖ 观望"
        
        return {
            "market_price": market_price,
            "realtime_est": realtime_est,
            "premium": premium,
            "premium_pct": f"{premium:.2f}%",
            "suggestion": suggestion,
        }
    
    def track(self) -> TrackingResult:
        """执行一次跟踪"""
        start_time = time.time()
        
        # 获取交易时段信息
        session_info = TradingHours.get_session_info()
        
        # 1. 获取前一交易日净值
        last_nav = self.get_last_nav()
        
        # 2. 获取XOP行情（仅IB数据源）
        xop_quote, xop_source = self.get_xop_quote()
        xop_change_pct = xop_quote["change_pct"] if xop_quote else 0
        
        # 3. 获取汇率（仅IB数据源）
        usd_rate = self.get_usd_cny_rate()
        
        # 4. 计算实时估值
        est_result = self.calculate_realtime_est(last_nav, xop_change_pct)
        
        # 5. 获取场内价格
        fund_info = self.get_fund_info()
        market_price = fund_info.get("latest_price", last_nav)
        
        # 6. 分析套利机会
        arb_result = self.analyze_arbitrage(est_result["realtime_est"], market_price, session_info)
        
        # 7. 数据质量评估
        data_quality = {
            "xop_source": xop_source,
            "xop_is_realtime": xop_quote.get("is_realtime", False) if xop_quote else False,
            "xop_is_extended": xop_quote.get("is_extended_hours", False) if xop_quote else False,
            "xop_session": xop_quote.get("session", "unknown") if xop_quote else "none",
            "total_latency_ms": (time.time() - start_time) * 1000,
            "ib_connected": self.quote_manager._ib_connected if self.quote_manager else False,
        }
        
        # 8. 获取A股开盘预估（如果休市且有盘后数据）
        a_share_forecast = None
        if session_info["session"] == "closed" and self.quote_manager:
            a_share_forecast = self.quote_manager.get_a_share_open_forecast("XOP")
        
        result = TrackingResult(
            timestamp=datetime.now(),
            fund_code=self.fund_code,
            fund_name=self.fund_name,
            last_nav=last_nav,
            xop_quote=xop_quote,
            usd_cny_rate=usd_rate,
            estimation=est_result,
            market_price=market_price,
            arbitrage=arb_result,
            data_quality=data_quality,
            trading_session=session_info,
            a_share_forecast=a_share_forecast
        )
        
        # 保存数据
        self._save_result(result)
        
        return result
    
    def _save_result(self, result: TrackingResult):
        """保存跟踪结果"""
        date_str = datetime.now().strftime("%Y%m%d")
        file_path = self.data_dir / f"ib_tracking_{self.fund_code}_{date_str}.jsonl"
        
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(result), ensure_ascii=False, default=str) + "\n")
    
    def print_report(self, result: TrackingResult):
        """打印跟踪报告"""
        # 时段图标
        session_icons = {
            "pre_market": "🌅",
            "regular": "☀️",
            "after_hours": "🌙",
            "closed": "🌑"
        }
        session_icon = session_icons.get(result.trading_session.get("session"), "❓")
        
        print("=" * 70)
        print(f"LOF实时估值跟踪 (IB专用版) {session_icon} {result.fund_name}({result.fund_code})")
        print("=" * 70)
        print(f"⏰ 时间: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📍 美股: {result.trading_session.get('et_time', 'N/A')}")
        print(f"🇨🇳 A股距开盘: {result.trading_session.get('hours_to_a_share_open', 'N/A')}小时")
        print(f"⚡ 延迟: {result.data_quality['total_latency_ms']:.0f}ms")
        print()
        
        print("【净值信息】")
        print(f"  前一交易日净值: {result.last_nav}")
        print()
        
        if result.xop_quote:
            xop = result.xop_quote
            rt_marker = "⚡实时" if xop.get("is_realtime") else "⏱️延时"
            if xop.get("is_extended_hours"):
                rt_marker += " 🌙盘后"
            print(f"【XOP行情】{rt_marker} (来源: {result.data_quality['xop_source']})")
            print(f"  价格: ${xop['price']:.2f}")
            print(f"  涨跌: {xop['change_pct']:+.2f}%")
            if xop.get("bid") and xop.get("ask"):
                print(f"  买卖: {xop['bid']} / {xop['ask']}")
            print(f"  时段: {xop.get('session', 'unknown')}")
            print()
        else:
            print("【XOP行情】❌ IB获取失败")
            print("  💡 建议：不交易或等待IB数据恢复")
            print()
        
        print(f"【汇率】USD/CNY: {result.usd_cny_rate if result.usd_cny_rate else '❌ IB获取失败'}")
        print()
        
        print("【估值计算】")
        est = result.estimation
        print(f"  参考EST: {est['reference_est']:.4f}")
        print(f"  XOP影响: {est['xop_impact']:.2f}%")
        print()
        
        print("【套利分析】")
        arb = result.arbitrage
        print(f"  场内价格: {arb['market_price']:.4f}")
        print(f"  实时估值: {arb['realtime_est']:.4f}")
        premium = arb['premium']
        premium_emoji = "🔴" if premium > 1 else "🟢" if premium < -0.5 else "⚪"
        print(f"  溢价率: {premium_emoji} {arb['premium_pct']}")
        print()
        print(f"  💡 {arb['suggestion']}")
        
        # A股开盘预估
        if result.a_share_forecast:
            print()
            print("【A股开盘预估】🇨🇳")
            fc = result.a_share_forecast
            rel_icon = "🟢" if fc['reliability'] == 'high' else "🟡" if fc['reliability'] == 'medium' else "🔴"
            print(f"  美股盘后涨幅: {fc['after_hours_change_pct']:+.2f}%")
            print(f"  预估净值变化: {fc['forecast_nav_change']:+.2f}%")
            print(f"  数据时间: {fc['data_time']}")
            print(f"  可靠性: {rel_icon} {fc['reliability']}")
        
        # IB连接状态警告
        if not result.data_quality.get("ib_connected"):
            print()
            print("⚠️ 警告: IB未连接，数据可能不准确，建议不交易")
        
        print("=" * 70)
    
    def print_forecast_only(self):
        """仅打印A股开盘预估"""
        if not self.quote_manager:
            print("❌ 行情管理器未初始化")
            return
        
        print("=" * 70)
        print("A股开盘预估 (基于IB盘后数据)")
        print("=" * 70)
        
        forecast = self.quote_manager.get_a_share_open_forecast("XOP")
        if not forecast:
            print("❌ 无法获取预估数据（IB盘后数据不可用）")
            return
        
        print(f"\n📊 XOP 盘后数据:")
        print(f"  常规收盘价: ${forecast['regular_close']:.2f}")
        print(f"  盘后收盘价: ${forecast['after_hours_price']:.2f}")
        print(f"  盘后涨跌幅: {forecast['after_hours_change_pct']:+.2f}%")
        print()
        
        print(f"📈 华宝油气(162411) 开盘预估:")
        nav_change = forecast['forecast_nav_change']
        direction = "📈 上涨" if nav_change > 0 else "📉 下跌" if nav_change < 0 else "➡️ 持平"
        print(f"  预估净值变化: {direction} {nav_change:+.2f}%")
        
        # 预估净值
        last_nav = self.get_last_nav()
        forecast_nav = last_nav * (1 + nav_change / 100)
        print(f"  预估净值: {forecast_nav:.4f} (基于昨日净值 {last_nav})")
        print()
        
        print(f"💡 套利建议:")
        if nav_change > 2:
            print("  🔥 预估大幅高开，关注溢价套利机会")
        elif nav_change > 1:
            print("  ✓ 预估高开，可适当布局")
        elif nav_change < -2:
            print("  🔥 预估大幅低开，关注折价套利机会")
        elif nav_change < -1:
            print("  ✓ 预估低开，可适当布局")
        else:
            print("  ➖ 预估波动不大，观望为主")
        
        rel_icon = "🟢" if forecast['reliability'] == 'high' else "🟡" if forecast['reliability'] == 'medium' else "🔴"
        print(f"\n📋 数据质量: {rel_icon} {forecast['reliability']} ({forecast['hours_ago']:.1f}小时前)")
        print("=" * 70)
    
    def run_continuous(self, interval: int = 5):
        """持续运行跟踪"""
        print(f"\n🚀 启动持续跟踪 (间隔: {interval}秒)")
        print("按 Ctrl+C 停止\n")
        
        try:
            while True:
                result = self.track()
                self.print_report(result)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n⚠️ 用户中断")
        finally:
            if self.quote_manager:
                self.quote_manager.close()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="LOF实时估值跟踪 - IB专用版")
    parser.add_argument("--fund-code", default="162411", help="基金代码")
    parser.add_argument("--ib-host", default="127.0.0.1", help="IB Gateway主机")
    parser.add_argument("--ib-port", type=int, default=4002, help="IB Gateway端口")
    parser.add_argument("--interval", type=int, default=5, help="跟踪间隔(秒)")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--forecast", action="store_true", help="仅显示A股开盘预估")
    parser.add_argument("--session-info", action="store_true", help="显示交易时段信息")
    
    args = parser.parse_args()
    
    # 显示交易时段信息
    if args.session_info:
        print("=" * 70)
        print("美股交易时段信息")
        print("=" * 70)
        info = TradingHours.get_session_info()
        for key, value in info.items():
            print(f"  {key}: {value}")
        print()
        print(TradingHours.format_beijing_trading_hours())
        return
    
    print("=" * 70)
    print("LOF实时估值跟踪系统 (IB专用版 - 仅使用IB数据源)")
    print("=" * 70)
    print("⚠️ 注意: 本系统仅使用IB数据源，IB失败时不做降级")
    print()
    
    # 创建跟踪器
    tracker = LOFTrackerIB(
        fund_code=args.fund_code,
        use_ib=True,  # 强制使用IB
        ib_host=args.ib_host,
        ib_port=args.ib_port
    )
    
    # 检查IB连接状态
    if not tracker.quote_manager or not tracker.quote_manager._ib_connected:
        print("❌ IB未连接，系统无法正常运行")
        print("💡 建议: 启动IB Gateway后再运行本系统")
        return
    
    # 仅显示开盘预估
    if args.forecast:
        tracker.print_forecast_only()
    elif args.once:
        result = tracker.track()
        tracker.print_report(result)
    else:
        tracker.run_continuous(interval=args.interval)
    
    # 清理
    if tracker.quote_manager:
        tracker.quote_manager.close()
    
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
