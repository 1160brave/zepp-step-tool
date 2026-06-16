#!/usr/bin/env python3
"""Shared Zepp Life API client used by both the CLI and Web app."""

import json
import logging
import socket
import struct
import time
import urllib.parse
from datetime import datetime
from typing import Any

import requests

USER_AGENT = "MiFit/6.12.0 (MCE16; Android 16; Density/1.5)"
APP_NAME = "com.xiaomi.hm.health"
DEVICE_ID = "00:00:00:00:00:00"
DATA_DEVICE_ID = "0000000000000000"

API_USER = "https://api-user.huami.com"
API_ACCOUNT = "https://account.huami.com"
API_ACCOUNT_CN = "https://account-cn.huami.com"
API_MIFIT_CN = "https://api-mifit-cn.huami.com"

DEFAULT_TIMEOUT = (5, 15)
NTP_SERVER = "ntp.ntsc.ac.cn"
NTP_DELTA = 2208988800


class ZeppError(Exception):
    """A user-facing Zepp API error."""

    def __init__(
        self,
        message: str,
        *,
        auth_expired: bool = False,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.auth_expired = auth_expired
        self.retry_after = retry_after


def get_timestamp(log: logging.Logger | None = None) -> int:
    """Return an NTP timestamp, falling back to local system time."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(3)
        data = bytearray(48)
        data[0] = 0x1B
        sock.sendto(data, (NTP_SERVER, 123))
        response, _ = sock.recvfrom(1024)
        if len(response) >= 48:
            return int(struct.unpack("!12I", response[:48])[10] - NTP_DELTA)
    except (OSError, struct.error) as exc:
        if log:
            log.debug("NTP unavailable, using system time: %s", exc)
    finally:
        sock.close()
    return int(time.time())


def build_data_json(date_str: str, device_id: str, steps: int) -> str:
    """Build the URL-encoded payload expected by the Zepp Life API."""
    return (
        "%5b%7b%22data_hr%22%3a%22"
        + "%5c%2fv7%2b" * 480
        + f"%22%2c%22date%22%3a%22{date_str}"
        + "%22%2c%22data%22%3a%5b%7b%22start%22%3a0%2c%22stop%22"
        + "%3a1439%2c%22value%22%3a%22"
        + "A" * 5760
        + f"%22%2c%22tz%22%3a32%2c%22did%22%3a%22{device_id}"
        + "%22%2c%22src%22%3a24%7d%5d%2c%22summary%22%3a%22%7b%5c%22v"
        + "%5c%22%3a6%2c%5c%22slp%5c%22%3a%7b%5c%22st%5c%22%3a0%2c"
        + "%5c%22ed%5c%22%3a0%2c%5c%22dp%5c%22%3a0%2c%5c%22lt%5c%22"
        + "%3a0%2c%5c%22wk%5c%22%3a0%2c%5c%22usrSt%5c%22%3a-1440%2c"
        + "%5c%22usrEd%5c%22%3a-1440%2c%5c%22wc%5c%22%3a0%2c%5c%22is"
        + "%5c%22%3a0%2c%5c%22lb%5c%22%3a0%2c%5c%22to%5c%22%3a0%2c"
        + "%5c%22dt%5c%22%3a0%2c%5c%22rhr%5c%22%3a0%2c%5c%22ss%5c%22"
        + "%3a0%7d%2c%5c%22stp%5c%22%3a%7b%5c%22ttl%5c%22%3a"
        + str(steps)
        + "%2c%5c%22dis%5c%22%3a0%2c%5c%22cal%5c%22%3a0%2c%5c%22wk"
        + "%5c%22%3a0%2c%5c%22rn%5c%22%3a0%2c%5c%22runDist%5c%22%3a0"
        + "%2c%5c%22runCal%5c%22%3a0%2c%5c%22stage%5c%22%3a%5b%5d%7d"
        + "%2c%5c%22goal%5c%22%3a0%2c%5c%22tz%5c%22%3a%5c%2228800"
        + "%5c%22%7d%22%2c%22source%22%3a24%2c%22type%22%3a0%7d%5d"
    )


class ZeppClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        logger: logging.Logger | None = None,
    ):
        self.session = session or requests.Session()
        self.log = logger or logging.getLogger("zepp_client")
        self.session.headers.update({"user-agent": USER_AGENT, "app_name": APP_NAME})

    @staticmethod
    def _json(response: requests.Response, action: str) -> dict[str, Any]:
        try:
            body = response.json()
        except (requests.exceptions.JSONDecodeError, json.JSONDecodeError, ValueError):
            raise ZeppError(f"{action}失败：服务器返回了无效响应") from None
        if not isinstance(body, dict):
            raise ZeppError(f"{action}失败：服务器响应格式不正确")
        return body

    @staticmethod
    def _login_identity(account: str) -> tuple[str, str]:
        if account.isdigit() and len(account) == 11 and account.startswith("1"):
            return f"+86{account}", "huami_phone"
        return account, "huami"

    def login(self, account: str, password: str) -> tuple[str, str]:
        login_name, third_name = self._login_identity(account)
        headers = {"content-type": "application/x-www-form-urlencoded; charset=UTF-8"}

        try:
            response = self.session.post(
                f"{API_USER}/registrations/{login_name}/tokens",
                data={
                    "client_id": "HuaMi",
                    "country_code": "CN",
                    "json_response": "true",
                    "name": login_name,
                    "password": password,
                    "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
                    "state": "REDIRECTION",
                    "token": "access",
                },
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ZeppError(f"登录网络异常：{exc}") from exc

        if response.status_code == 429:
            retry_header = response.headers.get("Retry-After")
            try:
                retry_after = max(1, int(retry_header))
            except (TypeError, ValueError):
                retry_after = 120
            raise ZeppError(
                f"请求过于频繁，请等待 {retry_after} 秒后再试",
                retry_after=retry_after,
            )
        if response.status_code != 200:
            raise ZeppError(f"登录失败 (HTTP {response.status_code})")
        code = self._json(response, "登录").get("access")
        if not code:
            raise ZeppError("用户名或密码不正确")

        try:
            response = self.session.post(
                f"{API_ACCOUNT}/v2/client/login",
                data={
                    "app_name": APP_NAME,
                    "country_code": "CN",
                    "code": code,
                    "device_id": DEVICE_ID,
                    "device_model": "android_phone",
                    "app_version": "6.12.0",
                    "grant_type": "access_token",
                    "allow_registration": "false",
                    "source": APP_NAME,
                    "third_name": third_name,
                },
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ZeppError(f"登录网络异常：{exc}") from exc

        if response.status_code != 200:
            raise ZeppError(f"登录第二步失败 (HTTP {response.status_code})")
        token_info = self._json(response, "登录").get("token_info", {})
        login_token = token_info.get("login_token")
        user_id = token_info.get("user_id")
        if not login_token or not user_id:
            raise ZeppError("登录响应缺少 token")
        return str(login_token), str(user_id)

    def get_app_token(self, login_token: str) -> str:
        try:
            response = self.session.get(
                f"{API_ACCOUNT_CN}/v1/client/app_tokens",
                params={"login_token": login_token},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ZeppError(f"获取 app_token 网络异常：{exc}") from exc

        if response.status_code != 200:
            raise ZeppError(f"获取 app_token 失败 (HTTP {response.status_code})")
        app_token = (
            self._json(response, "获取 app_token")
            .get("token_info", {})
            .get("app_token")
        )
        if not app_token:
            raise ZeppError("响应缺少 app_token")
        return str(app_token)

    def authenticate(self, account: str, password: str) -> tuple[str, str, str]:
        login_token, user_id = self.login(account, password)
        return login_token, self.get_app_token(login_token), user_id

    def submit_steps(self, user_id: str, app_token: str, steps: int) -> dict[str, Any]:
        timestamp = get_timestamp(self.log)
        date_str = datetime.now().strftime("%Y-%m-%d")
        form_data = urllib.parse.urlencode(
            {
                "userid": user_id,
                "last_sync_data_time": timestamp,
                "device_type": 0,
                "last_deviceid": DATA_DEVICE_ID,
            }
        )
        # data_json is already URL-encoded to match the payload sent by Zepp Life.
        form_data += f"&data_json={build_data_json(date_str, DATA_DEVICE_ID, steps)}"
        try:
            response = self.session.post(
                f"{API_MIFIT_CN}/v1/data/band_data.json",
                params={"t": timestamp},
                data=form_data,
                headers={
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "apptoken": app_token,
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ZeppError(f"提交网络异常：{exc}") from exc

        body = self._json(response, "提交")
        if response.status_code == 401 or body.get("code") == 401:
            raise ZeppError("Token 已过期", auth_expired=True)
        if response.status_code != 200:
            raise ZeppError(f"提交失败 (HTTP {response.status_code})")
        if body.get("message") != "success":
            message = body.get("message") or body.get("error") or "未知错误"
            raise ZeppError(f"提交失败：{message}")
        return {
            "ok": True,
            "steps": steps,
            "user_id": user_id,
            "date": date_str,
            "timestamp": timestamp,
        }
