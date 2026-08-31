#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""出力ゲート ルールA(非日本語スクリプト混入)= detect_nonjp / hangul_gate の回帰テスト。

なぜ要るか(2026-09-01 aegis-gl・ケヴィン・デブライネ):
  この族は3世代に渡って増えたのに**回帰テストが1本も無かった**。
    ①ハングル(ORG-45) ②簡体字(HQ-0224・commit e1a3afe) ③キリル(HQ-0227 裁定2・本ファイル)
  研究室HQの条件②=「既存の hangul/simplified の計器・記録先を壊さない=事後に再実行して
  赤が無いことを確認する」を満たすには、**再実行できる物**が要る。無かったので作った。

★test-must-fail: detect_cyrillic が常に None(=検知しない)なら「実物の破損タグを検知」が
  FAIL する。_NONJP_KIND から cyrillic の行を消せば「event が cyrillic」が FAIL する。
  ハングル/簡体字のケースは kind 追加の**前後で不変**であること自体を固定している。

★このファイルはキリル文字・簡体字・ハングルを**検体として含む**(含まないと検知できない)。
  ゲートに掛ければ当然鳴るが、これは仕様(ルールAの「판」と同じ)。

実行= python scripts/llm/test_nonjp_gate.py (全PASSで exit 0)。
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


# --- 検体 -------------------------------------------------------------------
# 普通の日本語返信。どの kind でも鳴ってはいけない(誤発火ガード)。
NORMAL_JP = (
    "Chami、直したよ。人格ハブのサムネをクリックしたら原寸で開くようにした。"
    "ホイールで拡大、背景クリックで閉じる。GitHub Pages へは反映済み。"
)
# ①ハングル(ORG-45 の実物型)
HANGUL_JP = "판定は終わってる。あとは投げるだけだ。"
# ②簡体字(HQ-0224 の実物= 「实况」)
SIMPLIFIED_JP = "前置きの实况はやめた。結果だけ書く。"
# ③キリル(HQ-0227 の実物= 人事部門 msg 1544081974363291729 の名乗りタグ)
CYRILLIC_JP = "[ККール] 2つとも手ぇ入れといたよ、先輩。画像ズームは入れた。"


def test_detect_each_kind():
    _check("通常返信はどの kind でも非検知", d.detect_nonjp(NORMAL_JP) is None)

    hit = d.detect_nonjp(HANGUL_JP)
    _check("①ハングルを検知(ORG-45 の既存挙動が不変)",
           hit is not None and hit["kind"] == "hangul")

    hit = d.detect_nonjp(SIMPLIFIED_JP)
    _check("②簡体字を検知(HQ-0224 の既存挙動が不変)",
           hit is not None and hit["kind"] == "simplified")
    _check("②簡体字は日本語の字を説明用に持つ(置換用ではない)",
           hit is not None and hit["jp"] == "実")

    hit = d.detect_nonjp(CYRILLIC_JP)
    _check("③実物の破損タグのキリルを検知",
           hit is not None and hit["kind"] == "cyrillic")
    _check("③検知位置は名乗りタグの中(index=1)・コードポイントは U+041A",
           hit is not None and hit["index"] == 1 and hit["codepoint"] == "U+041A")
    _check("③そっくりなラテン文字を説明用に持つ(置換用ではない)",
           hit is not None and hit["jp"] == "K")

    # 正名のタグは鳴らない=救済済み/正常な便を巻き込まない
    _check("③正名の名乗りタグ [ククール] は鳴らない",
           d.detect_nonjp("[ククール] 2つとも手ぇ入れといたよ、先輩。") is None)

    # 順番=ハングルが先。両方在ってもハングルとして扱う(既存挙動を1ミリも変えない)
    _check("順番: ハングル+キリルが同居したらハングル扱い",
           d.detect_nonjp("판" + CYRILLIC_JP)["kind"] == "hangul")
    _check("順番: 簡体字+キリルが同居したら簡体字扱い",
           d.detect_nonjp("实况 " + CYRILLIC_JP)["kind"] == "simplified")

    # fail-safe
    _check("空/None/非文字列でも例外を出さず非検知",
           d.detect_nonjp("") is None and d.detect_nonjp(None) is None
           and d.detect_nonjp(123) is None)


def test_kind_table():
    """kind を足したら、ログ文・監査event・警告文の3つが**同時に**増えていること。

    ★片方だけ足すと `_NONJP_WARN.get(kind, HANGUL_WARN)` が黙ってハングルの警告文を出す=
      「静かに壊れる推定」になる。表の欠けをここで赤くする。
    """
    for kind in ("hangul", "simplified", "cyrillic"):
        _check("表: %s に label/event/ref が在る" % kind,
               kind in d._NONJP_KIND
               and all(k in d._NONJP_KIND[kind] for k in ("label", "event", "ref")))
        _check("表: %s に専用の警告文が在る(ハングルへ黙って落ちない)" % kind,
               kind in d._NONJP_WARN)
    _check("表: 警告文は kind ごとに全部違う",
           len(set(d._NONJP_WARN.values())) == len(d._NONJP_WARN))
    _check("表: 監査の event も kind ごとに全部違う",
           len(set(v["event"] for v in d._NONJP_KIND.values())) == len(d._NONJP_KIND))
    # ★警告文そのものが検知に鳴かない(自分の警告で無限に鳴く事故を防ぐ)
    for kind, warn in d._NONJP_WARN.items():
        _check("表: %s の警告文が自分の検知器に鳴かない" % kind,
               d.detect_nonjp(warn) is None)


def test_gate_ladder():
    # 通常返信は素通し=1ミリも変わらない
    out, info = d.hangul_gate(NORMAL_JP)
    _check("梯子: 通常返信は不変(hit1=False)", out == NORMAL_JP and not info["hit1"])

    # ①再生成で消えれば、その本文を採用(警告は付かない)
    out, info = d.hangul_gate(CYRILLIC_JP, regen=lambda: "[ククール] 2つとも入れといたよ、先輩。")
    _check("梯子: 再生成で消えたら差し替え・警告なし",
           out == "[ククール] 2つとも入れといたよ、先輩。"
           and info["regenerated"] and not info["warned"])

    # ②再生成しても残る→**元文**に警告を付けて送る(送信は止めない・自動置換もしない)
    out, info = d.hangul_gate(CYRILLIC_JP, regen=lambda: CYRILLIC_JP)
    _check("梯子: 残ったら元文+警告(沈黙にしない)",
           out.startswith(CYRILLIC_JP) and info["warned"] and info["hit2"])
    _check("梯子: 付く警告はキリル専用の文(ハングルの文が出ない)",
           d.CYRILLIC_WARN in out and d.HANGUL_WARN not in out)
    _check("梯子: 本文は1文字も置換されていない", CYRILLIC_JP in out)

    # regen 無し=再生成できない経路でも沈黙にしない
    out, info = d.hangul_gate(CYRILLIC_JP)
    _check("梯子: regen無しでも警告付きで送る(fail-open)",
           info["warned"] and d.CYRILLIC_WARN in out)

    # regen が例外でも配送を殺さない
    def _boom():
        raise RuntimeError("boom")
    out, info = d.hangul_gate(CYRILLIC_JP, regen=_boom)
    _check("梯子: regen例外でも元文+警告(例外を外に出さない)",
           info["warned"] and out.startswith(CYRILLIC_JP))

    # 警告の二重付与をしない
    once, _ = d.hangul_gate(CYRILLIC_JP)
    twice, _ = d.hangul_gate(once)
    _check("梯子: 同じ警告を二重に付けない", twice.count(d.CYRILLIC_WARN) == 1)

    # ①②の既存 kind も梯子が不変であること
    out, info = d.hangul_gate(HANGUL_JP)
    _check("梯子: ハングルは従来どおり警告付き", info["warned"] and d.HANGUL_WARN in out)
    out, info = d.hangul_gate(SIMPLIFIED_JP)
    _check("梯子: 簡体字は従来どおり警告付き", info["warned"] and d.SIMPLIFIED_WARN in out)


if __name__ == "__main__":
    test_detect_each_kind()
    test_kind_table()
    test_gate_ladder()
    print("\n%d PASS / %d FAIL" % (_PASS, _FAIL))
    sys.exit(1 if _FAIL else 0)
