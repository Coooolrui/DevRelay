"""mitmproxy addon that routes matched requests to local HTTP services."""

from __future__ import annotations

import os
import re
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mitmproxy import ctx, http

from rules import ConfigError, capture_rule_values, find_rule, load_config, parse_target


class DevRelayProxy:
    def __init__(self) -> None:
        self.config_paths: list[Path] = [Path("configs/default.yml")]
        self.config: dict[str, Any] = {"rules": []}
        self.config_mtimes: dict[Path, int] = {}

    def load(self, loader: Any) -> None:
        loader.add_option(
            name="devrelay_configs",
            typespec=str,
            default="[]",
            help="JSON array of DevRelay proxy YAML configuration paths",
        )

    def configure(self, updated: set[str]) -> None:
        if "devrelay_configs" in updated:
            try:
                values = json.loads(ctx.options.devrelay_configs)
                if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                    raise ValueError
                self.config_paths = [Path(value).expanduser() for value in values]
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                ctx.log.error(f"配置文件列表无效: {exc}")
                self.config_paths = []
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
        flow.metadata["devrelay_captures"] = capture_rule_values(
            rule,
            host=request.pretty_host,
            path=request.path,
            method=request.method,
            headers=headers,
        )

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

        for name in self._string_list(rule.get("removeRequestHeaders", [])):
            request.headers.pop(name, None)

        self._apply_header_actions(
            request.headers,
            rule.get("requestHeaders"),
            flow,
            captures=flow.metadata.get("devrelay_captures", {}),
        )

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
        self._apply_header_actions(
            flow.response.headers,
            rule.get("responseHeaders"),
            flow,
            captures=flow.metadata.get("devrelay_captures", {}),
        )

    def _reload_config(self, *, force: bool = False) -> None:
        mtimes: dict[Path, int] = {}
        configs: list[dict[str, Any]] = []
        try:
            for config_path in self.config_paths:
                mtimes[config_path] = os.stat(config_path).st_mtime_ns
                configs.append(load_config(config_path))
        except ConfigError as exc:
            ctx.log.error(str(exc))
            return
        except OSError as exc:
            if force or self.config.get("rules"):
                ctx.log.error(f"读取配置失败: {exc}")
            return

        if not force and mtimes == self.config_mtimes:
            return
        self.config = {
            "rules": [rule for config in configs for rule in config.get("rules", [])]
        }
        self.config_mtimes = mtimes
        ctx.log.info(
            f"已加载 {len(self.config_paths)} 个配置文件，共 {len(self.config['rules'])} 条代理规则"
        )

    @classmethod
    def _render_value(cls, value: Any, flow: http.HTTPFlow, captures: Mapping[str, Any]) -> str:
        text = str(value)
        request = flow.request
        builtins = {
            "$origin": request.headers.get("Origin", ""),
            "$host": request.pretty_host,
            "$path": request.path.split("?", 1)[0],
            "$query": f"?{request.query}" if request.query else "",
            "$method": request.method,
        }
        for token, replacement in builtins.items():
            text = text.replace(token, replacement)
        return re.sub(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
            lambda match: str(captures.get(match.group(1), "")),
            text,
        )

    @classmethod
    def _apply_header_actions(
        cls,
        headers: Any,
        actions: Any,
        flow: http.HTTPFlow,
        *,
        captures: Mapping[str, Any],
    ) -> None:
        if isinstance(actions, list):
            for action in actions:
                if not isinstance(action, Mapping):
                    continue
                operation = str(action.get("action", "set")).lower()
                name = str(action.get("name", "")).strip()
                if not name:
                    continue
                if operation == "remove":
                    headers.pop(name, None)
                elif operation == "add":
                    headers.add(name, cls._render_value(action.get("value", ""), flow, captures))
                elif operation in {"set", "overwrite", "replace"}:
                    headers[name] = cls._render_value(action.get("value", ""), flow, captures)
            return
        if not isinstance(actions, Mapping):
            return

        # Keep the original mapping form working as an implicit overwrite
        # operation while the UI uses the explicit add/set/remove structure.
        if not any(key in actions for key in ("add", "set", "remove")):
            actions = {"set": actions}

        for name, value in cls._mapping(actions.get("set")).items():
            headers[name] = cls._render_value(value, flow, captures)
        for name, value in cls._mapping(actions.get("add")).items():
            headers.add(name, cls._render_value(value, flow, captures))
        for name in cls._string_list(actions.get("remove", [])):
            headers.pop(name, None)

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
