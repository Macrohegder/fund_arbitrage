# 微信公众号文章自动下载工具

## 功能说明

这个工具可以自动下载微信公众号文章并保存为Markdown格式，包含：
- 文章标题、作者、发布时间等元数据
- 正文内容（转换为Markdown）
- 图片（可选）

## 安装依赖

```bash
# 使用虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install camoufox markdownify beautifulsoup4 lxml

# 首次运行时会自动下载 Camoufox 浏览器（约700MB）
```

## 使用方法

### 1. 下载单篇文章

```bash
python3 download_wechat.py <文章URL>
```

示例：
```bash
python3 download_wechat.py https://mp.weixin.qq.com/s/SWXj-nHi9AJGbEvohDKOxg
```

下载的文章会保存到 `./wechat_articles/` 目录。

### 2. 批量下载（使用 wechat-article-for-ai 工具）

如果已安装 `wechat-article-for-ai`，可以使用更强大的批量下载功能：

```bash
# 编辑链接列表文件
vim wechat_articles_urls.txt

# 批量下载（在 wechat-article-for-ai 目录中）
cd /tmp/wechat-article-for-ai
python3 -m wechat_to_md.cli -f /root/.openclaw/workspace/fund_arbitrage/wechat_articles_urls.txt \
    -o /root/.openclaw/workspace/fund_arbitrage/wechat_articles \
    --force
```

## 文件结构

```
fund_arbitrage/
├── download_wechat.py          # 简单版下载脚本
├── wechat_articles_urls.txt    # 文章链接列表
├── WECHAT_DOWNLOAD_README.md   # 本文档
└── wechat_articles/            # 下载的文章保存目录
    └── 文章标题/
        ├── 文章标题.md
        └── images/
            └── img_001.jpg
```

## 获取文章链接的方法

由于微信公众号没有公开API，需要手动收集文章链接：

1. **从微信客户端获取**：
   - 在微信中打开文章
   - 点击右上角「...」→「复制链接」

2. **从公众号历史文章页面获取**：
   - 访问 `https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=MzI0ODYyMzE0Mw==`
   - 使用浏览器开发者工具提取链接

3. **从现有文档中提取**：
   - 查看已有的 `palmmicro_lof_arbitrage_articles.md` 等文档中的链接

## 注意事项

1. **反爬机制**：微信有反爬机制，过于频繁下载可能导致IP被限制
2. **验证码**：偶尔会遇到验证码页面，需要手动在浏览器中解决
3. **Camoufox浏览器**：首次运行会自动下载约700MB的浏览器文件

## 替代方案

### 方案1：使用 MCP 工具
如果你使用 Claude Desktop 或其他支持 MCP 的AI工具，可以配置以下MCP服务器：

```json
{
  "mcpServers": {
    "wechat-article": {
      "command": "python3",
      "args": ["-m", "wechat_to_md.mcp_server"],
      "env": {
        "PYTHONPATH": "/tmp/wechat-article-for-ai"
      }
    }
  }
}
```

### 方案2：使用现成的MCP服务
- `@alou/fetch-mcp`: `npx @alou/fetch-mcp fetch-txt --url "<文章链接>"`

## 自动化计划（TODO）

- [ ] 定时任务（cron）每天自动检查新文章
- [ ] 文章去重（根据URL或标题）
- [ ] 自动提取公众号文章列表
- [ ] 通知机制（新文章下载完成通知）
