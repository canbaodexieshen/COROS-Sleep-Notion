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


def _parse_duration_str(duration_str: str) -> int:
    """
    解析时长字符串（如 "7h 50min"、"6h 48min"、"490 min"）为分钟数
    """
    if not duration_str:
        return 0

    # 格式: "Xh Ymin" 或 "X hour Y min"
    match = re.search(r'(\d+)\s*h(?:our)?s?\s*(\d+)?\s*min?', duration_str, re.IGNORECASE)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2) or 0)
        return hours * 60 + minutes

    # 格式: "X min"
    match = re.search(r'(\d+)\s*min', duration_str, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # 格式: 纯数字（默认分钟）
    match = re.search(r'^(\d+)$', duration_str.strip())
    if match:
        return int(match.group(1))

    return 0


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

        self._initialized: bool = False
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

    async def _initialize_session(self) -> None:
        """
        初始化 MCP 连接（无状态模式）

        注意：COROS MCP v0.1.1+ 已改为无状态模式，不再需要 Session ID。
        此方法仅用于验证连接可用性。
        """
        if self._initialized:
            return

        token = await self._ensure_token()

        # 初始化连接（验证 MCP 服务可用）
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

        # 检查响应状态
        if response.status_code != 200:
            raise ValueError(f"初始化连接失败：HTTP {response.status_code}")

        # 解析响应（支持 SSE 格式）
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            lines = response.text.split("\n")
            data_lines = [line[5:].strip() for line in lines if line.startswith("data:")]
            if data_lines:
                payload = json.loads(data_lines[-1])
            else:
                raise ValueError("初始化响应为空")
        else:
            payload = response.json()

        if "error" in payload:
            raise ValueError(f"初始化连接失败：{payload['error']}")

        self._initialized = True

    async def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        调用 MCP 工具（无状态模式）

        注意：COROS MCP v0.1.1+ 已改为无状态模式，不再需要 Session ID。
        """
        token = await self._ensure_token()
        await self._initialize_session()

        response = await self.client.post(
            self.mcp_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
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

        # 提取文本数据并解析
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

                records = self._parse_sleep_text(text)
                sleep_records.extend(records)

        return sleep_records

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

        # 分割每个日期的数据块
        # 按日期行分割（格式：YYYY-MM-DD）
        blocks = re.split(r'\n\s*(?=\d{4}-\d{2}-\d{2}\s*\n)', text)

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
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', block)
            if not date_match:
                return None
            date = date_match.group(1)

            # 提取睡眠评分
            score_match = re.search(r'Sleep Score:\s*(\d+)', block)
            quality_score = int(score_match.group(1)) if score_match else None

            # 提取主要睡眠时长
            sleep_match = re.search(r'Main Sleep:\s*(.+?)(?:\n|$)', block)
            total_minutes = _parse_duration_str(sleep_match.group(1)) if sleep_match else None

            # 提取深度睡眠比例
            deep_match = re.search(r'Deep Sleep Ratio:\s*(\d+)%', block)
            deep_pct = float(deep_match.group(1)) if deep_match else None

            # 提取浅度睡眠比例
            light_match = re.search(r'Light Sleep Ratio:\s*(\d+)%', block)
            light_pct = float(light_match.group(1)) if light_match else None

            # 提取 REM 比例
            rem_match = re.search(r'REM Ratio:\s*(\d+)%', block)
            rem_pct = float(rem_match.group(1)) if rem_match else None

            # 提取清醒比例
            awake_pct_match = re.search(r'Awake Ratio:\s*(\d+)%', block)
            awake_pct = float(awake_pct_match.group(1)) if awake_pct_match else None

            # 提取清醒时间
            awake_time_match = re.search(r'Awake Time:\s*(\d+)\s*min', block)
            awake_minutes = int(awake_time_match.group(1)) if awake_time_match else None

            # 提取清醒次数
            awake_count_match = re.search(r'Awake Count.*?:\s*(\d+)', block)
            awake_count = int(awake_count_match.group(1)) if awake_count_match else None

            # 提取小睡时间
            nap_match = re.search(r'Naps Total:\s*(\d+)\s*min', block)
            nap_minutes = int(nap_match.group(1)) if nap_match else None

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
