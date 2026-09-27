import re
import unittest

from update_sleep_heatmap import generate_heatmap_svg


def cell_position(svg: str, date_string: str) -> tuple[int, int]:
    match = re.search(
        rf'<rect[^>]+x="(\d+)" y="(\d+)"[^>]+data-date="{date_string}"',
        svg,
    )
    if not match:
        raise AssertionError(f"找不到 {date_string} 的方块")
    return int(match.group(1)), int(match.group(2))


class HeatmapLayoutTests(unittest.TestCase):
    def test_days_are_aligned_to_monday_based_calendar_weeks(self):
        svg = generate_heatmap_svg(2026, {})

        # 2026-01-01 是周四；紧接着的周一必须进入下一列。
        self.assertEqual(cell_position(svg, "2026-01-01"), (40, 113))
        self.assertEqual(cell_position(svg, "2026-01-05"), (56, 65))
        self.assertEqual(cell_position(svg, "2026-01-12"), (72, 65))

        positions = re.findall(
            r'<rect[^>]+x="(\d+)" y="(\d+)"[^>]+data-date=', svg
        )
        self.assertEqual(len(positions), len(set(positions)))

    def test_svg_exposes_theme_classes(self):
        svg = generate_heatmap_svg(
            2026,
            {"2026-01-01": {"score": 90, "duration": 450, "nap": 20}},
        )

        self.assertIn('class="heatmap-svg"', svg)
        self.assertIn('class="cell-excellent has-nap"', svg)
        self.assertIn("var(--heat-excellent", svg)

    def test_width_accounts_for_rare_54_week_year(self):
        svg = generate_heatmap_svg(2012, {})
        self.assertIn('width="924"', svg)


if __name__ == "__main__":
    unittest.main()
