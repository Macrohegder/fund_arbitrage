#!/bin/bash
# LOF基金监控脚本
# 可添加到crontab定时执行

FUND_CODE=${1:-"162411"}
ALERT_THRESHOLD=${2:-"1.0"}  # 溢价超过1%时提醒
LOG_DIR="$(dirname "$0")/logs"
DATA_DIR="$(dirname "$0")/tracking_data"

# 确保目录存在
mkdir -p "$LOG_DIR"
mkdir -p "$DATA_DIR"

# 运行跟踪
OUTPUT=$(python3 "$(dirname "$0")/lof_tracker.py" --code "$FUND_CODE" 2>&1)

# 获取当前时间
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

# 记录日志
echo "[$TIMESTAMP] $FUND_CODE" >> "$LOG_DIR/monitor.log"
echo "$OUTPUT" >> "$LOG_DIR/monitor.log"
echo "---" >> "$LOG_DIR/monitor.log"

# 检查是否出现套利机会
if echo "$OUTPUT" | grep -q "套利机会"; then
    PREMIUM=$(echo "$OUTPUT" | grep "溢价率:" | awk '{print $2}' | tr -d '%')
    
    # 检查是否超过阈值
    if (( $(echo "$PREMIUM > $ALERT_THRESHOLD" | bc -l) )); then
        echo "[$TIMESTAMP] 🔔 $FUND_CODE 溢价率达到 ${PREMIUM}%!" >> "$LOG_DIR/alerts.log"
        
        # 这里可以添加更多通知方式
        # 例如: 发送邮件、钉钉、企业微信等
        # python3 send_notification.py "$FUND_CODE" "$PREMIUM"
    fi
fi

# 保留最近7天的日志
find "$LOG_DIR" -name "*.log" -mtime +7 -delete

echo "监控完成: $TIMESTAMP"
