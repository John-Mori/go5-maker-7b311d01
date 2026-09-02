"""セッション失効時の再ログイン補助(要Playwright + 実Chrome/Edge)。

利用者はこれを実行すると、実ブラウザ(browser_channel=chrome/msedge)がログイン画面で開く。
2FA/CAPTCHAも含めて人が手で通す。「ログイン状態を保持」にチェックしてログインすると、
そのセッションが session_dir(永続プロファイル)に保存され、以後の日次自動取得
(downloader.py の SessionDownloader)で再利用される。

パスワードはどこにも保存しない。zero-touchはここだけ崩れる= 初回1回 + 失効時
(年数回想定)のワンクリック。

Windows向けに relogin.bat から `python -m fanza_affi_report.relogin` を叩く運用を想定。
"""
from __future__ import annotations

import argparse
import sys

from .config import load_config


def run_relogin(session_dir: str, login_url: str, browser_channel: str = "chrome") -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.stderr.write(
            "Playwright が未インストールです。`pip install playwright` を実行してください。\n"
        )
        return 1

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            session_dir, channel=browser_channel, headless=False
        )
        page = context.new_page() if not context.pages else context.pages[0]
        page.goto(login_url)
        sys.stdout.write(
            "ブラウザでログインを完了してください(「ログイン状態を保持」にチェック)。\n"
            "ログインできたら、この画面で Enter を押すとセッションを保存して終了します。\n"
        )
        try:
            input()
        except EOFError:
            pass
        # 永続プロファイルなのでCookieはON-DISKに保持済み。明示クローズで確実に書き出す。
        context.close()
    sys.stdout.write("セッションを保存しました。\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DMMアフィ 再ログイン(セッション保存)")
    ap.add_argument("--config", default="config.ini")
    ap.add_argument(
        "--login-url",
        default="",
        help="ログイン画面URL(未指定なら config [download] login_url を使う)",
    )
    ap.add_argument(
        "--browser-channel",
        default="",
        help="chrome / msedge(未指定なら config [download] browser_channel を使う)",
    )
    args = ap.parse_args(argv)

    config = load_config(args.config)
    login_url = args.login_url or config.get("login_url", "")
    if not login_url:
        sys.stderr.write(
            "ログインURLが未設定です(--login-url か config.ini [download] login_url で指定してください)。\n"
        )
        return 1
    browser_channel = args.browser_channel or config.get("browser_channel", "chrome")

    return run_relogin(config["session_dir"], login_url, browser_channel)


if __name__ == "__main__":
    raise SystemExit(main())
