# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import httpx
from typing import Any, Dict, Optional
import re


class ApiSessionManager:
    """
    管理 HTTP 会话，包括：
    - base_url: API 基础地址
    - headers: 全局请求头
    - auth: 认证信息（token, api_key, basic_auth）
    - cookies: 持久化 Cookie
    - timeout: 请求超时
    - variables: 提取的变量（用于链式调用）
    - last_response: 保存上次响应，供后续断言/提取使用
    """

    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "")
        self.headers = config.get("headers", {})
        self.auth = config.get("auth", {})
        self.timeout = config.get("timeout", 30)
        self.variables: Dict[str, Any] = {}
        self.last_response: Optional[httpx.Response] = None
        self.session: Optional[httpx.Client] = None

    def get_client(self) -> httpx.Client:
        """获取或创建 HTTP 客户端"""
        if self.session is None:
            self.session = httpx.Client(
                base_url=self.base_url if self.base_url else "",
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True
            )

            # 设置认证
            self._setup_auth()

        return self.session

    def _setup_auth(self):
        """设置认证信息"""
        if not self.session:
            return

        auth_type = self.auth.get("type", "none")
        if auth_type == "bearer":
            token = self.auth.get("token", "")
            if token:
                self.session.headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            key_name = self.auth.get("key_name", "api_key")
            api_key = self.auth.get("api_key", "")
            location = self.auth.get("location", "header")
            if location == "header" and api_key:
                self.session.headers[key_name] = api_key
            elif location == "query" and api_key:
                # 会自动添加到每个请求的参数
                pass  # httpx 不直接支持全局 query 参数，需要在每个请求添加
        elif auth_type == "basic":
            username = self.auth.get("username", "")
            password = self.auth.get("password", "")
            if username and password:
                self.session.auth = (username, password)

    def update_headers(self, headers: dict):
        """更新全局请求头"""
        self.headers.update(headers)
        if self.session:
            self.session.headers.update(headers)

    def set_base_url(self, base_url: str):
        """设置 API 基础地址"""
        self.base_url = base_url
        # 对于 httpx.Client，base_url 在创建后无法直接修改，需要重新创建
        if self.session:
            old_headers = dict(self.session.headers)
            self.session = httpx.Client(
                base_url=base_url,
                headers=old_headers,
                timeout=self.timeout,
                follow_redirects=True
            )
            self._setup_auth()

    def set_auth(self, auth_config: dict):
        """设置认证配置"""
        self.auth = auth_config
        if self.session:
            # 清除现有认证头
            for key in list(self.session.headers.keys()):
                if key.lower() in ["authorization", "x-api-key"]:
                    del self.session.headers[key]
            self._setup_auth()

    def set_timeout(self, timeout: int):
        """设置请求超时"""
        self.timeout = timeout
        if self.session:
            self.session.timeout = timeout

    def set_variable(self, name: str, value: Any):
        """存储提取的变量"""
        self.variables[name] = value

    def get_variables(self) -> Dict[str, Any]:
        """获取所有已提取的变量"""
        return self.variables

    def clear_variables(self):
        """清空所有变量"""
        self.variables.clear()

    def resolve_variables(self, text: str) -> str:
        """替换字符串中的 {{variable}} 占位符"""
        if not self.variables:
            return text

        pattern = r'\{\{(\w+)\}\}'

        def replace_match(match):
            var_name = match.group(1)
            if var_name in self.variables:
                return str(self.variables[var_name])
            return match.group(0)  # 如果变量不存在，保持原样

        return re.sub(pattern, replace_match, text)

    def resolve_json_variables(self, data: Any) -> Any:
        """递归解析 JSON 结构中的变量占位符"""
        if isinstance(data, str):
            return self.resolve_variables(data)
        elif isinstance(data, dict):
            return {
                self.resolve_variables(key): self.resolve_json_variables(value)
                for key, value in data.items()
            }
        elif isinstance(data, list):
            return [self.resolve_json_variables(item) for item in data]
        else:
            return data

    def close(self):
        """关闭会话"""
        if self.session:
            self.session.close()
            self.session = None
