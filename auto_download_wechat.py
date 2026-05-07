#!/usr/bin/env python3
"""
微信公众号文章自动下载工具
基于 WeWe-RSS 服务，自动获取并下载最新文章

功能：
1. 从 WeWe-RSS API 获取订阅的公众号文章列表
2. 下载新文章（使用 camoufox 浏览器）
3. 保存为 Markdown 格式
4. 记录已下载的文章，避免重复

使用方法:
    python3 auto_download_wechat.py
    
    # 设置为定时任务 (crontab -e)
    0 10,22 * * * cd /root/quant/fund_arbitrage && python3 auto_download_wechat.py >> logs/wechat_download.log 2>&1
"""

import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx

# 配置
WEWE_RSS_URL = "http://localhost:4000"  # WeWe-RSS 服务地址
OUTPUT_DIR = Path(__file__).parent / "wechat_articles"
DB_PATH = Path(__file__).parent / "wewe-rss" / "data" / "db.sqlite"
DOWNLOADED_LOG = Path(__file__).parent / "downloaded_articles.json"

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_downloaded() -> set:
    """加载已下载的文章ID列表"""
    if DOWNLOADED_LOG.exists():
        try:
            data = json.loads(DOWNLOADED_LOG.read_text(encoding="utf-8"))
            return set(data.get("downloaded", []))
        except Exception:
            pass
    return set()


def save_downloaded(downloaded: set):
    """保存已下载的文章ID列表"""
    DOWNLOADED_LOG.write_text(
        json.dumps({
            "downloaded": list(downloaded),
            "last_update": datetime.now().isoformat()
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_articles_from_db() -> list:
    """从 WeWe-RSS 数据库获取文章列表"""
    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}")
        return []
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 查询文章表
        cursor.execute("""
            SELECT id, title, author, publish_time, link, mp_name 
            FROM articles 
            ORDER BY publish_time DESC
            LIMIT 50
        """)
        
        articles = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return articles
        
    except Exception as e:
        print(f"查询数据库失败: {e}")
        return []


async def download_article(url: str, title: str, author: str, output_dir: Path) -> bool:
    """下载单篇文章"""
    # 这里复用 wechat-article-for-ai 的下载逻辑
    # 或者使用简单的 requests +BeautifulSoup 方案
    
    try:
        # 导入 camoufox 下载器
        sys.path.insert(0, '/tmp/wechat-article-for-ai')
        from wechat_to_md.scraper import fetch_page_html
        from wechat_to_md.parser import extract_metadata, process_content
        from wechat_to_md.converter import convert_html_to_markdown, build_markdown
        from bs4 import BeautifulSoup
        from wechat_to_md.utils import sanitize_filename
        
        print(f"  正在下载: {title[:50]}...")
        
        html = await fetch_page_html(url, headless=True)
        soup = BeautifulSoup(html, "html.parser")
        
        # 解析内容
        meta = extract_metadata(soup, html, url=url)
        parsed = process_content(soup)
        
        if not parsed.content_html.strip():
            print(f"  警告: 文章内容为空")
            return False
        
        # 转换为 Markdown
        content_md = convert_html_to_markdown(parsed.content_html, parsed.code_blocks)
        
        # 构建完整 Markdown
        final_md = build_markdown(meta, content_md, parsed.media_references, use_frontmatter=True)
        
        # 保存文件
        safe_title = sanitize_filename(title)[:50]
        filename = f"{safe_title}.md"
        filepath = output_dir / filename
        
        # 如果文件已存在，添加数字后缀
        counter = 1
        while filepath.exists():
            filepath = output_dir / f"{safe_title}_{counter}.md"
            counter += 1
        
        filepath.write_text(final_md, encoding="utf-8")
        print(f"  ✓ 已保存: {filepath.name}")
        return True
        
    except Exception as e:
        print(f"  ✗ 下载失败: {e}")
        return False


async def main():
    """主函数"""
    print(f"=== 微信公众号文章自动下载 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 加载已下载列表
    downloaded = load_downloaded()
    print(f"已下载文章数: {len(downloaded)}")
    
    # 获取文章列表
    articles = get_articles_from_db()
    if not articles:
        print("没有获取到文章，请确保:")
        print("1. WeWe-RSS 服务已启动 (docker ps | grep wewe-rss)")
        print("2. 已添加微信读书账号并扫码登录")
        print("3. 已添加公众号订阅")
        return
    
    print(f"数据库中文章数: {len(articles)}")
    print()
    
    # 筛选未下载的文章（最近7天的）
    new_articles = []
    for article in articles:
        article_id = article.get('id') or article.get('link')
        if article_id and article_id not in downloaded:
            # 检查发布时间
            try:
                pub_time = datetime.fromisoformat(article.get('publish_time', '').replace('Z', '+00:00'))
                days_ago = (datetime.now(pub_time.tzinfo) - pub_time).days
                if days_ago <= 7:  # 只下载最近7天的文章
                    new_articles.append(article)
            except Exception:
                new_articles.append(article)
    
    if not new_articles:
        print("没有新文章需要下载")
        return
    
    print(f"待下载新文章: {len(new_articles)} 篇")
    print()
    
    # 下载文章
    success_count = 0
    for article in new_articles:
        title = article.get('title', '未知标题')
        url = article.get('link', '')
        author = article.get('mp_name') or article.get('author', '未知作者')
        
        print(f"[{success_count+1}/{len(new_articles)}] {title[:40]}...")
        
        if not url:
            print("  ✗ 缺少文章链接")
            continue
        
        # 创建作者目录
        author_dir = OUTPUT_DIR / sanitize_filename(author)
        author_dir.mkdir(exist_ok=True)
        
        success = await download_article(url, title, author, author_dir)
        
        if success:
            article_id = article.get('id') or article.get('link')
            downloaded.add(article_id)
            success_count += 1
        
        # 短暂延迟，避免请求过快
        await asyncio.sleep(2)
    
    # 保存已下载列表
    save_downloaded(downloaded)
    
    print()
    print(f"下载完成: {success_count}/{len(new_articles)} 篇")
    print(f"总计已下载: {len(downloaded)} 篇")


def sanitize_filename(filename: str) -> str:
    """清理文件名中的非法字符"""
    import re
    # 替换非法字符
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # 去除两端空白
    filename = filename.strip()
    # 限制长度
    return filename[:100]


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n操作已取消")
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
