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
                # 用 snake_case 验证客户端会以实际发现的工具名调用。
                result = {
                    "tools": [
                        {
                            "name": "query_sleep_data",
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
                self.assertEqual(body["params"]["name"], "query_sleep_data")
                self.assertEqual(
                    body["params"]["arguments"],
                    {"days": 3, "timezone": "Asia/Shanghai"},
                )
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Sleep Data\n========================\n\n"
                                "2026-09-25\nSleep Score: 88\n"
                                "Main Sleep: 7h 30min\nDeep Sleep Ratio: 20%\n"
                                "Light Sleep Ratio: 60%\nREM Ratio: 20%\n"
                                "Awake Time: 5 min\nNaps Total: 20 min"
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


if __name__ == "__main__":
    unittest.main()
