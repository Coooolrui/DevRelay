"""mitmproxy addon that routes matched requests to local HTTP services."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mitmproxy import ctx, http

from rules import ConfigError, find_rule, load_config, parse_target


class DevRelayProxy:
    def __init__(self) -> None:
        self.config_path = Path("proxy_config.yml")
        self.config: dict[str, Any] = {"rules": []}
        self.config_mtime_ns: int | None = None

    def load(self, loader: Any) -> None:
        loader.add_option(
            name="devrelay_config",
            typespec=str,
            default="proxy_config.yml",
            help="DevRelay proxy YAML configuration path",
        )

    def configure(self, updated: set[str]) -> None:
        if "devrelay_config" in updated:
            self.config_path = Path(ctx.options.devrelay_config).expanduser()
            self._reload_config(force=True)

    def request(self, flow: http.HTTPFlow) -> None:
        self._reload_config()
        request = flow.request
        headers = {name: value for name, value in request.headers.items()}
        rule = find_rule(
            self.config.get("rules", []),
            host=request.pretty_host,
            path=request.path,
            method=request.method,
            headers=headers,
        )
        if rule is None:
            return
        flow.metadata["devrelay_rule"] = rule

        if request.method == "OPTIONS" and self._cors_enabled(rule):
            flow.response = http.Response.make(204, b"", self._cors_headers(flow, rule))
            return

        original_host = request.pretty_host
        original_port = request.port
        original_scheme = request.scheme
        try:
            scheme, host, port = parse_target(rule)
        except ConfigError as exc:
            ctx.log.error(f"规则 {rule.get('name', '<unnamed>')} 目标无效: {exc}")
            return

        request.scheme = scheme
        request.host = host
        request.port = port

        if rule.get("preserveHost", True):
            request.headers["Host"] = self._host_header(
                original_host, original_port, original_scheme
            )
        else:
            request.headers["Host"] = self._host_header(host, port, scheme)

        for name, value in self._mapping(rule.get("requestHeaders", {})).items():
            request.headers[name] = value

        for name in self._string_list(rule.get("removeRequestHeaders", [])):
            request.headers.pop(name, None)

        self._rewrite_path(request, rule.get("rewritePath"))

        ctx.log.info(
            f"route {rule.get('name', '<unnamed>')} {request.method} -> "
            f"{scheme}://{host}:{port}{request.path}"
        )

    def response(self, flow: http.HTTPFlow) -> None:
        rule = flow.metadata.get("devrelay_rule")
        if flow.response is None or not isinstance(rule, dict):
            return
        if self._cors_enabled(rule):
            for name, value in self._cors_headers(flow, rule).items():
                flow.response.headers[name] = value

    def _reload_config(self, *, force: bool = False) -> None:
        try:
            mtime_ns = os.stat(self.config_path).st_mtime_ns
        except OSError as exc:
            if force or self.config.get("rules"):
                ctx.log.error(f"读取配置失败: {exc}")
            self.config = {"rules": []}
            self.config_mtime_ns = None
            return

        if not force and mtime_ns == self.config_mtime_ns:
            return
        try:
            self.config = load_config(self.config_path)
            self.config_mtime_ns = mtime_ns
            ctx.log.info(f"已加载 {len(self.config.get('rules', []))} 条代理规则")
        except ConfigError as exc:
            ctx.log.error(str(exc))

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, str]:
        if not isinstance(value, Mapping):
            return {}
        return {
            str(name): str(header_value)
            for name, header_value in value.items()
            if header_value is not None
        }

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    @staticmethod
    def _host_header(host: str, port: int, scheme: str) -> str:
        default_port = 443 if scheme == "https" else 80
        return host if port == default_port else f"{host}:{port}"

    @staticmethod
    def _rewrite_path(request: Any, rewrite: Any) -> None:
        if not isinstance(rewrite, dict):
            return
        pattern = rewrite.get("pattern")
        replacement = rewrite.get("replacement", "")
        if not isinstance(pattern, str) or not isinstance(replacement, str):
            return
        try:
            request.path = re.sub(pattern, replacement, request.path, count=1)
        except re.error as exc:
            ctx.log.error(f"路径重写正则无效: {exc}")

    @classmethod
    def _cors_headers(cls, flow: http.HTTPFlow, rule: dict[str, Any]) -> dict[str, str]:
        cors = rule.get("cors", {})
        origin = flow.request.headers.get("Origin", "")
        allow_origin = str(cors.get("allowOrigin", origin))
        if allow_origin == "$origin":
            allow_origin = origin

        headers = {
            "Access-Control-Allow-Origin": allow_origin,
            "Access-Control-Allow-Methods": str(
                cors.get(
                    "allowMethods",
                    "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                )
            ),
            "Access-Control-Allow-Headers": flow.request.headers.get(
                "Access-Control-Request-Headers",
                str(cors.get("allowHeaders", "Content-Type, Authorization")),
            ),
            "Access-Control-Max-Age": str(cors.get("maxAge", "600")),
            "Vary": "Origin",
        }
        if cors.get("allowCredentials", False):
            headers["Access-Control-Allow-Credentials"] = "true"
        return headers

    @staticmethod
    def _cors_enabled(rule: Mapping[str, Any]) -> bool:
        cors = rule.get("cors")
        return isinstance(cors, Mapping) and cors.get("enabled", False) is True


addons = [DevRelayProxy()]
