"""
Notion API Client - 将睡眠数据写入 Notion 数据库
使用 notion-client 官方 SDK（与 keep2notion 项目相同的方式）
"""

import logging
import os
from datetime import datetime
from typing import Optional

from notion_client import Client
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
    """Notion 睡眠数据客户端（使用 notion-client 官方 SDK）"""

    def __init__(self, token: str, database_id: str):
        """
        初始化 Notion 客户端

        Args:
            token: Notion Integration Token
            database_id: Notion 数据库 ID
        """
        self.token = token
        self.database_id = database_id
        # 使用 notion-client 官方 SDK（与 keep2notion 相同的方式）
        self.client = Client(auth=token, log_level=logging.ERROR)

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

    def find_page_by_date(self, date: str) -> Optional[str]:
        """
        按日期查找已存在的页面

        Args:
            date: YYYY-MM-DD 格式的日期

        Returns:
            页面 ID，如果不存在返回 None
        """
        try:
            # 使用 notion-client SDK 查询数据库（与 keep2notion 相同的方式）
            filter = {"property": "日期", "date": {"equals": date}}
            response = self.client.databases.query(
                database_id=self.database_id,
                filter=filter,
            )

            results = response.get("results", [])
            if results:
                return results[0]["id"]
            return None

        except Exception as e:
            print(f"   ⚠️  查询数据库失败: {e}")
            return None

    def create_sleep_page(self, record: SleepRecord) -> str:
        """
        创建睡眠数据页面

        Args:
            record: COROS 睡眠记录

        Returns:
            创建的页面 ID
        """
        page = self._sleep_record_to_page(record)
        properties = self._build_page_properties(page)

        # 使用 notion-client SDK 创建页面（与 keep2notion 相同的方式）
        parent = {"database_id": self.database_id, "type": "database_id"}
        response = self.client.pages.create(
            parent=parent,
            properties=properties,
        )

        return response["id"]

    def update_sleep_page(self, page_id: str, record: SleepRecord) -> str:
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

        # 使用 notion-client SDK 更新页面
        response = self.client.pages.update(
            page_id=page_id,
            properties=properties,
        )

        return response["id"]

    def sync_sleep_record(self, record: SleepRecord) -> dict:
        """
        同步单条睡眠记录（创建或更新）

        Args:
            record: COROS 睡眠记录

        Returns:
            包含操作类型和页面 ID 的字典
        """
        date = self._format_date(record.date)

        # 查找已存在的页面
        existing_page_id = self.find_page_by_date(date)

        if existing_page_id:
            # 更新已存在的页面
            page_id = self.update_sleep_page(existing_page_id, record)
            return {
                "action": "updated",
                "page_id": page_id,
                "date": date,
            }
        else:
            # 创建新页面
            page_id = self.create_sleep_page(record)
            return {
                "action": "created",
                "page_id": page_id,
                "date": date,
            }

    def sync_sleep_records(self, records: list[SleepRecord]) -> list[dict]:
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
                result = self.sync_sleep_record(record)
                results.append(result)
            except Exception as e:
                results.append({
                    "action": "failed",
                    "date": self._format_date(record.date),
                    "error": str(e),
                })
        return results
