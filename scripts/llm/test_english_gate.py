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


if __name__ == "__main__":
    test_detect()
    test_gate_ladder()
    print("\n%d PASS / %d FAIL" % (_PASS, _FAIL))
    sys.exit(1 if _FAIL else 0)
