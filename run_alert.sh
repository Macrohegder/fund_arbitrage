#!/bin/bash
#
# LOF折价套利定时任务脚本
# =======================
#
# 这个脚本用于crontab定时执行，监控折价>1%的套利机会
#
# 添加到crontab:
#   crontab -e
#   # A股交易时段内每5分钟检查一次
#   */5 9-15 * * 1-5 /root/quant/fund_arbitrage/run_alert.sh
#   
#   # 美股盘后收盘后发送A股开盘预估（北京时间08:30，夏令时）
#   30 8 * * 2-6 /root/quant/fund_arbitrage/run_alert.sh --forecast
#

# 设置环境
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="/root/quant/fund_arbitrage:$PYTHONPATH"

# 脚本目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 日志目录
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# 日志文件
LOG_FILE="$LOG_DIR/alert_$(date +%Y%m%d).log"

# 记录开始
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始检查" >> "$LOG_FILE"

# 解析参数
MODE="check"  # check 或 forecast

while [[ $# -gt 0 ]]; do
    case $1 in
        --forecast)
            MODE="forecast"
            shift
            ;;
        --help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --forecast  发送A股开盘预估通知"
            echo "  --help      显示帮助"
            echo ""
            echo "示例crontab配置:"
            echo "  # A股交易时段每5分钟检查折价机会"
            echo "  */5 9-15 * * 1-5 $0"
            echo ""
            echo "  # 美股盘后收盘后发送开盘预估"
            echo "  30 8 * * 2-6 $0 --forecast"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            echo "使用 --help 查看帮助"
            exit 1
            ;;
    esac
done

# 执行检查
if [ "$MODE" = "forecast" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 发送A股开盘预估" >> "$LOG_FILE"
    python3 alert_notifier.py --fund 162411 --forecast >> "$LOG_FILE" 2>&1
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 检查折价套利机会" >> "$LOG_FILE"
    python3 alert_notifier.py --fund 162411 >> "$LOG_FILE" 2>&1
fi

EXIT_CODE=$?

# 记录结果
if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 检查完成" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 检查失败或异常 (代码: $EXIT_CODE)" >> "$LOG_FILE"
fi

echo "---" >> "$LOG_FILE"

# 清理7天前的日志
find "$LOG_DIR" -name "alert_*.log" -mtime +7 -delete 2>/dev/null

exit $EXIT_CODE
