#!/usr/bin/env python3
"""
微信公众号文章下载工具
用于下载 woody1234/palmmicro 公众号的文章

使用方法:
    python3 download_wechat.py <文章URL>
    python3 download_wechat.py https://mp.weixin.qq.com/s/xxxxx
"""

import asyncio
import sys
from pathlib import Path

# 需要安装: pip install camoufox markdownify beautifulsoup4 lxml
from camoufox.async_api import AsyncCamoufox
from bs4 import BeautifulSoup
from markdownify import markdownify as md


async def fetch_article(url: str, output_dir: Path):
    """下载单篇微信公众号文章"""
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    async with AsyncCamoufox(headless=True) as browser:
        page = await browser.new_page()
        print(f"正在下载: {url}")
        
        await page.goto(url, wait_until="domcontentloaded")
        
        # 等待文章内容加载
        try:
            await page.wait_for_selector("#js_content", timeout=15000)
        except Exception:
            pass
            
        # 等待网络空闲
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            await asyncio.sleep(2)
        
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # 提取元数据
        title_elem = soup.select_one("#activity-name") or soup.select_one(".rich_media_title")
        title = title_elem.get_text(strip=True) if title_elem else "未知标题"
        
        author_elem = soup.select_one("#js_name") or soup.select_one(".profile_nickname")
        author = author_elem.get_text(strip=True) if author_elem else "palmmicro"
        
        publish_time_elem = soup.select_one("#publish_time") or soup.select_one(".rich_media_meta_text")
        publish_time = publish_time_elem.get_text(strip=True) if publish_time_elem else ""
        
        # 提取正文
        content_elem = soup.select_one("#js_content")
        if not content_elem:
            print("错误：无法找到文章内容")
            return False
            
        # 转换为Markdown
        content_html = str(content_elem)
        content_md = md(content_html, heading_style="ATX")
        
        # 构建Frontmatter
        frontmatter = f"""---
title: {title}
author: {author}
date: "{publish_time}"
source: "{url}"
---

"""
        
        # 保存文件
        safe_title = "".join(c for c in title if c.isalnum() or c in "_-")[:50]
        filename = f"{safe_title}.md"
        filepath = output_dir / filename
        
        filepath.write_text(frontmatter + content_md, encoding="utf-8")
        print(f"已保存: {filepath}")
        print(f"标题: {title}")
        print(f"作者: {author}")
        
        return True


def main():
    if len(sys.argv) < 2:
        print("用法: python3 download_wechat.py <微信公众号文章URL>")
        print("示例: python3 download_wechat.py https://mp.weixin.qq.com/s/xxxxx")
        sys.exit(1)
    
    url = sys.argv[1]
    
    if not url.startswith("https://mp.weixin.qq.com/"):
        print("错误: 请提供有效的微信公众号文章链接")
        sys.exit(1)
    
    output_dir = Path(__file__).parent / "wechat_articles"
    
    try:
        success = asyncio.run(fetch_article(url, output_dir))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n操作已取消")
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
