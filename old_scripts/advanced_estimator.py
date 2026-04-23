#!/usr/bin/env python3
"""
华宝油气高级估值器
结合多个数据源，提供更准确的EST估算

公式:
实时EST = 昨日净值 × (1 + XOP涨跌幅 × 仓位) × (1 + 汇率变化)

vs 天天基金估算:
天天基金EST = 昨日净值 × (1 + 重仓股涨跌估算)
"""

import requests
import json
from datetime import datetime


class AdvancedEstimator:
    """高级估值器"""
    
    def __init__(self):
        self.fund_code = "162411"
        self.position_ratio = 0.95
        
    def get_last_nav(self) -> float:
        """获取昨日净值"""
        url = f"http://fundgz.1234567.com.cn/js/{self.fund_code}.js"
        try:
            resp = requests.get(url, timeout=5)
            text = resp.text
            if "jsonpgz(" in text:
                data = json.loads(text[8:-2])
                return float(data.get("dwjz", 0))  # 昨日净值
        except:
            pass
        return 0.965  # 默认值
    
    def get_xop_change(self) -> float:
        """获取XOP涨跌幅"""
        # 使用新浪财经美股API
        url = "https://hq.sinajs.cn/list=usr_xop"
        try:
            resp = requests.get(url, timeout=5, headers={
                "Referer": "https://finance.sina.com.cn"
            })
            text = resp.text
            # var hq_str_usr_xop="价格,昨收,..."
            parts = text.split('"')[1].split(",")
            if len(parts) >= 2:
                price = float(parts[0])
                prev = float(parts[1])
                return (price - prev) / prev * 100
        except:
            pass
        return 0
    
    def get_usd_cny_change(self) -> float:
        """获取USD/CNY汇率变化"""
        # 这里简化处理，实际应该获取中间价变化
        # 返回今日汇率相对昨日变化百分比
        return 0  # 简化
    
    def calculate_est(self) -> dict:
        """计算三种EST"""
        last_nav = self.get_last_nav()
        xop_change = self.get_xop_change()
        rate_change = self.get_usd_cny_change()
        
        # 官方EST (T-1数据)
        official_est = last_nav
        
        # 参考EST (官方 + 汇率调整)
        reference_est = official_est * (1 + rate_change / 100)
        
        # 实时EST (参考 + XOP影响)
        realtime_est = reference_est * (1 + xop_change * self.position_ratio / 100)
        
        return {
            "last_nav": round(last_nav, 4),
            "official_est": round(official_est, 4),
            "reference_est": round(reference_est, 4),
            "realtime_est": round(realtime_est, 4),
            "xop_change": round(xop_change, 2),
            "rate_change": round(rate_change, 2),
            "timestamp": datetime.now().isoformat(),
        }
    
    def compare_with_tiantian(self):
        """对比天天基金估算"""
        # 获取天天基金估算
        url = f"http://fundgz.1234567.com.cn/js/{self.fund_code}.js"
        try:
            resp = requests.get(url, timeout=5)
            text = resp.text
            if "jsonpgz(" in text:
                data = json.loads(text[8:-2])
                tt_est = float(data.get("gsz", 0))
                
                # 计算我们的估算
                our_est = self.calculate_est()
                
                print("=" * 60)
                print("华宝油气估值对比")
                print("=" * 60)
                print(f"\n【昨日净值】{our_est['last_nav']}")
                print()
                print("【三种EST】")
                print(f"  官方EST (T-1):     {our_est['official_est']}")
                print(f"  参考EST (含汇率):  {our_est['reference_est']}")
                print(f"  实时EST (含XOP):   {our_est['realtime_est']}")
                print()
                print(f"【天天基金估算】     {tt_est}")
                print()
                
                # 计算差异
                diff = abs(tt_est - our_est['realtime_est']) / our_est['realtime_est'] * 100
                print(f"【差异】            {diff:.2f}%")
                
                if diff < 0.1:
                    print("  ✅ 差异很小，估算可信")
                elif diff < 0.3:
                    print("  ⚠️  差异中等，建议谨慎")
                else:
                    print("  ❌ 差异较大，可能存在调仓或数据异常")
                    
                print("=" * 60)
                
        except Exception as e:
            print(f"获取失败: {e}")


if __name__ == "__main__":
    est = AdvancedEstimator()
    est.compare_with_tiantian()
