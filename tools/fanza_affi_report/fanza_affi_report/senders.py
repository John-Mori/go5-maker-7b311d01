"""送信口の抽象。裁定(送信先=Discord/メール/…)がどちらに転んでも
中核を書き直さないための境界。★GL指示=最初から抽象。

失敗は握り潰さない。送れなければ SendError を投げ、呼び元がログへ残す。

添付(attachment_path): 送信本文の要約に加え、元のCSVをそのまま送る要件(設計メモ§6-5)。
Discordは multipart/form-data で payload_json + files[0] をPOSTする(標準ライブラリのみ)。
mail は裁定が固まっていないため、config は用意しつつ実装はプレースホルダに留める
(★未検証・実SMTP資格情報での動作確認はしていない)。
"""
from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.request
import uuid
from abc import ABC, abstractmethod
from pathlib import Path


class SendError(RuntimeError):
    """送信に失敗した。黙って成功扱いにしないための例外。"""


class Sender(ABC):
    @abstractmethod
    def send(self, subject: str, body: str, attachment_path: str | Path | None = None) -> None: ...


class StdoutSender(Sender):
    """--dry-run 用。送らず標準出力へ整形結果を出す。"""

    def send(self, subject: str, body: str, attachment_path: str | Path | None = None) -> None:
        print(f"===== {subject} =====")
        print(body)
        if attachment_path:
            size = os.path.getsize(attachment_path) if os.path.exists(attachment_path) else "?"
            print(f"[添付予定: {attachment_path} ({size} bytes)]")
        print("===== (dry-run: 送信していません) =====")


class DiscordWebhookSender(Sender):
    """Discord Webhook へ投稿。URLは利用者が config に入れる(同梱しない)。
    attachment_path が指定されていれば、本文と一緒に元CSVを multipart で添付する。
    """

    def __init__(self, webhook_url: str, timeout: float = 30.0):
        if not webhook_url:
            raise SendError("Discord Webhook URL が未設定です(config を確認)")
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send(self, subject: str, body: str, attachment_path: str | Path | None = None) -> None:
        # Discordの1メッセージ上限(2000字)を超える本文は分割して送る。
        # 添付は最終チャンクにだけ付ける(複数ファイルを重複送信しない)。
        header = f"**{subject}**\n"
        chunks = _split_for_discord(body, limit=2000 - len(header) - 8)
        last = len(chunks) - 1
        for i, chunk in enumerate(chunks):
            content = (header if i == 0 else "") + "```\n" + chunk + "\n```"
            if i == last and attachment_path:
                self._post_multipart(content, attachment_path)
            else:
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

    def _post_multipart(self, content: str, attachment_path: str | Path) -> None:
        attachment_path = Path(attachment_path)
        if not attachment_path.exists():
            raise SendError(f"添付ファイルが存在しません: {attachment_path}")
        boundary = uuid.uuid4().hex
        filename = attachment_path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        file_bytes = attachment_path.read_bytes()

        parts: list[bytes] = []
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(b'Content-Disposition: form-data; name="payload_json"\r\n')
        parts.append(b"Content-Type: application/json\r\n\r\n")
        parts.append(json.dumps({"content": content}).encode("utf-8"))
        parts.append(b"\r\n")
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(
            f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'.encode(
                "utf-8"
            )
        )
        parts.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        parts.append(file_bytes)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body_bytes = b"".join(parts)

        req = urllib.request.Request(
            self.webhook_url,
            data=body_bytes,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status not in (200, 204):
                    raise SendError(f"Webhook(添付付き)が {resp.status} を返しました")
        except urllib.error.URLError as e:
            raise SendError(f"Webhook 送信(添付付き)に失敗: {e}") from e


class MailSender(Sender):
    """メール配送(裁定#2でメールに転んだ場合の受け皿)。

    ★未実装(プレースホルダ)。SMTPの実資格情報での送信確認はしていない。
    config に smtp_host/smtp_port/smtp_user/smtp_password/mail_from/mail_to を
    埋めれば動く「形」だけ用意し、中身は最小限のsmtplib実装に留める。
    実配線(実SMTP)は🐧さんの回答が来てから検証する。
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        mail_from: str,
        mail_to: str,
        timeout: float = 30.0,
    ):
        missing = [
            name
            for name, val in (
                ("smtp_host", smtp_host),
                ("mail_from", mail_from),
                ("mail_to", mail_to),
            )
            if not val
        ]
        if missing:
            raise SendError(
                f"メール送信に必要な設定が未入力です: {', '.join(missing)}"
                "(config [output] を確認してください)"
            )
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.mail_from = mail_from
        self.mail_to = mail_to
        self.timeout = timeout

    def send(self, subject: str, body: str, attachment_path: str | Path | None = None) -> None:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.mail_from
        msg["To"] = self.mail_to
        msg.set_content(body)
        if attachment_path:
            attachment_path = Path(attachment_path)
            if not attachment_path.exists():
                raise SendError(f"添付ファイルが存在しません: {attachment_path}")
            data = attachment_path.read_bytes()
            ctype = mimetypes.guess_type(attachment_path.name)[0] or "application/octet-stream"
            maintype, _, subtype = ctype.partition("/")
            msg.add_attachment(
                data, maintype=maintype, subtype=subtype or "octet-stream",
                filename=attachment_path.name,
            )
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout) as smtp:
                smtp.starttls()
                if self.smtp_user:
                    smtp.login(self.smtp_user, self.smtp_password)
                smtp.send_message(msg)
        except Exception as e:  # noqa: BLE001 - 原因を問わず送信失敗として扱う
            raise SendError(f"メール送信に失敗: {e}") from e


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
    if kind == "mail":
        # ★未検証(プレースホルダ)。実SMTP資格情報での確認は🐧さんの回答後。
        port_raw = config.get("smtp_port", "587") or "587"
        try:
            port = int(port_raw)
        except ValueError:
            raise SendError(f"smtp_port が数値ではありません: {port_raw!r}")
        return MailSender(
            smtp_host=config.get("smtp_host", ""),
            smtp_port=port,
            smtp_user=config.get("smtp_user", ""),
            smtp_password=config.get("smtp_password", ""),
            mail_from=config.get("mail_from", ""),
            mail_to=config.get("mail_to", ""),
        )
    raise SendError(f"未対応の送信口: {kind!r}(対応=stdout/discord/mail)")
