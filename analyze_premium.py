#!/usr/bin/env python3
"""
LOF基金溢价率历史分析
用于分析跟踪数据，生成统计报告
"""

import json
import glob
import pandas as pd
from datetime import datetime
from pathlib import Path
import argparse


def load_tracking_data(fund_code: str, days: int = 30) -> pd.DataFrame:
    """加载历史跟踪数据"""
    data_dir = Path(__file__).parent / "tracking_data"
    
    all_data = []
    for file_path in sorted(data_dir.glob(f"{fund_code}_*.jsonl")):
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    all_data.append(record)
                except:
                    continue
    
    if not all_data:
        return pd.DataFrame()
    
    # 转换为DataFrame
    df = pd.DataFrame(all_data)
    
    # 解析溢价率
    df['premium'] = df['premium'].apply(lambda x: x.get('premium', 0) if isinstance(x, dict) else 0)
    df['market_price'] = df['premium'].apply(lambda x: x.get('market_price', 0) if isinstance(x, dict) else 0)
    df['est_nav'] = df['premium'].apply(lambda x: x.get('est_nav', 0) if isinstance(x, dict) else 0)
    
    # 解析时间
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # 筛选最近N天
    if days > 0:
        cutoff = datetime.now() - pd.Timedelta(days=days)
        df = df[df['timestamp'] > cutoff]
    
    return df.sort_values('timestamp')


def analyze_premium(df: pd.DataFrame, fund_code: str):
    """分析溢价率数据"""
    if df.empty:
        print(f"没有{fund_code}的历史数据")
        return
    
    print("=" * 60)
    print(f"📊 {fund_code} 溢价率分析报告")
    print("=" * 60)
    print(f"数据区间: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    print(f"数据条数: {len(df)}")
    print()
    
    # 基础统计
    print("【基础统计】")
    print(f"  平均溢价: {df['premium'].mean():.2f}%")
    print(f"  中位数: {df['premium'].median():.2f}%")
    print(f"  标准差: {df['premium'].std():.2f}%")
    print(f"  最大溢价: {df['premium'].max():.2f}%")
    print(f"  最小溢价: {df['premium'].min():.2f}%")
    print()
    
    # 套利机会统计
    print("【套利机会统计】")
    premium_opps = (df['premium'] > 1.5).sum()
    hedge_opps = ((df['premium'] > 0.15) & (df['premium'] <= 1.5)).sum()
    discount_opps = (df['premium'] < -0.5).sum()
    
    print(f"  溢价套利机会(>1.5%): {premium_opps}次 ({premium_opps/len(df)*100:.1f}%)")
    print(f"  XOP对冲机会(0.15%-1.5%): {hedge_opps}次 ({hedge_opps/len(df)*100:.1f}%)")
    print(f"  折价套利机会(<-0.5%): {discount_opps}次 ({discount_opps/len(df)*100:.1f}%)")
    print()
    
    # 时间段分析
    df['hour'] = df['timestamp'].dt.hour
    hourly_avg = df.groupby('hour')['premium'].mean()
    
    print("【时段分析】")
    print("  平均溢价率最高的时段:")
    for hour in hourly_avg.nlargest(3).index:
        print(f"    {hour:02d}:00 - {hourly_avg[hour]:.2f}%")
    print()
    
    # 最新数据
    latest = df.iloc[-1]
    print("【最新数据】")
    print(f"  时间: {latest['timestamp']}")
    print(f"  场内价格: {latest['market_price']}")
    print(f"  估算净值: {latest['est_nav']}")
    print(f"  溢价率: {latest['premium']:.2f}%")
    print()
    
    # 趋势判断
    recent = df.tail(10)['premium'].mean()
    overall = df['premium'].mean()
    
    if recent > overall * 1.1:
        trend = "近期溢价呈上升趋势 📈"
    elif recent < overall * 0.9:
        trend = "近期溢价呈下降趋势 📉"
    else:
        trend = "近期溢价相对稳定 ➡️"
    
    print(f"【趋势判断】{trend}")
    print("=" * 60)


def export_summary(df: pd.DataFrame, fund_code: str):
    """导出汇总数据"""
    if df.empty:
        return
    
    # 按日汇总
    df['date'] = df['timestamp'].dt.date
    daily = df.groupby('date').agg({
        'premium': ['mean', 'min', 'max', 'std'],
        'market_price': ['first', 'last'],
    }).round(2)
    
    # 保存CSV
    output_file = Path(__file__).parent / f"{fund_code}_daily_summary.csv"
    daily.to_csv(output_file)
    print(f"\n📁 日汇总数据已保存: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="LOF溢价率分析")
    parser.add_argument("--code", default="162411", help="基金代码")
    parser.add_argument("--days", type=int, default=7, help="分析最近N天")
    parser.add_argument("--export", action="store_true", help="导出CSV")
    args = parser.parse_args()
    
    # 加载数据
    df = load_tracking_data(args.code, args.days)
    
    # 分析
    analyze_premium(df, args.code)
    
    # 导出
    if args.export:
        export_summary(df, args.code)


if __name__ == "__main__":
    main()
