"""
Sleep Score Heatmap Generator
从 Notion 获取睡眠评分数据，生成 GitHub 风格热力图 SVG
"""

import os
import sys
import json
import requests
from datetime import datetime, date
from typing import Optional

# 配置
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
TARGET_YEAR = os.getenv("TARGET_YEAR", str(datetime.now().year))

# Notion API 配置
NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

# 请求超时配置（秒）
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 30

# 输出目录
OUT_FOLDER = "sleep_heatmap"
OLD_FOLDER = "old_heatmap"

# 颜色方案（基于睡眠评分）
COLORS = {
    "excellent": "#1ed760",    # > 85分：绿色
    "good": "#ffdd00",         # 60-85分：黄色
    "poor": "#fa2f47",         # < 60分：红色
    "empty": "#E8EAED",        # 无数据：灰色
}


def log(msg: str):
    """带 flush 的输出，确保 GitHub Actions 实时显示日志"""
    print(msg, flush=True)


def notion_request(method: str, endpoint: str, data: dict = None) -> dict:
    """
    发送 Notion API 请求（使用 requests 库，正确处理代理和超时）

    Args:
        method: HTTP 方法（GET/POST/PATCH）
        endpoint: API 端点
        data: 请求数据

    Returns:
        API 响应
    """
    url = f"{NOTION_BASE_URL}{endpoint}"

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        elif method == "POST":
            resp = requests.post(url, json=data, headers=headers, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        elif method == "PATCH":
            resp = requests.patch(url, json=data, headers=headers, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        else:
            raise ValueError(f"Unsupported method: {method}")

        resp.raise_for_status()
        return resp.json()

    except requests.exceptions.ConnectionError as e:
        log(f"   ❌ 连接 Notion API 失败: {e}")
        raise
    except requests.exceptions.Timeout as e:
        log(f"   ❌ Notion API 请求超时: {e}")
        raise
    except requests.exceptions.HTTPError as e:
        log(f"   ❌ Notion API 错误: {e.response.status_code} {e.response.text[:200]}")
        raise


def get_notion_data(year: int) -> dict:
    """
    从 Notion 获取指定年份的睡眠评分数据

    Returns:
        dict: {日期字符串: {"score": 评分, "duration": 时长分钟}}
    """
    log(f"📥 正在从 Notion 获取 {year} 年睡眠数据...")

    data = {}

    # 构建日期范围
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    # 构建查询参数
    query_data = {
        "filter": {
            "and": [
                {
                    "property": "日期",
                    "date": {
                        "on_or_after": start_date,
                    },
                },
                {
                    "property": "日期",
                    "date": {
                        "on_or_before": end_date,
                    },
                },
            ],
        },
        "page_size": 100,
    }

    # 分页查询
    has_more = True
    start_cursor = None
    page_count = 0

    while has_more:
        if start_cursor:
            query_data["start_cursor"] = start_cursor

        page_count += 1
        log(f"   📄 查询第 {page_count} 页...")

        response = notion_request("POST", f"/databases/{NOTION_DATABASE_ID}/query", query_data)

        results = response.get("results", [])
        log(f"   📦 本页获取 {len(results)} 条记录")

        for page in results:
            try:
                # 提取日期
                date_prop = page["properties"].get("日期", {})
                if not date_prop or not date_prop.get("date"):
                    continue
                date_str = date_prop["date"]["start"][:10]  # YYYY-MM-DD

                # 提取睡眠评分
                score = None
                score_prop = page["properties"].get("睡眠评分", {})

                if score_prop.get("number") is not None:
                    score = score_prop["number"]
                elif score_prop.get("formula", {}).get("number") is not None:
                    score = score_prop["formula"]["number"]

                # 提取总睡眠时长
                duration = None
                duration_prop = page["properties"].get("总睡眠", {})

                if duration_prop.get("number") is not None:
                    duration = duration_prop["number"]
                elif duration_prop.get("formula", {}).get("number") is not None:
                    duration = duration_prop["formula"]["number"]

                # 同一天多条记录时，取评分较高的
                if date_str not in data or (score is not None and (data[date_str]["score"] is None or score > data[date_str]["score"])):
                    data[date_str] = {
                        "score": score,
                        "duration": duration,
                    }

            except Exception as e:
                log(f"   ⚠️  解析记录失败: {e}")
                continue

        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    log(f"   ✅ 共获取 {len(data)} 条记录")
    return data


def get_score_category(score: Optional[int]) -> str:
    """根据睡眠评分返回类别"""
    if score is None:
        return "empty"
    elif score > 85:
        return "excellent"
    elif score >= 60:
        return "good"
    else:
        return "poor"


def format_duration(minutes: Optional[int]) -> str:
    """将分钟数格式化为 Xh Ymin 格式"""
    if minutes is None or minutes <= 0:
        return "无数据"
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0 and mins > 0:
        return f"{hours}h {mins}min"
    elif hours > 0:
        return f"{hours}h"
    else:
        return f"{mins}min"


def generate_heatmap_svg(year: int, data: dict) -> str:
    """
    生成热力图 SVG

    Args:
        year: 年份
        data: 睡眠数据 {日期: {score, duration}}

    Returns:
        SVG 字符串
    """
    log(f"🎨 正在生成 {year} 年热力图...")

    # 计算统计信息
    stats = {"excellent": 0, "good": 0, "poor": 0, "empty": 0}
    for d in data.values():
        cat = get_score_category(d.get("score"))
        stats[cat] += 1

    log(f"   📊 统计: {stats['excellent']}天优秀 · {stats['good']}天良好 · {stats['poor']}天较差")

    # 计算日期范围
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    # SVG 配置
    cell_size = 13
    cell_gap = 3
    left_margin = 40
    top_margin = 30
    month_label_height = 20

    # 计算总宽度和高度
    total_weeks = 53  # 一年最多53周
    total_width = left_margin + total_weeks * (cell_size + cell_gap) + 20
    total_height = top_margin + month_label_height + 7 * (cell_size + cell_gap) + 20

    # 生成 SVG 头部
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="{total_height}" viewBox="0 0 {total_width} {total_height}">
  <style>
    .month-label {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 12px; fill: #656d76; }}
    .day-label {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 10px; fill: #656d76; }}
    .stats-text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 12px; fill: #656d76; }}
  </style>

  <!-- 年份和统计信息 -->
  <text x="{left_margin}" y="15" class="stats-text" font-weight="bold">{year}: {stats['excellent']}天优秀 · {stats['good']}天良好 · {stats['poor']}天较差</text>

  <!-- 月份标签 -->
'''

    # 月份标签
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    current_date = start_date
    last_month = -1

    while current_date <= end_date:
        if current_date.month != last_month:
            week_num = (current_date - start_date).days // 7
            x = left_margin + week_num * (cell_size + cell_gap)
            svg += f'  <text x="{x}" y="{top_margin + 15}" class="month-label">{months[current_date.month - 1]}</text>\n'
            last_month = current_date.month
        # 移动到下周
        days_until_sunday = 6 - current_date.weekday()
        if days_until_sunday == 0:
            days_until_sunday = 7
        current_date = date.fromordinal(current_date.toordinal() + days_until_sunday)

    # 星期标签
    day_labels = ["Mon", "Wed", "Fri"]
    for i, label in enumerate(day_labels):
        y = top_margin + month_label_height + (i * 2 + 1) * (cell_size + cell_gap) + 10
        svg += f'  <text x="5" y="{y}" class="day-label">{label}</text>\n'

    # 生成热力图方块
    svg += '\n  <!-- 热力图方块 -->\n'
    current_date = start_date
    while current_date <= end_date:
        # 计算位置
        day_of_week = current_date.weekday()  # 0=Monday
        week_num = (current_date - start_date).days // 7

        x = left_margin + week_num * (cell_size + cell_gap)
        y = top_margin + month_label_height + day_of_week * (cell_size + cell_gap)

        # 获取数据
        date_str = current_date.strftime("%Y-%m-%d")
        day_data = data.get(date_str, {"score": None, "duration": None})
        score = day_data.get("score")
        duration = day_data.get("duration")
        category = get_score_category(score)

        color = COLORS[category]

        # 生成 tooltip
        score_text = f"评分: {score}" if score is not None else "无评分"
        duration_text = format_duration(duration)
        tooltip = f"{date_str} - {score_text} ({duration_text})"

        svg += f'  <rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" rx="2" ry="2" fill="{color}" data-date="{date_str}" data-score="{score or ""}" data-duration="{duration or ""}"><title>{tooltip}</title></rect>\n'

        # 移动到下一天
        current_date = date.fromordinal(current_date.toordinal() + 1)

    # 图例
    legend_y = total_height - 15
    legend_x = left_margin

    svg += f'''
  <!-- 图例 -->
  <text x="{legend_x}" y="{legend_y}" class="stats-text">Less</text>
  <rect x="{legend_x + 30}" y="{legend_y - 10}" width="{cell_size}" height="{cell_size}" rx="2" ry="2" fill="{COLORS['empty']}"/>
  <rect x="{legend_x + 46}" y="{legend_y - 10}" width="{cell_size}" height="{cell_size}" rx="2" ry="2" fill="{COLORS['poor']}"/>
  <rect x="{legend_x + 62}" y="{legend_y - 10}" width="{cell_size}" height="{cell_size}" rx="2" ry="2" fill="{COLORS['good']}"/>
  <rect x="{legend_x + 78}" y="{legend_y - 10}" width="{cell_size}" height="{cell_size}" rx="2" ry="2" fill="{COLORS['excellent']}"/>
  <text x="{legend_x + 96}" y="{legend_y}" class="stats-text">More</text>
'''

    svg += '</svg>'

    log(f"   ✅ SVG 生成完成")
    return svg


def save_svg(svg_content: str, output_path: str):
    """保存 SVG 文件"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    log(f"   💾 已保存到 {output_path}")


def main():
    """主函数"""
    # 立即 flush，确保 GitHub Actions 能看到输出
    log("=" * 50)
    log(f"🚀 开始生成睡眠评分热力图")

    # 检查配置
    if not NOTION_TOKEN:
        log("❌ 错误：未设置 NOTION_TOKEN 环境变量")
        sys.exit(1)
    if not NOTION_DATABASE_ID:
        log("❌ 错误：未设置 NOTION_DATABASE_ID 环境变量")
        sys.exit(1)

    year = int(TARGET_YEAR)
    log(f"📅 目标年份: {year}")
    log(f"🔑 Token: {NOTION_TOKEN[:10]}...{NOTION_TOKEN[-4:]}")
    log(f"📋 Database ID: {NOTION_DATABASE_ID[:10]}...")
    log()

    # 获取数据
    data = get_notion_data(year)

    if not data:
        log("⚠️  没有获取到数据，跳过生成")
        return

    # 生成 SVG
    svg = generate_heatmap_svg(year, data)

    # 保存到对应目录
    if year == datetime.now().year:
        output_path = os.path.join(OUT_FOLDER, "main.svg")
    else:
        output_path = os.path.join(OLD_FOLDER, f"{year}.svg")

    save_svg(svg, output_path)

    log()
    log(f"🎉 热力图生成完成！")


if __name__ == "__main__":
    main()
