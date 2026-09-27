import json
import time
import unittest
from unittest.mock import patch

import httpx

from src.coros_client import COROS_MCP_URL, CorosClient


class CorosClientMcpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.redirect_requests = []
        self.available_sleep_tool = "querySleepOverview"

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if request.url.host == "mcp.coros.com":
                self.redirect_requests.append((str(request.url), request.headers, body))
                return httpx.Response(
                    307,
                    headers={"location": "https://mcpcn.coros.com/mcp"},
                )
            self.requests.append((str(request.url), body))
            method = body["method"]

            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "coros", "version": "test"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": self.available_sleep_tool,
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "days": {"type": "integer"},
                                    "timezone": {"type": "string"},
                                },
                            },
                        }
                    ]
                }
                payload = json.dumps(
                    {"jsonrpc": "2.0", "id": body["id"], "result": result},
                    indent=2,
                )
                sse = "\n".join(f"data: {line}" for line in payload.splitlines())
                return httpx.Response(
                    200,
                    content=f"{sse}\n\n",
                    headers={"content-type": "text/event-stream"},
                )
            elif method == "tools/call":
                self.assertEqual(
                    body["params"]["name"], self.available_sleep_tool
                )
                self.assertEqual(
                    body["params"]["arguments"],
                    {"days": 3, "timezone": "Asia/Shanghai"},
                )
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "# Sleep Overview\n\n"
                                "## 2026-09-25 (Friday)\n"
                                "- **Sleep Score:** 88\n"
                                "- **Main Sleep Duration:** 7 hr 30 min\n"
                                "- **Deep Sleep:** 1 hr 30 min (20%)\n"
                                "- **Light Sleep:** 4 hr 30 min (60%)\n"
                                "- **REM:** 1 hr 30 min (20%)\n"
                                "- **Awake Duration:** 5 min\n"
                                "- **Awake Count:** 1\n"
                                "- **Naps:** 20 min"
                            ),
                        }
                    ]
                }
            else:
                return httpx.Response(400, json={"error": "unexpected method"})

            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": result},
            )

        self.client = CorosClient(
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            expires_at=int(time.time()) + 3600,
        )
        await self.client.client.aclose()
        self.client.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        )

    async def asyncTearDown(self):
        await self.client.close()

    async def test_discovers_tool_and_adapts_arguments(self):
        with patch("builtins.print"):
            records = await self.client.get_sleep_data("20260925", "20260927")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].date, "2026-09-25")
        self.assertEqual(records[0].total_duration_minutes, 450)
        self.assertEqual(records[0].quality_score, 88)
        self.assertEqual([item[1]["method"] for item in self.requests], [
            "initialize",
            "tools/list",
            "tools/call",
        ])
        self.assertEqual(len(self.redirect_requests), 1)
        self.assertEqual(self.redirect_requests[0][0], COROS_MCP_URL)
        self.assertEqual(
            self.redirect_requests[0][1]["authorization"],
            "Bearer test-access-token",
        )
        self.assertTrue(
            all(item[0] == "https://mcpcn.coros.com/mcp" for item in self.requests)
        )

    async def test_falls_back_to_legacy_sleep_tool_name(self):
        self.available_sleep_tool = "querySleepData"

        with patch("builtins.print"):
            records = await self.client.get_sleep_data("20260925", "20260927")

        self.assertEqual(len(records), 1)
        tool_call = next(
            body for _, body in self.requests if body["method"] == "tools/call"
        )
        self.assertEqual(tool_call["params"]["name"], "querySleepData")

    def test_parses_multiple_markdown_date_blocks(self):
        records = self.client._parse_sleep_text(
            "# Sleep Overview\n\n"
            "### Wake-up Date: 2026/09/24:\n"
            "- Sleep Score: 81\n"
            "- Main Sleep: 7h\n\n"
            "### 2026-09-25 Friday\n"
            "- Sleep Score: 88\n"
            "- Main Sleep Duration: 7 hours 30 minutes\n"
            "- Deep Sleep: 20%\n"
        )

        self.assertEqual([record.date for record in records], [
            "2026-09-24",
            "2026-09-25",
        ])
        self.assertEqual(records[0].total_duration_minutes, 420)
        self.assertEqual(records[1].total_duration_minutes, 450)
        self.assertEqual(records[1].deep_pct, 20)

    def test_parses_structured_sleep_overview(self):
        records = self.client._parse_structured_sleep({
            "sleepOverviews": [
                {
                    "wake_up_date": "20260925",
                    "sleep_score": 88,
                    "main_sleep_duration": "7h 30min",
                    "deep_sleep_ratio": 0.2,
                    "light_sleep_ratio": "60%",
                    "rem_ratio": 20,
                    "awake_duration": "5 min",
                    "awake_count": 1,
                    "nap_minutes": 20,
                }
            ]
        })

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].date, "2026-09-25")
        self.assertEqual(records[0].total_duration_minutes, 450)
        self.assertEqual(records[0].deep_pct, 20)
        self.assertEqual(records[0].phases.deep_minutes, 90)


if __name__ == "__main__":
    unittest.main()
