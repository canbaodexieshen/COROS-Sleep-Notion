"""
COROS API Client - 从 coros-mcp 项目提取的核心逻辑
支持获取睡眠数据（使用 Mobile API）
"""

import hashlib
import json
import random
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from pydantic import BaseModel

# COROS API 区域配置
COROS_REGIONS = {
    "eu": {
        "web_base_url": "https://teameuapi.coros.com",
        "mobile_base_url": "https://apieu.coros.com",
    },
    "us": {
        "web_base_url": "https://teamapi.coros.com",
        "mobile_base_url": "https://api.coros.com",
    },
    "asia": {
        "web_base_url": "https://teamcnapi.coros.com",
        "mobile_base_url": "https://apicn.coros.com",
    },
    "cn": {
        "web_base_url": "https://teamcnapi.coros.com",
        "mobile_base_url": "https://apicn.coros.com",
    },
}

# AES 加密常量（从 Coros APK 逆向得到）
MOBILE_AES_IV = b"weloop3_2015_03#"


class SleepPhases(BaseModel):
    """睡眠阶段数据"""
    deep_minutes: Optional[int] = None      # 深睡（分钟）
    light_minutes: Optional[int] = None     # 浅睡（分钟）
    rem_minutes: Optional[int] = None       # REM 快速眼动（分钟）
    awake_minutes: Optional[int] = None     # 清醒（分钟）
    nap_minutes: Optional[int] = None       # 午睡/小睡（分钟）


class SleepRecord(BaseModel):
    """睡眠记录"""
    date: str                                    # YYYYMMDD 格式
    total_duration_minutes: Optional[int] = None # 总睡眠时长（分钟）
    phases: Optional[SleepPhases] = None         # 各阶段分解
    avg_hr: Optional[int] = None                 # 平均心率
    min_hr: Optional[int] = None                 # 最小心率
    max_hr: Optional[int] = None                 # 最大心率
    quality_score: Optional[int] = None          # 质量评分（-1 = 未计算）


def _md5(text: str) -> str:
    """计算 MD5 哈希"""
    return hashlib.md5(text.encode()).hexdigest()


def _mobile_encrypt(plaintext: str, app_key: str) -> str:
    """
    Mobile API 登录加密（从 Coros APK 逆向得到）
    使用 AES-128-CBC 加密
    """
    from Crypto.Cipher import AES
    import base64

    data = plaintext.encode("utf-8")
    key = app_key.encode("utf-8")

    # XOR 明文与 appKey 字节循环异或
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    # PKCS7 填充到 16 字节边界
    pad_len = 16 - (len(xored) % 16)
    padded = xored + bytes([pad_len] * pad_len)

    # AES-128-CBC 加密
    cipher = AES.new(key, AES.MODE_CBC, MOBILE_AES_IV)
    encrypted = cipher.encrypt(padded)

    # Base64 编码
    return base64.b64encode(encrypted).decode("utf-8")


def _detect_account_type(account: str) -> int:
    """
    检测账号类型

    Args:
        account: 账号（邮箱或手机号）

    Returns:
        accountType: 1=手机号, 2=邮箱
    """
    # 移除空格
    account = account.strip()

    # 如果包含 @ 符号，认为是邮箱
    if "@" in account:
        return 2

    # 如果是纯数字（可能带 + 号），认为是手机号
    if account.replace("+", "").replace("-", "").isdigit():
        return 1

    # 默认返回邮箱类型
    return 2


class CorosClient:
    """COROS API 客户端"""

    def __init__(self, account: str, password: str, region: str = "asia"):
        """
        初始化 COROS 客户端

        Args:
            account: COROS 账号（邮箱或手机号）
            password: 密码
            region: 区域（eu/us/asia/cn）
        """
        self.account = account.strip()
        self.password = password
        self.region = region.lower()
        self.account_type = _detect_account_type(self.account)

        # 获取区域配置
        if self.region not in COROS_REGIONS:
            raise ValueError(f"不支持的区域: {region}. 支持: {list(COROS_REGIONS.keys())}")

        self.web_base_url = COROS_REGIONS[self.region]["web_base_url"]
        self.mobile_base_url = COROS_REGIONS[self.region]["mobile_base_url"]

        # Token
        self.mobile_token: Optional[str] = None
        self.mobile_login_payload: Optional[dict] = None

        # HTTP 客户端
        self.client = httpx.AsyncClient(timeout=30.0)

        # 输出账号类型信息
        account_type_name = "手机号" if self.account_type == 1 else "邮箱"
        print(f"   账号类型: {account_type_name}")

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()

    async def _mobile_login(self) -> str:
        """
        Mobile API 登录（获取睡眠数据专用）
        使用 AES 加密认证
        """
        # 生成随机 16 位 appKey
        app_key = str(random.randint(1_000_000_000_000_000, 9_999_999_999_999_999))

        # 加密账号和密码
        encrypted_account = _mobile_encrypt(self.account, app_key) + "\n"
        encrypted_pwd = _mobile_encrypt(_md5(self.password), app_key) + "\n"

        # 构建请求体
        payload = {
            "account": encrypted_account,
            "accountType": self.account_type,  # 1=手机号, 2=邮箱
            "appKey": app_key,
            "clientType": 1,
            "hasHrCalibrated": 0,
            "kbValidity": 0,
            "pwd": encrypted_pwd,
            "region": "310|Europe/Berlin|US",
            "skipValidation": False,
        }

        # 请求头
        headers = {
            "content-type": "application/json",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/4.12.0",
            "request-time": str(int(time.time() * 1000)),
            "yfheader": json.dumps({
                "appVersion": 1125917087236096,
                "clientType": 1,
                "deviceType": "android",
                "language": "en",
                "region": "eu",
            }),
        }

        # 发送登录请求
        url = f"{self.mobile_base_url}/coros/user/login"
        response = await self.client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        # 检查响应
        if data.get("result") != "0000":
            error_msg = data.get("message", "未知错误")
            raise ValueError(f"Mobile 登录失败: {error_msg}")

        # 保存 token 和 payload（用于刷新）
        self.mobile_token = data["data"]["accessToken"]
        self.mobile_login_payload = payload

        return self.mobile_token

    async def _ensure_mobile_token(self) -> str:
        """确保有有效的 Mobile Token"""
        if self.mobile_token:
            return self.mobile_token
        return await self._mobile_login()

    async def get_sleep_data(self, start_date: str, end_date: str) -> list[SleepRecord]:
        """
        获取睡眠数据

        Args:
            start_date: 开始日期，格式 YYYYMMDD
            end_date: 结束日期，格式 YYYYMMDD

        Returns:
            睡眠记录列表
        """
        # 确保有 token
        token = await self._ensure_mobile_token()

        # 构建请求
        url = f"{self.mobile_base_url}/coros/data/statistic/daily"
        params = {"accessToken": token}
        headers = {
            "Content-Type": "application/json",
            "accesstoken": token,
        }

        payload = {
            "allDeviceSleep": 1,
            "dataType": [5],           # 5 = 睡眠数据
            "dataVersion": 0,
            "startTime": int(start_date),
            "endTime": int(end_date),
            "statisticType": 1,
        }

        # 发送请求
        response = await self.client.post(
            url, json=payload, params=params, headers=headers
        )
        response.raise_for_status()
        data = response.json()

        # 检查 token 是否过期（result == "1019"）
        if data.get("result") == "1019":
            # 刷新 token 重试
            self.mobile_token = None
            token = await self._ensure_mobile_token()
            params = {"accessToken": token}
            headers["accesstoken"] = token
            response = await self.client.post(
                url, json=payload, params=params, headers=headers
            )
            response.raise_for_status()
            data = response.json()

        # 检查响应
        if data.get("result") != "0000":
            raise ValueError(f"获取睡眠数据失败: {data.get('message')}")

        # 解析数据
        sleep_records = []
        day_data_list = (
            data.get("data", {})
            .get("statisticData", {})
            .get("dayDataList", [])
        )

        for day_data in day_data_list:
            happen_day = day_data.get("happenDay")
            sleep_data = day_data.get("sleepData", {})
            performance = day_data.get("performance", -1)

            # 跳过没有睡眠数据的日期
            if not sleep_data or sleep_data.get("totalSleepTime", 0) == 0:
                continue

            # 构建睡眠记录
            record = SleepRecord(
                date=str(happen_day),
                total_duration_minutes=sleep_data.get("totalSleepTime"),
                phases=SleepPhases(
                    deep_minutes=sleep_data.get("deepTime"),
                    light_minutes=sleep_data.get("lightTime"),
                    rem_minutes=sleep_data.get("eyeTime"),
                    awake_minutes=sleep_data.get("wakeTime"),
                    nap_minutes=sleep_data.get("shortSleepTime"),
                ),
                avg_hr=sleep_data.get("avgHeartRate"),
                min_hr=sleep_data.get("minHeartRate"),
                max_hr=sleep_data.get("maxHeartRate"),
                quality_score=performance if performance != -1 else None,
            )
            sleep_records.append(record)

        return sleep_records

    async def get_recent_sleep_data(self, days: int = 7) -> list[SleepRecord]:
        """
        获取最近 N 天的睡眠数据

        Args:
            days: 天数，默认 7 天

        Returns:
            睡眠记录列表
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        return await self.get_sleep_data(start_date, end_date)
