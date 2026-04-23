# 微信公众号文章自动下载系统

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    微信公众号 (woody1234)                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  WeWe-RSS 服务 (Docker)                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  1. 基于微信读书 API 获取公众号文章                  │   │
│  │  2. 定时更新 (每天9:00和21:00)                       │   │
│  │  3. 提供 RSS 订阅源和 API 接口                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              auto_download_wechat.py (定时任务)             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  1. 从数据库读取最新文章列表                         │   │
│  │  2. 过滤已下载文章                                   │   │
│  │  3. 使用 camoufox 下载文章内容为 Markdown            │   │
│  │  4. 保存到 wechat_articles/ 目录                     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 检查服务状态

```bash
# 查看 WeWe-RSS 是否运行
docker ps | grep wewe-rss

# 查看服务日志
docker logs wewe-rss -f
```

### 2. 配置 WeWe-RSS

**访问管理界面：**
- 打开浏览器访问: `http://localhost:4000`
- 授权码: `fund_arbitrage_2024`

**步骤：**

1. **添加微信读书账号**
   - 点击「账号管理」→「添加账号」
   - 使用微信扫码登录（使用你的微信读书账号）
   - ⚠️ 不要勾选「24小时后自动退出」

2. **订阅公众号**
   - 点击「公众号源」→「添加」
   - 输入任意一篇 woody1234/palmmicro 公众号的文章链接，例如：
     ```
     https://mp.weixin.qq.com/s/SWXj-nHi9AJGbEvohDKOxg
     ```
   - 系统会自动识别并订阅该公众号

3. **获取 RSS 链接**
   - 订阅成功后，点击「RSS」按钮
   - 可以复制 RSS 链接到阅读器中使用

### 3. 测试自动下载

```bash
cd /root/.openclaw/workspace/fund_arbitrage

# 运行自动下载脚本
python3 auto_download_wechat.py
```

### 4. 设置定时任务

```bash
# 编辑 crontab
crontab -e

# 添加以下内容（每天10:00和22:00执行）
0 10,22 * * * cd /root/.openclaw/workspace/fund_arbitrage && python3 auto_download_wechat.py >> logs/wechat_download.log 2>&1
```

## 文件说明

| 文件/目录 | 说明 |
|----------|------|
| `wewe-rss/` | WeWe-RSS 服务目录 |
| `wewe-rss/data/db.sqlite` | 文章数据库 |
| `wechat_articles/` | 下载的文章保存目录 |
| `auto_download_wechat.py` | 自动下载脚本 |
| `downloaded_articles.json` | 已下载文章记录 |
| `logs/` | 日志目录 |

## 工作原理

### 定时更新机制

WeWe-RSS 默认每12小时自动检查一次新文章（可通过 `CRON_EXPRESSION` 配置）：
- 默认: `0 9,21 * * *` (每天9:00和21:00)
- 修改: 编辑 `docker run` 命令中的 `-e CRON_EXPRESSION=...`

### 文章下载流程

1. **检测新文章**: `auto_download_wechat.py` 读取 `wewe-rss/data/db.sqlite` 数据库
2. **去重**: 检查 `downloaded_articles.json` 中已下载的文章ID
3. **下载**: 使用 camoufox 浏览器模拟访问文章页面
4. **保存**: 转换为 Markdown 格式，按作者分类保存

## 常见问题

### Q: 无法访问 localhost:4000

```bash
# 检查容器状态
docker ps | grep wewe-rss

# 如果未运行，重新启动
docker start wewe-rss

# 或者重新创建容器
docker rm -f wewe-rss
cd /root/.openclaw/workspace/fund_arbitrage/wewe-rss
docker run -d --name wewe-rss -p 4000:4000 \
  -e DATABASE_TYPE=sqlite \
  -e AUTH_CODE=fund_arbitrage_2024 \
  -e CRON_EXPRESSION="0 9,21 * * *" \
  -e FEED_MODE=fulltext \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  cooderl/wewe-rss-sqlite:latest
```

### Q: 微信扫码登录失败

- 确保使用微信读书 App 扫码（不是微信）
- 检查网络连接
- 尝试重新添加账号

### Q: 添加公众号提示频繁

微信有反爬机制，添加频率过高会被限制：
- 等待24小时后重试
- 减少同时订阅的公众号数量

### Q: 文章下载失败

```bash
# 检查 camoufox 是否安装
python3 -c "from camoufox.async_api import AsyncCamoufox; print('OK')"

# 手动测试下载
python3 download_wechat.py https://mp.weixin.qq.com/s/xxxxx
```

### Q: 如何修改定时时间

```bash
# 停止并删除容器
docker rm -f wewe-rss

# 重新创建，修改 CRON_EXPRESSION
# 例如：每小时执行一次
CRON_EXPRESSION="0 * * * *"
```

## 高级配置

### 修改更新频率

编辑 `docker-compose.yml` 或在 `docker run` 中修改：

```yaml
environment:
  - CRON_EXPRESSION=0 */6 * * *  # 每6小时一次
```

### 全文模式 vs 摘要模式

```yaml
environment:
  - FEED_MODE=fulltext   # RSS包含全文（默认）
  # 或
  - FEED_MODE=summary    # RSS仅摘要，节省带宽
```

### 数据备份

```bash
# 备份数据库
cp wewe-rss/data/db.sqlite wewe-rss/data/db.sqlite.backup

# 备份下载的文章
tar -czvf wechat_articles_backup.tar.gz wechat_articles/
```

## 替代方案

如果 WeWe-RSS 不适用，可以考虑：

1. **RSSHub**: `https://github.com/DIYgod/RSSHub` (需要部署，可能不稳定)
2. **wechat-spider**: 基于爬虫的方案（风险较高，易被封）
3. **手动维护**: 定期手动复制文章链接到 `wechat_articles_urls.txt`

## 参考资料

- WeWe-RSS GitHub: https://github.com/cooderl/wewe-rss
- 微信读书: https://weread.qq.com/
