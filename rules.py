"""Configuration loading and request rule matching for the local proxy."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import yaml


class ConfigError(ValueError):
    """Raised when a proxy configuration is invalid."""


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在: {config_path}") from exc
    return parse_config_text(text, source=config_path)


def parse_config_text(text: str, *, source: str | Path = "配置") -> dict[str, Any]:
    try:
        config = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置 YAML 无效 ({source}): {exc}") from exc

    if not isinstance(config, dict) or not isinstance(config.get("rules", []), list):
        raise ConfigError("配置必须是对象，并包含 rules 数组")
    return config


def dump_config(config: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        dict(config),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _compile(pattern: str | None, field_name: str) -> re.Pattern[str] | None:
    if pattern is None or pattern == "":
        return None
    if not isinstance(pattern, str):
        raise ConfigError(f"{field_name} 必须是正则字符串")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"{field_name} 正则无效: {exc}") from exc


def _headers_match(expected: Mapping[str, str], actual: Mapping[str, str]) -> bool:
    normalized = {str(key).lower(): str(value) for key, value in actual.items()}
    for name, pattern in expected.items():
        if not isinstance(name, str) or not isinstance(pattern, str):
            return False
        value = normalized.get(name.lower())
        if value is None or re.search(pattern, value) is None:
            return False
    return True


def rule_matches(
    rule: Mapping[str, Any],
    *,
    host: str,
    path: str,
    method: str,
    headers: Mapping[str, str] | None = None,
) -> bool:
    if rule.get("enabled", True) is False:
        return False

    match = rule.get("match", {})
    if not isinstance(match, Mapping):
        return False

    checks = {
        "host": host,
        "path": path,
        "method": method,
    }
    for field_name, value in checks.items():
        pattern = _compile(match.get(field_name), f"match.{field_name}")
        if pattern is not None and pattern.search(value) is None:
            return False

    header_patterns = match.get("headers", {})
    if header_patterns and not isinstance(header_patterns, Mapping):
        return False
    if header_patterns and not _headers_match(header_patterns, headers or {}):
        return False
    return True


def find_rule(
    rules: list[Mapping[str, Any]],
    *,
    host: str,
    path: str,
    method: str,
    headers: Mapping[str, str] | None = None,
) -> Mapping[str, Any] | None:
    for rule in rules:
        if isinstance(rule, Mapping) and rule_matches(
            rule,
            host=host,
            path=path,
            method=method,
            headers=headers,
        ):
            return rule
    return None


def capture_rule_values(
    rule: Mapping[str, Any],
    *,
    host: str,
    path: str,
    method: str,
    headers: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return named Python regex groups captured while matching a rule."""
    match = rule.get("match", {})
    if not isinstance(match, Mapping):
        return {}

    captures: dict[str, str] = {}
    checks = {
        "host": host,
        "path": path,
        "method": method,
    }
    for field_name, value in checks.items():
        pattern = _compile(match.get(field_name), f"match.{field_name}")
        if pattern is None:
            continue
        matched = pattern.search(value)
        if matched:
            captures.update({name: group for name, group in matched.groupdict().items() if group is not None})

    header_patterns = match.get("headers", {})
    if isinstance(header_patterns, Mapping):
        normalized = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
        for name, pattern_text in header_patterns.items():
            value = normalized.get(str(name).lower())
            pattern = _compile(pattern_text, f"match.headers.{name}")
            if value is None or pattern is None:
                continue
            matched = pattern.search(value)
            if matched:
                captures.update({key: group for key, group in matched.groupdict().items() if group is not None})
    return captures


def parse_target(rule: Mapping[str, Any]) -> tuple[str, str, int]:
    target = rule.get("target")
    if isinstance(target, str):
        target_url = target if "://" in target else f"http://{target}"
        scheme, separator, authority = target_url.partition("://")
        if not separator or ":" not in authority:
            raise ConfigError("target 必须是 host:port 或带协议的地址")
        host, port_text = authority.rsplit(":", 1)
    elif isinstance(target, Mapping):
        scheme = str(target.get("scheme", "http"))
        host = str(target.get("host", "127.0.0.1"))
        port_text = str(target.get("port", ""))
    else:
        raise ConfigError("target 必须是字符串或对象")

    if scheme not in {"http", "https"} or not host or not port_text.isdigit():
        raise ConfigError("target 的 scheme、host 或 port 无效")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise ConfigError("target 端口必须在 1 到 65535 之间")
    return scheme, host, port
