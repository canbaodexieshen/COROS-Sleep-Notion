# COROS Sleep Data to Notion Sync

自动将 COROS 高驰手表的睡眠数据同步到 Notion 数据库。

## ✨ 功能特点

- 🔄 **自动同步**：通过 GitHub Actions 每日定时运行
- 🛌 **完整数据**：深睡、浅睡、REM、清醒、午睡、心率等
- 📊 **智能去重**：按日期自动更新，不会重复创建
- 🔒 **安全存储**：敏感信息使用 GitHub Secrets 加密存储
- 🚀 **易于部署**：一键配置，无需服务器

## 📋 数据字段

| 字段 | 说明 | 类型 |
|------|------|------|
| 日期 | 睡眠日期 | Date |
| 总睡眠 | 总睡眠时长（分钟） | Number |
| 深睡 | 深度睡眠（分钟） | Number |
| 浅睡 | 浅度睡眠（分钟） | Number |
| REM | REM 快速眼动睡眠（分钟） | Number |
| 清醒 | 夜间清醒时间（分钟） | Number |
| 午睡 | 白天午睡时间（分钟） | Number |
| 平均心率 | 睡眠期间平均心率 | Number |
| 最小心率 | 睡眠期间最小心率 | Number |
| 最大心率 | 睡眠期间最大心率 | Number |
| 睡眠评分 | 睡眠质量评分（0-100） | Number |

## 🚀 快速开始

### 1. Fork 仓库

点击右上角的「Fork」按钮，将此仓库复制到你的 GitHub 账号。

### 2. 创建 Notion 数据库

在 Notion 中创建一个新数据库，包含以下属性：

1. 打开 Notion，创建一个新页面
2. 选择「Database - Full page」
3. 添加以下属性：
   - **日期**（Date）
   - **总睡眠**（Number）
   - **深睡**（Number）
   - **浅睡**（Number）
   - **REM**（Number）
   - **清醒**（Number）
   - **午睡**（Number）
   - **平均心率**（Number）
   - **最小心率**（Number）
   - **最大心率**（Number）
   - **睡眠评分**（Number）

### 3. 创建 Notion Integration

1. 访问 [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. 点击「New integration」
3. 名称填写「COROS Sleep Sync」
4. 选择你的 Workspace
5. 权限勾选：
   - ✅ Read content
   - ✅ Insert content
   - ✅ Update content
6. 点击「Submit」
7. 复制「Internal Integration Secret」（以 `ntn_` 开头）

### 4. 授权 Integration 访问数据库

1. 在 Notion 数据库页面点击右上角「...」
2. 选择「Connections」→「Add connections」
3. 搜索并选择「COROS Sleep Sync」

### 5. 获取数据库 ID

打开数据库页面，URL 格式为：
```
https://www.notion.so/xxxxxxxxxx?v=yyyyyyyyyy
```
其中 `xxxxxxxxxx` 就是数据库 ID（32 位字符串）

### 6. 配置 GitHub Secrets

进入你 Fork 的仓库，点击「Settings」→「Secrets and variables」→「Actions」，添加以下 Secrets：

| Secret 名称 | 说明 | 示例 |
|-------------|------|------|
| `COROS_EMAIL` | COROS 登录邮箱 | user@example.com |
| `COROS_PASSWORD` | COROS 登录密码 | your_password |
| `COROS_REGION` | COROS 账号区域 | asia |
| `NOTION_TOKEN` | Notion Integration Token | ntn_xxx... |
| `NOTION_DATABASE_ID` | Notion 数据库 ID | xxx... |

### 7. 手动触发测试

1. 进入仓库的「Actions」页面
2. 选择「Sync COROS Sleep Data to Notion」
3. 点击「Run workflow」
4. 等待运行完成，检查 Notion 数据库是否有数据

## ⏰ 定时任务

默认配置为每天北京时间 8:00 自动运行。如需修改，编辑 `.github/workflows/sync-sleep.yml`：

```yaml
on:
  schedule:
    - cron: '0 0 * * *'  # UTC 0:00 = 北京时间 8:00
```

## 🛠️ 本地开发

### 安装依赖

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 配置环境变量

复制 `.env.example` 为 `.env` 并填写：

```bash
cp .env.example .env
# 编辑 .env 文件
```

### 运行测试

```bash
python -m src.main
```

## ⚠️ 注意事项

1. **非官方 API**：本项目使用 COROS 非官方 API（通过逆向工程获得），可能随时变更
2. **账号安全**：你的 COROS 密码会安全存储在 GitHub Secrets 中，不会泄露
3. **数据隐私**：所有数据处理都在 GitHub Actions 中进行，不会发送到第三方
4. **首次同步**：首次运行会同步最近 7 天的数据，之后每天同步最新数据

## 🔧 故障排除

### 同步失败

1. 检查 GitHub Actions 日志
2. 确认 COROS 账号密码正确
3. 确认 Notion Integration 已授权数据库访问
4. 确认 GitHub Secrets 配置正确

### 数据未更新

1. 检查 Notion 数据库属性名称是否与代码一致
2. 确认 Integration 有读写权限
3. 查看 Actions 运行日志是否有错误

## 📝 更新日志

- **v1.0.0** (2026-06-04)
  - 初始版本
  - 支持 COROS 睡眠数据同步
  - 支持 GitHub Actions 定时运行

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 🔗 相关项目

- [coros-mcp](https://github.com/cygnusb/coros-mcp) - COROS MCP 服务器（本项目的 API 逻辑来源）
- [running_page](https://github.com/yihong0618/running_page) - 跑步数据可视化
