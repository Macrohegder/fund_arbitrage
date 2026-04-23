#!/bin/bash
# 检查 Palmmicro 最新文章日期

echo "=== 检查网站最新文章 ==="
python3 << 'PYEOF'
import httpx
from bs4 import BeautifulSoup
import re

async def check():
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://palmmicro.com/woody/blogcn.php")
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text()
        
        if "全部：" in text:
            content = text.split("全部：")[1]
            lines = [l.strip() for l in content.split('\n') if l.strip()]
            
            current_year = None
            for line in lines:
                if re.match(r'^\d{4}$', line):
                    current_year = line
                match = re.match(r'(\d{1,2})月(\d{1,2})日\s+(.+)', line)
                if match and current_year:
                    month, day, title = match.groups()
                    print(f"网站最新: {current_year}-{int(month):02d}-{int(day):02d} - {title}")
                    break

import asyncio
asyncio.run(check())
PYEOF

echo ""
echo "=== 本地已下载文章 ==="
ls -lt website_articles/*.md 2>/dev/null | head -3 | awk '{print $6, $7, $8, $9}'

echo ""
echo "=== 当前时间 ==="
date "+%Y-%m-%d %H:%M:%S"

echo ""
echo "说明:"
echo "- 如果网站日期早于2025-02-23，说明网站确实停更了"
echo "- 建议检查公众号是否有新文章"
echo "- 访问 http://localhost:4000 查看 WeWe-RSS 状态"
