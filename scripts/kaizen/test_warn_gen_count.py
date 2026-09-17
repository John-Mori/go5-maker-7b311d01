# -*- coding: utf-8 -*-
"""warn_gen_count.py の受け入れ試験。

なぜ要るか= Chami依頼2便の肝を守る。
  ① 2026-09-17「⚠️ のやつちゃんと数えたりして」+「0の日は何も言わなくていい」。
  ② 2026-09-17「実際は問題ない時もあるから本当に問題があるのかどうか確かめてね」。
     → 生の⚠️は偽陽性を含む。数える前に「機械が実際に付けたフラグか」「引用でなく
       本物の混入か」を確かめる。このテストはその**取りこぼし/水増しの両方**を縛る。
このテストは実データに依存させない= 一時ファイルに既知の行を書いて数える。

手で走らせる= PYTHONIOENCODING=utf-8 python scripts/kaizen/test_warn_gen_count.py
"""
import io
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warn_gen_count as W  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  NG: %s" % name)


def _row(ts, dept, body):
    return json.dumps({"ts": ts, "dept": dept, "body": body, "event": "send"},
                      ensure_ascii=False)


def _flag(base, kind):
    """daemon の付け方(本体 + '\\n\\n' + 警告文)を模して genuine なフラグ便を作る。"""
    return base + "\n\n" + W.FLAG_SENTENCES[kind]


def _with_audit(rows, fn):
    """AUDIT を一時ファイルへ差し替えて fn() を呼ぶ。"""
    old = W.AUDIT
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        with io.open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(r + "\n")
        W.AUDIT = path
        return fn()
    finally:
        W.AUDIT = old
        os.remove(path)


def main():
    now = time.mktime((2026, 9, 17, 12, 0, 0, 0, 0, -1))
    ts_in = "2026-09-17T09:00:00"      # 窓内(直近24h)
    ts_old = "2026-08-01T09:00:00"     # 窓外(古い)

    # --- 本物の混入(引用/コード外に混入字が地の文で残る)は「本物疑い」へ ---
    real_rows = [
        _row(ts_in, "system-engineer", _flag("DevTools无くて困る話。", "簡体字混入")),
        _row(ts_in, "aegis-gl", _flag("무理せずに詰める。", "ハングル混入")),
        _row(ts_in, "llm-edu", _flag("Qwen3-8Bは処理中。結果待ち。", "名乗り無し")),
    ]
    r = _with_audit(real_rows, lambda: W.collect(now, 24.0))
    check("genuine=3", r["genuine"] == 3)
    check("本物疑い=2(无/무)", r["real"] == 2)
    check("実況=1(名乗り無し)", r["narration"] == 1)
    check("引用=0", r["quoted"] == 0)
    check("本物の部屋 system-engineer=1", r["real_by_dept"].get("system-engineer") == 1)

    # --- ★偽陽性(A)引用: 字例を「」で囲った/不具合を論じた便は「引用」へ落とす ---
    fp_quote = _flag("ここでは「无」と書かれていた例。", "簡体字混入")   # 引用符の中だけ
    fp_meta = _flag("簡体字の話。无 という字が例に挙がった。", "簡体字混入")  # 語彙で論じている
    r2 = _with_audit([_row(ts_in, "kaizen-analyst", fp_quote),
                      _row(ts_in, "qa-reviewer", fp_meta)],
                     lambda: W.collect(now, 24.0))
    check("引用符の中は本物にしない", r2["real"] == 0)
    check("論じた便2つは引用=2", r2["quoted"] == 2)
    check("genuine=2(フラグ自体は本物)", r2["genuine"] == 2)

    # --- ★偽陽性(B)非フラグ: 末尾完全一致でない便は「機械フラグ」に数えない ---
    #   B-1) ⚠️ を本文の途中で語っただけ(当室が「数える仕組みを入れた」と報告した便=#20型)
    mid = ("ちゃみくん、⚠️(自動)生成不良を数える仕組みを入れました。\n\n"
           "これは押しスタンプとは別物です。よろしくね。")
    #   B-2) 人格が語尾を変えて書いた警告文(「要確認なのよ」=#14型)は正本と不一致
    noyo = "本体。\n\n⚠️(自動)生成不良: 日本の漢字でない簡体字の混入を検知。要確認なのよ。"
    r3 = _with_audit([_row(ts_in, "kaizen-analyst", mid),
                      _row(ts_in, "hq", noyo)],
                     lambda: W.collect(now, 24.0))
    check("途中言及は機械フラグでない", r3["genuine"] == 0)
    check("語尾違いの警告文も機械フラグでない", r3["real"] == 0 and r3["quoted"] == 0)

    # --- 窓外は数えない ---
    r4 = _with_audit([_row(ts_old, "system-engineer", _flag("DevTools无く。", "簡体字混入"))],
                     lambda: W.collect(now, 24.0))
    check("窓外は genuine=0", r4["genuine"] == 0)

    # --- ⚠️印が全く無い普通の本文は拾わない ---
    r5 = _with_audit([_row(ts_in, "hq", "普通の返信本文。何の問題もない。")],
                     lambda: W.collect(now, 24.0))
    check("印無しは genuine=0", r5["genuine"] == 0)

    # --- ★render: 本物疑い+実況が0(引用しか無い)日は空文字=黙る ---
    #   Chami「0の日は何も言わない」+「実際は問題ない時もある」の両立。
    blk_q = _with_audit([_row(ts_in, "kaizen-analyst", fp_quote)],
                        lambda: W.render(now, 24.0))
    check("引用だけの日は render 空", blk_q == "")

    # --- render: 完全に0件でも空文字 ---
    blk0 = _with_audit([], lambda: W.render(now, 24.0))
    check("0件で render は空", blk0 == "")

    # --- render: 本物疑いが在れば見出しと件数を出す ---
    blk1 = _with_audit(real_rows, lambda: W.render(now, 24.0))
    check("本物疑いが在れば見出しが出る", blk1.startswith("◆⚠️(自動)生成不良"))
    check("本物疑いの件数が乗る", "本物疑い= 2件" in blk1)
    check("引用を外した旨も出す", "引用・誤検知" in blk1)

    n = PASS + FAIL
    print("=== %d/%d %s ===" % (PASS, n, "PASS" if FAIL == 0 else "FAIL"))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
