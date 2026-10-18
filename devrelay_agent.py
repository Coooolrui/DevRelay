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
CONFIG_DIR = BASE_DIR / "configs"
DEFAULT_CONFIG = CONFIG_DIR / "default.yml"
DEFAULT_STATE = BASE_DIR / ".devrelay_state.json"
UI_FILE = BASE_DIR / "ui" / "index.html"


class AgentManager:
    def __init__(self) -> None:
        self.config_dir = CONFIG_DIR
        self.selected_configs: list[str] = []
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
            state.setdefault("selectedConfigs", self.selected_config_names())
            return state

    def save_onboarding(self, state: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(state, dict):
            raise ValueError("初始化状态必须是对象")
        current = self.onboarding()
        current.update({
            "showOnLaunch": bool(state.get("showOnLaunch", current["showOnLaunch"])),
            "completed": bool(state.get("completed", current["completed"])),
            "steps": state.get("steps", current["steps"]),
            "selectedConfigs": state.get("selectedConfigs", current.get("selectedConfigs", [])),
        })
        if not isinstance(current["steps"], dict):
            raise ValueError("初始化步骤状态必须是对象")
        self._write_state(current)
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
        self._write_state(state)
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

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _available_config_names(self) -> list[str]:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        return sorted(
            path.name
            for path in self.config_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
        )

    def _config_path(self, name: str) -> Path:
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError("配置文件名无效")
        path = self.config_dir / name
        if path.suffix.lower() not in {".yml", ".yaml"}:
            raise ValueError("配置文件必须使用 .yml 或 .yaml 后缀")
        return path

    def selected_config_names(self) -> list[str]:
        available = self._available_config_names()
        state = self._read_state()
        saved = state.get("selectedConfigs")
        if saved is None:
            return available
        if not isinstance(saved, list):
            return []
        available_set = set(available)
        return [name for name in saved if isinstance(name, str) and name in available_set]

    def list_config_files(self) -> list[dict[str, Any]]:
        selected = self.selected_config_names()
        selected_set = set(selected)
        files: list[dict[str, Any]] = []
        for name in self._available_config_names():
            path = self._config_path(name)
            item: dict[str, Any] = {
                "name": name,
                "selected": name in selected_set,
                "rules": 0,
                "valid": True,
                "error": None,
            }
            try:
                item["rules"] = len(load_config(path).get("rules", []))
            except (ConfigError, OSError) as exc:
                item["valid"] = False
                item["error"] = str(exc)
            files.append(item)
        return files

    def select_configs(self, names: Any) -> dict[str, Any]:
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ValueError("配置文件选择必须是文件名数组")
        available = set(self._available_config_names())
        if any(name not in available for name in names):
            raise ValueError("选择的配置文件不存在")
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("代理运行中，请先停止代理再修改配置文件选择")
        self.selected_configs = list(dict.fromkeys(names))
        state = self.onboarding()
        state["selectedConfigs"] = self.selected_configs
        self._write_state(state)
        return {"selectedConfigs": self.selected_configs, "files": self.list_config_files()}

    def _active_config_name(self) -> str:
        selected = self.selected_config_names()
        if selected:
            return selected[0]
        available = self._available_config_names()
        if available:
            return available[0]
        raise ConfigError("没有可编辑的配置文件")

    def read_config_file(self, name: str) -> dict[str, Any]:
        path = self._config_path(name)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"读取配置失败: {exc}") from exc
        return {"name": name, "text": text, "config": parse_config_text(text, source=path)}

    def save_config_file_text(self, name: str, text: str) -> dict[str, Any]:
        if not isinstance(text, str):
            raise ConfigError("配置内容必须是 YAML 文本")
        path = self._config_path(name)
        config = parse_config_text(text, source=path)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        try:
            load_config(temporary)
            os.replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        self._append_log(f"保存配置文件 {name}: {len(config['rules'])} 条规则")
        return self.read_config_file(name)

    def create_config_file(self, name: str, text: str = "rules: []\n") -> dict[str, Any]:
        path = self._config_path(name)
        if path.exists():
            raise ValueError(f"配置文件已存在: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        return self.save_config_file_text(name, text)

    def rename_config_file(self, old_name: str, new_name: str) -> dict[str, Any]:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("代理运行中，请先停止代理再重命名配置文件")
        old_path = self._config_path(old_name)
        new_path = self._config_path(new_name)
        if not old_path.exists():
            raise ConfigError(f"配置文件不存在: {old_name}")
        if new_path.exists():
            raise ValueError(f"配置文件已存在: {new_name}")
        selected = self.selected_config_names()
        old_path.rename(new_path)
        if old_name in selected:
            selected[selected.index(old_name)] = new_name
            state = self.onboarding()
            state["selectedConfigs"] = selected
            self._write_state(state)
        return {"name": new_name, "files": self.list_config_files()}

    def delete_config_file(self, name: str) -> dict[str, Any]:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("代理运行中，请先停止代理再删除配置文件")
        path = self._config_path(name)
        if not path.exists():
            raise ConfigError(f"配置文件不存在: {name}")
        path.unlink()
        selected = [item for item in self.selected_config_names() if item != name]
        self.select_configs(selected)
        return {"files": self.list_config_files(), "selectedConfigs": selected}

    def copy_config_file(self, source_name: str, target_name: str) -> dict[str, Any]:
        source = self.read_config_file(source_name)
        return self.create_config_file(target_name, source["text"])

    def combined_config(self, names: list[str] | None = None) -> dict[str, Any]:
        selected = self.selected_config_names() if names is None else names
        rules: list[Any] = []
        for name in selected:
            config = self.read_config_file(name)["config"]
            rules.extend(config.get("rules", []))
        return {"rules": rules}

    def status(self) -> dict[str, Any]:
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            pid = self.process.pid if running and self.process else None
            selected = self.selected_config_names()
            config = self._read_config()
            return {
                "running": running,
                "pid": pid,
                "proxyHost": "127.0.0.1",
                "proxyPort": self.proxy_port,
                "webHost": "127.0.0.1",
                "configPath": str(self.config_dir),
                "configPaths": [str(self._config_path(name)) for name in selected],
                "selectedConfigs": selected,
                "configFiles": self.list_config_files(),
                "rules": len(config.get("rules", [])),
                "certificatePath": str(Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"),
                "certificateReady": (Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem").exists(),
            }

    def start_proxy(self) -> dict[str, Any]:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return self.status()

            selected = self.selected_config_names()
            if not selected:
                raise RuntimeError("请至少选择一个配置文件后再启动代理")
            # Validate every selected file before starting mitmproxy so a bad
            # file cannot leave the user with a half-started proxy process.
            self.combined_config(selected)

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
                f"devrelay_configs={json.dumps([str(self._config_path(name)) for name in selected], ensure_ascii=False)}",
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
        return self.save_config_file_text(self._active_config_name(), dump_config(config))["config"]

    def save_config_file(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict) or not isinstance(config.get("rules"), list):
            raise ConfigError("配置必须是对象，并包含 rules 数组")
        return self.save_config_file_text(name, dump_config(config))

    def read_config_text(self) -> str:
        return self.read_config_file(self._active_config_name())["text"]

    def save_config_text(self, text: str) -> dict[str, Any]:
        return self.save_config_file_text(self._active_config_name(), text)["config"]

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
            return self.combined_config()
        except (ConfigError, ValueError):
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


@app.get("/api/config/files")
def get_config_files() -> dict[str, Any]:
    return {
        "files": manager.list_config_files(),
        "selectedConfigs": manager.selected_config_names(),
    }


@app.put("/api/config/selection")
def put_config_selection(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.select_configs(payload.get("selectedConfigs", []))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/config/files")
def create_config_file(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.create_config_file(str(payload.get("name", "")), str(payload.get("text", "rules: []\n")))
    except (ConfigError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/config/files/import")
def import_config_file(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.create_config_file(str(payload.get("name", "")), str(payload.get("text", "")))
    except (ConfigError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/config/files/{name}")
def get_config_file(name: str) -> dict[str, Any]:
    try:
        return manager.read_config_file(name)
    except (ConfigError, OSError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/config/files/{name}")
def put_config_file(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if "config" in payload:
            return manager.save_config_file(name, payload["config"])
        return manager.save_config_file_text(name, str(payload.get("text", "")))
    except (ConfigError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/config/files/{name}")
def patch_config_file(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.rename_config_file(name, str(payload.get("newName", "")))
    except (ConfigError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/config/files/{name}/copy")
def copy_config_file(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return manager.copy_config_file(name, str(payload.get("newName", "")))
    except (ConfigError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/config/files/{name}")
def delete_config_file(name: str) -> dict[str, Any]:
    try:
        return manager.delete_config_file(name)
    except (ConfigError, OSError, RuntimeError, TypeError, ValueError) as exc:
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
    except (ConfigError, OSError, RuntimeError, ValueError) as exc:
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
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    parser.add_argument("--config", type=Path, default=None, help="兼容参数：指定包含配置文件的目录")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    manager.config_dir = (
        args.config.expanduser().resolve().parent
        if args.config is not None
        else args.config_dir.expanduser().resolve()
    )
    manager.config_dir.mkdir(parents=True, exist_ok=True)
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
