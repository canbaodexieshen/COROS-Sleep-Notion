"""
Sleep Score Heatmap Generator v2
从 Notion 获取睡眠评分数据，生成 GitHub 风格热力图 SVG

v2 新增：
- SVG 标题"睡眠评分热力图"（与 calorie 项目 --me 参数一致）
- 午睡检测：午睡字段不为 0 的日期，方块显示浅蓝色边框
- tooltip 增加"含午睡"标记

参照 calorie-notion-heatmap 项目设计
"""

import os
import sys
import requests
from datetime import datetime, date
from typing import Optional

# 配置
NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

# 请求超时配置（秒）
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30

# 输出目录
OUT_FOLDER = "sleep_heatmap"
OLD_FOLDER = "old_heatmap"

# 颜色方案（基于睡眠评分，与 sleep.html 图例一致）
COLORS = {
    "excellent": "#1ed760",    # > 85分：绿色
    "good": "#ffdd00",         # 60-85分：黄色
    "poor": "#fa2f47",         # < 60分：红色
    "empty": "#E8EAED",        # 无数据：灰色
}

# 午睡边框颜色
NAP_BORDER_COLOR = "#90b1fb"
NAP_STROKE_WIDTH = "1.5"


def log(msg: str):
    print(msg, flush=True)


def notion_request(method: str, endpoint: str, data: dict = None, token: str = None, db_id: str = None) -> dict:
    url = f"{NOTION_BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
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
            raise ValueError(f"Unsupported HTTP method: {method}")

        resp.raise_for_status()
        return resp.json()

    except requests.exceptions.ConnectionError as e:
        log(f"   [ERROR] Notion API 连接失败: {e}")
        raise
    except requests.exceptions.Timeout as e:
        log(f"   [ERROR] Notion API 请求超时（连接>{CONNECT_TIMEOUT}s, 读取>{READ_TIMEOUT}s）")
        raise
    except requests.exceptions.HTTPError as e:
        log(f"   [ERROR] Notion API HTTP {e.response.status_code}: {e.response.text[:200]}")
        raise


def _extract_number(prop: dict) -> Optional[int]:
    """从 Notion 属性中提取数值（支持 number 和 formula 两种类型）"""
    if prop.get("number") is not None:
        return prop["number"]
    if prop.get("formula", {}).get("number") is not None:
        return prop["formula"]["number"]
    return None


def get_notion_data(year: int, token: str, db_id: str) -> dict:
    """
    从 Notion 获取指定年份的睡眠评分数据

    Returns:
        dict: {日期字符串: {"score": 评分, "duration": 时长分钟, "nap": 午睡分钟}}
    """
    log(f"[STEP 1] 从 Notion 获取 {year} 年睡眠数据...")

    data = {}

    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    query_data = {
        "filter": {
            "and": [
                {"property": "日期", "date": {"on_or_after": start_date}},
                {"property": "日期", "date": {"on_or_before": end_date}},
            ],
        },
        "page_size": 100,
    }

    has_more = True
    start_cursor = None
    page_count = 0

    while has_more:
        if start_cursor:
            query_data["start_cursor"] = start_cursor

        page_count += 1
        log(f"   [PAGE] 查询第 {page_count} 页...")

        response = notion_request(
            "POST",
            f"/databases/{db_id}/query",
            data=query_data,
            token=token,
            db_id=db_id,
        )

        results = response.get("results", [])
        log(f"   [DATA] 本页 {len(results)} 条记录")

        for page in results:
            try:
                # 提取日期
                date_prop = page["properties"].get("日期", {})
                if not date_prop or not date_prop.get("date"):
                    continue
                date_str = date_prop["date"]["start"][:10]

                # 提取睡眠评分
                score = _extract_number(page["properties"].get("睡眠评分", {}))

                # 提取总睡眠时长
                duration = _extract_number(page["properties"].get("总睡眠", {}))

                # 提取午睡时长
                nap = _extract_number(page["properties"].get("午睡", {}))

                # 同一天多条记录时，取评分较高的
                if date_str not in data or (
                    score is not None
                    and (data[date_str]["score"] is None or score > data[date_str]["score"])
                ):
                    data[date_str] = {
                        "score": score,
                        "duration": duration,
                        "nap": nap,
                    }

            except Exception as e:
                log(f"   [WARN] 解析记录失败: {e}")
                continue

        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    log(f"   [DONE] 共获取 {len(data)} 条 {year} 年记录")
    return data


def get_score_category(score: Optional[int]) -> str:
    if score is None:
        return "empty"
    elif score > 85:
        return "excellent"
    elif score >= 60:
        return "good"
    else:
        return "poor"


def format_duration(minutes: Optional[int]) -> str:
    if minutes is None or minutes <= 0:
        return "N/A"
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
    生成 GitHub 贡献图风格的睡眠热力图 SVG

    布局：标题 + 副标题统计 + 53周 x 7天方块
    午睡不为 0 的日期显示浅蓝色边框
    """
    log(f"[STEP 2] 生成 {year} 年热力图 SVG...")

    # 统计信息
    stats = {"excellent": 0, "good": 0, "poor": 0, "empty": 0, "nap": 0}
    for d in data.values():
        cat = get_score_category(d.get("score"))
        stats[cat] += 1
        if d.get("nap") and d["nap"] > 0:
            stats["nap"] += 1

    log(f"   [STATS] {stats['excellent']}天优秀 · {stats['good']}天良好 · {stats['poor']}天较差 · {stats['nap']}天含午睡")

    # 日期范围
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    # SVG 布局参数
    cell_size = 13
    cell_gap = 3
    left_margin = 40
    title_height = 20       # 标题区域
    subtitle_height = 20    # 副标题（统计摘要）
    top_margin = title_height + subtitle_height + 5
    month_label_height = 20
    total_weeks = 53

    total_width = left_margin + total_weeks * (cell_size + cell_gap) + 20
    total_height = top_margin + month_label_height + 7 * (cell_size + cell_gap) + 20

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_width}" height="{total_height}" '
        f'viewBox="0 0 {total_width} {total_height}" '
        f'style="background-color:white;">'
    )
    lines.append("  <style>")
    lines.append(
        "    text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }"
    )
    lines.append("  </style>")

    # ===== 标题：睡眠评分热力图（与 calorie 项目 --me 参数效果一致）=====
    lines.append("")
    lines.append(
        f'  <text x="{left_margin}" y="16" font-size="15" fill="#24292f" font-weight="bold">'
        f"睡眠评分热力图</text>"
    )

    # 副标题：年份 + 各评分段统计
    lines.append("")
    lines.append(
        f'  <text x="{left_margin}" y="{16 + subtitle_height}" font-size="12" fill="#656d76">'
        f"{year}: {stats['excellent']}天优秀 · {stats['good']}天良好 · {stats['poor']}天较差"
        f"</text>"
    )

    # 月份标签
    lines.append("")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    cur = start_date
    last_month = -1
    while cur <= end_date:
        if cur.month != last_month:
            week_num = (cur - start_date).days // 7
            x = left_margin + week_num * (cell_size + cell_gap)
            lines.append(
                f'  <text x="{x}" y="{top_margin + 15}" font-size="12" fill="#656d76">'
                f"{months[cur.month - 1]}</text>"
            )
            last_month = cur.month
        days_to_next = 7 - cur.weekday()
        if days_to_next == 7:
            days_to_next = 7
        cur = date.fromordinal(cur.toordinal() + days_to_next)

    # 星期标签（Mon, Wed, Fri）
    lines.append("")
    for i, label in enumerate(["Mon", "Wed", "Fri"]):
        y = top_margin + month_label_height + (i * 2 + 1) * (cell_size + cell_gap) + 10
        lines.append(f'  <text x="5" y="{y}" font-size="10" fill="#656d76">{label}</text>')

    # 热力图方块
    lines.append("")
    lines.append("  <!-- Heatmap cells -->")
    cur = start_date
    while cur <= end_date:
        day_of_week = cur.weekday()
        week_num = (cur - start_date).days // 7

        x = left_margin + week_num * (cell_size + cell_gap)
        y = top_margin + month_label_height + day_of_week * (cell_size + cell_gap)

        # 查找数据
        date_str = cur.strftime("%Y-%m-%d")
        day_data = data.get(date_str, {"score": None, "duration": None, "nap": None})
        score = day_data.get("score")
        duration = day_data.get("duration")
        nap = day_data.get("nap")
        category = get_score_category(score)
        color = COLORS[category]

        # 判断是否含午睡
        has_nap = nap is not None and nap > 0

        # 构建 rect 属性
        rect_attrs = f'x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" rx="2" ry="2" fill="{color}"'
        if has_nap:
            rect_attrs += f' stroke="{NAP_BORDER_COLOR}" stroke-width="{NAP_STROKE_WIDTH}"'

        # tooltip
        score_text = f"{score}分" if score is not None else "无评分"
        duration_text = format_duration(duration)
        nap_text = f" + 午睡{format_duration(nap)}" if has_nap else ""
        tooltip = f"{date_str} | {score_text} | {duration_text}{nap_text}"

        lines.append(
            f'  <rect {rect_attrs} '
            f'data-date="{date_str}" data-score="{score or ""}" data-duration="{duration or ""}" '
            f'data-nap="{nap or ""}">'
            f"<title>{tooltip}</title></rect>"
        )

        cur = date.fromordinal(cur.toordinal() + 1)

    lines.append("</svg>")

    svg = "\n".join(lines)

    log(f"   [DONE] SVG 生成完成（{total_width}x{total_height}，{len(lines)} 行）")
    return svg


def save_svg(svg_content: str, output_path: str):
    dir_name = os.path.dirname(output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    log(f"   [FILE] 已保存 {output_path} ({len(svg_content)} bytes)")


def main():
    token = os.getenv("NOTION_TOKEN", "")
    db_id = os.getenv("NOTION_DATABASE_ID", "")
    target_year = os.getenv("TARGET_YEAR", str(datetime.now().year))

    log("=" * 50)
    log(f"Sleep Heatmap Generator v2 | {target_year}")
    log("=" * 50)

    if not token:
        log("[FATAL] NOTION_TOKEN 环境变量未设置")
        sys.exit(1)
    if not db_id:
        log("[FATAL] NOTION_DATABASE_ID 环境变量未设置")
        sys.exit(1)

    year = int(target_year)
    log(f"  Year:     {year}")
    log(f"  Token:    {token[:8]}...{token[-4:]}")
    log(f"  Database: {db_id[:8]}...{db_id[-4:]}")
    log("-" * 50)

    # Step 1: 从 Notion 获取数据
    data = get_notion_data(year, token, db_id)

    if not data:
        log(f"[WARN] {year} 年无数据，跳过生成")
        return

    # Step 2: 生成 SVG
    svg = generate_heatmap_svg(year, data)

    # Step 3: 保存文件
    if year == datetime.now().year:
        output_path = os.path.join(OUT_FOLDER, "main.svg")
    else:
        output_path = os.path.join(OLD_FOLDER, f"{year}.svg")

    save_svg(svg, output_path)

    log("-" * 50)
    log(f"[OK] 热力图生成完成")


if __name__ == "__main__":
    main()
