"""
COROS Sleep Data to Notion Sync
主程序入口
使用 COROS 官方 MCP 服务获取睡眠数据（不会踢出手机 App）
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

from .coros_client import CorosClient, SleepRecord
from .notion_client import NotionSleepClient


def load_config() -> dict:
    """
    从环境变量加载配置

    Returns:
        配置字典
    """
    # 加载 .env 文件（本地开发时使用）
    load_dotenv()

    config = {
        "coros_access_token": os.getenv("COROS_ACCESS_TOKEN"),
        "coros_refresh_token": os.getenv("COROS_REFRESH_TOKEN"),
        "coros_client_id": os.getenv("COROS_CLIENT_ID", "ccd9bd8c-6504-4b83-80ab-edad29e075cc"),
        "coros_region": os.getenv("COROS_REGION", "cn"),
        "coros_expires_at": int(os.getenv("COROS_EXPIRES_AT", "0")),
        "notion_token": os.getenv("NOTION_TOKEN"),
        "notion_database_id": os.getenv("NOTION_DATABASE_ID"),
        "sync_days": int(os.getenv("SYNC_DAYS", "7")),
    }

    # 验证必需的配置
    missing = []
    for k in ["coros_access_token", "coros_refresh_token", "notion_token", "notion_database_id"]:
        if config.get(k) is None:
            missing.append(k)

    if missing:
        raise ValueError(f"缺少必需的环境变量: {', '.join(missing)}")

    return config


def _merge_daily_health(
    sleep_records: list[SleepRecord],
    resting_hr_records: list,
    avg_hr_records: list,
    hrv_records: list,
    stress_records: list,
) -> None:
    """将每日健康指标按日期合并到睡眠记录中（原地修改）"""
    resting_hr_map = {r.date: r.resting_hr for r in resting_hr_records}
    avg_hr_map = {r.date: r.avg_hr for r in avg_hr_records}
    hrv_map = {r.date: r for r in hrv_records}
    stress_map = {r.date: r.stress_avg for r in stress_records}

    merged_count = 0
    for record in sleep_records:
        date = record.date
        has_data = False

        if date in resting_hr_map:
            record.resting_hr = resting_hr_map[date]
            has_data = True
        if date in avg_hr_map:
            record.daily_avg_hr = avg_hr_map[date]
            has_data = True
        if date in hrv_map:
            record.hrv_avg = hrv_map[date].hrv_avg
            record.hrv_result = hrv_map[date].hrv_result
            has_data = True
        if date in stress_map:
            record.stress_avg = stress_map[date]
            has_data = True

        if has_data:
            merged_count += 1

    print(f"   已合并 {merged_count}/{len(sleep_records)} 条记录的健康指标")


async def sync_sleep_data(config: dict) -> dict:
    """
    执行睡眠数据同步

    Args:
        config: 配置字典

    Returns:
        同步结果统计
    """
    print(f"🚀 开始同步 COROS 睡眠数据到 Notion")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   同步天数: {config['sync_days']}")
    print()

    # 初始化客户端
    coros_client = CorosClient(
        access_token=config["coros_access_token"],
        refresh_token=config["coros_refresh_token"],
        client_id=config["coros_client_id"],
        region=config["coros_region"],
        expires_at=config["coros_expires_at"] if config["coros_expires_at"] > 0 else None,
    )

    notion_client = NotionSleepClient(
        token=config["notion_token"],
        database_id=config["notion_database_id"],
    )

    try:
        # 1. 获取 COROS 睡眠数据
        print("📥 正在从 COROS 获取睡眠数据...")
        sleep_records = await coros_client.get_recent_sleep_data(
            days=config["sync_days"]
        )
        print(f"   获取到 {len(sleep_records)} 条睡眠记录")

        if not sleep_records:
            print("⚠️  没有获取到睡眠数据，同步结束")
            return {"total": 0, "created": 0, "updated": 0, "failed": 0}

        # 2. 获取每日健康指标
        print()
        print("📥 正在获取每日健康指标...")
        days = config["sync_days"]

        resting_hr_records = await coros_client.get_resting_hr(days=days)
        print(f"   静息心率: {len(resting_hr_records)} 条")

        avg_hr_records = await coros_client.get_avg_hr(days=days)
        print(f"   平均心率: {len(avg_hr_records)} 条")

        hrv_records = await coros_client.get_hrv(days=days)
        print(f"   HRV: {len(hrv_records)} 条")

        stress_records = await coros_client.get_stress(days=days)
        print(f"   压力水平: {len(stress_records)} 条")

        # 3. 按日期合并健康指标到睡眠记录
        print()
        print("🔗 正在按日期合并数据...")
        _merge_daily_health(sleep_records, resting_hr_records, avg_hr_records, hrv_records, stress_records)

        # 4. 同步到 Notion（notion-client SDK 是同步调用）
        print()
        print("📤 正在同步到 Notion...")
        results = notion_client.sync_sleep_records(sleep_records)

        # 5. 统计结果
        stats = {
            "total": len(results),
            "created": sum(1 for r in results if r["action"] == "created"),
            "updated": sum(1 for r in results if r["action"] == "updated"),
            "failed": sum(1 for r in results if r["action"] == "failed"),
        }

        # 6. 输出详细结果
        print()
        print("📊 同步结果:")
        for result in results:
            if result["action"] == "created":
                print(f"   ✅ 创建: {result['date']}")
            elif result["action"] == "updated":
                print(f"   🔄 更新: {result['date']}")
            elif result["action"] == "failed":
                print(f"   ❌ 失败: {result['date']} - {result.get('error')}")

        print()
        print(f"📈 统计:")
        print(f"   总计: {stats['total']} 条")
        print(f"   创建: {stats['created']} 条")
        print(f"   更新: {stats['updated']} 条")
        print(f"   失败: {stats['failed']} 条")

        # 7. 输出刷新后的 token（如果有）
        refreshed_token = coros_client.get_refreshed_token_data()
        if refreshed_token:
            print()
            print("🔑 Token 已刷新，新的 token 数据：")
            print(json.dumps(refreshed_token, indent=2))

        return stats

    finally:
        await coros_client.close()


def main():
    """主函数"""
    try:
        # 加载配置
        config = load_config()

        # 执行同步
        stats = asyncio.run(sync_sleep_data(config))

        # 如果有失败，返回非零退出码
        if stats["failed"] > 0:
            sys.exit(1)

    except Exception as e:
        print(f"❌ 同步失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
