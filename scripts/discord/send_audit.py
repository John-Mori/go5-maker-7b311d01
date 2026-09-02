# -*- coding: utf-8 -*-
"""send_audit — DiscordのOUT口に共通の送信ログを1本置く(記録先はここだけ)。

★0歩目に見た壊れた実物: msg 1544669455995637771(ad研究室ch)。本文が
  `--body-file /proc/self/fd/0` という**フラグの文字列そのもの**で投稿されていた。
  研究室HQが真因まで割った(bot_send.py L55= 残り引数を連結して本文にする口・フラグを解釈しない)。
  ★だが**誰がその便を出したのかは分からなかった**——bot_send.py 全89行に送信ログが1行も無く、
  「どのプロセスがどの部屋へ何を出したか」を残していなかったからだ。真因は分かったのに
  出所が追えない。これはガードの穴ではなく**観測の穴**で、次の事故でも同じ所で止まる。

なぜこの形か:
  - **合流点に置く**。OUT口ごとに書き方を変えると、割れた側が黙って抜ける
    (2026-09-01 の炎上表記ゲートが persona_send にだけ入って bot_send を素通しした型と同じ)。
    実際にDiscordへHTTPを撃つのは2箇所しかない= bot_send.main() と persona_send.post()。
    そこ**だけ**から呼ぶ。dispatch は自分でPOSTせず persona_send を起動する=この1本に乗る。
  - **記録先を2つに割らない**(ORG-11)。書き先は local/llm/send_audit.jsonl だけ。
  - **送信を殺さない**(fail-open)。この中の例外は全部握り潰す。ログが取れないより
    便が出ないことの方が重い(最悪の事故は沈黙)。
  - **止めた便も残す**(event="blocked")。鳴ったことが分からないガードは、
    登録されていても動いているか分からない=本番の初発火が初検証になる。

1行の形(JSONL):
  ts / event(send|blocked) / via(bot_send|persona_send) / channel_id / channel / dept /
  persona / status(HTTPコード or "ERR:例外名" or 止めた理由) / chars / head(本文の頭120字) /
  msg_id / pid / ppid / origin(環境変数 GO5_SEND_ORIGIN=呼び出し元の名乗り・任意) / argv

★secretは載せない= トークンはファイルから読むのでargvにもヘッダにも出ない。
  本文の頭は載せる(C-013= ローカル内は共有・ネットへは出さない。local/ は .gitignore 済み)。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
# ★テストは GO5_LOCAL_DIR で書き先だけ差し替える(判定と分岐は本物のまま回す)。
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
AUDIT = os.path.join(LOCAL, "llm", "send_audit.jsonl")
ROTATE_BYTES = 8 * 1024 * 1024
HEAD_CHARS = 120


def _head(body):
    s = str(body or "").replace("\r", "").replace("\n", "⏎")
    return s[:HEAD_CHARS]


def _argv():
    """起動時の引数。長い本文をそのまま抱えないよう1項目200字で切る。"""
    out = []
    for a in list(sys.argv)[:24]:
        a = str(a)
        out.append(a if len(a) <= 200 else a[:200] + "…")
    return out


def _rotate(path):
    try:
        if os.path.getsize(path) > ROTATE_BYTES:
            os.replace(path, path + ".1")
    except Exception:
        pass


def record(via, body="", event="send", status="", channel_id="", channel="",
           dept="", persona="", msg_id="", path=None):
    """1行追記する。★戻り値は使わせない=呼び出し元の分岐に絶対に絡ませない。"""
    try:
        p = path or AUDIT
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _rotate(p)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": str(event or "send"),
            "via": str(via or ""),
            "channel_id": str(channel_id or ""),
            "channel": str(channel or ""),
            "dept": str(dept or ""),
            "persona": str(persona or ""),
            "status": str(status or ""),
            "chars": len(str(body or "")),
            "head": _head(body),
            "msg_id": str(msg_id or ""),
            "pid": os.getpid(),
            "ppid": (os.getppid() if hasattr(os, "getppid") else 0),
            "origin": os.environ.get("GO5_SEND_ORIGIN", ""),
            "argv": _argv(),
        }
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass                    # ★fail-open= ここで送信を殺さない
