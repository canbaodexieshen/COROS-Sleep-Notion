"""
Notion API Client - 将睡眠数据写入 Notion 数据库
支持 Notion API 2025-09-03 版本（data_source 架构）
"""

import httpx
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from .coros_client import SleepRecord


class NotionSleepPage(BaseModel):
    """Notion 睡眠数据页面结构"""
    date: str                          # YYYY-MM-DD 格式
    total_sleep: Optional[int] = None  # 分钟
    deep_sleep: Optional[int] = None   # 分钟
    light_sleep: Optional[int] = None  # 分钟
    rem_sleep: Optional[int] = None    # 分钟
    awake: Optional[int] = None        # 分钟
    nap: Optional[int] = None          # 分钟
    avg_hr: Optional[int] = None       # bpm
    min_hr: Optional[int] = None       # bpm
    max_hr: Optional[int] = None       # bpm
    quality_score: Optional[int] = None


class NotionSleepClient:
    """Notion 睡眠数据客户端（使用 httpx 直接调用 Notion API）"""

    NOTION_API_BASE = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(self, token: str, database_id: str):
        """
        初始化 Notion 客户端

        Args:
            token: Notion Integration Token
            database_id: Notion 数据库 ID
        """
        self.token = token
        self.database_id = database_id
        self.data_source_id: Optional[str] = None  # 延迟获取
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": self.NOTION_VERSION,
        }
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()

    async def _ensure_data_source_id(self) -> str:
        """
        确保有有效的 data_source_id
        Notion API 2025-09-03 版本需要使用 data_source_id 而不是 database_id

        Returns:
            data_source_id
        """
        if self.data_source_id:
            return self.data_source_id

        # 获取数据库信息，提取 data_source_id
        url = f"{self.NOTION_API_BASE}/databases/{self.database_id}"
        response = await self.client.get(url, headers=self.headers)
        response.raise_for_status()
        data = response.json()

        # 从响应中提取 data_source_id
        # 新版本的 Notion API 会在 data_sources 字段中返回数据源列表
        data_sources = data.get("data_sources", [])
        if data_sources:
            self.data_source_id = data_sources[0]["id"]
            print(f"   📋 获取到 data_source_id: {self.data_source_id[:8]}...")
            return self.data_source_id

        # 如果没有 data_sources 字段，可能是因为数据库是旧版本
        # 尝试使用 database_id 作为 data_source_id（向后兼容）
        self.data_source_id = self.database_id
        print(f"   📋 使用 database_id 作为 data_source_id（向后兼容）")
        return self.data_source_id

    def _format_date(self, date_str: str) -> str:
        """
        将 YYYYMMDD 格式转换为 YYYY-MM-DD 格式

        Args:
            date_str: YYYYMMDD 格式的日期字符串

        Returns:
            YYYY-MM-DD 格式的日期字符串
        """
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    def _sleep_record_to_page(self, record: SleepRecord) -> NotionSleepPage:
        """
        将 COROS 睡眠记录转换为 Notion 页面结构

        Args:
            record: COROS 睡眠记录

        Returns:
            Notion 页面结构
        """
        return NotionSleepPage(
            date=self._format_date(record.date),
            total_sleep=record.total_duration_minutes,
            deep_sleep=record.phases.deep_minutes if record.phases else None,
            light_sleep=record.phases.light_minutes if record.phases else None,
            rem_sleep=record.phases.rem_minutes if record.phases else None,
            awake=record.phases.awake_minutes if record.phases else None,
            nap=record.phases.nap_minutes if record.phases else None,
            avg_hr=record.avg_hr,
            min_hr=record.min_hr,
            max_hr=record.max_hr,
            quality_score=record.quality_score,
        )

    def _build_page_properties(self, page: NotionSleepPage) -> dict:
        """
        构建 Notion 页面属性

        Args:
            page: Notion 睡眠页面结构

        Returns:
            Notion API 属性字典
        """
        properties = {
            "日期": {
                "date": {
                    "start": page.date,
                }
            },
            "总睡眠": {
                "number": page.total_sleep,
            },
            "深睡": {
                "number": page.deep_sleep,
            },
            "浅睡": {
                "number": page.light_sleep,
            },
            "REM": {
                "number": page.rem_sleep,
            },
            "清醒": {
                "number": page.awake,
            },
            "午睡": {
                "number": page.nap,
            },
            "平均心率": {
                "number": page.avg_hr,
            },
            "最小心率": {
                "number": page.min_hr,
            },
            "最大心率": {
                "number": page.max_hr,
            },
            "睡眠评分": {
                "number": page.quality_score,
            },
        }

        # 移除 None 值的属性
        return {
            key: value
            for key, value in properties.items()
            if value.get("number") is not None or key == "日期"
        }

    async def find_page_by_date(self, date: str) -> Optional[str]:
        """
        按日期查找已存在的页面

        Args:
            date: YYYY-MM-DD 格式的日期

        Returns:
            页面 ID，如果不存在返回 None
        """
        # 确保有 data_source_id
        data_source_id = await self._ensure_data_source_id()

        # 使用新的 data_source 端点
        url = f"{self.NOTION_API_BASE}/data_sources/{data_source_id}/query"
        payload = {
            "filter": {
                "property": "日期",
                "date": {
                    "equals": date,
                },
            },
        }

        response = await self.client.post(url, json=payload, headers=self.headers)
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        if results:
            return results[0]["id"]
        return None

    async def create_sleep_page(self, record: SleepRecord) -> str:
        """
        创建睡眠数据页面

        Args:
            record: COROS 睡眠记录

        Returns:
            创建的页面 ID
        """
        # 确保有 data_source_id
        data_source_id = await self._ensure_data_source_id()

        page = self._sleep_record_to_page(record)
        properties = self._build_page_properties(page)

        url = f"{self.NOTION_API_BASE}/pages"
        payload = {
            "parent": {"data_source_id": data_source_id},
            "properties": properties,
        }

        response = await self.client.post(url, json=payload, headers=self.headers)
        response.raise_for_status()
        data = response.json()

        return data["id"]

    async def update_sleep_page(self, page_id: str, record: SleepRecord) -> str:
        """
        更新睡眠数据页面

        Args:
            page_id: 页面 ID
            record: COROS 睡眠记录

        Returns:
            更新的页面 ID
        """
        page = self._sleep_record_to_page(record)
        properties = self._build_page_properties(page)

        url = f"{self.NOTION_API_BASE}/pages/{page_id}"
        payload = {
            "properties": properties,
        }

        response = await self.client.patch(url, json=payload, headers=self.headers)
        response.raise_for_status()
        data = response.json()

        return data["id"]

    async def sync_sleep_record(self, record: SleepRecord) -> dict:
        """
        同步单条睡眠记录（创建或更新）

        Args:
            record: COROS 睡眠记录

        Returns:
            包含操作类型和页面 ID 的字典
        """
        date = self._format_date(record.date)

        # 查找已存在的页面
        existing_page_id = await self.find_page_by_date(date)

        if existing_page_id:
            # 更新已存在的页面
            page_id = await self.update_sleep_page(existing_page_id, record)
            return {
                "action": "updated",
                "page_id": page_id,
                "date": date,
            }
        else:
            # 创建新页面
            page_id = await self.create_sleep_page(record)
            return {
                "action": "created",
                "page_id": page_id,
                "date": date,
            }

    async def sync_sleep_records(self, records: list[SleepRecord]) -> list[dict]:
        """
        批量同步睡眠记录

        Args:
            records: COROS 睡眠记录列表

        Returns:
            同步结果列表
        """
        results = []
        for record in records:
            try:
                result = await self.sync_sleep_record(record)
                results.append(result)
            except Exception as e:
                results.append({
                    "action": "failed",
                    "date": self._format_date(record.date),
                    "error": str(e),
                })
        return results
