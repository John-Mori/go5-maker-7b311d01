# -*- coding: utf-8 -*-
"""炎上巡回の便に「その投稿より後に入った物」が添わることの検査(2026-09-17 イージス研究室)。

発注= 研究室HQ `msg 1549946783634038815`(HQ-0272)。原文の芯=
  「巡回便の各項目に、その投稿のチャンネルID(cid)で `local/llm/change_log.jsonl` を引き、
    投稿時刻以降の行があれば添える」「dept では引けない」「0件なら何も添えない」
なぜ在るか= 09-17 09:30 の巡回便が配った炎上1件は**投稿の16分後に実機へ入り終わっていた**。
  便にその事実が無く、受け手が完了済みの仕事を「新設する」依頼票へ組み直す寸前まで行った。

★ソースの文字列一致では見ない(C-053)= **本物の item_block / dept_body を実行して**、
  組み上がった便の文字列を読む。偽物にするのは「どの台帳を引くか」(CHANGE_LOG)だけで、
  時刻の窓も cid の照合も件数の絞りも本物のまま通す。
★F群だけは**本番の change_log を読む**(実害が起きた現物で引けることの裏取り)。

  python scripts/discord/test_watch_changelog.py
  python scripts/discord/test_watch_changelog.py --mustfail   # 足す前の版(.bak)で赤を確認
"""
import importlib.util
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import reaction_watch as rw                      # noqa: E402

_fails = []
_ran = []          # ★合計は数えた実物で出す(手で TOTAL を書くと、項目を足した日にズレる)

# ★実害が起きた現物(HQが実測して便に書いた値)。F群で使う。
REAL_CID = "1549486988569354320"                 # 部屋『プロンプト変換と学習』
REAL_POSTED = "2026-09-16T05:03:58.000000+00:00"  # = JST 09-16 14:03:58(msg 1549647010305544213)


def ok(cond, name):
    print(("  OK  " if cond else "  NG  ") + name)
    _ran.append(name)
    if not cond:
        _fails.append(name)


def item(cid=REAL_CID, posted=REAL_POSTED, dept="local-lab"):
    """巡回が組み立てる項目そのものの形(collect() が作る dict と同じキー)。"""
    return {"key": f"{cid}:1549647010305544213:enjoh", "dept": dept,
            "channel": "プロンプト変換と学習", "channel_id": cid,
            "msg_id": "1549647010305544213",
            "emoji": "炎上(恒久) :enjoh:", "kind": "enjo", "meaning": "恒久対策しろ",
            "author": "chami_fusoh", "posted_at": posted,
            "content": "まって、そのあたりの構築をして。ろーかうrLLMの研究室なんだから",
            "by": ["chami_fusoh(1)"], "by_chami": True,
            "detected_at": "2026-09-17T09:30:00"}


def synth_log(rows):
    """合成の change_log を1本書いて、それを引く状態にする。"""
    p = os.path.join(tempfile.mkdtemp(prefix="chlog_"), "change_log.jsonl")
    with io.open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n")
    rw.CHANGE_LOG = p
    rw._changelog_cache = None                   # ★キャッシュを捨てる(1プロセス1回読みのため)
    return p


DONE_ROW = {
    "ts": "2026-09-16T14:35:36+09:00", "dept": "aegis-gl", "report_to": "hq",
    "何": f"部屋『プロンプト変換と学習』(cid {REAL_CID})を台帳と配線へ載せ、"
          "画像→WD14タグ列の橋渡しを入れた。",
    "なぜ": "Chami直令。", "触った": ["scripts/imagegen/wd14_tag.py(新)",
                                     "scripts/llm/local_responder.py"],
    "commit": ["49673dd", "03c6eff"]}

MARK = "この投稿より後に、この部屋で誰かが手を入れた記録"


def run():
    real_log = rw.CHANGE_LOG

    # --- A 誤発火しない(0件なら1文字も足さない= HQ指定) ------------------------------
    synth_log([])
    base = rw.item_block(item(), "123", 1)
    ok(MARK not in base, "A-1 台帳に一致が無ければ便は1文字も増えない")
    old = dict(DONE_ROW, ts="2026-09-16T13:59:00+09:00")       # 投稿の5分**前**
    synth_log([old])
    ok(MARK not in rw.item_block(item(), "123", 1),
       "A-2 投稿より前の行は拾わない(時刻の窓が本物に効いている)")
    synth_log([dict(DONE_ROW, 何="別の部屋(cid 1111111111111111111)の作業")])
    ok(MARK not in rw.item_block(item(), "123", 1),
       "A-3 cid が違う行は拾わない(部屋IDの照合が本物に効いている)")

    # --- B 実害の形をそのまま拾う ------------------------------------------------------
    synth_log([DONE_ROW])
    blk = rw.item_block(item(), "123", 1)
    ok(MARK in blk and "1件ある" in blk, "B-1 投稿の32分後に入った行を拾う")
    ok("aegis-gl" in blk,
       "B-2 ★dept が違っても拾う(項目= local-lab / 記録= aegis-gl。真因はここだった)")
    ok("wd14_tag.py" in blk and "49673dd" in blk,
       "B-3 触った物と commit が載る(受け手がその場で実物を見に行ける)")
    ok("新しく作り始める前に" in blk and "§4.55" in blk,
       "B-4 『新設する前に見ろ』と『入れた≠直った』が同じ枠に載る")
    ok(blk.startswith("1. 【") and "投稿の本文(原文のまま)" in blk and MARK in blk
       and blk.find("投稿の本文") < blk.find(MARK),
       "B-5 既存の項目を壊さず、本文の**後ろ**へ足している")

    # --- C 便を太らせない ---------------------------------------------------------------
    many = [dict(DONE_ROW, ts="2026-09-16T1%d:00:00+09:00" % i, commit="c%d" % i)
            for i in range(5, 10)]
    synth_log(many)
    blk = rw.item_block(item(), "123", 1)
    ok(blk.count("       commit= ") == rw.CHANGELOG_MAX,
       "C-1 何件あっても %d件まで(実測 %d件)" % (rw.CHANGELOG_MAX, blk.count("       commit= ")))
    ok("c9" in blk and "c5" not in blk, "C-2 新しい順に採る(古い行で枠を潰さない)")
    synth_log([dict(DONE_ROW, 何="あ" * 500)])
    blk = rw.item_block(item(), "123", 1)
    ok(max(len(x) for x in blk.splitlines()) < 400,
       "C-3 長い『何』は1行へ潰れる(台帳の全文を便へ流し込まない)")

    # --- D 出る面が2つとも(部門便・改善提案部門の一覧) --------------------------------
    synth_log([DONE_ROW])
    body = rw.dept_body("local-lab", [item()], "123")
    ok(MARK in body, "D-1 部門便(dept_body)に載る")
    kbody = rw.kaizen_body([item()], "123",
                           {"scanned": 1, "with_reaction": 1, "skipped_machine": 0,
                            "skipped_other": 0, "skipped_bot": 0, "truncated": []}, 24)
    ok(MARK in kbody, "D-2 改善提案部門の一覧(kaizen_body)にも載る= 足す点を数え漏らしていない")

    # --- E fail-open(見張りが巡回本体を巻き添えにしない) ------------------------------
    rw.CHANGE_LOG = os.path.join(tempfile.mkdtemp(prefix="none_"), "no_such.jsonl")
    rw._changelog_cache = None
    ok("投稿の本文" in rw.item_block(item(), "123", 1),
       "E-1 台帳が無い環境でも項目は組み上がる")
    synth_log(["{壊れた行", json.dumps(DONE_ROW, ensure_ascii=False), "  "])
    ok(MARK in rw.item_block(item(), "123", 1),
       "E-2 壊れた行が混ざっていても、その先の生きた行は拾える")
    synth_log([DONE_ROW])
    ok("投稿の本文" in rw.item_block(item(posted="いつか"), "123", 1)
       and MARK not in rw.item_block(item(posted="いつか"), "123", 1),
       "E-3 投稿時刻が読めない時は黙って添えない(窓が作れないのに拾わない)")
    ok("投稿の本文" in rw.item_block(item(cid=""), "123", 1),
       "E-4 cid が空でも項目は組み上がる")

    # --- F 本番の台帳で、実害が起きた現物を引けるか(★合成ではない) --------------------
    rw.CHANGE_LOG = real_log
    rw._changelog_cache = None
    hits = rw.changelog_after(REAL_CID, REAL_POSTED)
    ok(len(hits) >= 1, "F-1 本番の change_log から現物を引ける(実測 %d件)" % len(hits))
    txt = json.dumps(hits, ensure_ascii=False)
    ok("wd14" in txt or "タグ" in txt,
       "F-2 引けた行が、あの朝ローカル研究室が新設しかけた仕事そのものだ")
    ok(rw.changelog_after(REAL_CID, "2026-09-17T23:59:00+09:00") == [],
       "F-3 同じ cid でも未来の投稿には何も添わない(窓が本番データでも効く)")
    return not _fails


def mustfail():
    """足す前の版(.bak)で、この検査が本当に赤くなるかを同じ手番で示す。"""
    p = os.path.join(HERE, "reaction_watch.py.bak_20260917_changelog")
    if not os.path.exists(p):
        print("SKIP: 比較用の .bak が無い= " + p)
        return False
    tmp = os.path.join(tempfile.mkdtemp(prefix="rwold_"), "reaction_watch_old.py")
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(io.open(p, encoding="utf-8").read())
    spec = importlib.util.spec_from_file_location("reaction_watch_old", tmp)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    red = True
    for fn in ("done_since_block", "changelog_after", "load_change_log"):
        has = hasattr(old, fn)
        print(("  NG  " if has else "  OK  ") + ".bak に %s が無い= B/D/F が赤" % fn)
        red = red and not has
    synth_log([DONE_ROW])
    blk = old.item_block(item(), "123", 1)      # ★実行する(在る/無いの確認で済ませない)
    print(("  NG  " if MARK in blk else "  OK  ")
          + ".bak の項目には、投稿の後に入った物が1文字も載らない(実行で確認)")
    return red and MARK not in blk


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--mustfail" in sys.argv:
        sys.exit(0 if mustfail() else 1)
    good = run()
    print(("PASS 巡回便へ『既に入った物』を添える %d/%d" % (len(_ran) - len(_fails), len(_ran)))
          if good else ("FAIL %d件: %s" % (len(_fails), " / ".join(_fails))))
    sys.exit(0 if good else 1)
