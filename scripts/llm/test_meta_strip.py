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
    _orphan_fence_tests()
    _memo_tests()

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


# ============================================================================
# 孤立コードフェンス切り(2026-09-17・プラットフォームSE)
# ----------------------------------------------------------------------------
# 陽性の入力は**実物のコピー**= imagegen-fusoh-v0/カスミ msg 1549651824397778945。
#   本文の末尾に、対になる開始フェンスの無い ``` が1行だけ残っていた。
# ============================================================================

# 検体の形(本文の後に開始フェンスの無い ``` が1行)。
ORPHAN = ("そのとおりだ、ちゃみくん。この部屋は fusoh_v0 のLoRAを0.8で抱えて描く作りだ。\n"
          "だから注文に「手描き」と書き添える必要はない。放っておいても画風は乗る。\n"
          "```")
ORPHAN_BODY = ("そのとおりだ、ちゃみくん。この部屋は fusoh_v0 のLoRAを0.8で抱えて描く作りだ。\n"
               "だから注文に「手描き」と書き添える必要はない。放っておいても画風は乗る。")


def _orphan_fence_tests():
    # --- 陽性: 孤立した末尾フェンスを剥ぐ --------------------------------
    body, hits = meta_strip.strip_orphan_fence(ORPHAN)
    _check("実物の孤立フェンスが剥がれる", body == ORPHAN_BODY and len(hits) == 1)
    _check("剥いだ理由が記録に残る", hits and hits[0]["marker"] == "orphan_fence")

    b, h = meta_strip.strip_orphan_fence(ORPHAN_BODY + "\n```\n\n")
    _check("末尾に空行が続いても剥ぐ", b == ORPHAN_BODY and len(h) == 1)

    b, h = meta_strip.strip_orphan_fence(ORPHAN_BODY + "\n```python")
    _check("裸の開始フェンス(```lang だけ)も孤立なら剥ぐ", b == ORPHAN_BODY and len(h) == 1)

    # --- 陰性: 剥いではいけないもの(誤爆=本文欠け) ---------------------
    balanced = "結果はこうだ。\n```\ncode line\n```"
    _check("均衡したコードブロック(偶数個)は1文字も変えない",
           meta_strip.strip_orphan_fence(balanced) == (balanced, []))

    open_with_body = "手順を貼る。\n```\nstill inside the block"
    _check("フェンスの後ろに本文が続くなら切らない(中身を消さない)",
           meta_strip.strip_orphan_fence(open_with_body)[0] == open_with_body)

    no_fence = "了解した。手は空いてる。```を含まない本文。"
    _check("フェンス行が無ければ1文字も変えない",
           meta_strip.strip_orphan_fence(no_fence) == (no_fence, []))

    two_blocks = "A\n```\nx\n```\nB\n```\ny\n```"        # フェンス4個=均衡
    _check("複数の均衡ブロックは触らない",
           meta_strip.strip_orphan_fence(two_blocks) == (two_blocks, []))

    tail_content = "```\ncode\n```\n続きの本文"           # 末尾のフェンスの後ろに本文
    _check("均衡+末尾に本文がある形は触らない",
           meta_strip.strip_orphan_fence(tail_content) == (tail_content, []))

    # --- fail-open: どんな入力でも例外を投げない --------------------------
    ok = True
    for bad in (None, 123, {"a": 1}, [], "", "   \n  "):
        try:
            meta_strip.strip_orphan_fence(bad)
        except Exception:                                  # noqa: BLE001
            ok = False
    _check("壊れた入力でも例外を投げない", ok)

    # --- must-fail(C-053): **動く別実装**を当てて、壊れる側を1つ固定する ---
    #   別実装= 均衡(奇数/偶数)を見ずに「末尾が裸フェンスなら常に剥ぐ」。
    #   これは検体をちゃんと剥ぐ=「動く」。だが**均衡したコードブロック**の閉じフェンスまで
    #   剥いでしまう、という差だけを出す(=奇数個ガードが効いている証拠)。
    def alt_strip_no_balance_check(text):
        s = str(text or "")
        lines = s.splitlines()
        if lines and meta_strip._BARE_FENCE_RE.match(lines[-1]):
            return "\n".join(lines[:-1]).rstrip(), [{"marker": "alt", "line": lines[-1]}]
        return s, []

    _check("[must-fail] 別実装も検体は剥げる(=動く実装である)",
           alt_strip_no_balance_check(ORPHAN)[0] == ORPHAN_BODY)
    _check("[must-fail] 均衡ガードを外すと正しいコードブロックの閉じ ``` まで剥ぐ=このガードが効いている",
           alt_strip_no_balance_check(balanced)[0] != balanced)


# ============================================================================
# 自己申告メモの丸ごと抑止(2026-09-23・プラットフォームSE / DEF-platform-se-8f7599cc3c)
# ----------------------------------------------------------------------------
# 陽性の入力は**実物のコピー**= local/llm/send_audit.jsonl msg 1551880577232277526
#   (漏れた作業メモそのもの。作業実況2段落 + 末尾に自己申告の丸括弧行)。
# 陰性の実物= 直後の謝罪便 msg 1551884541915037698(「作業メモ」を「」で括って論じている)。
#   → 恒久対策がこの謝罪便を巻き込んで消したら、事故を論じる便が消える=それこそ事故。固定する。
# ============================================================================

MEMO_SPEC = ("閾値外出しの載せ替え確認と台帳記帳を背景タスク b9g7f95rs に任せ、完了通知を待ちます。"
             "Jev合流の配線自体は現行常駐(pid 19172・328433fc52e7)で既に稼働中で、外出し分は"
             "既定値0.7が同一のため反映待ちでも挙動は変わりません。完了を確認してから、"
             "研究室HQへの1行を含む返信を1本だけ出します。\n\n"
             "*(これは作業メモで、部屋への投稿ではありません。載せ替え＋記帳の確認後に "
             "`[一ノ瀬怜]` の返信を送ります。)*")

MEMO_APOLOGY = ("あなたの指摘のとおりです。あの「作業メモ」、部屋へそのまま出ていました。"
                "投稿にならない前提で書いた私のミスです。私が打つ文字は全部この部屋へ届く——"
                "そう扱いますわ。以後、内輪メモを返信本文に混ぜません。出すのは実のある1本だけにします。")


def _memo_tests():
    # --- 陽性: 実物の作業メモは本文まるごと抑止される ---------------------
    body, hits = meta_strip.strip_selfdeclared_memo(MEMO_SPEC)
    _check("実物の自己申告メモは丸ごと抑止(空を返す)", body == "" and len(hits) == 1)
    _check("抑止の理由が記録に残る",
           bool(hits) and hits[0]["marker"] in ("memo_not_post", "not_a_room_post"))

    # --- 陰性: 剥いではいけないもの(誤爆=事故を論じる便が消える) ---------
    _check("謝罪便(「作業メモ」を引用して論じている)は1文字も変えない",
           meta_strip.strip_selfdeclared_memo(MEMO_APOLOGY) == (MEMO_APOLOGY, []))

    quoted = ('デブライネ、漏れた原文=「これは作業メモで、部屋への投稿ではありません」。'
              'この形を機構で止める。')
    _check("引用符「」の中の宣言は抑止しない",
           meta_strip.strip_selfdeclared_memo(quoted) == (quoted, []))

    bq = "報告です。\n> これは作業メモで、部屋への投稿ではありません"
    _check("引用ブロック(>)の中の宣言は抑止しない",
           meta_strip.strip_selfdeclared_memo(bq) == (bq, []))

    fenced = "貼ります。\n```\nこれは作業メモで、部屋への投稿ではありません\n```"
    _check("コードブロックの中の宣言は抑止しない",
           meta_strip.strip_selfdeclared_memo(fenced) == (fenced, []))

    normal = "怜、②受け取った。実物を見て測った。1本だけ返すわ。"
    _check("宣言が無ければ1文字も変えない",
           meta_strip.strip_selfdeclared_memo(normal) == (normal, []))

    mixne = "以後、内輪メモを返信本文に混ぜません。出すのは1本だけにします。"
    _check("『メモを混ぜません』は投稿否定ではない=素通し",
           meta_strip.strip_selfdeclared_memo(mixne) == (mixne, []))

    # --- fail-open: どんな入力でも例外を投げない --------------------------
    ok = True
    for bad in (None, 123, {"a": 1}, [], "", "   \n  "):
        try:
            meta_strip.strip_selfdeclared_memo(bad)
        except Exception:                                  # noqa: BLE001
            ok = False
    _check("壊れた入力でも例外を投げない", ok)

    # --- 本物の合流点(dept_daemon.strip_meta)を**実行で**通す(C-053) ----
    #   外向きの手(投稿)は差し替えず、実際の剥ぎ経路そのものへ検体を流す。
    import dept_daemon as dd                               # noqa: E402
    rec = {"msg_id": "TEST-memo"}
    _check("常駐の合流点strip_metaに通すと検体は空になる(=生成失敗で送られない)",
           dd.strip_meta("platform-se", rec, MEMO_SPEC) == "")
    _check("常駐の合流点strip_metaに通すと謝罪便は残る(=素通し)",
           dd.strip_meta("platform-se", rec, MEMO_APOLOGY) == MEMO_APOLOGY)

    # --- must-fail(C-053): **動く別実装**を当てて、壊れる側を1つ固定する ---
    #   別実装= 引用ガードを標準の _QUOTE_OPEN(丸括弧 (（ を**含む**)で行う版。
    #   検体はメモを丸括弧で囲っている= 丸括弧を引用扱いにすると**検体を取り逃がす**。
    #   これで「引用ガードから丸括弧を外した判断」が効いていることを1つ固定する。
    def alt_with_standard_quote_guard(text):
        s = str(text or "")
        for ln in s.splitlines():
            b = ln.lstrip(meta_strip._DECOR)
            if b.lstrip().startswith(">"):
                continue
            for name, rx in meta_strip._MEMO_NOTPOST:
                m = rx.search(b)
                if m and not any(q in b[:m.start()] for q in meta_strip._QUOTE_OPEN):
                    return "", [{"marker": name}]
        return s, []

    _check("[must-fail] 標準の引用ガード(丸括弧込み)だと検体を取り逃がす=丸括弧を外した判断が効いている",
           alt_with_standard_quote_guard(MEMO_SPEC) == (MEMO_SPEC, []))
    _check("[must-fail] 本実装は同じ検体を抑止できる(=正しい実装である)",
           meta_strip.strip_selfdeclared_memo(MEMO_SPEC)[0] == "")


if __name__ == "__main__":
    sys.exit(main())
