"""
COROS Sleep Data to Notion Sync
主程序入口
"""

import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from .coros_client import CorosClient
from .notion_client import NotionSleepClient


def load_config() -> dict:
    """
    从环境变量加载配置

    Returns:
        配置字典
    """
    # 加载 .env 文件（本地开发时使用）
    load_dotenv()

    # 支持 COROS_ACCOUNT 或 COROS_EMAIL（兼容旧配置）
    coros_account = os.getenv("COROS_ACCOUNT") or os.getenv("COROS_EMAIL")

    config = {
        "coros_account": coros_account,
        "coros_password": os.getenv("COROS_PASSWORD"),
        "coros_region": os.getenv("COROS_REGION", "asia"),
        "notion_token": os.getenv("NOTION_TOKEN"),
        "notion_database_id": os.getenv("NOTION_DATABASE_ID"),
        "sync_days": int(os.getenv("SYNC_DAYS", "7")),
    }

    # 验证必需的配置
    missing = [k for k, v in config.items() if v is None and k != "sync_days"]
    if missing:
        raise ValueError(f"缺少必需的环境变量: {', '.join(missing)}")

    return config


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
        account=config["coros_account"],
        password=config["coros_password"],
        region=config["coros_region"],
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

        # 2. 同步到 Notion（notion-client SDK 是同步调用）
        print()
        print("📤 正在同步到 Notion...")
        results = notion_client.sync_sleep_records(sleep_records)

        # 3. 统计结果
        stats = {
            "total": len(results),
            "created": sum(1 for r in results if r["action"] == "created"),
            "updated": sum(1 for r in results if r["action"] == "updated"),
            "failed": sum(1 for r in results if r["action"] == "failed"),
        }

        # 4. 输出详细结果
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
