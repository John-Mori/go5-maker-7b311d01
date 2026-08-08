# -*- coding: utf-8 -*-
"""fail-open(relay無人時に精霊が1本返す)を**安全に1回通す**検証器。

なぜ要るか= fail-open は `_relay_ok=False`(部屋の永続セッションが返せない)でしか発火しない。
  自然発火を待つと、生きた部屋が事故を起こすまで永久に確認できない
  (実測= 2026-08-02 06:53 armed → 2026-08-08 まで6日間、発火ログ0件)。
  確認のために生きた消費者を殺すのは**事故の自作**で §3「本番の部屋でテストしない」に反する。
  → `dept_daemon.failopen_inject` の注入点を使い、**消費者に一切触れずに**失敗の枝だけ通す。

安全性(この検証器が本番を汚さない理由)=
  1 便に `test: true` を付ける= **Discordへの送信だけが止まる**(dept_daemon 行4552)。部屋は汚れない。
  2 `channel` を空にする= 既読リアクションのsubprocessも走らない。
  3 `relay_fail_inject: true` が無ければ注入は効かない=本番の便は1バイトも変わらない。
  4 キューを経由しない= 走っている常駐と便を取り合わない(二重処理・レースが起きない)。
  ★fail-open 自体がOFF(フラグファイルが無い/enable=false)なら**何も起きない**
    =この検証器は kill-switch を迂回しない。

使い方=
  python scripts/llm/verify_failopen.py [--dept system-engineer-b]
確認する所= local/llm/dept_daemon_<dept>.log に次の3行が並ぶこと。
  ★fail-open検証: relay不成立を注入した / ★fail-open発火: relay不成立→精霊が一次応答 / [test] 送信を抑止
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_daemon as d          # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="fail-open を安全に1回通す(検証用)")
    # ★既定は 2026-08-02 に armed したカナリア部門。owner室(hq/aegis-gl/research-room/
    #   keiei-kikaku)は §3.1 の除外なので指定しても None で素通りする(仕様どおり)。
    ap.add_argument("--dept", default="system-engineer-b")
    a = ap.parse_args()

    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dept": a.dept,
        "channel": "",                      # ★空= 既読リアクションを打たない
        "author": "イージス研究室(fail-open検証)",
        "content": ("これは fail-open の検証便です。relayが返せなかった時に"
                    "精霊が一次応答を出せるかを確かめています。短く一言返してください。"),
        "msg_id": "FOTEST-%d" % int(time.time()),
        "via": "verify_failopen",
        "test": True,                       # ★門1= 送信を止める
        "relay_fail_inject": True,          # ★門2= relay不成立を注入する
    }

    if not d.failopen_inject(rec):
        print("注入が効かない=門の条件を満たしていない。中止する。")
        return 2
    if not d.failopen_enabled(a.dept, rec):
        print("fail-open が無効(kill-switch/フラグファイル)。"
              "local/queue/relay_failopen.flag を確認しろ。中止する。")
        return 3

    print("注入して1回通す: dept=%s msg=%s" % (a.dept, rec["msg_id"]))
    dm = d.Daemon(a.dept)
    dm.handle(rec, json.dumps(rec, ensure_ascii=False))
    print("通した。ログを見ろ= local/llm/dept_daemon_%s.log" % a.dept)
    return 0


if __name__ == "__main__":
    sys.exit(main())
