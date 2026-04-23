#!/usr/bin/env python3
"""
Palmmicro 网站文章自动下载工具

从 https://palmmicro.com/woody/blogcn.php 抓取最新文章

使用方法:
    python3 download_website.py              # 下载所有文章
    python3 download_website.py --latest 5   # 只下载最近5篇
    python3 download_website.py --check      # 只检查，不下载
"""

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

# 配置
BASE_URL = "https://palmmicro.com/woody/blogcn.php"
DOMAIN = "https://palmmicro.com"
OUTPUT_DIR = Path(__file__).parent / "website_articles"
DOWNLOADED_LOG = Path(__file__).parent / "downloaded_website_articles.json"

# 只下载套利相关关键词的文章
KEYWORDS = [
    "套利", "华宝油气", "LOF", "QDII", "XOP", "纳指", "期货", 
    "黄金", "原油", "KWEB", "美股", "夜盘", "估值", "溢价", "折价"
]

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_downloaded() -> dict:
    """加载已下载的文章列表"""
    if DOWNLOADED_LOG.exists():
        try:
            return json.loads(DOWNLOADED_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"downloaded": {}, "last_check": None}


def save_downloaded(data: dict):
    """保存已下载的文章列表"""
    data["last_check"] = datetime.now().isoformat()
    DOWNLOADED_LOG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def is_arbitrage_related(title: str, content: str = "") -> bool:
    """判断文章是否与套利相关"""
    text = (title + content).lower()
    return any(kw in text for kw in KEYWORDS)


async def fetch_article_list() -> list:
    """获取文章列表"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(BASE_URL)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text()
        
        # 找到 "全部：" 后面的内容
        if "全部：" not in text:
            return []
            
        content = text.split("全部：")[1]
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        
        articles = []
        current_year = None
        
        for line in lines:
            # 检查是否是年份
            if re.match(r'^\d{4}$', line):
                current_year = line
                continue
            
            # 匹配文章: 月日 + 标题
            match = re.match(r'(\d{1,2})月(\d{1,2})日\s+(.+)', line)
            if match and current_year:
                month, day, title = match.groups()
                title = title.strip()
                date_str = f"{current_year}-{int(month):02d}-{int(day):02d}"
                
                # 构建文章URL (分类可能是 entertainment 或 palmmicro)
                # 先尝试 entertainment，失败时再尝试其他
                article_url = f"{DOMAIN}/woody/blog/entertainment/{current_year}{int(month):02d}{int(day):02d}cn.php"
                
                articles.append({
                    "title": title,
                    "date": date_str,
                    "url": article_url,
                    "year": current_year
                })
        
        return articles


async def download_article(article: dict) -> bool:
    """下载单篇文章"""
    url = article["url"]
    title = article["title"]
    date = article["date"]
    
    print(f"  正在下载: {date} - {title[:50]}...")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                print(f"    ✗ HTTP {response.status_code}")
                return False
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 提取正文内容
            # 网站结构: 标题 + 日期 + 正文 + 评论
            content_div = soup.find("div", class_=re.compile("content|main|article"))
            if not content_div:
                # 尝试提取所有文本
                text = soup.get_text()
                # 清理导航文本
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                content_text = '\n\n'.join(lines[5:-3])  # 去掉首尾导航
            else:
                content_text = content_div.get_text(separator='\n\n')
            
            # 转换为 Markdown
            if content_div:
                content_md = md(str(content_div), heading_style="ATX")
            else:
                # 简单文本转换
                content_md = content_text
            
            # 构建 Frontmatter
            frontmatter = f"""---
title: {title}
date: "{date}"
source: "{url}"
author: "woody1234"
---

"""
            
            # 保存文件
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:50]
            filename = f"{date}_{safe_title}.md"
            filepath = OUTPUT_DIR / filename
            
            filepath.write_text(frontmatter + content_md, encoding="utf-8")
            print(f"    ✓ 已保存: {filename}")
            return True
            
    except Exception as e:
        print(f"    ✗ 错误: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="下载 Palmmicro 网站文章")
    parser.add_argument("--latest", type=int, help="只下载最近N篇")
    parser.add_argument("--check", action="store_true", help="只检查，不下载")
    parser.add_argument("--all", action="store_true", help="下载所有文章（包括非套利相关）")
    args = parser.parse_args()
    
    print("=" * 60)
    print("Palmmicro 网站文章下载工具")
    print("=" * 60)
    print()
    
    # 获取文章列表
    print("正在获取文章列表...")
    articles = await fetch_article_list()
    print(f"找到 {len(articles)} 篇文章")
    print()
    
    if not articles:
        print("没有找到文章，请检查网络连接")
        return
    
    # 加载已下载记录
    downloaded_data = load_downloaded()
    downloaded = downloaded_data.get("downloaded", {})
    
    # 筛选未下载的文章
    new_articles = []
    for article in articles:
        url = article["url"]
        if url not in downloaded:
            # 检查是否与套利相关
            if args.all or is_arbitrage_related(article["title"]):
                new_articles.append(article)
    
    # 只取最新N篇
    if args.latest:
        new_articles = new_articles[:args.latest]
    
    print(f"待下载文章: {len(new_articles)} 篇")
    if not args.all:
        print(f"(只显示与套利相关的文章，使用 --all 查看全部)")
    print()
    
    if args.check:
        print("检查模式，不执行下载:")
        for article in new_articles:
            print(f"  - {article['date']}: {article['title']}")
        return
    
    if not new_articles:
        print("没有新文章需要下载")
        return
    
    # 下载文章
    success_count = 0
    for i, article in enumerate(new_articles, 1):
        print(f"[{i}/{len(new_articles)}]")
        success = await download_article(article)
        
        if success:
            downloaded[article["url"]] = {
                "title": article["title"],
                "date": article["date"],
                "downloaded_at": datetime.now().isoformat()
            }
            success_count += 1
        
        # 短暂延迟
        await asyncio.sleep(0.5)
    
    # 保存记录
    downloaded_data["downloaded"] = downloaded
    save_downloaded(downloaded_data)
    
    print()
    print("=" * 60)
    print(f"下载完成: {success_count}/{len(new_articles)} 篇")
    print(f"总计已下载: {len(downloaded)} 篇")
    print(f"保存目录: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n操作已取消")
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
