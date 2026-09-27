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
cat ~/.coros-mcp-skill-gateway/cn/token.json
```

你会看到类似这样的输出：
```json
{
  "access_token": "eyJ...",
  "refresh_token": "u43wl...",
  "expires_at_epoch": 1781072275,
  "token_type": "Bearer",
  "client_id": "以实际动态注册值为准"
}
```

### 7. 配置 GitHub Secrets

进入你 Fork 的仓库，点击「Settings」→「Secrets and variables」→「Actions」，添加以下 Secrets：

| Secret 名称 | 说明 | 示例 |
|-------------|------|------|
| `COROS_ACCESS_TOKEN` | COROS 访问令牌 | eyJ... |
| `COROS_REFRESH_TOKEN` | COROS 刷新令牌 | u43wl... |
| `COROS_CLIENT_ID` | 与当前 token 同时生成的动态客户端 ID | 从同一份 token.json 原样复制 |
| `COROS_REGION` | 区域 | cn |
| `COROS_EXPIRES_AT` | 令牌过期时间戳 | 1781072275 |
| `NOTION_TOKEN` | Notion Integration Token | ntn_xxx... |
| `NOTION_DATABASE_ID` | Notion 数据库 ID | xxx... |
| `COROS_SECRET_UPDATE_TOKEN` | 仅授权本仓库读写 Actions Secrets 的 GitHub 细粒度令牌 | github_pat_xxx... |

`COROS_SECRET_UPDATE_TOKEN` 用于在 COROS OAuth Token 刷新后自动回写上述三个
COROS Secrets。创建方法：

1. 打开 GitHub「Settings → Developer settings → Personal access tokens → Fine-grained tokens」。
2. Repository access 只选择当前仓库。
3. Repository permissions 中将 `Secrets` 设置为 `Read and write`，其余权限保持最小。
4. 创建后把令牌保存为仓库 Secret `COROS_SECRET_UPDATE_TOKEN`。

> 不要把 COROS 账号密码保存到 GitHub。官方 COROS MCP 使用 OAuth 2.0 浏览器授权，
> 本项目只保存授权产生的 token，并通过 refresh token 自动续期。
>
> `COROS_CLIENT_ID` 不是项目固定值。COROS 官方工具会动态注册 OAuth 客户端；
> access token、refresh token 和 client_id 必须来自同一次授权生成的同一份
> `token.json`，区域也必须与该文件所在的 `cn`、`eu` 或 `us` 目录一致。

### 8. 手动触发测试

1. 进入仓库的「Actions」页面
2. 选择「Sync COROS Sleep Data to Notion」
3. 点击「Run workflow」
4. 首次配置自动续期时，可勾选「强制刷新并验证 COROS Token 自动回写」进行一次验证
5. 等待运行完成，检查 Notion 数据库是否有数据

## ⏰ 定时任务

默认配置为每天北京时间 8:00 自动运行。如需修改，编辑 `.github/workflows/sync-sleep.yml`：

```yaml
on:
  schedule:
    - cron: '0 0 * * *'  # UTC 0:00 = 北京时间 8:00
```

## 🔄 Token 刷新

COROS Token 有效期约 30 天。脚本会在每次运行时检查到期时间，并在临近过期时：

1. 使用 refresh token 向 COROS 官方 OAuth 端点续期。
2. 将新 token 写入 GitHub Runner 的临时文件，不输出到 Actions 日志。
3. 使用 `COROS_SECRET_UPDATE_TOKEN` 自动更新 `COROS_ACCESS_TOKEN`、
   `COROS_REFRESH_TOKEN`、`COROS_EXPIRES_AT` 和 `COROS_CLIENT_ID`。
4. 更新完成后删除 Runner 临时文件。

完成一次初始 OAuth 授权和上述 GitHub Secret 配置后，正常情况下无需每月手工更新
COROS Token。如果 COROS 主动撤销授权、refresh token 本身失效，或
`COROS_SECRET_UPDATE_TOKEN` 到期，才需要重新授权或更换对应令牌。

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
python test_local.py
```

测试通过后执行完整同步：

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

### `Unknown tool` / `Tool not found`

客户端会优先连接 COROS 官方统一入口 `https://mcp.coros.com/mcp`，
并在每次运行时通过 `tools/list` 以当前账号实际可见的工具名和参数为准。
睡眠数据同时兼容新名 `querySleepOverview` 和旧名 `querySleepData`。
如日志明确提示工具未暴露，请重新授权 COROS 并更新 GitHub Secrets 中的 Token；
日志会列出服务端当时返回的可用工具，便于继续定位。

### Token 过期

1. 在 WorkBuddy 中重新运行 coros-health 技能
2. 获取新的 token 数据
3. 更新 GitHub Secrets

### 数据未更新

1. 检查 Notion 数据库属性名称是否与代码一致
2. 确认 Integration 有读写权限
3. 查看 Actions 运行日志是否有错误

