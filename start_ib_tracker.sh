#!/bin/bash
#
# LOF实时跟踪启动脚本 (IB专用版 - 仅使用IB数据源)
# ==================================================
#
# Usage:
#   ./start_ib_tracker.sh              # 启动持续跟踪
#   ./start_ib_tracker.sh --once       # 运行一次
#   ./start_ib_tracker.sh --forecast   # 仅显示A股开盘预估
#   ./start_ib_tracker.sh --session    # 显示交易时段信息
#

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  LOF实时跟踪启动器 (IB专用版)${NC}"
echo -e "${BLUE}  仅使用IB数据源，无降级机制${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查Python
echo -e "${BLUE}▶ 检查Python环境...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python3 未安装${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1)
echo -e "${GREEN}✓ Python版本: $PYTHON_VERSION${NC}"

# 检查依赖
echo ""
echo -e "${BLUE}▶ 检查依赖...${NC}"

# 检查pytz
if python3 -c "import pytz" 2>/dev/null; then
    echo -e "${GREEN}✓ pytz 已安装${NC}"
else
    echo -e "${YELLOW}⚠ pytz 未安装，正在安装...${NC}"
    pip3 install pytz -q
fi

# 检查ibapi
if python3 -c "from ibapi.client import EClient" 2>/dev/null; then
    echo -e "${GREEN}✓ ibapi 已安装${NC}"
else
    echo -e "${YELLOW}⚠ ibapi 未安装，正在安装...${NC}"
    pip3 install ibapi -q
fi

# 获取脚本目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 显示当前交易时段信息
echo ""
echo -e "${CYAN}▶ 当前交易时段:${NC}"
python3 -c "
from ib_realtime_client import TradingHours
info = TradingHours.get_session_info()
session_icons = {
    'pre_market': '🌅',
    'regular': '☀️',
    'after_hours': '🌙',
    'closed': '🌑'
}
icon = session_icons.get(info['session'], '❓')
print(f\"  {icon} 美股时段: {info['session']}\")
print(f\"  🕐 ET时间: {info['et_time']}\")
print(f\"  🕐 北京时间: {info['beijing_time']}\")
print(f\"  ⏳ 距A股开盘: {info['hours_to_a_share_open']:.1f}小时\")
" 2>/dev/null || echo -e "${YELLOW}  (无法获取时段信息)${NC}"

# 检查IB Gateway连接
echo ""
echo -e "${BLUE}▶ 检查IB Gateway连接...${NC}"
IB_HOST="${IB_HOST:-127.0.0.1}"
IB_PORT="${IB_PORT:-4002}"

if timeout 2 bash -c "echo >/dev/tcp/$IB_HOST/$IB_PORT" 2>/dev/null; then
    echo -e "${GREEN}✓ IB Gateway 可连接 ($IB_HOST:$IB_PORT)${NC}"
    IB_AVAILABLE=true
else
    echo -e "${RED}✗ IB Gateway 未启动 ($IB_HOST:$IB_PORT)${NC}"
    echo -e "${YELLOW}  请先启动IB Gateway后再运行本系统${NC}"
    IB_AVAILABLE=false
fi

# 解析参数
ONCE=false
FORECAST=false
SHOW_SESSION=false
INTERVAL=5

while [[ $# -gt 0 ]]; do
    case $1 in
        --once)
            ONCE=true
            shift
            ;;
        --forecast)
            FORECAST=true
            shift
            ;;
        --session)
            SHOW_SESSION=true
            shift
            ;;
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        --help)
            echo ""
            echo "用法: ./start_ib_tracker.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --forecast     仅显示A股开盘预估（基于IB盘后数据）"
            echo "  --session      显示交易时段信息"
            echo "  --once         只运行一次"
            echo "  --interval N   设置跟踪间隔(秒)，默认5秒"
            echo "  --help         显示帮助"
            echo ""
            echo "环境变量:"
            echo "  IB_HOST        IB Gateway主机 (默认: 127.0.0.1)"
            echo "  IB_PORT        IB Gateway端口 (默认: 4002)"
            echo ""
            echo "注意:"
            echo "  本系统仅使用IB数据源，IB失败时不会降级到其他数据源"
            echo "  如果IB Gateway未启动，系统将提示错误并建议不交易"
            echo ""
            exit 0
            ;;
        *)
            echo -e "${RED}✗ 未知选项: $1${NC}"
            echo "使用 --help 查看帮助"
            exit 1
            ;;
    esac
done

# 构建命令
echo ""
echo -e "${BLUE}▶ 启动跟踪...${NC}"

# 判断运行模式
if [ "$SHOW_SESSION" = true ]; then
    CMD="python3 lof_tracker_ib.py --session-info"
    echo -e "${BLUE}  模式: 显示交易时段信息${NC}"
elif [ "$FORECAST" = true ]; then
    CMD="python3 lof_tracker_ib.py --forecast"
    echo -e "${CYAN}  模式: A股开盘预估${NC}"
elif [ "$ONCE" = true ]; then
    CMD="python3 lof_tracker_ib.py --once"
    echo -e "${BLUE}  模式: 单次运行${NC}"
else
    CMD="python3 lof_tracker_ib.py --interval $INTERVAL"
    echo -e "${BLUE}  模式: 持续跟踪 (间隔: ${INTERVAL}秒)${NC}"
fi

# IB连接参数
if [ "$IB_AVAILABLE" = true ]; then
    CMD="$CMD --ib-host $IB_HOST --ib-port $IB_PORT"
    echo -e "${GREEN}  数据源: IB实时行情（含盘前盘后）${NC}"
else
    echo -e "${RED}  警告: IB Gateway未连接，系统将提示错误${NC}"
fi

echo ""
echo -e "${BLUE}----------------------------------------${NC}"

# 执行
eval $CMD

# 捕获退出状态
EXIT_CODE=$?

echo ""
echo -e "${BLUE}----------------------------------------${NC}"

if [ $EXIT_CODE -eq 0 ] || [ $EXIT_CODE -eq 130 ]; then  # 130 = Ctrl+C
    echo -e "${GREEN}✓ 程序已退出${NC}"
else
    echo -e "${RED}✗ 程序异常退出 (代码: $EXIT_CODE)${NC}"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  提示:${NC}"
echo -e "${BLUE}  • 本系统仅使用IB数据源，无降级机制${NC}"
echo -e "${BLUE}  • IB失败时建议不交易${NC}"
echo -e "${BLUE}  • 盘后数据保存在 after_hours_snapshots/ 目录${NC}"
echo -e "${BLUE}  • 跟踪数据保存在 tracking_data/ 目录${NC}"
echo -e "${BLUE}  • 使用 --help 查看更多选项${NC}"
echo -e "${BLUE}========================================${NC}"
