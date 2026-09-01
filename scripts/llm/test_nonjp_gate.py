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
    # ★`jp` の枕詞= ハングル/簡体字は「日本語では」でよいが、キリルの `jp` は**ラテン文字**だ。
    #   枕詞を使い回すと監査ログが「日本語ではK」と嘘を書く。既定と上書きの両方をここで固定する。
    _check("枕詞: ハングルは既定のまま(『日本語では』)",
           d._NONJP_KIND["hangul"].get("as", "日本語では") == "日本語では")
    _check("枕詞: 簡体字は既定のまま(『日本語では』)",
           d._NONJP_KIND["simplified"].get("as", "日本語では") == "日本語では")
    _check("枕詞: キリルは『日本語では』と言わない(ラテン文字のそっくりさん)",
           d._NONJP_KIND["cyrillic"].get("as", "日本語では") != "日本語では")


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


def test_audit_record():
    """audit_hangul を**実行で**通す(§3=外へ出る手だけ偽物・判定と分岐は本物)。

    偽物にするのは2つだけ= ①書き込み先 HANGUL_AUDIT(一時ファイルへ向ける) ②log(標準出力へ
    垂れ流さず配列へ溜める)。detect_nonjp も _NONJP_KIND も本物のまま走る。
    ★これが無いと「表に as が在る」だけの検査になり、**ログ文が実際に変わったか**を誰も見ていない。
    """
    import json
    import tempfile

    real_audit, real_log = d.HANGUL_AUDIT, d.log
    tmpdir = tempfile.mkdtemp(prefix="nonjp_audit_")
    d.HANGUL_AUDIT = os.path.join(tmpdir, "hangul_audit.jsonl")
    lines = []
    d.log = lambda dept, msg: lines.append(msg)
    try:
        d.audit_hangul("aegis-gl", {"msg_id": "1"}, HANGUL_JP)
        d.audit_hangul("aegis-gl", {"msg_id": "2"}, SIMPLIFIED_JP)
        d.audit_hangul("aegis-gl", {"msg_id": "3"}, CYRILLIC_JP)
        d.audit_hangul("aegis-gl", {"msg_id": "4"}, NORMAL_JP)   # 鳴らない=1行も書かない
        recs = [json.loads(x) for x in
                open(d.HANGUL_AUDIT, encoding="utf-8").read().splitlines() if x.strip()]
    finally:
        d.HANGUL_AUDIT, d.log = real_audit, real_log

    _check("監査: 鳴った3件だけが着地し、通常返信は1行も書かない", len(recs) == 3 and len(lines) == 3)
    _check("監査: event は kind どおり",
           [r["event"] for r in recs] == ["hangul", "simplified", "cyrillic"])
    _check("監査: キリルの char/codepoint が実物(К U+041A)",
           recs[2]["char"] == "К" and recs[2]["codepoint"] == "U+041A")
    # ★嘘の枕詞をここで赤くする= 「日本語ではK」と書いたら FAIL。
    #   ★実行して分かった現状(推定ではない)= detect_hangul は `jp` を返さないので、
    #     ハングルのログには枕詞の節が**そもそも出ない**。簡体字だけが「=日本語では実」を出す。
    _check("監査ログ: ハングルは jp を持たず枕詞の節が出ない(現状の観測)",
           "日本語では" not in lines[0] and "ハングル混入を検知 판(U+D310)" in lines[0])
    _check("監査ログ: 簡体字は従来どおり『=日本語では実』", "=日本語では実" in lines[1])
    _check("監査ログ: キリルは『日本語では』と書かない",
           "日本語では" not in lines[2])
    _check("監査ログ: キリルは『見た目は』でラテン文字を示す", "=見た目はK" in lines[2])
    _check("監査: jsonl の as も kind ごとに正しい",
           recs[0]["as"] == "日本語では" and recs[1]["as"] == "日本語では"
           and recs[2]["as"] == "見た目は")
    _check("監査: 本物の hangul_audit.jsonl は触っていない",
           d.HANGUL_AUDIT == real_audit and d.log is real_log)


def test_code_span_is_not_judged():
    """2026-09-02: コード柵/インラインコード/URL の中のキリルは鳴らない(実測で入れた縮小)。

    なぜ= hangul_audit.jsonl の event=cyrillic 11行のうち **8行が「このバグを報告した便」**で、
      2行は既に ``` / ` ` の中に在った=**正しく引用したのに自分の警報を鳴らしていた**。
    ★test-must-fail: detect_cyrillic から _mask_code_spans を外すと下の3本が FAIL する。
    ★★同時に固定する= **地の文の混入は今までどおり鳴る**(縮めすぎの検出)。
    """
    fence = "実物はこれだった:\n```\n[ККール] 直しといたよ\n```\n以上。"
    _check("柵: ``` の中のキリルは鳴らない", d.detect_nonjp(fence) is None)
    inline = "ちゃみのリンク先はククールの名乗りが `[ккール]` になってる。"
    _check("柵: `インラインコード` の中のキリルは鳴らない", d.detect_nonjp(inline) is None)
    _check("柵: URL の中のキリルは鳴らない",
           d.detect_nonjp("https://example.com/К/path を見てくれ。") is None)

    # ★縮めすぎていないこと= 地の文の本物(実測 #7 と #10 の実物)は今までどおり鳴る
    _check("柵: 地の文の так は今までどおり鳴る(実測#7)",
           d.detect_nonjp("так、4因子で切り分ける。")["kind"] == "cyrillic")
    _check("柵: 地の文の триアージ は今までどおり鳴る(実測#10)",
           d.detect_nonjp("短く триアージだけ残す。")["kind"] == "cyrillic")
    _check("柵: 柵の外に在れば、柵が同居していても鳴る",
           d.detect_nonjp("ККール化けの件。\n```\nlog\n```\n以上。") is not None)

    # index/context は**原文基準**(マスクで位置がずれたら監査ログが嘘の場所を指す)
    hit = d.detect_cyrillic("あいう```x```так")
    _check("柵: マスクしても index は原文基準のまま",
           hit is not None and hit["index"] == "あいう```x```так".index("т"))


def test_cyrillic_warn_only_in_tag():
    """2026-09-02: キリルの ⚠️ は**名乗りタグが壊れた便だけ**に出す(依頼= ククール/Chami)。

    ★test-must-fail: CYRILLIC_WARN_ONLY_IN_TAG を False にすると「地の文は画面へ出さない」が
      FAIL する。cyrillic_in_name_tag が常に False を返すようにすると「タグ壊れは出す」が FAIL。
    ★ハングル/簡体字は**巻き添えにしない**ことも同時に固定する(そちらは別の裁定)。
    """
    _check("判定: 破損した名乗りタグはタグ内と判る",
           d.cyrillic_in_name_tag("[ККール] 入れといたよ") is True)
    _check("判定: 地の文の言及はタグ内ではない",
           d.cyrillic_in_name_tag("ККール化けの恒久対策を入れた") is False)
    _check("判定: `[ккール]` と引用しただけならタグではない(柵の中)",
           d.cyrillic_in_name_tag("名乗りが `[ккール]` になってる") is False)

    # ①タグが壊れた便= 従来どおり画面へ ⚠️(本来の獲物・実測#5の型)
    out, info = d.hangul_gate(CYRILLIC_JP, regen=lambda: CYRILLIC_JP)
    _check("警報: タグ壊れは今までどおり警告付き",
           info["warned"] and d.CYRILLIC_WARN in out and not info.get("suppressed"))

    # ②地の文だけの便= 画面へ出さない。ただし hit1 は立つ=**台帳とログには残る**
    prose = "ККール化けの恒久対策(裁定2)を実装した。以上。"
    out, info = d.hangul_gate(prose, regen=lambda: prose)
    _check("警報: 地の文の言及は画面へ出さない(本文を1文字も足さない)",
           out == prose and not info["warned"] and info.get("suppressed"))
    _check("警報: 抑制しても hit1 は立つ(=audit_hangul は従来どおり1行書く)",
           info["hit1"] and info["kind"] == "cyrillic")

    # ③regen 無しの経路でも同じ(session_relay 等)
    out, info = d.hangul_gate(prose)
    _check("警報: regen無しの経路でも地の文は抑制される",
           out == prose and info.get("suppressed") and not info["warned"])

    # ④★ハングル/簡体字は1ミリも変えない(巻き添え禁止)
    out, info = d.hangul_gate(HANGUL_JP)
    _check("警報: ハングルは抑制しない(ORG-45 の挙動が不変)",
           info["warned"] and d.HANGUL_WARN in out and not info.get("suppressed"))
    out, info = d.hangul_gate(SIMPLIFIED_JP)
    _check("警報: 簡体字は抑制しない(HQ-0224 の挙動が不変)",
           info["warned"] and d.SIMPLIFIED_WARN in out and not info.get("suppressed"))

    # ⑤戻せること= 定数1つで 2026-09-01 の挙動へ完全復帰する(逃げ道が本当に在るか確かめる)
    real = d.CYRILLIC_WARN_ONLY_IN_TAG
    try:
        d.CYRILLIC_WARN_ONLY_IN_TAG = False
        out, info = d.hangul_gate(prose, regen=lambda: prose)
        _check("警報: 定数を False にすれば地の文も従来どおり鳴る(1行で戻せる)",
               info["warned"] and d.CYRILLIC_WARN in out)
    finally:
        d.CYRILLIC_WARN_ONLY_IN_TAG = real
    _check("警報: 定数を戻した(テストが本番の既定値を汚さない)",
           d.CYRILLIC_WARN_ONLY_IN_TAG is True)


def test_homoglyph_tag_fix():
    """2026-09-02: 化けた名乗りタグを**候補がただ1人の時だけ**正名へ直す(依頼①)。

    ★test-must-fail: PERSONA_TAG_HOMOGLYPH_FIX を False にすると「多人格部屋でも直る」が
      FAIL する。_homoglyph_unique を _homoglyph_near に戻すと「同点なら直さない」が FAIL。
    ★C-035 の線に触れる変更なので、**取り違えないこと**を人数ではなく一意性で固定する。
    """
    names = ("ククール", "五月")
    _check("一意: ККール はククール1人の化けと決まる",
           d._homoglyph_unique("ККール", names) == "ククール")
    _check("一意: ккール(小文字)も同じく決まる",
           d._homoglyph_unique("ккール", names) == "ククール")
    _check("一意: 正名そのものは化けではない(None)",
           d._homoglyph_unique("ククール", names) is None)
    # ★同点2人= 機械には決められない。直さない(従来どおり漏れとして数えるだけ)。
    _check("一意: 同点候補が2人居たら直さない",
           d._homoglyph_unique("Аキ", ("アキ", "ユキ")) is None)
    _check("一意: 近くもない字は直さない",
           d._homoglyph_unique("Ыxyz", names) is None)

    # --- 多人格部屋の分割で実際に救済されるか(実物= hr-room の10便の型) --------------
    def _resolve(nm):
        return "ククール" if str(nm).strip() in ("ククール",) else None
    broken = "[ККール] その2枚、もう入ってるぜ。"
    real_audit = d._audit_tag
    seen = []
    d._audit_tag = lambda dept, who, outcome, line="": seen.append((who, outcome))
    try:
        blocks = d.split_persona_blocks(broken, _resolve, dept="hr-room", names=names)
    finally:
        d._audit_tag = real_audit
    _check("救済: 化けたタグでも名義が解ける(既定人格へ倒れない)",
           len(blocks) == 1 and blocks[0][0] == "ククール")
    _check("救済: 本文からタグが消える(画面へ壊れた字が出ない)",
           blocks and "ККール" not in blocks[0][1] and "その2枚" in blocks[0][1])
    _check("救済: 漏れ(tag_homoglyph_leak)を**先に**残してから直す=化けた回数が消えない",
           [o for _, o in seen] == ["tag_homoglyph_leak", "tag_homoglyph_rescued"])

    # ★取り違えない= 同点2人の部屋では直さず、従来どおり [(None, 本文)] のまま
    def _resolve2(nm):
        return str(nm).strip() if str(nm).strip() in ("アキ", "ユキ") else None
    real_audit = d._audit_tag
    d._audit_tag = lambda *a, **k: None
    try:
        blocks = d.split_persona_blocks("[Аキ] やっといた。", _resolve2,
                                        dept="t", names=("アキ", "ユキ"))
    finally:
        d._audit_tag = real_audit
    _check("救済: 同点2人の部屋では直さない(名義未解決のまま=従来挙動)",
           len(blocks) == 1 and blocks[0][0] is None)

    # ★逃げ道= 定数1つで従来挙動へ戻る
    real = d.PERSONA_TAG_HOMOGLYPH_FIX
    real_audit, d._audit_tag = d._audit_tag, (lambda *a, **k: None)
    try:
        d.PERSONA_TAG_HOMOGLYPH_FIX = False
        blocks = d.split_persona_blocks(broken, _resolve, dept="hr-room", names=names)
        _check("救済: 定数を False にすれば従来どおり名義未解決(1行で戻せる)",
               len(blocks) == 1 and blocks[0][0] is None)
    finally:
        d.PERSONA_TAG_HOMOGLYPH_FIX = real
        d._audit_tag = real_audit


def test_warn_silent_when_rescuable():
    """2026-09-02: 直せるタグの便は黙る/直せないタグは今までどおり鳴る(依頼②)。"""
    names = ["ククール", "五月"]
    broken = "[ККール] その2枚、もう入ってるぜ。"
    out, info = d.hangul_gate(broken, regen=lambda: broken, names=names)
    _check("黙る: 下流で直るタグなら ⚠️ を出さない(本文も足さない)",
           out == broken and info.get("suppressed") and not info["warned"])
    _check("黙る: 黙っても hit1 は立つ(台帳とログには残る)", info["hit1"])

    # ★直せないタグ(名簿の誰にも寄らない)は**今までどおり鳴る**= 依頼の「救済不能な時だけ残す」
    out, info = d.hangul_gate("[Ыфвапр] やった。", regen=lambda: "[Ыфвапр] やった。",
                              names=names)
    _check("黙る: 直せないタグは今までどおり警告付き",
           info["warned"] and d.CYRILLIC_WARN in out)

    # ★名簿を渡さない呼び元(session_relay 等)は従来どおり= タグ壊れは鳴る
    out, info = d.hangul_gate(broken, regen=lambda: broken)
    _check("黙る: 名簿を渡さない経路は従来どおり鳴る(既定は安全側)",
           info["warned"] and d.CYRILLIC_WARN in out)


if __name__ == "__main__":
    test_detect_each_kind()
    test_kind_table()
    test_gate_ladder()
    test_audit_record()
    test_code_span_is_not_judged()
    test_cyrillic_warn_only_in_tag()
    test_homoglyph_tag_fix()
    test_warn_silent_when_rescuable()
    print("\n%d PASS / %d FAIL" % (_PASS, _FAIL))
    sys.exit(1 if _FAIL else 0)
