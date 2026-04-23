#!/bin/bash
# LOF套利监控启动脚本

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}   LOF套利Telegram监控系统               ${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: 未找到python3${NC}"
    exit 1
fi

# 检查配置文件
if [ ! -f "notify_config.json" ]; then
    echo -e "${RED}错误: 未找到notify_config.json${NC}"
    echo "请先编辑notify_config.json配置Telegram信息"
    exit 1
fi

# 检查环境变量
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    echo -e "${YELLOW}警告: 环境变量未设置${NC}"
    echo ""
    echo "请选择配置方式:"
    echo "1. 临时设置环境变量"
    echo "2. 从notify_config.json读取"
    echo "3. 显示设置指南"
    echo ""
    read -p "请输入选项 (1/2/3): " choice
    
    case $choice in
        1)
            read -p "请输入Bot Token: " token
            read -p "请输入Chat ID: " chat_id
            export TELEGRAM_BOT_TOKEN="$token"
            export TELEGRAM_CHAT_ID="$chat_id"
            echo -e "${GREEN}环境变量已设置${NC}"
            ;;
        2)
            # 从JSON读取配置
            if command -v jq &> /dev/null; then
                token=$(jq -r '.telegram.bot_token' notify_config.json)
                chat_id=$(jq -r '.telegram.chat_id' notify_config.json)
                export TELEGRAM_BOT_TOKEN="$token"
                export TELEGRAM_CHAT_ID="$chat_id"
                echo -e "${GREEN}已从配置文件读取${NC}"
            else
                echo -e "${RED}错误: 需要安装jq来解析JSON${NC}"
                echo "安装: apt-get install jq 或 brew install jq"
                exit 1
            fi
            ;;
        3)
            python3 telegram_notifier.py --setup
            exit 0
            ;;
        *)
            echo -e "${RED}无效选项${NC}"
            exit 1
            ;;
    esac
fi

# 测试发送
echo ""
echo -e "${YELLOW}正在测试Telegram连接...${NC}"
python3 telegram_notifier.py --fund 162411 --force

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ 测试成功！${NC}"
    echo ""
    read -p "是否启动持续监控? (y/n): " start_monitor
    
    if [ "$start_monitor" = "y" ] || [ "$start_monitor" = "Y" ]; then
        echo ""
        echo -e "${GREEN}启动监控... 按Ctrl+C停止${NC}"
        echo ""
        python3 telegram_notifier.py --monitor --interval 300
    else
        echo ""
        echo "使用以下命令手动检查:"
        echo "  python3 telegram_notifier.py --fund 162411"
        echo "  python3 telegram_notifier.py --fund 161127"
        echo ""
        echo "启动监控:"
        echo "  python3 telegram_notifier.py --monitor --interval 300"
    fi
else
    echo -e "${RED}❌ 测试失败，请检查配置${NC}"
    exit 1
fi
