#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clean_reader --refresh-all を定期実行で回すための薄い器(イージス研究室 2026-09-03)。

なぜ器を挟むか(直接 clean_reader.py を叩かない理由):
  タスクスケジューラは pythonw で起動する=標準出力がどこにも残らない。
  refresh_all() は1件ずつ例外を握って続行する設計なので、**全件失敗しても rc=0 で終わる**。
  そのまま登録すると「動いているのに何も更新していない」状態が誰にも見えない
  =mirror_to_discord が2週間静かに死んだのと同じ形になる。
  そこで、①毎回かならず1行書く脈ログを持たせ ②その脈を producers.json へ登録して
  absence_watchdog に age で見張らせる(C-042=読ませる経路まで同時に決める)。

書くもの= local/_work/clean_reader_refresh.log(1行1回・追記のみ)。
  ts / rc / elapsed / 更新・飛ばし・失敗・索引の件数 / 例外があればその型名。
  ★成功でも失敗でも必ず1行書く(書かない分岐を作ると脈が嘘をつく)。

本体(scripts/analysis/clean_reader.py)は分析部門の持ち物なので触っていない。
呼ぶだけ=refresh_all() を import して回す。

止め方: schtasks /Delete /TN go5_clean_reader_refresh /F
"""
import datetime
import io
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(ROOT, "local", "_work", "clean_reader_refresh.log")
sys.path.insert(0, os.path.join(ROOT, "scripts", "analysis"))


def _now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(
        timespec="seconds")


def main():
    t0 = time.time()
    rc, note, counts = 0, "", ""
    # refresh_all() は print で結果を出す=標準出力を捕まえて件数だけ拾う
    buf = io.StringIO()
    stdout, stderr = sys.stdout, sys.stderr
    # ★pythonw 起動では sys.stderr が None になる。clean_reader は証明書切れサイトの
    #   フォールバック時に sys.stderr.write() で警告を出すので、そのまま回すと
    #   AttributeError が refresh_all の per-URL の except に食われ「取得失敗」に化ける
    #   (実測 2026-09-03 00:53: 対話実行=失敗0本 / タスク実行=失敗1本 vippers.jp)。
    #   捨て先を必ず与える=器の側で塞ぐ(本体は分析部門の持ち物なので触らない)。
    ebuf = io.StringIO()
    try:
        import clean_reader
        sys.stdout = buf
        sys.stderr = ebuf
        clean_reader.refresh_all()
    except Exception as e:  # noqa: BLE001  器は落ちない(落ちると脈も残らない)
        rc = 1
        note = type(e).__name__ + ": " + str(e)[:120]
    finally:
        sys.stdout, sys.stderr = stdout, stderr
    out = buf.getvalue()
    m = re.search(r"完了: 更新(\d+)本 / 飛ばし(\d+)本 / 失敗(\d+)本 / 索引(\d+)本", out)
    if m:
        counts = "更新%s/飛ばし%s/失敗%s/索引%s" % m.groups()
    else:
        counts = "完了行なし"
        if rc == 0:
            rc = 2
    line = "%s rc=%d elapsed=%.1fs %s%s\n" % (
        _now(), rc, time.time() - t0, counts, (" " + note) if note else "")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
