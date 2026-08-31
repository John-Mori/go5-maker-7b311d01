#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""meta_strip(送信直前ゲートE= 内部の手続きメタの剥ぎ)の回帰テスト。

なぜ要るか(2026-08-15 イージス研究室):
  「ソースの文字列一致は検査ではなく保険だ。入力を差し替えて経路を実行で通せ」(HQ裁定2026-08-14)。
  このゲートは**本文を削る**方向に働く唯一のゲートなので、
  陽性(実物の漏れ)と同じ数だけ**陰性(剥いではいけない文)**を固定しておく。
  ★陽性の入力は実物のコピー= local/llm/recent_copy-director.jsonl の
    msg_id=DISPATCH-copy-director-1786794044539 の reply(Chami指示③の壊れた実物)。

実行= python scripts/llm/test_meta_strip.py (全PASSで exit 0)
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import meta_strip                                          # noqa: E402

_PASS = 0
_FAIL = 0

# ★実物(壊れた本文そのもの)。1行=本文の全部だった。
LEAK = ("No response requested — this is a backchannel HQ→部門 answer to my own §3.9 上申, "
        "with no Chami手番 and nothing left on my side (winning-patterns.md 4行目の "
        "`★★C-047` ポインタはアロンソコーチの実測どおりコア条文と一致・変更不要)。"
        "§4.7に従い部屋への「了解」返信はしない。")


def _check(name, cond):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("PASS %s" % name)
    else:
        _FAIL += 1
        print("FAIL %s" % name)


def main():
    # --- 陽性: 剥ぐべきもの ------------------------------------------------
    body, hits = meta_strip.strip_meta_tail(LEAK)
    _check("実物の漏れが剥がれる", body == "" and len(hits) == 1)
    _check("剥いだ理由が記録に残る", hits and hits[0]["marker"] == "no_response_requested")

    real = "怜、②受け取った。実物を見て測った。縛り5つは満たしてる。"
    body, hits = meta_strip.strip_meta_tail(real + "\n\n" + LEAK)
    _check("本文の後ろに付いたメタだけ剥ぐ", body == real and len(hits) == 1)

    body, _ = meta_strip.strip_meta_tail(real + "\n\nNo further action required.")
    _check("no further action も剥ぐ", body == real)

    body, hits = meta_strip.strip_meta_tail(real + "\n\n**No response requested.**\n\n")
    _check("飾り付き・末尾空行つきでも剥ぐ", body == real and len(hits) == 1)

    # --- 陰性: 剥いではいけないもの(誤爆=本文欠け=取り返しがつかない) ------
    same = "了解した。手は空いてる。"
    _check("マーカーが無ければ1文字も変えない", meta_strip.strip_meta_tail(same) == (same, []))

    quoted = ('デブライネ、③を基盤へ回す。漏れた原文=\n'
              '「No response requested — this is a backchannel …」\n'
              'これは§4.8違反が出力へ抜けた形だ。')
    _check("引用符の中のマーカーは剥がない", meta_strip.strip_meta_tail(quoted)[0] == quoted)

    tail_quoted = real + '\n「No response requested」を高確度マーカーにする。'
    _check("末尾でも引用なら剥がない", meta_strip.strip_meta_tail(tail_quoted)[0] == tail_quoted)

    bq = real + "\n> No response requested — this is a backchannel"
    _check("引用ブロック(>)は剥がない", meta_strip.strip_meta_tail(bq)[0] == bq)

    fenced = real + "\n```\nNo response requested\n```"
    _check("コードブロックの中は剥がない", meta_strip.strip_meta_tail(fenced)[0] == fenced)

    mid = "No response requested\n" + real
    _check("末尾でないメタは剥がない(真ん中は触らない)",
           meta_strip.strip_meta_tail(mid)[0] == mid)

    jp = real + "\n§4.7に従い、部屋への返信は人事部門へ回す。"
    _check("日本語の規律語だけでは剥がない", meta_strip.strip_meta_tail(jp)[0] == jp)

    # --- fail-open: どんな入力でも例外を投げない --------------------------
    ok = True
    for bad in (None, 123, {"a": 1}, [], "", "   \n  "):
        try:
            meta_strip.strip_meta_tail(bad)
        except Exception:                                  # noqa: BLE001
            ok = False
    _check("壊れた入力でも例外を投げない", ok)
    _check("Noneは空を返す(送信側で失敗扱いになる)",
           meta_strip.strip_meta_tail(None)[0] in ("", None))

    _narration_tests()

    print("\n%d PASS / %d FAIL" % (_PASS, _FAIL))
    return 1 if _FAIL else 0


# ============================================================================
# 実況漏れ検知(2026-09-01・イージス研究室)
# ----------------------------------------------------------------------------
# 入力は全部**実物のコピー**(HQ hr/memory から引いた)。作り話の文は1つも使わない。
#   陽性= shorts-analyst.jsonl 2026-09-01T03:00:09 / msg 1544041139580178502
#   陰性= 同じ機械語を**本人の声で**語っている実便(トトリの受け入れ条件2=07-29型)
# ============================================================================

# 検体そのもの(本文の全部)。
SPEC = "リトライ中はPythonのstdoutバッファで出力が末尾までflushされない。完了通知を待つ。"

# 陰性の実物① platform-se 2026-07-29T16:22:05(「リトライ」を含むが声が在る)
VOICED_1 = ("できました。改修部門αが仕組みを建てて反映済み、私も実物を確認しました——"
            "`scripts/comp_frames.py`(4.5秒付近を1枚だけ抜く)とGASの口。リトライも入れてある。")
# 陰性の実物② hr-room 2026-07-29T04:03:01(「msg=」を含むが声が在る)
VOICED_2 = ("ちゃみ、やっぱりな——「俺」がまだ出るってことは、"
            "hrが直した正本が五月の出力を作ってるセッションに届いてねえ。\n\n"
            "回したぜ。platform-se(一ノ瀬怜)行きだが、飛び級できないルールに引っかかったんで"
            "部門長の aegis-gl 経由で投函した(msg=DISPATCH-aegis-gl-...)。")
# 陰性の実物③ ai-office 2026-07-22T16:56:54(行頭の呼びかけ「アロンソ、受けた。」)
VOICED_3 = ("アロンソ、受けた。\n\n■ やった作業(ai-office)\n\n"
            "build_office.py にキューDB可視化(inbox.db / read-only)を追加した。"
            "pending/dead の合計 + 部門別内訳を常時表示。")


def _narration_tests():
    # --- 陽性: 実物の検体が鳴る ------------------------------------------
    hit = meta_strip.detect_narration_leak(SPEC)
    _check("実物の検体(09-01 shorts-analyst)が鳴る", bool(hit))
    _check("当たった機械語が記録に残る",
           bool(hit) and set(hit["machine"]) >= {"flush", "stdout", "リトライ", "完了通知"})

    # --- 陰性: 鳴ってはいけない実物 --------------------------------------
    for name, txt in (("① 声が在る便(私・ました)", VOICED_1),
                      ("② 声が在る便(ちゃみ・俺)", VOICED_2),
                      ("③ 行頭の呼びかけが在る便", VOICED_3)):
        _check("機械語が在っても素通し %s" % name,
               meta_strip.detect_narration_leak(txt) is None)

    _check("名乗り[名前]が在れば素通し",
           meta_strip.detect_narration_leak("[アメス]\n" + SPEC) is None)
    _check("コードブロックの中の機械語では鳴らない",
           meta_strip.detect_narration_leak("結果。\n```\nmsg=1 pending\n```") is None)
    _check("機械語が無ければ鳴らない",
           meta_strip.detect_narration_leak("了解した。手は空いてる。") is None)

    ok = True
    for bad in (None, 123, {"a": 1}, [], "", "   \n  "):
        try:
            meta_strip.detect_narration_leak(bad)
        except Exception:                                  # noqa: BLE001
            ok = False
    _check("壊れた入力でも例外を投げない", ok)

    # --- 本物の分岐を**実行で**通す(外向きの手=再生成だけを差し替える) ----
    import dept_daemon as dd                               # noqa: E402

    calls = []

    def regen_ok():
        calls.append("ok")
        return "[アメス]\nリトライで転んでたのを直したわ。完了通知はこっちで待つから、任せて。"

    def regen_still_broken():
        calls.append("ng")
        return "バッチはpendingのまま。回送済。"

    out, info = dd.narration_gate(SPEC, regen=regen_ok, strip_marker=None)
    _check("再生成で声が戻れば、そちらへ差し替える",
           info["hit1"] and info["regenerated"] and not info["warned"]
           and "リトライで転んでたのを直した" in out)

    out, info = dd.narration_gate(SPEC, regen=regen_still_broken, strip_marker=None)
    _check("2回目も漏れていたら元文に警告を付けて**送る**(沈黙にしない)",
           info["hit1"] and info["hit2"] and info["warned"]
           and out.startswith(SPEC) and dd.NARRATION_WARN in out)

    out, info = dd.narration_gate(SPEC, regen=None, strip_marker=None)
    _check("再生成の手が無い経路でも警告付きで送る",
           info["warned"] and out.startswith(SPEC) and dd.NARRATION_WARN in out)

    out, info = dd.narration_gate(VOICED_2, regen=regen_ok, strip_marker=None)
    _check("正常便では再生成を1回も呼ばない(トークンを使わない)",
           out == VOICED_2 and not info["hit1"] and calls.count("ok") == 1)

    def regen_boom():
        raise RuntimeError("生成が落ちた")

    out, info = dd.narration_gate(SPEC, regen=regen_boom, strip_marker=None)
    _check("再生成が例外でも送信は止めない(fail-open)",
           out.startswith(SPEC) and dd.NARRATION_WARN in out)

    # --- must-fail(C-053): **動く別実装**を当てて、壊れる側を1つ固定する ---
    #   別実装= トトリの素案そのまま(条件①②だけ・③「声の不在」を見ない)。
    #   これは検体をちゃんと検知する=「動く」。だが実便を巻き込む、という差だけを出す。
    def alt_detect_no_voice_condition(text):
        s = str(text or "")
        if meta_strip._TAG_RE.search(s):
            return None
        machine = [w for w in meta_strip._MACHINE_WORDS if w in s]
        return {"machine": machine, "reason": "alt"} if machine else None

    _check("[must-fail] 別実装も検体は検知できる(=動く実装である)",
           bool(alt_detect_no_voice_condition(SPEC)))
    broken = [n for n, t in (("①", VOICED_1), ("②", VOICED_2), ("③", VOICED_3))
              if alt_detect_no_voice_condition(t) is not None]
    _check("[must-fail] ③(声の不在)を外すと正常便3件を突き返す=この条件が効いている",
           len(broken) == 3)


if __name__ == "__main__":
    sys.exit(main())
