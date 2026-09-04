#!/usr/bin/env python3
"""C-015の締めの1行が**裁定カタログから**来ていることを、実行で確かめる。

なぜ在るか(実測・2026-09-04):
  `_verdict_block()` は発注先の表を毎便・全27室へ配る。表は `|` 行をカタログから拾っていたが、
  **締めの1行だけコード側にハードコード**されていた(旧 L1696)。
  そのため部門名の改称→同日撤回(改修α→構築α→改修α)で、カタログを戻しても
  **封筒には旧字面が出続けた**。正本が2つあり、下流のこちらが勝っていた(共通規律§4)。
  検出= ルカ・モドリッチ(ad研究室)便 msg `1545250032524075030`。

★この試験の作法(共通規律§3): **ソースの文字列一致は検査ではない。**
  台帳(裁定カタログ)そのものを差し替えて `_verdict_block()` を実行で通し、
  出てきた封筒の字が台帳に追随するかを見る。
★must-fail(C-053): 壊し方は「動く別の実装」= **旧実装(ハードコード)を再現**して、
  同じ検査が赤になることを確かめる。赤が出せない検査は何も守っていない。

    python scripts/llm/test_c015_tail_from_catalog.py
"""
import os
import sys
import time
import tempfile
import contextlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)

import dept_daemon as dd                                     # noqa: E402

REAL_MD = dd._VERDICT_MD
FAIL = []


def ok(cond, label, got=None):
    print(("  OK   " if cond else "  FAIL ") + label + ("" if cond else f"\n         got: {got!r}"))
    if not cond:
        FAIL.append(label)


@contextlib.contextmanager
def catalog(text):
    """裁定カタログを差し替えて封筒を作らせる。mtimeキャッシュも落とす(=都度読みを実際に通す)。"""
    old_md, old_cache = dd._VERDICT_MD, dict(dd._verdict_cache)
    fd, path = tempfile.mkstemp(suffix=".md", prefix="c015_")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.utime(path, (time.time(), time.time() + len(text)))   # mtime衝突よけ
    dd._VERDICT_MD = path
    dd._verdict_cache["mtime"] = None
    try:
        yield
    finally:
        dd._VERDICT_MD = old_md
        dd._verdict_cache.clear()
        dd._verdict_cache.update(old_cache)
        dd._verdict_cache["mtime"] = None
        os.remove(path)


def tail_now():
    """いま封筒に載る発注先ブロックの、表より後ろ(=締めの但し書き)だけ返す。"""
    _, table_txt, _ = dd.verdict_parts()
    lines = table_txt.split("\n")
    last_row = max((i for i, ln in enumerate(lines) if ln.startswith("|")), default=-1)
    return "\n".join(lines[last_row + 1:])


def hardcoded_tail(_text):
    """★旧実装の再現(must-fail用)= カタログを一度も見ずに固定の字を返していた。"""
    return "★改修α(system-engineer)は**5秒動画メーカー専用**だ。組織の仕組み・人格・常駐構成を持ち込むな。"


CAT = """### C-014 まえの裁定
なにか

### C-015 発注先(2026-07-26 Chami)

Chami原文= 前置き。ここは封筒に入れない。

| 改修の中身 | 出す先 |
|---|---|
| **本体** | `system-engineer` |
| 判断がつかない時 | HQが決める |

{prose}

★**2026-08-23 の一時停止線は撤回済。**これは経緯の記録=封筒に毎便載せる物ではない。

### C-016 つぎの裁定
なにか
"""
STANDING = "★改修α(system-engineer)は**5秒動画メーカー専用**だ。"


def main():
    print("=== C-015 締めの但し書きは裁定カタログから来るか ===\n")

    print("[0] 実物のカタログ= 締めが本文にあり、ハードコードでない")
    real = tail_now()
    with open(REAL_MD, encoding="utf-8") as f:
        raw = f.read()
    ok(real.strip() != "" and real.strip() in raw,
       "封筒の締めが 裁定カタログ.md に一字一句そのまま在る", real[-90:])
    ok("★C-015の但し書きが拾えていない" not in real, "警告文ではなく本文が出ている", real[-90:])

    print("\n[1] 台帳を1文字変えたら封筒が追随する(モドリッチ指定の確認法)")
    with catalog(CAT.format(prose=STANDING)):
        before = tail_now()
    with catalog(CAT.format(prose=STANDING + "ZZZ")):
        after = tail_now()
    ok(before.strip() == STANDING, "差し替えた台帳の字がそのまま出る", before)
    ok(after.strip() == STANDING + "ZZZ", "1文字足したら封筒も1文字増えた", after)
    ok(before != after, "台帳を変えたのに封筒が変わらない、が起きていない", after)

    print("\n[2] must-fail= 旧実装(ハードコード)は同じ検査で赤になる(C-053)")
    old_before = hardcoded_tail(CAT.format(prose=STANDING))
    old_after = hardcoded_tail(CAT.format(prose=STANDING + "ZZZ"))
    ok(old_before == old_after, "旧実装は台帳を変えても1バイトも動かない(=事故の再現)", old_after)
    ok(old_after != after, "この検査は新旧を区別できている(赤を出せる)", old_after)

    print("\n[3] 名前が動いた時に追随する(改修α→構築α→改修α の往復を台帳だけで再現)")
    names = ["★改修αは**5秒動画メーカー専用**だ。",
             "★構築αは**5秒動画メーカー専用**だ。",
             "★改修αは**5秒動画メーカー専用**だ。"]
    got = []
    for n in names:
        with catalog(CAT.format(prose=n)):
            got.append(tail_now().strip())
    ok(got == names, "3回とも台帳どおり(往復して戻る)", got)
    ok(got[1] != got[2], "撤回が封筒に効いている", got)

    print("\n[4] 経緯の記録(★**日付= …)は封筒に入れない")
    with catalog(CAT.format(prose=STANDING)):
        t = tail_now()
    ok("2026-08-23" not in t, "日付始まりの★行を拾っていない", t)
    ok(t.count("\n") <= 8, "封筒が段落1つ分に収まっている", t)

    print("\n[5] 但し書きが消えても黙って消えない(=『直したつもり』の再発防止)")
    with catalog(CAT.format(prose="ふつうの散文。★で始まらない。")):
        t = tail_now()
    ok("拾えていない" in t, "拾えない時は警報が封筒に出る", t)

    print("\n[6] 表そのものが無い体裁なら何も足さない(fail-open)")
    with catalog("### C-015 発注先\n\n" + STANDING + "\n\n### C-016 つぎ\n"):
        _, table_txt, _ = dd.verdict_parts()
    ok(table_txt == "", "表が無ければ発注先ブロックごと出さない", table_txt)

    print("\n[7] 継続行のある段落が千切れない(行単位で拾っていない)")
    para = ("★**2026-07-27 実例**= 教育部門が\n名指し配線を回した。Chami原文=「部門違い」。\n" + STANDING)
    with catalog(CAT.format(prose=para)):
        t = tail_now().strip()
    ok(t == para, "段落ごと拾えている(文が途中で切れていない)", t)

    print("\n" + ("=== 全て通過 ===" if not FAIL else f"=== 失敗 {len(FAIL)}件: {FAIL} ==="))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
