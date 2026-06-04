"""
年度热力图归档脚本
生成指定历史年份的睡眠评分热力图 SVG
"""

import os
import sys
from datetime import datetime

# 导入主脚本的核心函数
from update_sleep_heatmap import get_notion_data, generate_heatmap_svg, save_svg, OLD_FOLDER


def main():
    """主函数"""
    # 获取目标年份
    manual_year = os.getenv("MANUAL_YEAR")
    if manual_year:
        target_year = int(manual_year)
    else:
        target_year = datetime.now().year - 1

    print(f"🚀 开始生成 {target_year} 年度睡眠评分热力图")
    print()

    # 获取数据
    data = get_notion_data(target_year)

    if not data:
        print("⚠️  没有获取到数据，跳过生成")
        return

    # 生成 SVG
    svg = generate_heatmap_svg(target_year, data)

    # 保存到历史目录
    output_path = os.path.join(OLD_FOLDER, f"{target_year}.svg")
    save_svg(svg, output_path)

    print()
    print(f"🎉 {target_year} 年度热力图生成完成！")


if __name__ == "__main__":
    main()
