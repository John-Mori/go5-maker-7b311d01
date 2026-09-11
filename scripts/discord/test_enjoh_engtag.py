#!/usr/bin/env python3
"""本文へ漏れた制御タグ/英語段落を合流点で止める検査(2026-09-11 イージス研究室)。

発注= 改善提案部門トトリ(DISPATCH-aegis-gl-1789090853313)。実物= system-engineer の
msg 1547703386911285425(オタコン)。Chami が **恒久+再発** を二重スタンプした投稿は3層だった:
    日本語本文 + `<system>WIPは付けない。実際に調べる。</system>` + 末尾の英語1文
    `Let me investigate the data source behind the roster.`
★「英語が本文へそのまま出る」は 08-14 から少なくとも6波・平均5日に1回で、**全DEFが open**
  = 心がけでは一度も止まっていない。だから機械で止める。その機械がこの検査の対象。

何を担保するか:
  A 実物と同じ3層の本文を**合流点(enjoh_backstop)へ実際に通し**、2層が剥げて日本語本文が
    1字も欠けないこと。
  B 触らない側(誤発火する安全網は無視される・規律§3)= コード柵内 / 日本語混じり段落 /
    まるごと英語の便 / 名乗りタグ入り / 剥ぐと本文が死ぬ便。
  C 配線= 5口の合流点 enjoh_backstop と、6つ目の口 dispatch.enjoh_gate_pass(C-064)。
    ★dispatch には**制御タグ剥ぎだけ**通す。封筒には英語の原文引用が普通に載るため。
  D lang_gate.strip_english_paragraphs の純関数としての振る舞い。
  E must-fail= **改修前の .bak をそのまま読み込んで**、同じ本文が漏れるのを毎回その場で見る。
    (0歩目に壊れている側を見る/落ちるのを見る/直す/PASSを見る= 規律§3)

実行: python scripts/discord/test_enjoh_engtag.py (全PASSで exit 0)
★Discordへは1件も出さない。外の口は1つも叩かない(純関数と配線だけを見る検査)。
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "llm"))

P = F = 0


def ok(cond, name):
    global P, F
    if cond:
        P += 1
        print("PASS", name)
    else:
        F += 1
        print("FAIL", name)


def load_file(name, path, replace_from=None, replace_to=None):
    """任意のファイル(.bak を含む)を**動くモジュール**として読み込む。

    replace_* を渡すと一部を別の実装へ差し替える(文法は壊さない= 行を消すと偽の緑になる)。
    """
    src = io.open(path, encoding="utf-8").read()
    if replace_from is not None:
        assert replace_from in src, f"変異の当たり所が無い: {name}"
        src = src.replace(replace_from, replace_to)
    tmp = tempfile.mkdtemp(prefix="engtag_")
    p = os.path.join(tmp, name + ".py")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod, tmp


import enjoh  # noqa: E402
import lang_gate  # noqa: E402

# 実物の再現(3層)。日本語本文はオタコンの投稿の骨格をそのまま使う。
JP_BODY = ("名簿の件、data.js の版ずれを直した。selfcheck を足したので同じ形では再発しない。\n"
           "persona-hub 側の反映は改修αで持つ。")
SYS_TAG = "<system>WIPは付けない。実際に調べる。</system>"
EN_TAIL = "Let me investigate the data source behind the roster."
REAL = JP_BODY + "\n\n" + SYS_TAG + "\n\n" + EN_TAIL

# --- A 実物を合流点へ通す -------------------------------------------------------------
out = enjoh.enjoh_backstop(REAL, tag="test", quiet=True)
ok("<system>" not in out and "</system>" not in out, "A-1 制御タグの札が残らない")
ok("WIPは付けない" not in out, "A-1 制御タグの中身(運転指示)も残らない")
ok("Let me investigate" not in out, "A-2 末尾の英語段落が残らない")
ok("data.js の版ずれを直した" in out and "persona-hub 側の反映は改修αで持つ" in out,
   "A-3 日本語本文は1字も欠けない")
ok("\n\n\n" not in out and out == out.strip(), "A-3 剥いだ跡の空行が畳まれている")

# A-4 英語が**中間**に居る便(末尾だけの実装だと抜ける)。
mid = ("先に結論を書く。名簿は直っている。\n\n" + EN_TAIL + "\n\n"
       "残りは persona-hub の反映待ちだ。今日中に見る。")
out_mid = enjoh.enjoh_backstop(mid, tag="test", quiet=True)
ok("Let me investigate" not in out_mid and "名簿は直っている" in out_mid
   and "反映待ちだ" in out_mid, "A-4 中間の英語段落も剥ぐ(末尾専用ではない)")

# A-5 閉じ損ねた片割れの札= 札だけ落として中身は残す(本文を巻き添えにしない)。
lone = "名簿の件は直した。selfcheck も足してある。\n<system>\nこの行は本文として読める内容だ。"
out_lone = enjoh.enjoh_backstop(lone, tag="test", quiet=True)
ok("<system>" not in out_lone and "この行は本文として読める内容だ。" in out_lone,
   "A-5 片割れの札だけ落とし、中身は消さない")

# --- B 触らない側(誤発火しない) -------------------------------------------------------
fenced = ("この漏れ方だ。原文をそのまま貼る:\n\n```\n" + SYS_TAG + "\n" + EN_TAIL
          + "\n```\n\n見ての通り2層が混ざっている。ここを機械で止める。")
ok(enjoh.enjoh_backstop(fenced, tag="test", quiet=True) == fenced,
   "B-1 コード柵の中は1ミリも変えない(実物を見せる面がある)")

inline = "本文に `<system>` が出ていた。英語も `Let me investigate the data source.` が出た。"
ok(enjoh.enjoh_backstop(inline, tag="test", quiet=True) == inline,
   "B-1 インラインcodeの中も変えない")

mixed = ("結論から言う。名簿は直っている。\n\n"
         "Let me investigate the data source behind the roster. ← これが漏れた英語だ。\n\n"
         "同じ形は selfcheck で止まる。")
ok(enjoh.enjoh_backstop(mixed, tag="test", quiet=True) == mixed,
   "B-2 日本語が1字でも在る段落は触らない")

all_en = ("Let me investigate the data source behind the roster.\n\n"
          "I will report back once the selfcheck finishes running.")
ok(enjoh.enjoh_backstop(all_en, tag="test", quiet=True) == all_en,
   "B-3 まるごと英語の便は触らない(english_gate/再生成の持ち場・握り潰さない)")

named = ("[アメス] Let me investigate the data source behind the roster right now.\n\n"
         "名簿の件はこちらで見るから、少し休みなさいね。無理はしないで。")
ok(enjoh.enjoh_backstop(named, tag="test", quiet=True) == named,
   "B-4 名乗りタグ [..] を含む段落は剥がない(1行目が壊れると監査ごと抜ける)")

thin = "了解。\n\n" + EN_TAIL
ok(enjoh.enjoh_backstop(thin, tag="test", quiet=True) == thin,
   "B-5 剥ぐと日本語が20字未満になる便は触らない(空の本文を作らない)")

cmdish = ("この手順で直す。\n\n"
          "python scripts/hr/persona_settings_index.py --rebuild --out docs/data.js\n\n"
          "そのあと Pages へ出す。")
ok(enjoh.enjoh_backstop(cmdish, tag="test", quiet=True) == cmdish,
   "B-6 コマンド/パスの塊は散文ではない=剥がない")

urlish = ("参照はここだ。\n\n"
          "https://example.invalid/departments/hr/characters/ROSTER.md#learning-coach\n\n"
          "名簿の正本はこの1本にする。")
ok(enjoh.enjoh_backstop(urlish, tag="test", quiet=True) == urlish, "B-6 URL単体の段落も剥がない")

ok(enjoh.enjoh_backstop("", tag="test", quiet=True) == ""
   and enjoh.enjoh_backstop(None, tag="test", quiet=True) is None,
   "B-7 空文字/Noneで落ちない(fail-open)")

plain = "名簿は直した。persona-hub の反映は改修αが持つ。今日はここまでだ。"
ok(enjoh.enjoh_backstop(plain, tag="test", quiet=True) == plain,
   "B-7 普通の日本語の便は1ミリも変えない")

# --- C 配線(合流点1本 + 6つ目の口) ----------------------------------------------------
names = enjoh.enjoh_backstop.__code__.co_names
ok("control_tag_scrub" in names, "C-1 enjoh_backstop が制御タグ剥ぎを呼ぶ")
ok("english_para_scrub" in names, "C-1 enjoh_backstop が英語段落剥ぎを呼ぶ")
ok("filler_line_scrub" in names and "fire_normalize" in names,
   "C-1 既存の2枚(フィラー行/炎上表記)の配線が残っている")
ok("strip_english_paragraphs" in enjoh.english_para_scrub.__code__.co_names,
   "C-1 判定の正本は lang_gate の1本(写しを作っていない=ORG-11)")

import dispatch  # noqa: E402

dnames = dispatch.enjoh_gate_pass.__code__.co_names
ok("control_tag_scrub" in dnames, "C-2 dispatch の口も制御タグ剥ぎを呼ぶ(C-064)")
ok("english_para_scrub" not in dnames and "filler_line_scrub" not in dnames,
   "C-2 dispatch には英語段落/フィラー行を当てない(封筒の引用を消さない)")
env = "【依頼】名簿の件。原文は下記。\n\n" + SYS_TAG + "\n\n" + EN_TAIL
denv = dispatch.enjoh_gate_pass(env, "dummy")
ok("<system>" not in denv and "WIPは付けない" not in denv, "C-2 封筒からも制御タグは剥げる")
ok("Let me investigate" in denv, "C-2 封筒の英語引用は残る(依頼の情報を消さない)")

# --- D lang_gate の純関数 --------------------------------------------------------------
two = (JP_BODY + "\n\n" + EN_TAIL + "\n\n目下の宿題はここまでだ。\n\n"
       "I will report back once the selfcheck finishes running on the roster.")
o2, i2 = lang_gate.strip_english_paragraphs(two)
ok(i2["stripped"] == 2 and "Let me investigate" not in o2 and "I will report" not in o2,
   "D-1 英語段落は2つとも剥げる(最初の1つで止まらない)")
ok(i2["removed_latin"] > 70 and len(i2["excerpts"]) == 2, "D-1 監査の数字が付いてくる")
ok("目下の宿題はここまでだ。" in o2, "D-1 間に挟まった日本語段落は残る")
o3, i3 = lang_gate.strip_english_paragraphs(plain)
ok(o3 == plain and i3["stripped"] == 0, "D-2 剥ぐ物が無ければ入力と同一を返す")
ok(lang_gate.strip_english_paragraphs(None)[0] is None, "D-2 Noneで落ちない(fail-safe)")
# D-3 位置の取り方(_mask_code_spans は長さを保存する= index は原文基準)。
sp = lang_gate._english_paragraph_spans(REAL)
ok(len(sp) == 1 and REAL[sp[0]["start"]:sp[0]["end"]] == EN_TAIL,
   "D-3 span が原文の英語段落をぴたりと指す")

# --- E must-fail: 改修前の .bak をそのまま読み込んで漏れるのを見る -----------------------
_tmps = []
old_lang, t1 = load_file("lang_gate_old", os.path.join(ROOT, "llm", "lang_gate.py.bak_20260911_engtag"))
_tmps.append(t1)
old_enjoh, t2 = load_file("enjoh_old", os.path.join(HERE, "enjoh.py.bak_20260911_engtag"))
_tmps.append(t2)

old_out = old_enjoh.enjoh_backstop(REAL, tag="test", quiet=True)
ok("<system>" in old_out, "E-1 must-fail 改修前は制御タグがそのまま出る(=Aは効いている)")
ok("Let me investigate" in old_out, "E-2 must-fail 改修前は英語段落がそのまま出る")
ok(not hasattr(old_lang, "strip_english_paragraphs"),
   "E-3 must-fail 改修前は剥ぐ手が存在しない(検知だけだった)")
ok(old_lang.detect_english_paragraph(REAL) is not None,
   "E-3 must-fail ★改修前も**検知はしていた**= 死角は閾値ではなく『除去へ配線が無い』形だった")
ok(old_lang.detect_english_dump(REAL) is None
   and old_lang.strip_english_preamble(REAL)[1]["stripped"] is False
   and old_lang.detect_latin_midband(REAL) is None,
   "E-3 must-fail 他の3枚は改修前も今も鳴らない(この本文の死角の実測)")

# E-4 変異: 「日本語が1字でも在れば触らない」を外すと、B-2の混在段落が壊れる。
mut, t3 = load_file(
    "lang_gate_mut", os.path.join(ROOT, "llm", "lang_gate.py"),
    "            if not body or _JP_RE.search(body):\n                continue                       # 日本語が1文字でも在る段落は触らない",
    "            if not body:\n                continue                       # 変異: 日本語混じりも剥ぐ")
_tmps.append(t3)
ok(mut.strip_english_paragraphs(mixed)[1]["stripped"] > 0,
   "E-4 must-fail 日本語混じりを許すと B-2 が壊れる(=安全弁は本当に効いている)")

# E-5 変異: 残りの日本語量の下限を外すと、B-5の薄い便から本文が消える。
mut2, t4 = load_file(
    "lang_gate_mut2", os.path.join(ROOT, "llm", "lang_gate.py"),
    "        if len(_JP_RE.findall(out)) < min_jp_left:",
    "        if False:  # 変異: 残りが薄くても剥ぐ")
_tmps.append(t4)
ok(mut2.strip_english_paragraphs(thin)[1]["stripped"] > 0,
   "E-5 must-fail 下限を外すと薄い便まで削る(=B-5は本当に効いている)")

for t in _tmps:
    shutil.rmtree(t, ignore_errors=True)

print(f"\n{P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
