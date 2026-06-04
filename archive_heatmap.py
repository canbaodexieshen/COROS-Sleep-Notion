"""
年度热力图归档脚本
将指定历史年份的睡眠评分热力图从 main.svg 移到 old_heatmap/{year}.svg
每年1月1日由 GitHub Actions 自动触发，也可手动触发
"""

import os
import sys
from datetime import datetime

# 导入主脚本的核心函数
from update_sleep_heatmap import get_notion_data, generate_heatmap_svg, save_svg, OLD_FOLDER


def main():
    """主函数"""
    # 在 main() 内读取环境变量
    token = os.getenv("NOTION_TOKEN", "")
    db_id = os.getenv("NOTION_DATABASE_ID", "")

    # 获取目标年份（支持 MANUAL_YEAR 或 TARGET_YEAR，兼容两种 workflow）
    manual_year = os.getenv("MANUAL_YEAR", "")
    target_year_str = os.getenv("TARGET_YEAR", "")
    if manual_year:
        target_year = int(manual_year)
    elif target_year_str:
        target_year = int(target_year_str)
    else:
        target_year = datetime.now().year - 1

    print(f"Archive Sleep Heatmap | {target_year}", flush=True)
    print("=" * 50, flush=True)

    if not token or not db_id:
        print("[FATAL] NOTION_TOKEN / NOTION_DATABASE_ID 未设置", flush=True)
        sys.exit(1)

    # 获取数据
    data = get_notion_data(target_year, token, db_id)

    if not data:
        print(f"[WARN] {target_year} 年无数据，跳过", flush=True)
        return

    # 生成并保存到 old_heatmap 目录
    svg = generate_heatmap_svg(target_year, data)
    output_path = os.path.join(OLD_FOLDER, f"{target_year}.svg")
    save_svg(svg, output_path)

    print("-" * 50, flush=True)
    print(f"[OK] {target_year} 年度热力图归档完成", flush=True)


if __name__ == "__main__":
    main()
