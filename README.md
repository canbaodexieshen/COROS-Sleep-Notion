# COROS Sleep Data to Notion Sync

自动将 COROS 高驰手表的睡眠数据同步到 Notion 数据库。

**使用 COROS 官方 MCP 服务**，不会踢出手机 App 登录！

## ✨ 功能特点

- 🔄 **自动同步**：通过 GitHub Actions 每日定时运行
- 🛌 **完整数据**：深睡、浅睡、REM、清醒、午睡、心率等
- 📊 **智能去重**：按日期自动更新，不会重复创建
- 🔒 **安全存储**：敏感信息使用 GitHub Secrets 加密存储
- 🚀 **易于部署**：一键配置，无需服务器
- 📱 **不踢出手机 App**：使用官方 MCP 服务（OAuth2.0 认证）

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

### 6. 获取 COROS Token

**在 WorkBuddy 中运行 coros-health 技能**，它会自动完成登录并获取 token。

然后执行以下命令获取 token 数据：
```bash
cat ~/.coros-mcp-skill-gateway-ts/cn/token.json
```

你会看到类似这样的输出：
```json
{
  "access_token": "eyJ...",
  "refresh_token": "u43wl...",
  "expires_at_epoch": 1781072275,
  "token_type": "Bearer",
  "client_id": "ccd9bd8c-6504-4b83-80ab-edad29e075cc"
}
```

### 7. 配置 GitHub Secrets

进入你 Fork 的仓库，点击「Settings」→「Secrets and variables」→「Actions」，添加以下 Secrets：

| Secret 名称 | 说明 | 示例 |
|-------------|------|------|
| `COROS_ACCESS_TOKEN` | COROS 访问令牌 | eyJ... |
| `COROS_REFRESH_TOKEN` | COROS 刷新令牌 | u43wl... |
| `COROS_CLIENT_ID` | 客户端 ID | ccd9bd8c-6504-4b83-80ab-edad29e075cc |
| `COROS_REGION` | 区域 | cn |
| `COROS_EXPIRES_AT` | 令牌过期时间戳 | 1781072275 |
| `NOTION_TOKEN` | Notion Integration Token | ntn_xxx... |
| `NOTION_DATABASE_ID` | Notion 数据库 ID | xxx... |

### 8. 手动触发测试

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

## 🔄 Token 刷新

COROS Token 有效期约 30 天。脚本会在每次运行时自动检查并刷新 token。

如果 token 过期，脚本会：
1. 使用 refresh_token 获取新的 access_token
2. 输出新的 token 数据到日志

**如何更新 GitHub Secrets**：
1. 查看 GitHub Actions 运行日志
2. 找到 `🔑 Token 已刷新，新的 token 数据：` 部分
3. 复制新的 token 数据
4. 更新 GitHub Secrets 中的 `COROS_ACCESS_TOKEN`、`COROS_REFRESH_TOKEN`、`COROS_EXPIRES_AT`

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

1. **使用 COROS 官方 MCP 服务**：本项目使用 OAuth2.0 认证，不会踢出手机 App
2. **Token 有效期**：约 30 天，过期后需要重新获取
3. **数据隐私**：所有数据处理都在 GitHub Actions 中进行，不会发送到第三方

## 🔧 故障排除

### 同步失败

1. 检查 GitHub Actions 日志
2. 确认 COROS Token 正确且未过期
3. 确认 Notion Integration 已授权数据库访问
4. 确认 GitHub Secrets 配置正确

### Token 过期

1. 在 WorkBuddy 中重新运行 coros-health 技能
2. 获取新的 token 数据
3. 更新 GitHub Secrets

### 数据未更新

1. 检查 Notion 数据库属性名称是否与代码一致
2. 确认 Integration 有读写权限
3. 查看 Actions 运行日志是否有错误

## 📝 更新日志

- **v2.0.0** (2026-06-04)
  - 改用 COROS 官方 MCP 服务（不会踢出手机 App）
  - 使用 OAuth2.0 认证（支持 token 自动刷新）
  - 移除 Mobile API 依赖

- **v1.0.0** (2026-06-04)
  - 初始版本
  - 使用 Mobile API 获取睡眠数据
  - 支持 GitHub Actions 定时运行

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 🔗 相关项目

- [coros-mcp](https://github.com/cygnusb/coros-mcp) - COROS MCP 服务器
- [running_page](https://github.com/yihong0618/running_page) - 跑步数据可视化
