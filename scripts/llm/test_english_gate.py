#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""出力ゲート(英文ダンプ)= detect_english_dump / english_gate の回帰テスト。

なぜ要るか(2026-08-18 platform-se・一ノ瀬怜):
  Chami「謎英文の表示無駄だからやめて」(msg 1539153227491180624)。日本語話者の部屋に
  Claude原文の英語がそのまま出た(花海咲季・実物 _daemon_reply_system-engineer.txt)。
  2026-07-21 の同じ苦情(ORG-23)は退役したミラー経路に恒久策があり、別経路(dept_daemon)で
  再発した=P4/C-038。dept_daemon の送信直前・合流点に言語ゲートを載せ直した。
  「入力を差し替えて経路を実行で通せ」(HQ裁定2026-08-14)=空PASSにしないため実物で固定する。

★test-must-fail: detect_english_dump が常に None(=検知しない)なら
  「実物の英文ダンプを検知」ケースが FAIL する=この検査は空PASSではない。

実行= python scripts/llm/test_english_gate.py (全PASSで exit 0)。ネイティブPythonで走る。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_QUEUE = os.path.normpath(os.path.join(_HERE, "..", "queue"))
if _QUEUE not in sys.path:
    sys.path.insert(0, _QUEUE)

import dept_daemon as d  # noqa: E402

_PASS = 0
_FAIL = 0


def _check(name, cond):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("PASS", name)
    else:
        _FAIL += 1
        print("FAIL", name)


# --- 実物・準実物のサンプル -------------------------------------------------
# 花海咲季の実際の英文ダンプ(冒頭。コード識別子・規約番号・日本語1語が混じる)。
ENGLISH = (
    "I've delivered the measured branch-A verdict to the room. The live-click probe "
    "(background task `bixl42dn0`) is still fetching against the throttled worker and will "
    "notify me when it lands. I'll apply the fix under C-043 once it returns, and won't close "
    "anything until I see 視聴履歴.作品クリック数 go non-empty with real data per §4.55.\n\n"
    "Standing by for the probe result."
)
# 普通の日本語返信(英単語=固有名詞のみ)。鳴ってはいけない。
NORMAL_JP = (
    "Chami、無視じゃない。今この場で端から端まで追い直して、サーバ側は「今まさに生きてる」ことまで"
    "確認した。Drive保存のWorkerは生存で、月詠みの認証→Drive照会を叩いて saved:false が返った。"
    "最新版は昨夜0:36(JST)に本番反映済み。"
)
# 英字それなり+日本語多数の混在。鳴ってはいけない(誤検知ガード)。
MIXED = (
    "確認した。The Drive worker is alive and saved:false が返った。最新版は昨夜反映済みで、"
    "同題名の上書きも効いてる。あとで probe の結果を見て writer の直し方を決める。"
)
# 日本語本文だがコード柵に英語が大量=柵は判定から除くので鳴ってはいけない。
JP_WITH_CODE = (
    "直したよ。差分はこれ。\n```js\nfunction resolveWorkLink(url){ return shorten(url) }\n```\n"
    "これで作品リンクは投稿直前に短縮へ差し替わる。"
)
# ★英語前置き+日本語本文の混在(実物 オタコン msg 1540768290568409130 を模した形)。
#   detect_english_dump は日本語が多くて鳴らない=strip_english_preamble が剥がすべき対象。
PREAMBLE_JP = (
    "Confirmed at line 1408: applyPreview early-returns when prevB is null, and the "
    "previewReady chain yields null exactly when the preview was never captured. So the "
    "black history thumbnails are the downstream of the same capturePreview bug I fixed "
    "today. Reporting honestly:\n"
    "追えたよ。これ、別々の壊れ方が2つ重なってる——分けて話す。"
    "(1)履歴サムネが真っ黒: これは今日直した capturePreview_ の穴の下流だ。"
    "投稿完了時にプレビュー実体が撮れてないと applyPreview が早期returnして画像を1枚も書かない。"
)
# 先頭が固有名詞だけの短い英字=通常返信。剥がしてはいけない。
LEADING_NOUN = "GitHub Pages に v=879 を反映した。プレビューは効いてる。確認済み。"

# ★実物(2026-09-01 aegis-gl・人事部門 msg 1544081974363291729 の冒頭そのまま)。英字ちょうど35字。
#   ★2026-09-01 に閾値を 40→35 へ下げた(研究室HQ裁定・HQ commit c6e8f6a)ので、**これは剥がれる側へ
#     移った**。名前を NEAR_MISS_35 のまま据え置くのは、この実物が「40では届かず35で届く」境目そのもの
#     だからだ= 閾値を戻す改修が入れば C-4 が赤くなる。
NEAR_MISS_35 = (
    "Done. Report to Chami (output text = the reply):\n\n---\n\n"
    "2つとも手ぇ入れといたよ、先輩。人格ハブのサムネをクリックしたら原寸オーバーレイで"
    "開くようにした。ホイールかダブルクリックで拡大、拡大中はドラッグで移動できる。"
)
# ★実物(学習コーチ msg 1528704940342775808 の冒頭そのまま)。**閉じていないバックティック**の中に
#   Windowsパスが入っていて、インラインコード除去の正規表現がペアを作れず英字31字と数えられる。
#   これが「閾値を30まで下げてはいけない」根拠の実物= 30なら本文の先頭パスごと剥がれて壊れる。
#   35でも30〜34は触らないので不変。この検査は**下げすぎ**を赤くするための番人だ。
FALSE_POS_31 = (
    "`D:\\SougouStartFolder\\5SecMovieMaker\\"
    "起動_go5-maker.bat`\n\nこれがメインのやつよ。cwd を go5-maker 直下に固定してから"
    "Claude を起動する。これで書き込みが飛ばない。"
)


def test_detect():
    _check("実物の英文ダンプを検知", d.detect_english_dump(ENGLISH) is not None)
    _check("普通の日本語は非検知", d.detect_english_dump(NORMAL_JP) is None)
    _check("混在返信は非検知(誤検知ガード)", d.detect_english_dump(MIXED) is None)
    _check("コード柵の英語は判定から除外", d.detect_english_dump(JP_WITH_CODE) is None)
    _check("空文字は非検知(fail-safe)", d.detect_english_dump("") is None)
    _check("Noneは例外を出さず非検知", d.detect_english_dump(None) is None)


def test_gate_ladder():
    # 通常返信は素通し=1ミリも変わらない
    out, info = d.english_gate(NORMAL_JP)
    _check("通常返信は不変(hit1=False)", out == NORMAL_JP and not info["hit1"])

    # ①再生成で日本語に戻れば、その本文を採用
    out, info = d.english_gate(ENGLISH, regen=lambda: "日本語で言い直したよ。保存はされてる。")
    _check("①再生成で日本語→採用",
           out == "日本語で言い直したよ。保存はされてる。" and info["regenerated"])

    # ②再生成しても英語のまま→translateで日本語化を採用
    out, info = d.english_gate(ENGLISH, regen=lambda: ENGLISH,
                               translate=lambda t: "翻訳したよ。ブランチAの判定を部屋へ渡した。")
    _check("②言い換えで日本語→採用", info["translated"] and not info["regenerated"])

    # ③再生成も翻訳も英語のまま→保留(空を返す=送らない合図)
    out, info = d.english_gate(ENGLISH, regen=lambda: ENGLISH, translate=lambda t: ENGLISH)
    _check("③どちらも英語→保留(空を返す)", out == "" and info["suppressed"])

    # regen/translate 無し→保留(送らない)
    out, info = d.english_gate(ENGLISH)
    _check("thunk無し→保留", out == "" and info["suppressed"])

    # fail-open: regenが例外でも送信を殺さず保留へ倒す(例外を外に出さない)
    def _boom():
        raise RuntimeError("boom")
    out, info = d.english_gate(ENGLISH, regen=_boom, translate=None)
    _check("regen例外でも保留・例外を外に出さない", out == "" and info["suppressed"])

    # strip_marker: 再生成本文の <<WIP>> を落としてから判定
    out, info = d.english_gate(
        ENGLISH, regen=lambda: "直したよ。保存は効いてる。<<WIP>>",
        strip_marker=lambda s: (s.replace("<<WIP>>", ""), True))
    _check("strip_markerで再生成本文の印を除去", out == "直したよ。保存は効いてる。" and info["regenerated"])


def test_strip_preamble():
    # C-1 英語前置き+日本語本文 → 前置きを剥がし、日本語本文が頭から残る(実物パターン)
    out, info = d.strip_english_preamble(PREAMBLE_JP)
    _check("C-1 英語前置きを剥離(stripped=True)", info["stripped"])
    _check("C-1 剥離後は日本語本文から始まる", out.startswith("追えたよ。"))
    _check("C-1 英語前置きが本文から消えている",
           ("Confirmed" not in out) and ("Reporting honestly" not in out))
    _check("C-1 日本語本文は保全(履歴サムネの説明が残る)", "履歴サムネが真っ黒" in out)

    # C-2 頭から日本語(固有名詞混じり)→ 剥がさない(通常返信は不変)
    out, info = d.strip_english_preamble(LEADING_NOUN)
    _check("C-2 頭から日本語は不変(stripped=False)", (not info["stripped"]) and out == LEADING_NOUN)

    # C-2' 既存の混在サンプル(頭から日本語)も不変=誤って剥がさない
    out, info = d.strip_english_preamble(MIXED)
    _check("C-2' 混在(頭から日本語)は不変", (not info["stripped"]) and out == MIXED)

    # C-3 まるごと英語(日本語が薄い)→ 剥がさない=english_gate の suppress/翻訳へ委ねる
    out, info = d.strip_english_preamble(ENGLISH)
    _check("C-3 まるごと英語は剥がさず後段へ委ねる(stripped=False)",
           (not info["stripped"]) and out == ENGLISH)

    # C-4 実物35字の英語前置き= 閾値を35へ下げたので**剥がれる側**。境目そのものを釘付けにする。
    out, info = d.strip_english_preamble(NEAR_MISS_35)
    _check("C-4 実物35字の英語前置きは剥がれる(閾値35・stripped=True)",
           info["stripped"] and info["removed_latin"] == 35)
    _check("C-4 剥離後に英語前置きは残っていない",
           "Done. Report to Chami" not in out and "the reply" not in out)
    _check("C-4 日本語本文は保全(オーバーレイの説明が残る)", "原寸オーバーレイ" in out)
    # ★境目の下側= 前置きから英字を1字削って34にすると**剥がれない**。35が効いている証拠を両側で挟む。
    #   (「35未満は触らない」を実行で示す= ソースの数字を読むだけの検査にしない)
    out34, info34 = d.strip_english_preamble(NEAR_MISS_35.replace("Done.", "Don.", 1))
    _check("C-4 英字34字は剥がさない(閾値35の下側)",
           (not info34["stripped"]) and info34["removed_latin"] == 0)
    # ★★2026-09-05 ここは**直したので向きが反転した**(イージス研究室)。
    #   旧= 切り出しが「最初の日本語文字」からなので本文頭の半角数字が落ちた
    #       (実物 "2つとも" → "つとも")。この検査はその副作用を観測のまま釘付けにしていて、
    #       「恒久の直しは行の頭で切ること。入れればこの検査が赤くなる」と書いてあった。
    #   新= その行の日本語より前に**英字が1文字も無い**時だけ行の頭まで戻す= 数字は残る。
    #   引き金の実物= 救出本文の名乗り `[ヴィルシーナ]` の **`[` を食っていた**
    #     (剥離後が `ヴィルシーナ]` になり、1行目の `[名前]` が成立しない)。
    _check("C-4 ★剥離は行の頭から=本文頭の半角数字が落ちない(2026-09-05に直した)",
           out.startswith("2つとも手ぇ"))
    # ★戻しすぎない側= 同じ行に英字が居るなら行の頭へは戻さない(剥がした英語を連れ戻さない)。
    out_same, info_same = d.strip_english_preamble(
        NEAR_MISS_35.replace("\n\n2つとも", "\nStill checking 2つとも", 1))
    _check("C-4 ★同じ行に英字が残る時は行の頭へ戻さない(英語を連れ戻さない)",
           (not info_same["stripped"]) or "Still checking" not in out_same)

    # C-4b ★名乗りの `[` を食っていた実物(C-053= 壊れていた側を**動く実装**で赤く出す)。
    #   赤の作り= 変更前の lang_gate(.bak)を別モジュールとして読み、**同じ本文**に当てる。
    TAG_MIX = ("Let me check the daemon logs first. I will read the relay source and "
               "search for the timeout branch before reporting back.\n\n"
               "[ヴィルシーナ]\n調べた。打ち切りは600秒のhard-killで、常駐の側に落ち度は無い。"
               "実物は次の便で出す。")
    out_tag, info_tag = d.strip_english_preamble(TAG_MIX)
    _check("C-4b ★剥離しても名乗り `[名前]` が壊れない(緑)",
           info_tag["stripped"] and out_tag.startswith("[ヴィルシーナ]"))
    _bak = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "lang_gate.py.bak_20260905_tagcut")
    try:
        import importlib.machinery
        import importlib.util
        _ldr = importlib.machinery.SourceFileLoader("lang_gate_old", _bak)
        _old = importlib.util.module_from_spec(importlib.util.spec_from_loader("lang_gate_old", _ldr))
        _ldr.exec_module(_old)
        _o, _i = _old.strip_english_preamble(TAG_MIX)
        _check("C-4b ★変更前の実装は同じ本文で `[` を食う(赤の実物・これを直した)",
               _i["stripped"] and _o.startswith("ヴィルシーナ]"))
    except Exception as _e:                                 # noqa: BLE001
        _check(f"C-4b .bak を読めない({type(_e).__name__})", False)

    # C-5 ★閾値を30まで下げてはいけない実物= 閉じていないバックティックのWindowsパス(英字31字)。
    #   35では触らない=不変。ここが赤くなったら「下げすぎ」だ。
    out, info = d.strip_english_preamble(FALSE_POS_31)
    _check("C-5 英字31字の未閉じバックティック(実物)は35でも不変",
           (not info["stripped"]) and out == FALSE_POS_31)
    _check("C-5 本文の先頭パスが削られていない", out.startswith("`D:\\SougouStartFolder"))

    # コード柵で始まる本文は剥がさない(コードを誤除去しない・安全側)
    code_head = "```js\nfunction f(){ return doSomethingEnglishAndLong(x) }\n```\n直したよ。これで動く。効いてる。"
    out, info = d.strip_english_preamble(code_head)
    _check("先頭コード柵は剥がさない", (not info["stripped"]) and out == code_head)

    # fail-safe: None/空でも例外を出さず不変
    out, info = d.strip_english_preamble(None)
    _check("Noneは例外を出さず不変", (not info["stripped"]) and out == "")


if __name__ == "__main__":
    test_detect()
    test_gate_ladder()
    test_strip_preamble()
    print("\n%d PASS / %d FAIL" % (_PASS, _FAIL))
    sys.exit(1 if _FAIL else 0)
