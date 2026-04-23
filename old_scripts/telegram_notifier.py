#!/usr/bin/env python3
"""
Telegram折价套利提醒系统 (仅折价套利)
支持161127(XBI)折价套利监控

使用方法:
1. 已配置好Telegram，直接运行: python3 telegram_notifier.py
2. 只监控折价机会，自动计算对冲配比
"""

import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# 配置 - 优先从workspace目录读取配置文件
CONFIG_FILE = Path("/root/.openclaw/workspace/.telegram_bot_config")

def load_telegram_config():
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

# 加载配置
_CONFIG = load_telegram_config()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", _CONFIG.get("BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", _CONFIG.get("CHAT_ID", ""))

# 提醒阈值 - 只监控折价
ALERT_THRESHOLDS = {
    "161127": {
        "premium_low": -0.5,   # 折价超过0.5%提醒
        "min_arbitrage": 10000,  # 最小套利金额(元)
    },
    "162411": {
        "premium_low": -0.5,
        "min_arbitrage": 10000,
    }
}

# 基金配置
FUND_CONFIG = {
    "161127": {
        "name": "易方达标普生物科技",
        "proxy_etf": "XBI",
        "position_ratio": 0.95,
        "exchange": "sz",
    },
    "162411": {
        "name": "华宝标普油气",
        "proxy_etf": "XOP", 
        "position_ratio": 0.95,
        "exchange": "sz",
    }
}


class HedgeCalculator:
    """对冲计算器"""
    
    @staticmethod
    def calculate_hedge_ratio(fund_code: str, arbitrage_amount_cny: float = 10000.0,
                             usdcny_rate: float = 7.25) -> Dict:
        """
        计算对冲配比
        
        Args:
            fund_code: 基金代码
            arbitrage_amount_cny: 套利金额（人民币，默认1万）
            usdcny_rate: 美元兑人民币汇率
            
        Returns:
            对冲配比详情
        """
        config = FUND_CONFIG.get(fund_code, FUND_CONFIG["161127"])
        position = config["position_ratio"]
        etf_symbol = config["proxy_etf"]
        
        # 计算人民币端
        fund_amount = arbitrage_amount_cny  # 买入LOF金额
        fund_exposure = fund_amount * position  # 实际跟踪ETF的敞口
        
        # 计算美股端（需要对冲的美元金额）
        hedge_usd_amount = fund_exposure / usdcny_rate  # 需要对冲的美元金额
        
        # 获取ETF当前价格（估算）
        etf_price_usd = HedgeCalculator._get_etf_price(etf_symbol)
        
        # 计算ETF股数
        if etf_price_usd and etf_price_usd > 0:
            etf_shares = int(hedge_usd_amount / etf_price_usd)
            actual_hedge_usd = etf_shares * etf_price_usd
            actual_hedge_cny = actual_hedge_usd * usdcny_rate
        else:
            etf_shares = 0
            actual_hedge_usd = 0
            actual_hedge_cny = 0
            etf_price_usd = 0
        
        return {
            "fund_code": fund_code,
            "fund_name": config["name"],
            "arbitrage_amount_cny": arbitrage_amount_cny,  # 总套利金额
            "fund_amount_cny": fund_amount,  # 买入LOF金额
            "fund_position_ratio": position,  # LOF仓位
            "fund_exposure_cny": fund_exposure,  # LOF实际ETF敞口
            "usdcny_rate": usdcny_rate,  # 汇率
            "hedge_usd_amount": hedge_usd_amount,  # 理论对冲美元金额
            "etf_symbol": etf_symbol,
            "etf_price_usd": etf_price_usd,  # ETF价格
            "etf_shares": etf_shares,  # ETF股数
            "actual_hedge_usd": actual_hedge_usd,  # 实际对冲美元金额
            "actual_hedge_cny": actual_hedge_cny,  # 实际对冲人民币金额
            "hedge_ratio": actual_hedge_cny / fund_amount if fund_amount > 0 else 0,  # 对冲比例
        }
    
    @staticmethod
    def _get_etf_price(symbol: str) -> Optional[float]:
        """获取ETF当前价格"""
        try:
            # 使用NASDAQ API
            url = f"https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=etf"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status", {}).get("rCode") == 200:
                    primary = data.get("data", {}).get("primaryData", {})
                    price_str = primary.get("lastSalePrice", "$0").replace("$", "").replace(",", "")
                    return float(price_str)
        except Exception:
            pass
        
        # 默认值
        defaults = {"XBI": 123.92, "XOP": 181.62}
        return defaults.get(symbol)
    
    @staticmethod
    def format_hedge_calculation(calc: Dict) -> str:
        """格式化对冲计算结果"""
        
        message = f"""
<b>📐 对冲配比计算 ({calc['fund_name']})</b>

<b>【套利资金分配】</b>
• 总套利金额: <code>{calc['arbitrage_amount_cny']:,.0f}</code> 元

<b>【A股端 (买入LOF)】</b>
• 买入金额: <code>{calc['fund_amount_cny']:,.0f}</code> 元
• 基金仓位: <code>{calc['fund_position_ratio']*100:.0f}%</code>
• 实际ETF敞口: <code>{calc['fund_exposure_cny']:,.0f}</code> 元
  <i>({calc['fund_amount_cny']:,.0f} × {calc['fund_position_ratio']})</i>

<b>【美股端 (对冲)】</b>
• 汇率: <code>{calc['usdcny_rate']:.2f}</code> (USD/CNY)
• 需对冲美元: <code>{calc['hedge_usd_amount']:,.0f}</code> 美元
  <i>({calc['fund_exposure_cny']:,.0f} ÷ {calc['usdcny_rate']:.2f})</i>
• ETF标的: <code>{calc['etf_symbol']}</code>
• ETF价格: <code>${calc['etf_price_usd']:.2f}</code>
• 买入股数: <code>{calc['etf_shares']}</code> 股
• 实际对冲: <code>{calc['actual_hedge_usd']:,.0f}</code> 美元
  <i>({calc['etf_shares']} × ${calc['etf_price_usd']:.2f})</i>

<b>【对冲效果】</b>
• 对冲比例: <code>{calc['hedge_ratio']*100:.1f}%</code>
• 敞口差额: <code>{calc['fund_exposure_cny'] - calc['actual_hedge_cny']:+.0f}</code> 元

<b>💡 操作示例</b>
<code>
步骤1: 买入 {calc['fund_amount_cny']:,.0f}元 {calc['fund_code']}
步骤2: 同时买入 {calc['etf_shares']}股 {calc['etf_symbol']} (约{calc['actual_hedge_usd']:,.0f}美元)
步骤3: T+1日提交{calc['fund_code']}赎回
步骤4: T+1日卖出{calc['etf_shares']}股 {calc['etf_symbol']}
</code>
"""
        return message


class TelegramNotifier:
    """Telegram通知器"""
    
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        
    def validate_config(self) -> bool:
        """验证配置是否有效"""
        if not self.bot_token or self.bot_token == "YOUR_BOT_TOKEN":
            print("❌ 错误: 请设置TELEGRAM_BOT_TOKEN环境变量")
            return False
        if not self.chat_id or self.chat_id == "YOUR_CHAT_ID":
            print("❌ 错误: 请设置TELEGRAM_CHAT_ID环境变量")
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
                    print(f"✅ 消息发送成功")
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
    
    def format_discount_alert(self, fund_code: str, fund_name: str,
                             est_nav: float, market_price: float,
                             premium: float, etf_change: float,
                             etf_symbol: str, confidence: str,
                             hedge_calc: Dict) -> str:
        """格式化折价套利提醒"""
        
        message = f"""
<b>🟢 折价套利机会提醒</b>

<b>{fund_name} ({fund_code})</b>

<b>【估值数据】</b>
• 估算净值: <code>{est_nav:.4f}</code>
• 场内价格: <code>{market_price:.3f}</code>
• 折价率: <code>{abs(premium):.2f}%</code> ⬇️
• 置信度: {confidence}

<b>【对冲标的】</b>
• {etf_symbol}涨跌: {etf_change:+.2f}%

<b>【盈亏估算】</b>
• 理论收益: {abs(premium):.2f}%
• 扣除成本(0.53%): {abs(premium) - 0.53:+.2f}%
• 建议操作金额: {hedge_calc['arbitrage_amount_cny']:,.0f}元

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return message


def check_discount_arbitrage(fund_code: str = "161127", force: bool = False,
                             arbitrage_amount: float = 10000.0) -> bool:
    """
    检查折价套利机会
    
    Args:
        fund_code: 基金代码
        force: 强制发送，无视阈值
        arbitrage_amount: 套利金额（默认1万元）
    """
    from professional_estimator import ProfessionalEstimator
    
    print(f"正在检查 {fund_code} 折价套利机会...")
    
    # 创建估算器
    estimator = ProfessionalEstimator(fund_code)
    result = estimator.estimate()
    
    # 创建通知器
    notifier = TelegramNotifier()
    
    # 获取阈值
    thresholds = ALERT_THRESHOLDS.get(fund_code, ALERT_THRESHOLDS["161127"])
    premium = result.premium
    
    # 只检查折价（premium < 0）
    is_discount = premium < 0
    meets_threshold = abs(premium) >= abs(thresholds["premium_low"])
    
    # 判断是否需要提醒
    should_notify = force or (is_discount and meets_threshold)
    
    if should_notify:
        # 计算对冲配比
        calc = HedgeCalculator.calculate_hedge_ratio(fund_code, arbitrage_amount)
        
        # 确定ETF符号和涨跌
        config = FUND_CONFIG.get(fund_code, FUND_CONFIG["161127"])
        etf_symbol = config["proxy_etf"]
        etf_change = result.xop_sources[0].value if result.xop_sources else 0
        
        # 发送折价套利提醒
        alert_msg = notifier.format_discount_alert(
            fund_code=fund_code,
            fund_name=result.fund_name,
            est_nav=result.final_est,
            market_price=result.market_price,
            premium=premium,
            etf_change=etf_change,
            etf_symbol=etf_symbol,
            confidence=result.confidence,
            hedge_calc=calc
        )
        
        success = notifier.send_message(alert_msg)
        
        # 发送对冲配比计算
        if success:
            hedge_msg = HedgeCalculator.format_hedge_calculation(calc)
            notifier.send_message(hedge_msg)
        
        return success
    else:
        if not is_discount:
            print(f"当前溢价 {premium:.2f}%，不是折价，不提醒")
        elif not meets_threshold:
            print(f"折价率 {abs(premium):.2f}% 未达到阈值({abs(thresholds['premium_low']):.2f}%)，不提醒")
        return True


def monitor_discount_loop(interval: int = 300, fund_codes: List[str] = None,
                         arbitrage_amount: float = 10000.0):
    """
    持续监控折价套利机会
    
    Args:
        interval: 检查间隔（秒），默认5分钟
        fund_codes: 监控的基金代码列表
        arbitrage_amount: 套利金额
    """
    if fund_codes is None:
        fund_codes = ["161127"]  # 默认只监控161127
    
    notifier = TelegramNotifier()
    if not notifier.validate_config():
        print("配置无效，退出监控")
        return
    
    print(f"启动折价套利监控循环，检查间隔: {interval}秒")
    print(f"监控基金: {', '.join(fund_codes)}")
    print(f"套利金额: {arbitrage_amount:,.0f}元")
    
    # 发送启动通知
    start_msg = f"""
<b>🤖 LOF折价套利监控系统已启动</b>

监控基金:
• 161127 标普生物科技 (XBI对冲)

套利配置:
• 操作金额: {arbitrage_amount:,.0f}元
• 折价阈值: ≥0.5%
• 检查间隔: {interval//60}分钟

<b>仅监控折价套利机会</b>
<i>（溢价套利不做）</i>

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    notifier.send_message(start_msg)
    
    # 监控循环
    import time
    try:
        while True:
            for fund_code in fund_codes:
                try:
                    check_discount_arbitrage(fund_code, arbitrage_amount=arbitrage_amount)
                except Exception as e:
                    print(f"检查 {fund_code} 出错: {e}")
            
            print(f"下次检查: {interval}秒后")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n监控已停止")
        stop_msg = f"""
<b>🛑 LOF折价套利监控系统已停止</b>

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        notifier.send_message(stop_msg)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="LOF折价套利Telegram提醒 (仅折价)")
    parser.add_argument("--fund", default="161127", help="基金代码，默认161127")
    parser.add_argument("--amount", type=float, default=10000, help="套利金额，默认10000元")
    parser.add_argument("--monitor", action="store_true", help="持续监控模式")
    parser.add_argument("--interval", type=int, default=300, help="监控间隔(秒)，默认300")
    parser.add_argument("--force", action="store_true", help="强制发送通知")
    parser.add_argument("--calc-only", action="store_true", help="仅计算对冲配比")
    args = parser.parse_args()
    
    if args.calc_only:
        # 仅计算并显示对冲配比
        calc = HedgeCalculator.calculate_hedge_ratio(args.fund, args.amount)
        print(HedgeCalculator.format_hedge_calculation(calc))
        return
    
    if args.monitor:
        monitor_discount_loop(args.interval, [args.fund], args.amount)
    else:
        success = check_discount_arbitrage(args.fund, args.force, args.amount)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
