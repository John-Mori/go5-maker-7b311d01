#!/usr/bin/env python3
"""Discord返信送信 (Phase DB・Bot経由のOUT口。webhook版discord_notify.pyの上位互換)。

使い方:
  python scripts/discord/bot_send.py "総合-受付" "本文..."
  python scripts/discord/bot_send.py --dept system-engineer "改修完了: ..."   (dept名でチャンネル解決)
  echo 本文 | python scripts/discord/bot_send.py "品質-QA"

前提: local/discord_bot_token.txt と local/discord_channels.json (手順=local/discord_bot_setup.md)。
秘密(トークン)は出力しない。本文は2000字制限の安全側1900字で切る。
"""
import json
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # stdinもUTF-8に(パイプ経路 `echo 日本語 | bot_send` の文字化け根治・2026-07-15)。
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")

# ★炎上表記ゲート(素の🔥→<:enjoh:…> / 絵文字に隣接したラベル「炎上」→「恒久」・正本= enjoh.py)。
#   ここはBot APIのOUT口= webhook(persona_send)と並ぶ**もう1つの合流点**。2026-09-01 に
#   persona_send だけへ入れた結果、bot_send 経由の便(例 absence_watchdog の配送失敗警報)は
#   素の🔥がChamiの目の前へ出続けた= 部分適用。同じ実装を両方から呼んで割れを止める
#   (REQ-kaizen-analyst-90ebe8bfc8)。
if HERE not in sys.path:
    sys.path.insert(0, HERE)
try:
    from enjoh import enjoh_backstop
except Exception as _e:                        # 正本が読めない時も送信は殺さない(fail-open)
    print(f"[bot_send] 炎上表記ゲートの正本 enjoh.py を読めない({type(_e).__name__})=素通し。",
          file=sys.stderr)

    def enjoh_backstop(body, tag="bot_send"):
        return body

# ★共通の送信ログ(2026-09-02・研究室HQからの恒久依頼)。この口には送信ログが1行も無く、
#   事故便 msg 1544669455995637771 の**出所が追えなかった**。正本= send_audit.py 1本だけ。
try:
    import send_audit as _send_audit
except Exception:                              # ログが無くても送信は殺さない(fail-open)
    _send_audit = None


def _audit(**kw):
    try:
        if _send_audit is not None:
            _send_audit.record("bot_send", **kw)
    except Exception:
        pass


def main():
    args = sys.argv[1:]
    by_dept = False
    if args and args[0] == "--dept":
        by_dept = True
        args = args[1:]
    if not args:
        print("使い方: bot_send.py [--dept] <チャンネル名|dept> [本文]")
        sys.exit(1)
    key = args[0]
    rest = args[1:]
    # ★--body-file / --body をこの口にも持たせる(2026-09-02・書式の割れが事故の温床だった)。
    #   persona_send / dispatch は前から持っていて、bot_send だけ持たなかった。
    #   「口ごとに本文の渡し方が違う」状態そのものを畳む= 3つとも --body-file で渡せる。
    explicit = bool(rest) and rest[0] in ("--body-file", "--body")
    if explicit:
        flag = rest[0]
        if len(rest) < 2:
            print(f"{flag} の値がありません。")
            sys.exit(1)
        if len(rest) > 2:
            print(f"{flag} の後ろに余分な引数があります: {rest[2:]}\n"
                  "  本文全体を1つの引数にしてください(引用符で囲む)。")
            sys.exit(1)
        if flag == "--body-file":
            try:
                with open(rest[1], "r", encoding="utf-8") as f:
                    body = f.read().strip()
            except OSError as e:
                print(f"本文ファイルを読めません: {rest[1]} ({type(e).__name__})")
                sys.exit(1)
        else:
            body = rest[1].strip()
    else:
        body = " ".join(rest) if rest else sys.stdin.read().strip()
    if not body:
        print("本文が空です。")
        sys.exit(1)
    # ★生CLIフラグを本文として投稿しない(2026-09-02 事故 msg 1544669455995637771)。
    #   この口は本文を「残り引数の連結」で作る=persona_send/dispatch の書式(--body-file 等)を
    #   そのまま渡すと、フラグの文字列がad研究室chへ本文として出た。ここは対応していないので
    #   黙って出さず、失敗させて呼び出し元に気づかせる(止血・恒久はプラットフォームSE)。
    #   ★--body-file/--body は**上でそう渡された時だけ**網から外す。標準入力や連結から
    #     その文字列が出てきたなら、それは渡し方を間違えた便だ(事故と同じ形)=止める。
    _SEND_FLAGS = {
        "--persona", "--channel", "--dept", "--from", "--from-dept",
        "--audience", "--also-post", "--avatar", "--color", "--etitle", "--to",
        "--sender", "--direct", "--dry-run", "--silent", "--plain", "--big",
        "--nobold", "--suffix", "--print-id", "--work", "--broadcast",
    }
    #   ★判定はargvでなく**出来上がった本文の頭**で見る= 引数から来ても標準入力から来ても同じ網にかかる。
    if not explicit:
        _SEND_FLAGS |= {"--body-file", "--body"}
    _head = body.split()[0].split("=")[0] if body.split() else ""
    if _head in _SEND_FLAGS:
        _audit(body=body, event="blocked", status="flag_as_body:" + _head, channel=key)
        print(f"本文がフラグから始まっています: {_head}\n"
              "  bot_send.py が解釈するのは --dept(先頭) と --body-file / --body だけです。\n"
              "  本文をファイルから渡すなら: python scripts/discord/bot_send.py --dept <slug> "
              "--body-file <path>\n"
              "  人格の名義で出すなら: python scripts/discord/persona_send.py --dept <slug> "
              "--persona <名前> --body-file <path>")
        sys.exit(4)
    with open(os.path.join(LOCAL, "discord_bot_token.txt"), "r", encoding="utf-8") as f:
        token = f.read().strip()
    with open(os.path.join(LOCAL, "discord_channels.json"), "r", encoding="utf-8") as f:
        channels = json.load(f)
    field = "dept" if by_dept else "name"
    ch = next((c for c in channels if c.get(field) == key and str(c.get("id", "")).strip().isdigit()), None)
    if not ch:
        print(f"チャンネル未登録: {key} (local/discord_channels.json を確認)")
        sys.exit(2)
    # ★POSTの直前=この口の最後の一点で正規化する(呼び出し元が何本あっても必ず通る)。
    body = enjoh_backstop(body, tag="bot_send")
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{ch['id']}/messages",
        data=json.dumps({"content": body[:1900]}).encode("utf-8"),
        headers={
            "Authorization": "Bot " + token,
            "Content-Type": "application/json",
            "User-Agent": "go5-org-send (personal, v1)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            # ★2026-09-03 応答本文からmsg_idを拾う。Bot APIは**投稿したメッセージのJSONを
            #   必ず返している**のに、旧実装は r.read() を呼ばず捨てていた= send_audit に
            #   msg_id="" で残り、後から「この便は誰が何のために出したのか」を辿れなかった
            #   (webhook側=persona_send も同じ穴。あちらは wait=true を足して塞いだ)。
            #   ★idが読めなくても送信は成功している= ここで例外を上へ出さない。
            mid = ""
            try:
                mid = str((json.loads(r.read().decode("utf-8")) or {}).get("id", "") or "")
            except Exception:
                mid = ""
            _audit(body=body, status=str(r.status), channel_id=str(ch["id"]),
                   channel=str(ch.get("name", "")), dept=str(ch.get("dept", "")), msg_id=mid)
            print(f"送信OK → {ch.get('name')} (HTTP {r.status})" + (f" msg={mid}" if mid else ""))
    except Exception as e:
        _audit(body=body, status="ERR:" + type(e).__name__, channel_id=str(ch["id"]),
               channel=str(ch.get("name", "")), dept=str(ch.get("dept", "")))
        print(f"送信失敗: {type(e).__name__}")
        sys.exit(3)


if __name__ == "__main__":
    main()
