"""送信口の抽象。裁定(送信先=Discord/メール/…)がどちらに転んでも
中核を書き直さないための境界。★GL指示=最初から抽象。

失敗は握り潰さない。送れなければ SendError を投げ、呼び元がログへ残す。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod


class SendError(RuntimeError):
    """送信に失敗した。黙って成功扱いにしないための例外。"""


class Sender(ABC):
    @abstractmethod
    def send(self, subject: str, body: str) -> None: ...


class StdoutSender(Sender):
    """--dry-run 用。送らず標準出力へ整形結果を出す。"""

    def send(self, subject: str, body: str) -> None:
        print(f"===== {subject} =====")
        print(body)
        print("===== (dry-run: 送信していません) =====")


class DiscordWebhookSender(Sender):
    """Discord Webhook へ投稿。URLは利用者が config に入れる(同梱しない)。"""

    def __init__(self, webhook_url: str, timeout: float = 15.0):
        if not webhook_url:
            raise SendError("Discord Webhook URL が未設定です(config を確認)")
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send(self, subject: str, body: str) -> None:
        # Discordの1メッセージ上限(2000字)を超える本文は分割して送る。
        header = f"**{subject}**\n"
        chunks = _split_for_discord(body, limit=2000 - len(header) - 8)
        for i, chunk in enumerate(chunks):
            content = (header if i == 0 else "") + "```\n" + chunk + "\n```"
            self._post(content)

    def _post(self, content: str) -> None:
        payload = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status not in (200, 204):
                    raise SendError(f"Webhook が {resp.status} を返しました")
        except urllib.error.URLError as e:
            raise SendError(f"Webhook 送信に失敗: {e}") from e


def _split_for_discord(text: str, limit: int) -> list[str]:
    if limit <= 0:
        limit = 1800
    lines = text.split("\n")
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for ln in lines:
        add = len(ln) + 1
        if cur_len + add > limit and cur:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(ln)
        cur_len += add
    if cur:
        chunks.append("\n".join(cur))
    return chunks or [""]


def build_sender(config: dict, dry_run: bool = False) -> Sender:
    """config["output"] から送信口を組み立てる。--dry-run は常に stdout。"""
    if dry_run:
        return StdoutSender()
    kind = (config.get("sender") or "stdout").strip().lower()
    if kind == "stdout":
        return StdoutSender()
    if kind == "discord":
        return DiscordWebhookSender(config.get("webhook_url", ""))
    # メール等は裁定が返ってから実装(境界は既にここ)。
    raise SendError(f"未対応の送信口: {kind!r}(対応=stdout/discord)")
