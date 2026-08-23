# -*- coding: utf-8 -*-
"""常駐のコード版の遅れを**時系列で**記録するサンプラ(観測だけ・警報は出さない)。

なぜ要るか(2026-08-23 イージス研究室):
  研究室HQが `relay_health.py` 検査14 を入れて「2時間を超えて遅れたままの部門」を★にした。
  だが検査14は**今この瞬間**しか出さないうえ、`relay_health.py` を定期実行している登録タスクは
  **0本**(全タスクのアクションを走査して確認)。つまり誰かが手で叩いた時だけ鳴る計器だ。
  そしてHQは1回の観測(08:5x 遅れ4)から「常時2〜5室が遅れている定常状態」と読み、
  こちらが09:3xに測ると **32/32 同版・遅れ0** だった。**どちらも一度の観測**で、C-041 そのものだ。

  だから警報を足す前に、まず「2時間超が実在するか」を測る。これはその計器。
  ★閾値の判定はここに書かない(判定の正本は検査14=`check_codever` の1つだけにする)。
  ここがやるのは**観測の記録**だけ= 後から何回でも数え直せる形で残す。

出力: local/_state/codever_history.jsonl へ1行追記(追記のみ・既存行を消さない)。
  {"ts", "cur", "same", "total", "newest", "behind":[{"slug","ver","min"}]}
"""
import io
import json
import os
import time
from datetime import datetime

PJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CODEVER_DIR = os.path.join(PJ, "local", "_daemon_codever")
OUT = os.path.join(PJ, "local", "_state", "codever_history.jsonl")


def sample():
    """今の版分布を1件のdictで返す。読めない時は None(黙って落ちる方へ倒さない)。"""
    if not os.path.isdir(CODEVER_DIR):
        return None
    rows = []
    for fn in sorted(os.listdir(CODEVER_DIR)):
        if not (fn.startswith("dept_") and fn.endswith(".txt")):
            continue
        path = os.path.join(CODEVER_DIR, fn)
        try:
            with io.open(path, encoding="utf-8", errors="replace") as fh:
                head = fh.read().strip()
            rows.append((fn[5:-4], head.split("\t")[0], os.path.getmtime(path)))
        except OSError:
            continue
    if not rows:
        return None
    now = time.time()
    newest = max(r[2] for r in rows)
    cur = [r[1] for r in rows if r[2] == newest][0]
    behind = [r for r in rows if r[1] != cur]
    return {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "cur": cur,
        "same": len(rows) - len(behind),
        "total": len(rows),
        "newest": datetime.fromtimestamp(newest).strftime("%H:%M"),
        "behind": [{"slug": s, "ver": v, "min": int((now - m) // 60)}
                   for s, v, m in sorted(behind, key=lambda r: r[2])],
    }


def main():
    rec = sample()
    if rec is None:
        print("確認できず: %s が読めない" % CODEVER_DIR)
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # C-048= 書いた後の実物を読み直した値で言う
    with io.open(OUT, encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip()]
    last = json.loads(lines[-1])
    print("記録 %s  現行 %s = %d/%d  遅れ%d件%s  (累計%d行)"
          % (last["ts"], last["cur"], last["same"], last["total"], len(last["behind"]),
             "" if not last["behind"] else " 最古 %d分" % max(b["min"] for b in last["behind"]),
             len(lines)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
