# IB 实时行情集成指南（IB专用版）

> ⚠️ **重要提示**: 本版本仅使用 Interactive Brokers (IB) 数据源，**无降级机制**。IB数据失败时，系统将提示错误，建议不交易。

## 📋 功能概述

### 核心特性
- ✅ **仅IB数据源** - 不使用新浪财经、akshare等低质量数据源
- ✅ **全时段覆盖** - 盘前(Pre-market)、常规(Regular)、盘后(After-hours)
- ✅ **盘后数据快照** - 自动保存盘后收盘价，用于A股开盘预估
- ✅ **交易时段智能判断** - 自动识别当前处于哪个交易时段
- ✅ **A股开盘预估** - 基于美股盘后数据预估次日华宝油气净值变化
- ❌ **无降级机制** - IB失败时不使用备用数据源，建议不交易

### 新增文件
| 文件 | 说明 | 大小 |
|-----|------|------|
| `ib_realtime_client.py` | IB API 实时行情客户端（含盘后） | 26KB |
| `quote_manager.py` | **IB专用版** 行情管理器 | 20KB |
| `lof_tracker_ib.py` | **IB专用版** LOF跟踪器 | 21KB |
| `start_ib_tracker.sh` | 一键启动脚本（已更新） | 6KB |
| `demo_ib_quote.py` | 功能演示脚本（已更新） | 9KB |
| `ib_config.json` | 配置文件（已更新） | 2KB |
| `IB_QUOTE_README.md` | 本文档 | - |

## 📅 美股交易时段（北京时间）

| 时段 | 美东时间 | 北京时间（夏令时）| 北京时间（冬令时）| 图标 |
|-----|---------|-----------------|-----------------|------|
| **盘前** | 4:00-9:30 | 16:00-21:30 | 17:00-22:30 | 🌅 |
| **常规** | 9:30-16:00 | 21:30-04:00 | 22:30-05:00 | ☀️ |
| **盘后** | 16:00-20:00 | 04:00-08:00 | 05:00-09:00 | 🌙 |

> 夏令时 = 3月第2周日-11月第1周日，其余为冬令时

### 对LOF套利的意义

```
美股盘后收盘 (08:00 Beijing) ─────→ A股开盘 (09:30 Beijing)
            ↑                               ↓
      XOP盘后行情已确定              华宝油气开始交易
```

**套利策略**：
- 如果美股盘后XOP大涨/大跌，可在A股开盘前预判净值变化
- 提前知道溢价/折价方向，抢开盘套利机会

## 🚀 快速开始

### 1. 确保IB Gateway已启动

```bash
# 参考 ib-data 项目启动Gateway
/root/quant/ib-data/scripts/start_vnc.sh

# 在VNC中登录IB Gateway
```

### 2. 运行跟踪器

```bash
cd /root/quant/fund_arbitrage

# 方式1: 一键启动（自动检测IB连接和交易时段）
./start_ib_tracker.sh

# 方式2: 仅运行一次
./start_ib_tracker.sh --once

# 方式3: 查看A股开盘预估（基于盘后数据）
./start_ib_tracker.sh --forecast

# 方式4: 显示当前交易时段信息
./start_ib_tracker.sh --session
```

### 3. 命令行选项

```bash
./start_ib_tracker.sh --help

# 选项:
#   --forecast     A股开盘预估
#   --session      显示交易时段
#   --once         单次运行
#   --interval N   设置间隔(秒)
```

**注意**: `--no-ib` 选项已移除，本系统仅使用IB数据源。

## 📊 使用示例

### 示例1: A股开盘预估（重点功能）

```bash
./start_ib_tracker.sh --forecast
```

输出示例：
```
A股开盘预估 (基于IB盘后数据)
======================================

📊 XOP 盘后数据:
  常规收盘价: $152.30
  盘后收盘价: $153.80
  盘后涨跌幅: +0.98%

📈 华宝油气(162411) 开盘预估:
  预估净值变化: 📈 上涨 +0.93%
  预估净值: 0.9740 (基于昨日净值 0.9650)

💡 套利建议:
  ✓ 预估高开，可适当布局

📋 数据质量: 🟢 high (0.5小时前)
```

### 示例2: Python代码集成

```python
from quote_manager import QuoteManager, TradingHours

# 创建行情管理器
qm = QuoteManager(auto_connect=True)

# 检查IB连接状态
status = qm.get_connection_status()
if not status['ib_connected']:
    print("❌ IB未连接，建议不交易")
    qm.close()
    return

# 获取当前交易时段
session = TradingHours.get_session()
print(f"当前时段: {session.value}")

# 获取XOP行情（仅使用IB数据源）
quote = qm.get_quote("XOP")
if quote:
    print(f"XOP: ${quote.price:.2f} ({quote.change_pct:+.2f}%)")
    print(f"时段: {quote.session}")
else:
    print("❌ IB获取失败，建议不交易")

# 获取盘后收盘参考价（用于A股开盘预估）
ah_quote = qm.get_after_hours_reference("XOP")
if ah_quote:
    print(f"盘后收盘: ${ah_quote.price:.2f}")

# 获取A股开盘预估
forecast = qm.get_a_share_open_forecast("XOP")
if forecast:
    print(f"预估净值变化: {forecast['forecast_nav_change']:+.2f}%")
    print(f"数据可靠性: {forecast['reliability']}")

qm.close()
```

### 示例3: LOF跟踪器完整用法

```python
from lof_tracker_ib import LOFTrackerIB

# 创建跟踪器
tracker = LOFTrackerIB(
    fund_code="162411",
    use_ib=True
)

# 检查IB连接
if not tracker.quote_manager or not tracker.quote_manager._ib_connected:
    print("❌ IB未连接，建议不交易")
    return

# 执行一次跟踪
result = tracker.track()
tracker.print_report(result)

# 数据质量信息
print(f"XOP数据源: {result.data_quality['xop_source']}")
print(f"是否实时: {result.data_quality['xop_is_realtime']}")
print(f"是否盘后: {result.data_quality['xop_is_extended']}")

# A股开盘预估（如果休市）
if result.a_share_forecast:
    print(f"预估净值变化: {result.a_share_forecast['forecast_nav_change']:+.2f}%")

tracker.quote_manager.close()
```

## 🔧 数据源策略

### 重要变更

| 版本 | 策略 |
|-----|------|
| v1.x | 多数据源，智能降级（IB → 新浪财经 → akshare）|
| **v2.x** | **仅IB数据源，无降级机制** |

### 仅使用IB数据源的原因

1. **数据质量** - IB数据准确可靠，新浪财经/akshare有延迟和误差
2. **交易安全** - 低质量数据可能导致错误交易决策
3. **简单明确** - 数据要么来自IB（可信），要么不可用（不交易）

### 数据有效期

| 数据源 | 有效期 |
|-------|--------|
| IB实时数据 | 5秒 |
| IB盘后快照 | 1小时（作为A股开盘参考）|

## 📁 数据存储

### 盘后数据快照
- 路径: `after_hours_snapshots/ah_snapshot_YYYYMMDD.json`
- 自动保存: 美股盘后收盘时(20:00 ET)
- 用途: A股开盘前净值预估

### 跟踪数据
- 路径: `tracking_data/ib_tracking_162411_YYYYMMDD.jsonl`
- 格式: JSON Lines
- 包含: 完整跟踪记录，含交易时段信息

## ⚠️ 常见问题

### Q: IB连接失败怎么办？
A: 系统将提示错误，**建议不交易**。不会降级到其他数据源。

### Q: 如何判断当前使用的是不是盘后数据？
A: 查看报告中的标记：
- 🌙 = 盘后数据
- 🌅 = 盘前数据
- ☀️ = 常规交易数据
- ⚡实时 = IB实时推送

### Q: 盘后数据有什么用？
A: 美股盘后收盘时间是北京时间08:00，A股09:30开盘。盘后XOP涨跌可用于预估华宝油气开盘净值，提前发现套利机会。

### Q: 为什么移除了新浪财经/akshare支持？
A: 这些数据源质量不稳定，有延迟和误差。为确保交易决策的准确性，本系统仅使用IB数据源。

### Q: 盘后快照什么时候保存？
A: 自动在美股盘后收盘时(20:00 ET / 北京时间08:00或09:00)保存。

## 🔄 数据流向

```
┌─────────────────────────────────────┐
│            数据源层                  │
├─────────────────────────────────────┤
│  IB实时行情 (唯一数据源)              │
│  - 盘前/常规/盘后 全时段              │
│  - 盘后快照保存                       │
└──────────────┬──────────────────────┘
               │
    ┌──────────▼──────────┐
    │  quote_manager.py   │
    │  (IB专用版)          │
    │  - 无降级机制        │
    │  - IB失败返回None    │
    └──────────┬──────────┘
               │
    ┌──────────▼──────────┐
    │  lof_tracker_ib.py  │
    │  (IB专用版)          │
    │  - 仅使用IB数据      │
    └──────────┬──────────┘
               │
    ┌──────────▼──────────┐
    │   报告/数据存储      │
    │   - 盘后快照         │
    │   - 跟踪数据         │
    └─────────────────────┘
```

## 📝 更新日志

### v2.0 (2026-03-27) - IB专用版
- 🔥 **重大变更**: 仅使用IB数据源
- 🔥 **移除**: 新浪财经、akshare等备用数据源
- 🔥 **移除**: 自动降级机制
- ✅ IB失败时提示错误，建议不交易

### v1.1 (2026-03-26)
- ✨ 支持美股盘前/盘后数据
- ✨ 新增盘后数据快照自动保存
- ✨ 新增A股开盘预估功能
- ✨ 新增交易时段判断和显示

### v1.0 (2026-03-26)
- ✨ 新增 IB 实时行情支持
- ✨ 新增智能数据源降级
- ✨ 新增数据质量监控
