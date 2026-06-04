"""
COROS API Client - 使用 COROS 官方 MCP 服务获取睡眠数据
使用 OAuth2.0 认证（不会踢出手机 App）
支持 token 自动刷新
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

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


# COROS MCP 配置
COROS_MCP_CONFIGS = {
    "cn": {
        "issuer": "https://mcp.coros.com",
        "mcp_url": "https://mcpcn.coros.com/mcp",
    },
    "eu": {
        "issuer": "https://mcp.coros.com",
        "mcp_url": "https://mcpeu.coros.com/mcp",
    },
    "us": {
        "issuer": "https://mcp.coros.com",
        "mcp_url": "https://mcpus.coros.com/mcp",
    },
}
CLIENT_ID = "ccd9bd8c-6504-4b83-80ab-edad29e075cc"


class CorosClient:
    """COROS API 客户端（使用官方 MCP 服务）"""

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        client_id: str = CLIENT_ID,
        region: str = "cn",
        expires_at: Optional[int] = None,
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
        self.mcp_url = config["mcp_url"]

        self.session_id: Optional[str] = None
        self.client = httpx.AsyncClient(timeout=60.0)

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

    async def _initialize_session(self) -> str:
        """初始化 MCP 会话"""
        if self.session_id:
            return self.session_id

        token = await self._ensure_token()

        # 初始化会话
        response = await self.client.post(
            self.mcp_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "coros-sleep-notion",
                        "version": "1.0.0",
                    },
                },
            },
        )

        # 获取 session ID
        self.session_id = response.headers.get("mcp-session-id")
        if not self.session_id:
            raise ValueError("初始化会话失败：未获取到 session ID")

        # 发送 initialized 通知
        await self.client.post(
            self.mcp_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": self.session_id,
            },
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        return self.session_id

    async def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """调用 MCP 工具"""
        token = await self._ensure_token()
        session_id = await self._initialize_session()

        response = await self.client.post(
            self.mcp_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            },
        )

        # 解析响应（支持 SSE 格式）
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            # SSE 格式，提取最后一个 data 行
            lines = response.text.split("\n")
            data_lines = [line[5:].strip() for line in lines if line.startswith("data:")]
            if data_lines:
                payload = json.loads(data_lines[-1])
            else:
                raise ValueError("MCP 响应为空")
        else:
            payload = response.json()

        if "error" in payload:
            raise ValueError(f"MCP 工具调用失败: {payload['error']}")

        return payload.get("result", {})

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

        # 调用 querySleepData 工具
        result = await self._call_tool(
            "querySleepData",
            {
                "startDate": start_date,
                "endDate": end_date,
                "days": 180,
                "timezone": "Asia/Shanghai",
            },
        )

        # 解析结果
        sleep_records = []

        # 从 MCP 响应中提取数据
        content_list = result.get("content", [])
        if not content_list:
            print(f"   ⚠️  未获取到睡眠数据")
            return sleep_records

        # 提取 JSON 数据
        for content in content_list:
            if content.get("type") == "text":
                try:
                    data = json.loads(content["text"])
                    if isinstance(data, list):
                        for item in data:
                            record = self._parse_sleep_record(item)
                            if record:
                                sleep_records.append(record)
                    elif isinstance(data, dict):
                        # 尝试不同的数据结构
                        sleep_data = data.get("sleepData") or data.get("data") or [data]
                        if isinstance(sleep_data, list):
                            for item in sleep_data:
                                record = self._parse_sleep_record(item)
                                if record:
                                    sleep_records.append(record)
                except json.JSONDecodeError:
                    continue

        return sleep_records

    def _parse_sleep_record(self, data: dict) -> Optional[SleepRecord]:
        """解析单条睡眠记录"""
        try:
            # 尝试不同的字段名
            date = (
                data.get("date")
                or data.get("happenDay")
                or data.get("sleepDate")
                or data.get("startDate")
            )
            if not date:
                return None

            # 格式化日期
            if isinstance(date, str) and len(date) == 8:
                # YYYYMMDD -> YYYY-MM-DD
                date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            elif isinstance(date, str) and len(date) == 10:
                # YYYY-MM-DD 格式，保持不变
                pass
            elif isinstance(date, int):
                # YYYYMMDD 整数
                date_str = str(date)
                date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

            # 获取睡眠时长（分钟）
            total_minutes = (
                data.get("totalSleepTime")
                or data.get("total_sleep_time")
                or data.get("totalDurationMinutes")
                or data.get("sleepDuration")
                or data.get("duration")
            )

            # 获取睡眠阶段
            phases = data.get("phases") or data.get("sleepPhases") or data.get("stageData") or {}

            deep_minutes = (
                phases.get("deepMinutes")
                or phases.get("deepTime")
                or data.get("deepTime")
                or data.get("deep_sleep_time")
                or data.get("deep")
            )
            light_minutes = (
                phases.get("lightMinutes")
                or phases.get("lightTime")
                or data.get("lightTime")
                or data.get("light_sleep_time")
                or data.get("light")
            )
            rem_minutes = (
                phases.get("remMinutes")
                or phases.get("eyeTime")
                or data.get("eyeTime")
                or data.get("rem_sleep_time")
                or data.get("rem")
            )
            awake_minutes = (
                phases.get("awakeMinutes")
                or phases.get("wakeTime")
                or data.get("wakeTime")
                or data.get("awake_time")
                or data.get("awake")
            )
            nap_minutes = (
                phases.get("napMinutes")
                or phases.get("shortSleepTime")
                or data.get("shortSleepTime")
                or data.get("nap_time")
                or data.get("nap")
            )

            # 获取心率
            avg_hr = (
                data.get("avgHeartRate")
                or data.get("averageHeartRate")
                or data.get("avg_hr")
                or data.get("averageHr")
            )
            min_hr = (
                data.get("minHeartRate")
                or data.get("minimumHeartRate")
                or data.get("min_hr")
                or data.get("minHr")
            )
            max_hr = (
                data.get("maxHeartRate")
                or data.get("maximumHeartRate")
                or data.get("max_hr")
                or data.get("maxHr")
            )

            # 获取睡眠评分
            quality_score = (
                data.get("performance")
                or data.get("qualityScore")
                or data.get("quality_score")
                or data.get("sleepScore")
                or data.get("score")
            )
            if quality_score == -1:
                quality_score = None

            # 获取百分比
            deep_pct = data.get("deepSleepPercentage") or data.get("deep_pct") or data.get("deepPercent")
            light_pct = data.get("lightSleepPercentage") or data.get("light_pct") or data.get("lightPercent")
            rem_pct = data.get("remSleepPercentage") or data.get("rem_pct") or data.get("remPercent")

            # 如果没有总时长但有阶段数据，计算总时长
            if not total_minutes and (deep_minutes or light_minutes or rem_minutes):
                total_minutes = sum(filter(None, [deep_minutes, light_minutes, rem_minutes, awake_minutes]))

            if not total_minutes or total_minutes == 0:
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
                avg_hr=avg_hr,
                min_hr=min_hr,
                max_hr=max_hr,
                quality_score=quality_score,
                deep_pct=deep_pct,
                light_pct=light_pct,
                rem_pct=rem_pct,
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
