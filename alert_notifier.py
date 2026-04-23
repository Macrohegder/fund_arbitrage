#!/usr/bin/env python3
"""
LOF折价套利 Telegram 通知器 (IB行情版)
========================================
监控折价大于1%的机会，通过Telegram发送通知
支持IB实时行情和盘后数据

Features:
- 折价阈值：>1%
- 支持IB实时行情
- 支持A股开盘预估（基于美股盘后数据）
- 自动计算对冲配比
- 定时任务友好

Usage:
    # 检查一次
    python3 alert_notifier.py
    
    # 指定基金
    python3 alert_notifier.py --fund 162411
    
    # 强制发送测试
    python3 alert_notifier.py --force
    
    # 查看A股开盘预估
    python3 alert_notifier.py --forecast
"""

import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

# 配置
CONFIG_FILE = Path("/root/.openclaw/workspace/.telegram_bot_config")

# ============ 配置加载 ============

def load_telegram_config() -> Dict:
    """加载Telegram配置"""
    config = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    return config

_CONFIG = load_telegram_config()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", _CONFIG.get("BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", _CONFIG.get("CHAT_ID", ""))

# ============ 配置参数 ============

# 折价阈值：大于1%才提醒
DISCOUNT_THRESHOLD = 1.0  # 1%

# 基金配置
FUND_CONFIG = {
    "162411": {
        "name": "华宝标普油气",
        "proxy_etf": "XOP",
        "position_ratio": 0.95,
        "exchange": "sz",
    },
    "161127": {
        "name": "易方达标普生物科技",
        "proxy_etf": "XBI",
        "position_ratio": 0.95,
        "exchange": "sz",
    },
}

# IB Gateway 配置
IB_HOST = "127.0.0.1"
IB_PORT = 4002


# ============ Telegram 通知器 ============

class TelegramNotifier:
    """Telegram通知器"""
    
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        
    def validate_config(self) -> bool:
        """验证配置"""
        if not self.bot_token:
            print("❌ 错误: 请设置TELEGRAM_BOT_TOKEN")
            return False
        if not self.chat_id:
            print("❌ 错误: 请设置TELEGRAM_CHAT_ID")
            return False
        return True
    
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """发送消息"""
        if not self.validate_config():
            return False
        
        url = f"{self.api_base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    print("✅ Telegram消息发送成功")
                    return True
                else:
                    print(f"❌ Telegram API错误: {data.get('description')}")
                    return False
            else:
                print(f"❌ HTTP错误: {resp.status_code}")
                return False
        except Exception as e:
            print(f"❌ 发送失败: {e}")
            return False


# ============ 折价套利检查 ============

class DiscountArbitrageChecker:
    """折价套利检查器"""
    
    def __init__(self, fund_code: str = "162411"):
        self.fund_code = fund_code
        self.config = FUND_CONFIG.get(fund_code, FUND_CONFIG["162411"])
        self.notifier = TelegramNotifier()
        
    def check(self, force: bool = False) -> bool:
        """
        检查折价套利机会
        
        Args:
            force: 强制发送（用于测试）
            
        Returns:
            bool: 是否成功检查
        """
        print(f"\n{'='*60}")
        print(f"检查 {self.config['name']}({self.fund_code}) 折价套利机会")
        print(f"折价阈值: >{DISCOUNT_THRESHOLD}%")
        print('='*60)
        
        # 获取跟踪数据
        try:
            from lof_tracker_ib import LOFTrackerIB
            
            tracker = LOFTrackerIB(
                fund_code=self.fund_code,
                use_ib=True,
                ib_host=IB_HOST,
                ib_port=IB_PORT
            )
            
            result = tracker.track()
            tracker.print_report(result)
            
            # 清理
            if tracker.quote_manager:
                tracker.quote_manager.close()
            
        except Exception as e:
            print(f"❌ 获取数据失败: {e}")
            # 降级到原有方法
            return self._check_fallback(force)
        
        # 检查折价
        premium = result.arbitrage.get('premium', 0)
        is_discount = premium < -DISCOUNT_THRESHOLD  # 折价大于1%
        
        print(f"\n检查结果:")
        print(f"  溢价率: {premium:.2f}%")
        print(f"  折价阈值: -{DISCOUNT_THRESHOLD}%")
        print(f"  是否满足条件: {'✅ 是' if is_discount else '❌ 否'}")
        
        if is_discount or force:
            return self._send_alert(result, force)
        else:
            print(f"\n折价率 {abs(premium):.2f}% 未达到阈值({DISCOUNT_THRESHOLD}%)，不发送通知")
            return True
    
    def _check_fallback(self, force: bool = False) -> bool:
        """备用检查方法（当IB不可用时）"""
        print("⚠️ 使用备用数据源检查...")
        
        try:
            from realtime_calculator import RealtimeCalculator
            
            calc = RealtimeCalculator()
            data = calc.calculate()
            
            premium = data.get('premium', 0)
            is_discount = premium < -DISCOUNT_THRESHOLD
            
            print(f"\n检查结果:")
            print(f"  溢价率: {premium:.2f}%")
            print(f"  是否满足条件: {'✅ 是' if is_discount else '❌ 否'}")
            
            if is_discount or force:
                return self._send_alert_fallback(data, force)
            else:
                print(f"\n折价率 {abs(premium):.2f}% 未达到阈值，不发送通知")
                return True
                
        except Exception as e:
            print(f"❌ 备用检查也失败: {e}")
            return False
    
    def _send_alert(self, result, force: bool = False) -> bool:
        """发送折价套利提醒"""
        premium = result.arbitrage.get('premium', 0)
        
        # 构建消息
        message = f"""
<b>🟢 LOF折价套利机会提醒</b>

<b>{result.fund_name} ({result.fund_code})</b>

<b>【估值数据】</b>
• 估算净值: <code>{result.estimation['realtime_est']:.4f}</code>
• 场内价格: <code>{result.market_price:.3f}</code>
• <b>折价率: {abs(premium):.2f}%</b> ⬇️
• 数据源: {result.data_quality.get('xop_source', 'unknown')}
"""
        
        # 添加盘后信息（如果适用）
        if result.a_share_forecast:
            message += f"""
<b>【A股开盘预估】</b>
• 美股盘后涨幅: {result.a_share_forecast['after_hours_change_pct']:+.2f}%
• 预估净值变化: {result.a_share_forecast['forecast_nav_change']:+.2f}%
"""
        
        # 添加盈亏估算
        message += f"""
<b>【盈亏估算】</b>
• 理论收益: {abs(premium):.2f}%
• 扣除成本(0.53%): <b>{abs(premium) - 0.53:+.2f}%</b>

<b>【对冲标的】</b>
• {self.config['proxy_etf']}参考: {result.xop_quote.get('price', 'N/A') if result.xop_quote else 'N/A'}

<b>【操作建议】</b>
1. 买入 {result.fund_code}（场内）
2. 同时做空 {self.config['proxy_etf']} 对冲
3. T+1日提交赎回

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        if force:
            message += "\n<i>⚠️ 测试消息（强制发送）</i>"
        
        success = self.notifier.send_message(message)
        
        if success:
            print(f"\n✅ 折价套利提醒已发送（折价率: {abs(premium):.2f}%）")
        
        return success
    
    def _send_alert_fallback(self, data: Dict, force: bool = False) -> bool:
        """备用发送方法"""
        premium = data.get('premium', 0)
        
        message = f"""
<b>🟢 LOF折价套利机会提醒 (备用数据源)</b>

<b>{data.get('fund_name', '华宝油气')} ({data.get('fund_code', '162411')})</b>

<b>【估值数据】</b>
• 估算净值: <code>{data.get('reference_est', 0):.4f}</code>
• 场内价格: <code>{data.get('market_price', 0):.3f}</code>
• <b>折价率: {abs(premium):.2f}%</b> ⬇️

<b>【盈亏估算】</b>
• 理论收益: {abs(premium):.2f}%
• 扣除成本(0.53%): <b>{abs(premium) - 0.53:+.2f}%</b>

<b>【操作建议】</b>
1. 买入 {data.get('fund_code', '162411')}（场内）
2. 同时做空 {self.config['proxy_etf']} 对冲
3. T+1日提交赎回

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
<i>（数据源：新浪财经）</i>
"""
        
        if force:
            message += "\n<i>⚠️ 测试消息（强制发送）</i>"
        
        success = self.notifier.send_message(message)
        
        if success:
            print(f"\n✅ 折价套利提醒已发送（折价率: {abs(premium):.2f}%）")
        
        return success


# ============ A股开盘预估通知 ============

def send_forecast_notification(fund_code: str = "162411") -> bool:
    """
    发送A股开盘预估通知
    基于美股盘后数据，预估次日开盘情况
    """
    print(f"\n{'='*60}")
    print(f"发送 {fund_code} A股开盘预估通知")
    print('='*60)
    
    try:
        from lof_tracker_ib import LOFTrackerIB
        
        tracker = LOFTrackerIB(fund_code=fund_code, use_ib=True)
        
        # 获取A股开盘预估
        if not tracker.quote_manager:
            print("❌ 行情管理器未初始化")
            return False
        
        forecast = tracker.quote_manager.get_a_share_open_forecast(
            FUND_CONFIG[fund_code]['proxy_etf']
        )
        
        tracker.quote_manager.close()
        
        if not forecast:
            print("❌ 无法获取预估数据")
            return False
        
        nav_change = forecast['forecast_nav_change']
        direction = "📈 高开" if nav_change > 0 else "📉 低开" if nav_change < 0 else "➡️ 平开"
        
        # 只有预估变化超过1%才发送通知
        if abs(nav_change) < 0.5:
            print(f"预估变化 {nav_change:+.2f}% 小于0.5%，不发送通知")
            return True
        
        notifier = TelegramNotifier()
        
        message = f"""
<b>🇨🇳 A股开盘预估通知</b>

<b>{FUND_CONFIG[fund_code]['name']} ({fund_code})</b>

<b>【美股盘后数据】</b>
• 常规收盘价: ${forecast['regular_close']:.2f}
• 盘后收盘价: ${forecast['after_hours_price']:.2f}
• 盘后涨跌幅: {forecast['after_hours_change_pct']:+.2f}%

<b>【A股开盘预估】</b>
• 预估方向: <b>{direction}</b>
• 预估净值变化: <b>{nav_change:+.2f}%</b>

<b>【套利建议】</b>
"""
        
        if nav_change > 1.5:
            message += "🔥 预估大幅高开，关注<b>溢价套利</b>机会（申购-卖出）\n"
        elif nav_change > 0.5:
            message += "✓ 预估高开，可适当关注\n"
        elif nav_change < -1.5:
            message += "🔥 预估大幅低开，关注<b>折价套利</b>机会（买入-赎回）\n"
        elif nav_change < -0.5:
            message += "✓ 预估低开，可适当关注\n"
        else:
            message += "➖ 预估波动不大\n"
        
        rel_icons = {"high": "🟢", "medium": "🟡", "low": "🔴"}
        rel_icon = rel_icons.get(forecast['reliability'], "⚪")
        
        message += f"""
<b>【数据质量】</b>
• 可靠性: {rel_icon} {forecast['reliability']}
• 数据时间: {forecast['data_time'][:19]}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
<i>美股盘后数据，仅供参考</i>
"""
        
        success = notifier.send_message(message)
        
        if success:
            print(f"\n✅ A股开盘预估通知已发送（预估变化: {nav_change:+.2f}%）")
        
        return success
        
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============ 主函数 ============

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="LOF折价套利 Telegram 通知器")
    parser.add_argument("--fund", default="162411", help="基金代码，默认162411")
    parser.add_argument("--force", action="store_true", help="强制发送（用于测试）")
    parser.add_argument("--forecast", action="store_true", help="发送A股开盘预估")
    parser.add_argument("--all", action="store_true", help="检查所有配置的基金")
    
    args = parser.parse_args()
    
    print("="*60)
    print("LOF折价套利 Telegram 通知器")
    print(f"折价阈值: >{DISCOUNT_THRESHOLD}%")
    print("="*60)
    
    # 验证配置
    notifier = TelegramNotifier()
    if not notifier.validate_config():
        print("\n❌ Telegram配置无效")
        print(f"请检查配置文件: {CONFIG_FILE}")
        sys.exit(1)
    
    print("✅ Telegram配置有效")
    
    # A股开盘预估模式
    if args.forecast:
        success = send_forecast_notification(args.fund)
        sys.exit(0 if success else 1)
    
    # 检查所有基金
    if args.all:
        success_count = 0
        for fund_code in FUND_CONFIG:
            checker = DiscountArbitrageChecker(fund_code)
            if checker.check(force=args.force):
                success_count += 1
        print(f"\n✅ 完成检查 {success_count}/{len(FUND_CONFIG)} 个基金")
        sys.exit(0 if success_count == len(FUND_CONFIG) else 1)
    
    # 检查单个基金
    checker = DiscountArbitrageChecker(args.fund)
    success = checker.check(force=args.force)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
