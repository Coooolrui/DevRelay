"""DevRelay local web manager for the mitmproxy engine."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from rules import ConfigError, dump_config, load_config, parse_config_text


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "proxy_config.yml"
DEFAULT_STATE = BASE_DIR / ".devrelay_state.json"
UI_FILE = BASE_DIR / "ui" / "index.html"


class AgentManager:
    def __init__(self) -> None:
        self.config_path = DEFAULT_CONFIG
        self.state_path = DEFAULT_STATE
        self.proxy_port = 8080
        self.process: subprocess.Popen[str] | None = None
        self.browser_processes: list[subprocess.Popen[Any]] = []
        self.logs: deque[str] = deque(maxlen=300)
        self.lock = threading.RLock()

    def onboarding(self) -> dict[str, Any]:
        """Return persisted onboarding preferences without making the UI state implicit."""
        with self.lock:
            state = self._read_state()
            state.setdefault("showOnLaunch", True)
            state.setdefault("completed", False)
            state.setdefault("steps", {})
            state.setdefault("proxyPort", self.proxy_port)
            return state

    def save_onboarding(self, state: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(state, dict):
            raise ValueError("初始化状态必须是对象")
        current = self.onboarding()
        current.update({
            "showOnLaunch": bool(state.get("showOnLaunch", current["showOnLaunch"])),
            "completed": bool(state.get("completed", current["completed"])),
            "steps": state.get("steps", current["steps"]),
        })
        if not isinstance(current["steps"], dict):
            raise ValueError("初始化步骤状态必须是对象")
        self.state_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return current

    def reset_onboarding(self) -> dict[str, Any]:
        return self.save_onboarding({"completed": False, "steps": {}})

    def set_proxy_port(self, value: Any) -> dict[str, Any]:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("代理运行中，请先停止代理再修改端口")
        try:
            port = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("代理端口必须是数字") from exc
        if not 1 <= port <= 65535:
            raise ValueError("代理端口必须在 1 到 65535 之间")
        self.proxy_port = port
        state = self.onboarding()
        state["proxyPort"] = port
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self._append_log(f"设置代理端口: {port}")
        return self.status()

    def check_local_service(self, url: str, timeout: float = 3.0) -> dict[str, Any]:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("本地服务地址不能为空")
        target = url.strip()
        if not target.startswith(("http://", "https://")):
            target = "http://" + target
        request = urllib.request.Request(target, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return {"reachable": True, "status": response.status, "url": target}
        except urllib.error.HTTPError as exc:
            # HTTP 4xx/5xx still prove that the local server is reachable.
            return {"reachable": True, "status": exc.code, "url": target}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"reachable": False, "url": target, "error": str(exc.reason if isinstance(exc, urllib.error.URLError) else exc)}

    def _read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def status(self) -> dict[str, Any]:
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            pid = self.process.pid if running and self.process else None
            return {
                "running": running,
                "pid": pid,
                "proxyHost": "127.0.0.1",
                "proxyPort": self.proxy_port,
                "webHost": "127.0.0.1",
                "configPath": str(self.config_path),
                "rules": len(self._read_config().get("rules", [])),
                "certificatePath": str(Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"),
                "certificateReady": (Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem").exists(),
            }

    def start_proxy(self) -> dict[str, Any]:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return self.status()

            mitmdump = shutil.which("mitmdump")
            if not mitmdump:
                raise RuntimeError("找不到 mitmdump，请先执行 uv sync")
            command = [
                mitmdump,
                "-p",
                str(self.proxy_port),
                "-s",
                str(BASE_DIR / "devrelay_proxy.py"),
                "--set",
                f"devrelay_config={self.config_path}",
            ]
            self._append_log("启动代理: " + " ".join(command))
            self.process = subprocess.Popen(
                command,
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            threading.Thread(target=self._read_proxy_logs, daemon=True).start()
            return self.status()

    def stop_proxy(self) -> dict[str, Any]:
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                return self.status()
            self._append_log("停止代理")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            return self.status()

    def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict) or not isinstance(config.get("rules"), list):
            raise ConfigError("配置必须是对象，并包含 rules 数组")
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(
            dump_config(config),
            encoding="utf-8",
        )
        try:
            load_config(temporary)
            os.replace(temporary, self.config_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        self._append_log(f"保存配置: {len(config['rules'])} 条规则")
        return config

    def read_config_text(self) -> str:
        try:
            return self.config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"读取配置失败: {exc}") from exc

    def save_config_text(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str):
            raise ConfigError("配置内容必须是 YAML 文本")
        config = parse_config_text(text, source=self.config_path)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        try:
            load_config(temporary)
            os.replace(temporary, self.config_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        self._append_log(f"保存配置: {len(config['rules'])} 条规则")
        return config

    def launch_browser(self, browser: str, url: str) -> None:
        if browser not in {"chrome", "edge"}:
            raise ValueError("浏览器必须是 chrome 或 edge")
        command = [
            sys.executable,
            str(BASE_DIR / "launch_browser.py"),
            "--browser",
            browser,
            "--proxy-port",
            str(self.proxy_port),
            "--profile-dir",
            str(BASE_DIR / ".profiles"),
            "--url",
            url,
        ]
        self._append_log(f"启动 {browser}: {url}")
        process = subprocess.Popen(command, cwd=BASE_DIR)
        self.browser_processes.append(process)

    def _read_config(self) -> dict[str, Any]:
        try:
            return load_config(self.config_path)
        except ConfigError:
            return {"rules": []}

    def _read_proxy_logs(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._append_log(line.rstrip())
        self._append_log("代理进程已退出")

    def _append_log(self, message: str) -> None:
        with self.lock:
            self.logs.append(message)


manager = AgentManager()
app = FastAPI(title="DevRelay")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_FILE)


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    return manager.status()


@app.get("/api/onboarding")
def get_onboarding() -> dict[str, Any]:
    return manager.onboarding()


@app.put("/api/onboarding")
def put_onboarding(state: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.save_onboarding(state)
    except (OSError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/onboarding/reset")
def reset_onboarding() -> dict[str, Any]:
    try:
        return manager.reset_onboarding()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/local-service/check")
def check_local_service(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.check_local_service(str(payload.get("url", "")))
    except (OSError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/settings")
def put_settings(settings: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.set_proxy_port(settings.get("proxyPort"))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return manager._read_config()


@app.get("/api/config/raw")
def get_config_raw() -> dict[str, str]:
    try:
        return {"format": "yaml", "text": manager.read_config_text()}
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/config")
def put_config(config: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.save_config(config)
    except (ConfigError, OSError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/config/raw")
def put_config_raw(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.save_config_text(payload.get("text", ""))
    except (ConfigError, OSError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/proxy/start")
def start_proxy() -> dict[str, Any]:
    try:
        return manager.start_proxy()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/proxy/stop")
def stop_proxy() -> dict[str, Any]:
    return manager.stop_proxy()


@app.get("/api/logs")
def get_logs() -> dict[str, list[str]]:
    with manager.lock:
        return {"logs": list(manager.logs)}


@app.post("/api/browser/{browser}")
def start_browser(browser: str, payload: dict[str, str]) -> dict[str, str]:
    url = payload.get("url", "http://mitm.it")
    try:
        manager.launch_browser(browser, url)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "started", "browser": browser, "url": url}


def main() -> None:
    parser = argparse.ArgumentParser(description="DevRelay local web manager")
    parser.add_argument("--web-port", type=int, default=8787)
    parser.add_argument("--proxy-port", type=int, default=None)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    manager.config_path = args.config.expanduser().resolve()
    saved_state = manager._read_state()
    saved_port = saved_state.get("proxyPort", 8080)
    if args.proxy_port is None:
        try:
            saved_port = int(saved_port)
        except (TypeError, ValueError):
            saved_port = 8080
        if not 1 <= saved_port <= 65535:
            saved_port = 8080
    manager.proxy_port = args.proxy_port if args.proxy_port is not None else saved_port
    if not args.no_open:
        threading.Timer(
            1.0,
            lambda: webbrowser.open(f"http://127.0.0.1:{args.web_port}"),
        ).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.web_port, log_level="warning")
    finally:
        manager.stop_proxy()


if __name__ == "__main__":
    main()
