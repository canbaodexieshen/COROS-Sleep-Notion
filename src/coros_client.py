"""
COROS API Client - 使用 COROS 官方 MCP 服务获取睡眠数据
使用 OAuth2.0 认证（不会踢出手机 App）
支持 token 自动刷新
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel


class SleepPhases(BaseModel):
    """睡眠阶段数据"""
    deep_minutes: Optional[int] = None      # 深睡（分钟）
    light_minutes: Optional[int] = None     # 浅睡（分钟）
    rem_minutes: Optional[int] = None       # REM 快速眼动（分钟）
    awake_minutes: Optional[int] = None     # 清醒（分钟）
    nap_minutes: Optional[int] = None       # 午睡/小睡（分钟）


class SleepRecord(BaseModel):
    """睡眠记录"""
    date: str                                    # YYYY-MM-DD 格式
    total_duration_minutes: Optional[int] = None # 总睡眠时长（分钟）
    phases: Optional[SleepPhases] = None         # 各阶段分解
    avg_hr: Optional[int] = None                 # 平均心率
    min_hr: Optional[int] = None                 # 最小心率
    max_hr: Optional[int] = None                 # 最大心率
    quality_score: Optional[int] = None          # 睡眠评分
    deep_pct: Optional[float] = None             # 深睡百分比
    light_pct: Optional[float] = None            # 浅睡百分比
    rem_pct: Optional[float] = None              # REM 百分比
    awake_pct: Optional[float] = None            # 清醒百分比
    awake_count: Optional[int] = None            # 清醒次数
    # --- 每日健康指标（由 main.py 合并填入） ---
    resting_hr: Optional[int] = None             # 静息心率 bpm
    daily_avg_hr: Optional[int] = None           # 每日平均心率 bpm
    hrv_avg: Optional[int] = None                # HRV 平均值 ms
    hrv_result: Optional[str] = None             # HRV 评估结果
    stress_avg: Optional[int] = None             # 每日平均压力


class RestingHrRecord(BaseModel):
    """静息心率记录"""
    date: str                        # YYYY-MM-DD 格式
    resting_hr: Optional[int] = None # 静息心率 bpm


class AvgHrRecord(BaseModel):
    """平均心率记录"""
    date: str                      # YYYY-MM-DD 格式
    avg_hr: Optional[int] = None   # 平均心率 bpm


class HrvRecord(BaseModel):
    """HRV 记录"""
    date: str                        # YYYY-MM-DD 格式
    hrv_avg: Optional[int] = None    # HRV 平均值 ms
    hrv_result: Optional[str] = None # HRV 评估结果


class StressRecord(BaseModel):
    """压力记录"""
    date: str                        # YYYY-MM-DD 格式
    stress_avg: Optional[int] = None # 平均压力值


# COROS MCP 配置
# 官方开发文档将统一入口作为首选，区域入口仅用于回退。
COROS_MCP_URL = "https://mcp.coros.com/mcp"
COROS_MCP_CONFIGS = {
    "cn": {
        "issuer": "https://mcp.coros.com",
        "regional_mcp_url": "https://mcpcn.coros.com/mcp",
    },
    "eu": {
        "issuer": "https://mcp.coros.com",
        "regional_mcp_url": "https://mcpeu.coros.com/mcp",
    },
    "us": {
        "issuer": "https://mcp.coros.com",
        "regional_mcp_url": "https://mcpus.coros.com/mcp",
    },
}
CLIENT_ID = "ccd9bd8c-6504-4b83-80ab-edad29e075cc"

# COROS 的不同区域/发布批次可能在新旧工具名之间切换。
# tools/list 仍是最终依据，这里只定义语义等价的兼容名称。
TOOL_ALIASES = {
    "querySleepOverview": ("querySleepData",),
    "querySleepData": ("querySleepOverview",),
}


def _parse_duration_str(duration_str: str) -> int:
    """
    解析时长字符串（如 "7h 50min"、"6h 48min"、"490 min"）为分钟数
    """
    if not duration_str:
        return 0

    # 格式: "Xh Ymin"、"X hr Y min" 或 "X hours Y minutes"
    match = re.search(
        r'(\d+)\s*h(?:ours?|rs?)?(?:\s*(\d+)\s*m(?:in(?:ute)?s?)?)?',
        duration_str,
        re.IGNORECASE,
    )
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2) or 0)
        return hours * 60 + minutes

    # 格式: "X min"
    match = re.search(r'(\d+)\s*m(?:in(?:ute)?s?)?', duration_str, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # 格式: "7:30"（小时:分钟）
    match = re.search(r'\b(\d{1,2}):(\d{2})\b', duration_str)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))

    # 格式: 纯数字（默认分钟）
    match = re.search(r'^(\d+)$', duration_str.strip())
    if match:
        return int(match.group(1))

    return 0


def _extract_labeled_value(block: str, *labels: str) -> Optional[str]:
    """从普通文本或 Markdown 列表中提取“标签: 值”。"""
    cleaned = block.replace("**", "").replace("__", "")
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf'(?im)^[ \t]*(?:[-*•][ \t]+)?(?:{label_pattern})[ \t]*[:：][ \t]*(.+?)[ \t]*$',
        cleaned,
    )
    return match.group(1).strip() if match else None


def _extract_percentage(block: str, *labels: str) -> Optional[float]:
    value = _extract_labeled_value(block, *labels)
    if value is None:
        return None
    match = re.search(r'(\d+(?:\.\d+)?)\s*%', value)
    return float(match.group(1)) if match else None


def _normalized_mapping_value(data: dict, *names: str):
    """按忽略大小写和分隔符的字段名读取 MCP 结构化数据。"""
    normalized = {
        re.sub(r"[^a-z0-9]", "", str(key).lower()): value
        for key, value in data.items()
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if key in normalized:
            return normalized[key]
    return None


def _duration_value_to_minutes(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # MCP 通常返回分钟；明显超出一天时按秒处理。
        return round(value / 60) if value > 1440 else round(value)
    parsed = _parse_duration_str(str(value))
    return parsed or None


def _ratio_value(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        match = re.search(r'(\d+(?:\.\d+)?)\s*%?', value)
        if not match:
            return None
        number = float(match.group(1))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    else:
        return None
    return number * 100 if 0 < number <= 1 else number


class CorosClient:
    """COROS API 客户端（使用官方 MCP 服务）"""

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        client_id: str = CLIENT_ID,
        region: str = "cn",
        expires_at: Optional[int] = None,
        mcp_url: Optional[str] = None,
    ):
        """
        初始化 COROS 客户端

        Args:
            access_token: 访问令牌
            refresh_token: 刷新令牌
            client_id: 客户端 ID
            region: 区域（cn/eu/us）
            expires_at: 令牌过期时间戳（秒）
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.region = region.lower()
        self.expires_at = expires_at

        config = COROS_MCP_CONFIGS.get(self.region, COROS_MCP_CONFIGS["cn"])
        self.issuer = config["issuer"]
        configured_mcp_url = mcp_url or os.getenv("COROS_MCP_URL")
        self.mcp_url = configured_mcp_url or COROS_MCP_URL
        self._mcp_urls = [self.mcp_url]
        regional_mcp_url = config["regional_mcp_url"]
        if not configured_mcp_url and regional_mcp_url != self.mcp_url:
            self._mcp_urls.append(regional_mcp_url)

        self._initialized: bool = False
        self._available_tools: Optional[dict[str, dict]] = None
        self._rpc_id = 0
        # COROS 统一入口会跨子域跳转。跳转由 _post_rpc 按白名单处理，
        # 避免 HTTP 客户端跨主机时丢弃 Authorization 头。
        self.client = httpx.AsyncClient(timeout=60.0, follow_redirects=False)

        # 存储刷新后的 token（用于返回给调用者）
        self._refreshed_token_data: Optional[dict] = None

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()

    def _is_token_expired(self) -> bool:
        """检查 token 是否过期"""
        if not self.expires_at:
            return True
        # 提前 5 分钟刷新，避免刚好过期
        return self.expires_at < time.time() + 300

    async def _refresh_token(self) -> dict:
        """
        刷新 access_token

        Returns:
            新的 token 数据
        """
        print(f"   🔄 正在刷新 COROS Token...")

        response = await self.client.post(
            f"{self.issuer}/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": self.refresh_token,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        if response.status_code != 200:
            raise ValueError(f"Token 刷新失败: {response.status_code} {response.text}")

        payload = response.json()

        # 更新 token 数据
        self.access_token = payload.get("access_token", self.access_token)
        self.refresh_token = payload.get("refresh_token", self.refresh_token)
        self.expires_at = int(time.time()) + payload.get("expires_in", 2592000)

        # 保存刷新后的 token 数据
        self._refreshed_token_data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at_epoch": self.expires_at,
            "token_type": payload.get("token_type", "Bearer"),
            "client_id": self.client_id,
        }

        print(f"   ✅ Token 刷新成功!")
        return self._refreshed_token_data

    async def _ensure_token(self) -> str:
        """确保有有效的 token"""
        if self._is_token_expired():
            await self._refresh_token()
        return self.access_token

    async def _initialize_session(self) -> None:
        """
        初始化 MCP 连接（无状态模式）

        注意：COROS MCP v0.1.1+ 已改为无状态模式，不再需要 Session ID。
        此方法仅用于验证连接可用性。
        """
        if self._initialized:
            return

        token = await self._ensure_token()
        errors = []

        # 先用官方统一入口；如路由失败，再回退到账号所在区域。
        for mcp_url in self._mcp_urls:
            self.mcp_url = mcp_url
            try:
                payload = await self._post_rpc(
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "coros-sleep-notion",
                            "version": "1.1.0",
                        },
                    },
                    token,
                )
                if "error" in payload:
                    raise ValueError(str(payload["error"]))
                self._initialized = True
                return
            except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{mcp_url}: {exc}")

        raise ValueError("初始化 COROS MCP 连接失败：" + " | ".join(errors))

    async def _post_rpc(
        self,
        method: str,
        params: dict,
        token: str,
    ) -> dict:
        """发送 JSON-RPC 请求并兼容 COROS 返回的 JSON/SSE 两种格式。"""
        self._rpc_id += 1
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        body = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": method,
            "params": params,
        }
        request_url = self.mcp_url
        allowed_hosts = {
            "mcp.coros.com",
            "mcpcn.coros.com",
            "mcpeu.coros.com",
            "mcpus.coros.com",
        }
        response = None
        for _ in range(4):
            response = await self.client.post(request_url, headers=headers, json=body)
            if response.status_code not in {301, 302, 303, 307, 308}:
                break

            location = response.headers.get("location")
            if not location:
                raise ValueError("COROS MCP 返回了缺少 Location 的重定向")
            redirected_url = urljoin(request_url, location)
            parsed = urlparse(redirected_url)
            if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
                raise ValueError(f"拒绝 COROS MCP 的非安全重定向: {redirected_url}")
            request_url = redirected_url
            self.mcp_url = redirected_url
        else:
            raise ValueError("COROS MCP 重定向次数过多")

        if response is None:
            raise ValueError("COROS MCP 未返回响应")
        if response.status_code != 200:
            detail = response.text[:300].replace("\n", " ")
            raise ValueError(f"HTTP {response.status_code}: {detail}")

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            # SSE 一个事件可以由多个 data: 行组成，空行表示事件结束。
            events = []
            current_event = []
            for line in response.text.splitlines():
                if not line:
                    if current_event:
                        events.append("\n".join(current_event))
                        current_event = []
                elif line.startswith("data:"):
                    current_event.append(line[5:].lstrip())
            if current_event:
                events.append("\n".join(current_event))

            if not events:
                raise ValueError("MCP SSE 响应为空")
            for event in reversed(events):
                try:
                    return json.loads(event)
                except json.JSONDecodeError:
                    continue
            raise ValueError("MCP SSE 响应不包含有效 JSON")
        return response.json()

    async def _list_tools(self, refresh: bool = False) -> dict[str, dict]:
        """读取当前账号和端点实际可用的工具，避免依赖过期的硬编码列表。"""
        if self._available_tools is not None and not refresh:
            return self._available_tools

        await self._initialize_session()
        token = await self._ensure_token()
        payload = await self._post_rpc("tools/list", {}, token)
        if "error" in payload:
            raise ValueError(f"读取 MCP 工具列表失败: {payload['error']}")

        tools = payload.get("result", {}).get("tools", [])
        self._available_tools = {
            tool["name"]: tool
            for tool in tools
            if isinstance(tool, dict) and tool.get("name")
        }
        return self._available_tools

    @staticmethod
    def _normalized_name(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.lower())

    async def _resolve_tool(self, requested_name: str) -> tuple[str, dict]:
        tools = await self._list_tools()
        candidates = (requested_name, *TOOL_ALIASES.get(requested_name, ()))

        for candidate in candidates:
            if candidate in tools:
                return candidate, tools[candidate]

        normalized_candidates = {
            self._normalized_name(candidate) for candidate in candidates
        }
        for actual_name, definition in tools.items():
            if self._normalized_name(actual_name) in normalized_candidates:
                return actual_name, definition

        available = ", ".join(sorted(tools)) or "(空)"
        raise ValueError(
            f"COROS MCP 当前未暴露工具 {requested_name!r}。"
            f"端点: {self.mcp_url}；可用工具: {available}"
        )

    def _adapt_tool_arguments(self, definition: dict, arguments: dict) -> dict:
        """按 tools/list 返回的 schema 对齐参数命名，并移除服务端不接受的旧参数。"""
        schema = definition.get("inputSchema") or {}
        properties = schema.get("properties") or {}
        if not properties:
            return arguments

        normalized_properties = {
            self._normalized_name(name): name for name in properties
        }
        adapted = {}
        for name, value in arguments.items():
            actual_name = name if name in properties else normalized_properties.get(
                self._normalized_name(name)
            )
            if actual_name:
                adapted[actual_name] = value
        return adapted

    async def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        调用 MCP 工具（无状态模式）

        注意：COROS MCP v0.1.1+ 已改为无状态模式，不再需要 Session ID。
        """
        token = await self._ensure_token()
        actual_name, definition = await self._resolve_tool(tool_name)
        adapted_arguments = self._adapt_tool_arguments(definition, arguments)
        payload = await self._post_rpc(
            "tools/call",
            {"name": actual_name, "arguments": adapted_arguments},
            token,
        )

        if "error" in payload:
            raise ValueError(f"MCP 工具调用失败: {payload['error']}")

        result = payload.get("result", {})
        if result.get("isError"):
            messages = [
                item.get("text", "")
                for item in result.get("content", [])
                if item.get("type") == "text"
            ]
            raise ValueError("MCP 工具返回错误: " + " ".join(messages))
        return result

    async def get_sleep_data(self, start_date: str, end_date: str) -> list[SleepRecord]:
        """
        获取睡眠数据（通过 MCP 官方服务）

        Args:
            start_date: 开始日期，格式 YYYYMMDD
            end_date: 结束日期，格式 YYYYMMDD

        Returns:
            睡眠记录列表
        """
        print(f"   📡 使用 COROS 官方 MCP 服务获取睡眠数据...")

        start = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        days = max(1, (end - start).days + 1)

        # 新版服务名为 querySleepOverview，老区域仍可能返回
        # querySleepData；_resolve_tool 会根据 tools/list 自动选择。
        result = await self._call_tool(
            "querySleepOverview",
            {
                "startDate": start_date,
                "endDate": end_date,
                "days": days,
                "timezone": "Asia/Shanghai",
            },
        )

        # 解析结果。新版 MCP 可能同时返回 structuredContent 和文本 content。
        sleep_records = self._parse_structured_sleep(result.get("structuredContent"))

        # 从 MCP 响应中提取数据
        content_list = result.get("content", [])
        if not content_list:
            if not sleep_records:
                print(f"   ⚠️  未获取到睡眠数据")
            return sleep_records

        # 提取文本数据并解析
        unparsed_texts = []
        for content in content_list:
            if content.get("type") == "text":
                raw_text = content.get("text", "")

                # MCP 返回的文本是 JSON 转义的字符串，需要先解析
                # 例如: "\"Sleep Data\\n========================\\n...\""
                # 需要先用 json.loads 解析得到真正的文本
                try:
                    # 尝试用 json.loads 解析（处理转义字符）
                    text = json.loads(raw_text) if isinstance(raw_text, str) else raw_text
                except (json.JSONDecodeError, TypeError):
                    # 如果解析失败，直接使用原始文本
                    text = raw_text

                # 如果文本被双引号包裹，去掉引号
                if isinstance(text, str) and text.startswith('"') and text.endswith('"'):
                    text = text[1:-1]

                # 将转义的换行符替换为实际换行符
                if isinstance(text, str):
                    text = text.replace('\\n', '\n').replace('\\t', '\t')

                if isinstance(text, str):
                    records = self._parse_sleep_text(text)
                    sleep_records.extend(records)
                    if text.strip() and not records:
                        unparsed_texts.append(text)
                elif isinstance(text, (dict, list)):
                    sleep_records.extend(self._parse_structured_sleep(text))

            elif content.get("type") in {"json", "resource"}:
                sleep_records.extend(
                    self._parse_structured_sleep(
                        content.get("json", content.get("data", content.get("resource")))
                    )
                )

        if not sleep_records and unparsed_texts:
            # 只输出字段名和日期标记数，不把用户的具体睡眠值写入日志。
            combined = "\n".join(unparsed_texts)
            labels = sorted({
                match.strip()
                for match in re.findall(
                    r'(?im)^[ \t]*(?:[-*•][ \t]+)?(?:\*\*)?([A-Za-z][A-Za-z0-9 ()/>_-]{1,40})(?:\*\*)?[ \t]*[:：]',
                    combined,
                )
            })
            date_count = len(re.findall(r'\d{4}[-/]\d{2}[-/]\d{2}', combined))
            fields = ", ".join(labels[:20]) or "(未识别到标签)"
            print(
                f"   ⚠️  MCP 已返回内容，但睡眠格式未能解析；"
                f"日期标记={date_count}，字段={fields}"
            )

        # structuredContent 与 content 可能是同一批数据的两种表示，按日期去重。
        return list({record.date: record for record in sleep_records}.values())

    def _parse_structured_sleep(self, payload) -> list[SleepRecord]:
        """解析 MCP 的 JSON/structuredContent 睡眠响应。"""
        records = []
        if isinstance(payload, list):
            for item in payload:
                records.extend(self._parse_structured_sleep(item))
            return records
        if not isinstance(payload, dict):
            return records

        date_value = _normalized_mapping_value(
            payload, "date", "wakeUpDate", "sleepDate", "day"
        )
        if date_value is None:
            for value in payload.values():
                if isinstance(value, (dict, list)):
                    records.extend(self._parse_structured_sleep(value))
            return records

        date_match = re.search(r'(\d{4})[-/]?(\d{2})[-/]?(\d{2})', str(date_value))
        if not date_match:
            return records
        date = "-".join(date_match.groups())

        score_value = _normalized_mapping_value(
            payload, "sleepScore", "qualityScore", "score"
        )
        score_match = re.search(r'\d+', str(score_value)) if score_value is not None else None
        quality_score = int(score_match.group()) if score_match else None

        total_minutes = _duration_value_to_minutes(_normalized_mapping_value(
            payload,
            "mainSleepDuration",
            "mainSleepMinutes",
            "mainSleepTotal",
            "mainSleep",
            "dailySleepDuration",
            "dailySleep",
        ))
        deep_pct = _ratio_value(_normalized_mapping_value(
            payload, "deepSleepRatio", "deepRatio", "deepSleepPercentage", "deepPct"
        ))
        light_pct = _ratio_value(_normalized_mapping_value(
            payload, "lightSleepRatio", "lightRatio", "lightSleepPercentage", "lightPct"
        ))
        rem_pct = _ratio_value(_normalized_mapping_value(
            payload, "remRatio", "remSleepRatio", "remSleepPercentage", "remPct"
        ))
        awake_pct = _ratio_value(_normalized_mapping_value(
            payload, "awakeRatio", "awakePercentage", "awakePct"
        ))
        awake_minutes = _duration_value_to_minutes(_normalized_mapping_value(
            payload, "awakeTime", "awakeDuration", "awakeMinutes"
        ))
        awake_count_value = _normalized_mapping_value(
            payload, "awakeCount", "wakeCount"
        )
        awake_count_match = (
            re.search(r'\d+', str(awake_count_value))
            if awake_count_value is not None else None
        )
        awake_count = int(awake_count_match.group()) if awake_count_match else None
        nap_minutes = _duration_value_to_minutes(_normalized_mapping_value(
            payload, "napsTotal", "napTotal", "napDuration", "napMinutes"
        ))

        if total_minutes is None and quality_score is None:
            return records
        records.append(SleepRecord(
            date=date,
            total_duration_minutes=total_minutes,
            phases=SleepPhases(
                deep_minutes=(
                    int(total_minutes * deep_pct / 100)
                    if total_minutes and deep_pct is not None else None
                ),
                light_minutes=(
                    int(total_minutes * light_pct / 100)
                    if total_minutes and light_pct is not None else None
                ),
                rem_minutes=(
                    int(total_minutes * rem_pct / 100)
                    if total_minutes and rem_pct is not None else None
                ),
                awake_minutes=awake_minutes,
                nap_minutes=nap_minutes,
            ),
            quality_score=quality_score,
            deep_pct=deep_pct,
            light_pct=light_pct,
            rem_pct=rem_pct,
            awake_pct=awake_pct,
            awake_count=awake_count,
        ))
        return records

    def _parse_sleep_text(self, text: str) -> list[SleepRecord]:
        """
        解析 MCP 返回的睡眠数据文本

        文本格式示例：
        Sleep Data
        ========================

        2026-05-28
        Sleep Score: 93
        Main Sleep: 7h 50min
        Deep Sleep Ratio: 26%
        Light Sleep Ratio: 61%
        REM Ratio: 12%
        Awake Ratio: 1%
        Awake Time: 7 min
        Awake Count (>5 min): 0
        Main Sleep Window: 01:25 - 09:22
        Naps Total: 0 min
        """
        records = []

        if not isinstance(text, str):
            return records

        # 同时支持旧版纯日期行和新版 Markdown/Date 日期标题。
        date_line_pattern = re.compile(
            r'(?im)^[ \t]*(?:[-*•][ \t]+)?(?:#{1,6}[ \t]+)?'
            r'(?:(?:Date|Wake[- ]?up Date)[ \t]*[:：][ \t]*)?'
            r'(\d{4}[-/]\d{2}[-/]\d{2})'
            r'(?:[ \t]*\([^\r\n)]*\)|[ \t]+[A-Za-z]+)?[ \t]*[:：]?[ \t]*$'
        )
        date_markers = list(date_line_pattern.finditer(text))
        if not date_markers:
            # 某些发布批次会把一整天压成一行，以任意日期位置作为兜底分界。
            date_markers = list(re.finditer(
                r'(?<!\d)\d{4}[-/]\d{2}[-/]\d{2}(?!\d)', text
            ))
        if date_markers:
            blocks = [
                text[marker.start():(
                    date_markers[index + 1].start()
                    if index + 1 < len(date_markers)
                    else len(text)
                )]
                for index, marker in enumerate(date_markers)
            ]
        else:
            blocks = [text]

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            record = self._parse_sleep_block(block)
            if record:
                records.append(record)

        return records

    def _parse_sleep_block(self, block: str) -> Optional[SleepRecord]:
        """解析单个睡眠数据块"""
        try:
            # 提取日期
            date_match = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2})', block)
            if not date_match:
                return None
            date = date_match.group(1).replace('/', '-')

            # 提取睡眠评分
            score_value = _extract_labeled_value(block, "Sleep Score", "Score")
            score_match = re.search(r'\d+', score_value or "")
            quality_score = int(score_match.group()) if score_match else None

            # 提取主要睡眠时长
            sleep_value = _extract_labeled_value(
                block,
                "Main Sleep Duration",
                "Main Sleep Total",
                "Main Sleep",
            )
            if sleep_value is None:
                nested_duration = re.search(
                    r'(?is)Main Sleep.{0,160}?\bDuration[ \t]*[:：][ \t]*([^\r\n]+)',
                    block.replace("**", "").replace("__", ""),
                )
                sleep_value = nested_duration.group(1).strip() if nested_duration else None
            if sleep_value is None:
                sleep_value = _extract_labeled_value(
                    block, "Daily Sleep Duration", "Daily Sleep"
                )
            parsed_duration = _parse_duration_str(sleep_value or "")
            total_minutes = parsed_duration or None

            # 提取深度睡眠比例
            deep_pct = _extract_percentage(
                block, "Deep Sleep Ratio", "Deep Ratio", "Deep Sleep"
            )

            # 提取浅度睡眠比例
            light_pct = _extract_percentage(
                block, "Light Sleep Ratio", "Light Ratio", "Light Sleep"
            )

            # 提取 REM 比例
            rem_pct = _extract_percentage(block, "REM Ratio", "REM Sleep Ratio", "REM")

            # 提取清醒比例
            awake_pct = _extract_percentage(block, "Awake Ratio", "Awake")

            # 提取清醒时间
            awake_value = _extract_labeled_value(
                block, "Awake Time", "Awake Duration"
            )
            parsed_awake = _parse_duration_str(awake_value or "")
            awake_minutes = parsed_awake or None

            # 提取清醒次数
            awake_count_value = _extract_labeled_value(
                block, "Awake Count", "Awake Count (>5 min)", "Wake Count"
            )
            awake_count_match = re.search(r'\d+', awake_count_value or "")
            awake_count = int(awake_count_match.group()) if awake_count_match else None

            # 提取小睡时间
            nap_value = _extract_labeled_value(
                block,
                "Naps Total",
                "Nap Total",
                "Total Naps",
                "Nap Duration",
                "Naps",
            )
            parsed_nap = _parse_duration_str(nap_value or "")
            nap_minutes = parsed_nap or None

            # 计算各阶段的分钟数（基于总时长和百分比）
            deep_minutes = None
            light_minutes = None
            rem_minutes = None

            if total_minutes and deep_pct is not None:
                deep_minutes = int(total_minutes * deep_pct / 100)
            if total_minutes and light_pct is not None:
                light_minutes = int(total_minutes * light_pct / 100)
            if total_minutes and rem_pct is not None:
                rem_minutes = int(total_minutes * rem_pct / 100)

            if total_minutes is None and quality_score is None:
                return None

            return SleepRecord(
                date=date,
                total_duration_minutes=total_minutes,
                phases=SleepPhases(
                    deep_minutes=deep_minutes,
                    light_minutes=light_minutes,
                    rem_minutes=rem_minutes,
                    awake_minutes=awake_minutes,
                    nap_minutes=nap_minutes,
                ),
                quality_score=quality_score,
                deep_pct=deep_pct,
                light_pct=light_pct,
                rem_pct=rem_pct,
                awake_pct=awake_pct,
                awake_count=awake_count,
            )

        except Exception as e:
            print(f"   ⚠️  解析睡眠记录失败: {e}")
            return None

    async def get_recent_sleep_data(self, days: int = 7) -> list[SleepRecord]:
        """
        获取最近 N 天的睡眠数据

        Args:
            days: 天数，默认 7 天

        Returns:
            睡眠记录列表
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        return await self.get_sleep_data(start_date, end_date)

    def get_refreshed_token_data(self) -> Optional[dict]:
        """获取刷新后的 token 数据（用于保存到 GitHub Secrets）"""
        return self._refreshed_token_data

    async def get_resting_hr(self, days: int = 7) -> list[RestingHrRecord]:
        """
        获取静息心率数据

        Args:
            days: 天数，默认 7 天

        Returns:
            静息心率记录列表
        """
        result = await self._call_tool(
            "queryRestingHeartRate",
            {"days": days, "timezone": "Asia/Shanghai"},
        )

        records = []
        content_list = result.get("content", [])
        if not content_list:
            return records

        for content in content_list:
            if content.get("type") == "text":
                text = content.get("text", "")
                try:
                    text = json.loads(text) if isinstance(text, str) else text
                except (json.JSONDecodeError, TypeError):
                    pass

                if isinstance(text, str):
                    text = text.replace('\\n', '\n')

                # 解析格式: "2026-06-27: 53 bpm"
                for line in text.split('\n'):
                    match = re.match(r'(\d{4}-\d{2}-\d{2}):\s+(\d+)\s+bpm', line)
                    if match:
                        records.append(RestingHrRecord(
                            date=match.group(1),
                            resting_hr=int(match.group(2))
                        ))

        return records

    async def get_avg_hr(self, days: int = 7) -> list[AvgHrRecord]:
        """
        获取平均心率数据

        Args:
            days: 天数，默认 7 天

        Returns:
            平均心率记录列表
        """
        result = await self._call_tool(
            "queryAvgHeartRate",
            {"days": days, "timezone": "Asia/Shanghai"},
        )

        records = []
        content_list = result.get("content", [])
        if not content_list:
            return records

        for content in content_list:
            if content.get("type") == "text":
                text = content.get("text", "")
                try:
                    text = json.loads(text) if isinstance(text, str) else text
                except (json.JSONDecodeError, TypeError):
                    pass

                if isinstance(text, str):
                    text = text.replace('\\n', '\n')

                # 解析格式: "2026-06-27: 53 bpm (Min: 44, Max: 72)"
                for line in text.split('\n'):
                    match = re.match(r'(\d{4}-\d{2}-\d{2}):\s+(\d+)\s+bpm', line)
                    if match:
                        records.append(AvgHrRecord(
                            date=match.group(1),
                            avg_hr=int(match.group(2))
                        ))

        return records

    async def get_hrv(self, days: int = 7) -> list[HrvRecord]:
        """
        获取 HRV 数据

        Args:
            days: 天数，默认 7 天

        Returns:
            HRV 记录列表
        """
        result = await self._call_tool(
            "querySleepHrv",
            {"days": days, "timezone": "Asia/Shanghai"},
        )

        records = []
        content_list = result.get("content", [])
        if not content_list:
            return records

        for content in content_list:
            if content.get("type") == "text":
                text = content.get("text", "")
                try:
                    text = json.loads(text) if isinstance(text, str) else text
                except (json.JSONDecodeError, TypeError):
                    pass

                if isinstance(text, str):
                    text = text.replace('\\n', '\n')

                # 解析 querySleepHrv 返回的格式
                # 格式示例：
                # 2026-06-27:
                #   HRV Avg: 68 ms — Normal
                #   Normal Range: 42 - 70 ms
                #   Baseline: 56 ms
                current_date = None
                hrv_avg = None
                hrv_result = None

                for line in text.split('\n'):
                    # 匹配日期行
                    date_match = re.match(r'\s*(\d{4}-\d{2}-\d{2}):', line)
                    if date_match:
                        # 保存之前的记录
                        if current_date and hrv_avg is not None:
                            records.append(HrvRecord(
                                date=current_date,
                                hrv_avg=hrv_avg,
                                hrv_result=hrv_result
                            ))
                        current_date = date_match.group(1)
                        hrv_avg = None
                        hrv_result = None
                        continue

                    # 匹配 HRV Avg 行（带评估结果）
                    hrv_match = re.search(r'HRV Avg:\s+(\d+)\s+ms\s*[—-]\s*(.+)', line)
                    if hrv_match:
                        hrv_avg = int(hrv_match.group(1))
                        hrv_result = hrv_match.group(2).strip()
                        continue

                    # 仅匹配 HRV Avg（无评估结果）
                    hrv_avg_only = re.search(r'HRV Avg:\s+(\d+)\s+ms', line)
                    if hrv_avg_only and hrv_avg is None:
                        hrv_avg = int(hrv_avg_only.group(1))

                # 处理最后一个记录
                if current_date and hrv_avg is not None:
                    records.append(HrvRecord(
                        date=current_date,
                        hrv_avg=hrv_avg,
                        hrv_result=hrv_result
                    ))

        return records

    async def get_stress(self, days: int = 7) -> list[StressRecord]:
        """
        获取压力数据

        Args:
            days: 天数，默认 7 天

        Returns:
            压力记录列表
        """
        result = await self._call_tool(
            "queryStressLevel",
            {"days": days, "timezone": "Asia/Shanghai"},
        )

        records = []
        content_list = result.get("content", [])
        if not content_list:
            return records

        for content in content_list:
            if content.get("type") == "text":
                text = content.get("text", "")
                try:
                    text = json.loads(text) if isinstance(text, str) else text
                except (json.JSONDecodeError, TypeError):
                    pass

                if isinstance(text, str):
                    text = text.replace('\\n', '\n')

                # 解析格式: "2026-06-27:\nAverage Stress: 13 (Relaxed)"
                current_date = None
                stress_avg = None

                for line in text.split('\n'):
                    date_match = re.match(r'(\d{4}-\d{2}-\d{2}):', line)
                    if date_match:
                        if current_date and stress_avg is not None:
                            records.append(StressRecord(
                                date=current_date,
                                stress_avg=stress_avg
                            ))
                        current_date = date_match.group(1)
                        stress_avg = None

                    stress_match = re.search(r'Average Stress:\s+(\d+)', line)
                    if stress_match:
                        stress_avg = int(stress_match.group(1))

                # 处理最后一个记录
                if current_date and stress_avg is not None:
                    records.append(StressRecord(
                        date=current_date,
                        stress_avg=stress_avg
                    ))

        return records
