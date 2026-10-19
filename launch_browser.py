"""Launch Chrome or Edge with an isolated profile and local proxy."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _mac_candidates(browser: str) -> list[str]:
    app = "Google Chrome" if browser == "chrome" else "Microsoft Edge"
    return [f"/Applications/{app}.app/Contents/MacOS/{app}"]


def _windows_candidates(browser: str) -> list[str]:
    app = "Google\\Chrome\\Application\\chrome.exe" if browser == "chrome" else "Microsoft\\Edge\\Application\\msedge.exe"
    roots = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")]
    return [str(Path(root) / app) for root in roots if root]


def find_browser(browser: str) -> str:
    candidates = _mac_candidates(browser) if sys.platform == "darwin" else _windows_candidates(browser)
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    executable = "google-chrome" if browser == "chrome" else "microsoft-edge"
    resolved = shutil.which(executable)
    if resolved:
        return resolved
    raise SystemExit(f"找不到 {browser}，请修改 launch_browser.py 中的浏览器路径")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["chrome", "edge"], default="chrome")
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=8080)
    parser.add_argument("--profile-dir", type=Path, default=Path(".profiles"))
    parser.add_argument("--url", default="about:blank")
    args = parser.parse_args()

    browser = find_browser(args.browser)
    profile = args.profile_dir.expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True)
    proxy = f"http={args.proxy_host}:{args.proxy_port};https={args.proxy_host}:{args.proxy_port}"
    command = [
        browser,
        f"--user-data-dir={profile}",
        f"--proxy-server={proxy}",
        "--proxy-bypass-list=<-loopback>",
        args.url,
    ]
    print("启动:", " ".join(command))
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
