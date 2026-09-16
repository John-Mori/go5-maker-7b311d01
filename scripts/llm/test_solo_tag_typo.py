#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""単独人格部屋の名乗り救済が**同スクリプトの1字ずれ**を素通しする穴の回帰検査(2026-09-13)。

依頼= 品質管理部門オタコン msg 1548587480872394937(欠陥 DEF-qa-reviewer-9c7f2b0c4e)。
壊れた実物= local/llm/send_audit.jsonl の
  {"ts": "2026-09-13T12:23:07", "channel": "🌏プラットフォームse-一ノ瀬怜",
   "dept": "platform-se", "persona": "一ノ瀬怜", "status": "200",
   "head": "[一ノ怜]⏎デブライネさんの返信、読みました。…"}
= 本文1行目の `[一ノ怜]`(正しくは「一ノ瀬怜」= **瀬が1字欠落**)がそのままChamiの画面へ出た。

真因= `strip_solo_persona_tag` の §5-2 救済が `_homoglyph_near` の
  **foreign-script 必須**(`_has_foreign_script`)を通るため、全部日本語の1字欠けは
  ①resolve が引けない ②救済に入れない ③`_avatar_keys()` に載らないので
  `tag_solo_leak` でも数えない、の**三重で漏れて監査に1行も映らなかった**。

見る物:
  ① 実物の再現= platform-se で `[一ノ怜]` が落ち、本文は1文字も欠けない
  ② 穴が計器に映る= `tag_typo_leak` → `tag_typo_rescued` の順で1行ずつ残る
  ③ 退行させていない= 正しい名乗り(`tag_solo_fixed`)/ホモグリフ(丙)は従来どおり
  ④ 広げ過ぎていない= 本文中のタグ(`[検証]` 等)も距離2の別名も触らない。
     多人格部屋の `_homoglyph_unique` へは波及しない(C-035不変)
  ⑤ must-fail(C-053)= foreign-script 必須へ戻した**動く別の実装**では①②が赤くなる
  ⑥ ★この検査が**本番の監査台帳へ1バイトも書かない**
     (2026-09-13 に send_audit / wait_guard で2回踏んだ穴・C-038)

実行: python scripts/llm/test_solo_tag_typo.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dept_daemon as dd               # noqa: E402
import persona_render                  # noqa: E402

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


# ★実物そのもの(12:23:07 の便の冒頭・本文は要旨)。
REAL = ("[一ノ怜]\n"
        "デブライネさんの返信、読みました。私の`wait_guard.jsonl`は生まれた瞬間から"
        "汚れていました。")
REAL_WANT = ("デブライネさんの返信、読みました。私の`wait_guard.jsonl`は生まれた瞬間から"
             "汚れていました。")

_captured = []


def _fake_audit(dept, persona, outcome, detail="", chars_in=0, chars_out=0):
    _captured.append((outcome, persona))


def run_strip(text, dept, persona):
    """監査を横取りして strip を1回通す。戻り= (本文, [(outcome, persona), ...])"""
    conf = dd.DEPT_CONF.get(dept) or {}
    resolve = dd.solo_tag_resolver(conf, persona)
    _captured.clear()
    keep = persona_render._audit
    persona_render._audit = _fake_audit
    try:
        out = dd.strip_solo_persona_tag(text, resolve, dept=dept)
    finally:
        persona_render._audit = keep
    return out, list(_captured)


def names_of(dept, persona):
    return tuple(getattr(dd.solo_tag_resolver(dd.DEPT_CONF.get(dept) or {}, persona),
                         "names", ()) or ())


def main():
    # ---- 0) 前提: 単独部屋の候補は**ただ1人**(C-035の安全論拠そのもの) -------------
    print("\n[0] 前提= 単独人格部屋の候補は1人(誰と読み違えても行き先が同じ)")
    for _d, _p in (("platform-se", "一ノ瀬怜"), ("hr-room", "ククール"),
                   ("llm-qa", "中野五月"), ("aegis-gl", "ケヴィン・デブライネ")):
        check(f"{_d} の resolve.names は1要素", len(names_of(_d, _p)) == 1)

    # ---- 1) 実物が直ること(オタコンの逐語要件) ----------------------------------
    print("\n[1] ★実物= platform-se で [一ノ怜] を落とす / 少なくとも1行数える")
    out, rec = run_strip(REAL, "platform-se", "一ノ瀬怜")
    check("実物: タグ [一ノ怜] が消える", "[一ノ怜]" not in out)
    check("実物: 本文は1文字も欠けない", out == REAL_WANT)
    outcomes = [o for o, _ in rec]
    check("実物: 穴が計器に映る(tag_typo_leak が1行)", outcomes.count("tag_typo_leak") == 1)
    check("実物: 救済も数える(tag_typo_rescued が1行)",
          outcomes.count("tag_typo_rescued") == 1)
    check("実物: leak を**先に**残す= 生成側が壊した回数は救済で消えない(C-054)",
          outcomes == ["tag_typo_leak", "tag_typo_rescued"])
    check("実物: 推定した正名は「一ノ瀬怜」", all(w == "一ノ瀬怜" for _, w in rec))
    check("実物: 丙(ホモグリフ)の数字には混ぜない",
          "tag_homoglyph_leak" not in outcomes and "tag_homoglyph_rescued" not in outcomes)

    # ---- 2) 退行していないこと --------------------------------------------------
    print("\n[2] 退行していない= 正しい名乗り・ホモグリフは従来どおり")
    out2, rec2 = run_strip("[一ノ瀬怜]\n本文です。", "platform-se", "一ノ瀬怜")
    check("正しい名乗りは今までどおり落ちる", out2 == "本文です。")
    check("正しい名乗りは tag_solo_fixed のまま(新種を混ぜない)",
          [o for o, _ in rec2] == ["tag_solo_fixed"])
    # 丙の実物= hr-room の `ККール`(先頭2字がキリル К U+041A)
    out3, rec3 = run_strip("[ККール]\nおはよう。", "hr-room", "ククール")
    check("ホモグリフ(ККール)は今までどおり落ちる", out3 == "おはよう。")
    check("ホモグリフは丙(tag_homoglyph_*)のまま",
          [o for o, _ in rec3] == ["tag_homoglyph_leak", "tag_homoglyph_rescued"])

    # ---- 3) 広げ過ぎていないこと ------------------------------------------------
    print("\n[3] 広げ過ぎていない= 本文中のタグ・遠い名前・多人格部屋へは効かない")
    for _tag in ("検証", "実物", "WIP", "注意", "参考"):
        o, r = run_strip(f"[{_tag}]\n本文です。", "platform-se", "一ノ瀬怜")
        check(f"本文中の [{_tag}] は触らない・数えない", o.startswith(f"[{_tag}]") and not r)
    _n = names_of("platform-se", "一ノ瀬怜")
    check("同スクリプトで距離2(一ノ背玲)は救わない= 別の名前を拾わない",
          dd._homoglyph_near("一ノ背玲", _n, allow_same_script=True) is None)
    check("同スクリプトで距離1(一ノ瀬玲)は救う= 1字ずれの誤字は拾う",
          dd._homoglyph_near("一ノ瀬玲", _n, allow_same_script=True) == "一ノ瀬怜")
    check("★既定(引数なし)では従来どおり同スクリプトを拾わない= 既存の呼び出し元は不変",
          dd._homoglyph_near("一ノ怜", _n) is None)
    check("★多人格部屋の門(_homoglyph_unique)へは波及しない(C-035不変)",
          dd._homoglyph_unique("一ノ怜", _n) is None)
    check("_audit_homoglyph も既定では同スクリプトを数えない",
          dd._audit_homoglyph("platform-se", "一ノ怜", _n, "[一ノ怜]") is False)

    # ---- 4) must-fail: foreign-script 必須へ戻した変異体(C-053) -----------------
    print("\n[4] must-fail: 2026-09-13以前の実装(foreign-script 必須)へ戻す")
    keep_near = dd._homoglyph_near

    def _mutant(tag, names, allow_same_script=False):
        """救済条件に foreign-script を必ず要求した版(=穴が開いていた頃の実装)。"""
        return keep_near(tag, names, allow_same_script=False)

    dd._homoglyph_near = _mutant
    try:
        out_m, rec_m = run_strip(REAL, "platform-se", "一ノ瀬怜")
        check("★変異体では実物が再び素通しになる(=①の緑は今回の変更のおかげだと証明)",
              "[一ノ怜]" in out_m)
        check("★変異体では計器にも1行も映らない(穴の三重構造そのもの)", not rec_m)
        out_h, rec_h = run_strip("[ККール]\nおはよう。", "hr-room", "ククール")
        check("★変異体でもホモグリフは落ちたまま(壊したのは同スクリプト側だけ)",
              out_h == "おはよう。" and [o for o, _ in rec_h][:1] == ["tag_homoglyph_leak"])
    finally:
        dd._homoglyph_near = keep_near
    out_b, rec_b = run_strip(REAL, "platform-se", "一ノ瀬怜")
    check("戻した後は再び落ちる", "[一ノ怜]" not in out_b and len(rec_b) == 2)


# ---- 6) ★本番の監査台帳へ1バイトも書かない(2026-09-13 に2回踏んだ穴) -------------
def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return -1


PROD = [persona_render.RENDER_AUDIT,
        os.path.join(dd.LOCAL, "llm", "send_audit.jsonl"),
        os.path.join(dd.LOCAL, "llm", "wait_guard.jsonl"),
        os.path.join(dd.LOCAL, "llm", "scope_guard.jsonl")]
_before = {p: _size(p) for p in PROD}

main()

print("\n[5] ★この検査が本番の監査台帳を汚さない(C-038= 同型の再発を止める)")
for _p in PROD:
    check(f"{os.path.basename(_p)} のバイト数が増えていない", _size(_p) == _before[_p])

ok = sum(1 for _, c in results if c)
print(f"\n=== {ok}/{len(results)} PASS ===")
for name, c in results:
    if not c:
        print(f"  FAIL: {name}")
sys.exit(0 if ok == len(results) else 1)
