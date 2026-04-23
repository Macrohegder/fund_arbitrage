#!/bin/bash
#
# 设置LOF折价套利定时任务
# ======================
#
# Usage:
#   ./setup_cron.sh          # 安装定时任务
#   ./setup_cron.sh --remove # 移除定时任务
#   ./setup_cron.sh --list   # 查看当前定时任务
#

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ALERT_SCRIPT="$SCRIPT_DIR/run_alert.sh"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  LOF折价套利定时任务管理${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查脚本是否存在
if [ ! -f "$ALERT_SCRIPT" ]; then
    echo -e "${RED}错误: 找不到脚本 $ALERT_SCRIPT${NC}"
    exit 1
fi

# 解析参数
case "${1:-}" in
    --remove)
        echo -e "${YELLOW}▶ 移除定时任务...${NC}"
        
        # 备份当前crontab
        crontab -l 2>/dev/null > /tmp/crontab_backup_$(date +%Y%m%d_%H%M%S).txt
        
        # 删除包含fund_arbitrage的行
        crontab -l 2>/dev/null | grep -v "fund_arbitrage" | crontab -
        
        echo -e "${GREEN}✅ 定时任务已移除${NC}"
        echo "备份保存在: /tmp/crontab_backup_*.txt"
        ;;
        
    --list)
        echo -e "${CYAN}▶ 当前定时任务:${NC}"
        echo ""
        crontab -l 2>/dev/null | grep -E "fund_arbitrage|# LOF" || echo "没有LOF相关定时任务"
        ;;
        
    --help)
        echo "用法: $0 [选项]"
        echo ""
        echo "选项:"
        echo "  (无)       安装定时任务"
        echo "  --remove   移除定时任务"
        echo "  --list     查看当前定时任务"
        echo "  --help     显示帮助"
        echo ""
        echo "安装的定时任务:"
        echo "  1. A股交易时段每5分钟检查折价>1%的机会"
        echo "  2. 美股盘后收盘后发送A股开盘预估"
        echo ""
        ;;
        
    *)
        # 安装模式
        echo -e "${GREEN}▶ 安装定时任务...${NC}"
        echo ""
        
        # 首先移除旧的
        echo -e "${YELLOW}  清理旧任务...${NC}"
        crontab -l 2>/dev/null | grep -v "fund_arbitrage" > /tmp/crontab_new.txt || true
        
        # 添加新任务
        echo "" >> /tmp/crontab_new.txt
        echo "# LOF折价套利监控 - 安装时间: $(date '+%Y-%m-%d %H:%M:%S')" >> /tmp/crontab_new.txt
        echo "# 折价阈值: >1%" >> /tmp/crontab_new.txt
        echo "# 监控基金: 162411(华宝油气), 161127(标普生物科技)" >> /tmp/crontab_new.txt
        echo "" >> /tmp/crontab_new.txt
        
        # 任务1: A股交易时段每5分钟检查
        echo "# A股交易时段监控折价机会 (周一到周五 9:30-15:00)" >> /tmp/crontab_new.txt
        echo "*/5 9-15 * * 1-5 $ALERT_SCRIPT >> /tmp/lof_cron.log 2>&1" >> /tmp/crontab_new.txt
        echo "" >> /tmp/crontab_new.txt
        
        # 任务2: 美股盘后发送A股开盘预估（夏令时08:30，冬令时09:30）
        # 这里用08:30，如果是冬令时会有一小时偏差，但影响不大
        echo "# 美股盘后收盘后发送A股开盘预估 (周二到周六 08:30)" >> /tmp/crontab_new.txt
        echo "30 8 * * 2-6 $ALERT_SCRIPT --forecast >> /tmp/lof_cron.log 2>&1" >> /tmp/crontab_new.txt
        echo "" >> /tmp/crontab_new.txt
        
        # 应用新crontab
        crontab /tmp/crontab_new.txt
        rm -f /tmp/crontab_new.txt
        
        echo -e "${GREEN}✅ 定时任务已安装${NC}"
        echo ""
        echo -e "${CYAN}已添加的定时任务:${NC}"
        echo "  1. A股交易时段每5分钟检查折价>1%的机会"
        echo "     时间: 周一到周五 09:00-15:59"
        echo ""
        echo "  2. 美股盘后发送A股开盘预估"
        echo "     时间: 周二到周六 08:30"
        echo ""
        echo -e "${YELLOW}注意:${NC}"
        echo "  • 请确保IB Gateway在美股交易时段保持连接"
        echo "  • 日志文件: logs/alert_YYYYMMDD.log"
        echo "  • crontab日志: /tmp/lof_cron.log"
        echo ""
        echo -e "${CYAN}查看定时任务:${NC}"
        echo "  crontab -l"
        echo ""
        echo -e "${CYAN}手动测试:${NC}"
        echo "  $ALERT_SCRIPT --force"
        ;;
esac

echo ""
echo -e "${BLUE}========================================${NC}"
