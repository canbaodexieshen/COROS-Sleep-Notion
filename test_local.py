"""
本地测试脚本
用于验证项目配置和基本功能
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


async def test_coros_connection():
    """测试 COROS 连接"""
    from src.coros_client import CorosClient

    email = os.getenv("COROS_EMAIL")
    password = os.getenv("COROS_PASSWORD")
    region = os.getenv("COROS_REGION", "asia")

    if not email or not password:
        print("❌ 缺少 COROS_EMAIL 或 COROS_PASSWORD 环境变量")
        return False

    print(f"🔐 正在登录 COROS...")
    print(f"   邮箱: {email[:3]}***{email[-4:]}")
    print(f"   区域: {region}")

    client = CorosClient(email=email, password=password, region=region)

    try:
        # 尝试获取最近 3 天的数据
        records = await client.get_recent_sleep_data(days=3)
        print(f"✅ COROS 连接成功！获取到 {len(records)} 条睡眠记录")

        # 显示数据预览
        if records:
            print("\n📊 数据预览:")
            for record in records[:3]:
                print(f"   {record.date}: 总睡眠 {record.total_duration_minutes} 分钟")
                if record.phases:
                    print(f"      深睡: {record.phases.deep_minutes} 分钟")
                    print(f"      浅睡: {record.phases.light_minutes} 分钟")
                    print(f"      REM: {record.phases.rem_minutes} 分钟")
                if record.avg_hr:
                    print(f"      平均心率: {record.avg_hr} bpm")

        return True

    except Exception as e:
        print(f"❌ COROS 连接失败: {e}")
        return False

    finally:
        await client.close()


def test_notion_connection():
    """测试 Notion 连接"""
    from notion_client import Client

    token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not token or not database_id:
        print("❌ 缺少 NOTION_TOKEN 或 NOTION_DATABASE_ID 环境变量")
        return False

    print(f"\n🔗 正在测试 Notion 连接...")
    print(f"   Token: {token[:10]}...")
    print(f"   Database ID: {database_id[:10]}...")

    try:
        client = Client(auth=token)

        # 尝试查询数据库
        response = client.databases.query(database_id=database_id, page_size=1)
        print(f"✅ Notion 连接成功！")

        # 显示数据库信息
        results = response.get("results", [])
        print(f"   数据库中已有 {len(results)} 条记录（示例）")

        return True

    except Exception as e:
        print(f"❌ Notion 连接失败: {e}")
        print("\n💡 可能的原因：")
        print("   1. Token 无效或已过期")
        print("   2. 数据库 ID 不正确")
        print("   3. Integration 未授权访问数据库")
        return False


async def main():
    """主测试函数"""
    print("=" * 50)
    print("🧪 COROS Sleep Sync 本地测试")
    print("=" * 50)

    # 加载 .env 文件
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ 已加载 .env 文件")
    else:
        print(f"⚠️  未找到 .env 文件，将使用系统环境变量")
        print(f"   请复制 .env.example 为 .env 并填写配置")

    print()

    # 测试 COROS 连接
    coros_ok = await test_coros_connection()

    # 测试 Notion 连接
    notion_ok = test_notion_connection()

    # 输出总结
    print("\n" + "=" * 50)
    print("📋 测试结果总结:")
    print(f"   COROS: {'✅ 通过' if coros_ok else '❌ 失败'}")
    print(f"   Notion: {'✅ 通过' if notion_ok else '❌ 失败'}")

    if coros_ok and notion_ok:
        print("\n🎉 所有测试通过！可以运行同步脚本了：")
        print("   python -m src.main")
    else:
        print("\n⚠️  请先修复上述问题后再运行同步脚本")

    print("=" * 50)

    return coros_ok and notion_ok


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
