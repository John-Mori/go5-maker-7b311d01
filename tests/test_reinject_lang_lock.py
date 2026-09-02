# -*- coding: utf-8 -*-
"""4種不具合の恒久策 #1 の検査(2026-09-02 イージス研究室 / 発注= 改善提案部門
`docs/departments/kaizen-analyst/設計_4種不具合恒久策_横断_2026-09-02.md` §2-1生成側・§2-2層1・
回帰ガード §5-3「8ターン進めた擬似会話で封筒の実文字列にリマインダーが載らなければfail」)。

0歩目(壊れている実物): 投入前の封筒には応答言語の固定文が**1文字も無かった**
  (`必ず日本語|日本語で答え|respond in Japanese` の grep が session_relay/dept_daemon で0件)。
  声の芯も起動文の1回きりで、8〜12ターン後には薄れていた(=口調崩れの実測)。

見るもの:
  A 言語固定  : どの便の封筒にも「必ず日本語」が載る(会話便・作業便・部門不明も)
  B 定期再注入: 8便に1回だけ声の芯が載る。1〜7便目には**1文字も足さない**
  C 前倒し    : 直近便で口調が崩れた(tone_audit の event="tone")次便は周期を待たず載る
  D fail-open : characterfile が読めない / conf が無い / 状態ファイルが書けない
                → 何も足さないが封筒は必ず組み上がる(★配送を殺さないのが本丸)
  E 封筒の作法: 本文は1文字も変わらない・再注入は依頼文より**前**に置く
  F must-fail : ①投入前(固定文なし)②「起動時1回だけ注入する」動く別実装(C-053)
                のどちらへ戻しても A/B が赤くなる
  H 同調よけ  : 相手が方言で書いて来た便(実物= 軍議 msg 1544752273253728276)で、
                標準語登録の人格に「同調するな」+声の芯が**崩れる前に**載る
                (2026-09-03 追加 / 種= トトリ msg 1544753745815011444)

  python tests/test_reinject_lang_lock.py
★本番の local/ は触らない(GO5_LOCAL_DIR を temp へ向けてから import する)。
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="reinject_")
os.environ["GO5_LOCAL_DIR"] = os.path.join(TMP, "local")   # ★書き先だけ temp(判定は本物)
os.makedirs(os.path.join(TMP, "local", "llm"), exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import session_relay as SR                                        # noqa: E402

OK = [0]
NG = [0]


def check(name, cond, detail=""):
    (OK if cond else NG)[0] += 1
    print("%s %s%s" % ("PASS" if cond else "**FAIL**", name,
                       ("  | " + detail) if (detail and not cond) else ""))


# --- 素材: 本物の characterfile と同じ書き方をした2枚(声の芯の行だけ拾えるか見る) ---
CHAR_A = os.path.join(TMP, "debruyne_test.md")
CHAR_B = os.path.join(TMP, "ames_test.md")
open(CHAR_A, "w", encoding="utf-8").write(
    "# characterfile: ケヴィン・デブライネ(検査用)\n"
    "## 人格\n"
    "- 名: ケヴィン・デブライネ / モチーフ: 実在のサッカー選手\n"
    "- 呼び方: アロンソコーチ / 怜は呼び捨て\n"
    "- ★**一人称=「俺」**(「僕」「オレ」は使わない)\n"
    "- 口調: 敬語なし。結論を先に言う。\n"
    "- 芯1: 残酷なほど正直\n"
    "- 芯2: 口数で存在を示さない。仕事で示す\n"
    "- 芯3: ドライなユーモアがある\n"
    "## 職務\n- 部門長として配下19室を見る\n")
open(CHAR_B, "w", encoding="utf-8").write(
    "# characterfile: アメス(検査用)\n"
    "## ★声の型\n"
    "- 一人称=「わたし」\n"
    "- 語尾: 「〜だよ」「〜だね」\n")
CONF = {"persona": "ケヴィン・デブライネ", "character": CHAR_A,
        "personas": [{"persona": "アメス", "character": CHAR_B}]}
DEPT = "aegis-gl-test"
BODY = "呼称と口調の恒久策、実装をお願いします。"


def rec(msg_id="1", content=BODY):
    return {"author": "トトリ", "msg_id": msg_id, "channel": "イージス研究室",
            "ts": "2026-09-02T21:00:00", "content": content}


def env(dept=DEPT, conf=CONF, is_work=True, msg_id="1"):
    return SR.build_envelope(rec(msg_id), is_work=is_work, dept=dept, conf=conf)


LANG = "必ず日本語"
CORE = "声の芯を戻す"

# ---------------------------------------------------------------- A 言語固定文
print("== A 応答言語の固定文(投入前は0件だった) ==")
check("A 作業便の封筒に載る", LANG in env(msg_id="a1"))
check("A 会話便の封筒にも載る", LANG in env(is_work=False, msg_id="a2"))
check("A 部門が空でも載る", LANG in env(dept="", conf=None, msg_id="a3"))
_e = env(msg_id="a4")
check("A 依頼文より**前**に置かれている", _e.index(LANG) < _e.index(BODY))
check("A コード・固有名詞は原語のままだと断ってある", "固有名詞" in _e)

# ---------------------------------------------------------------- B 定期再注入
print("\n== B 定期再注入(8便に1回) ==")
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_b.json")
fired = []
for i in range(1, 17):
    e = env(msg_id="b%d" % i)
    if CORE in e:
        fired.append(i)
check("B 8便目と16便目にだけ載る(周期=%d)" % SR.REINJECT_EVERY,
      fired == [8, 16], "載ったのは %s便目" % fired)
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_b2.json")
for i in range(1, 8):
    env(msg_id="b2_%d" % i)
e8 = env(msg_id="b2_8")
check("B 声の芯の中身が載る(一人称)", "一人称=「俺」" in e8, e8[:80])
check("B 2人格とも載る", "ケヴィン・デブライネ" in e8 and "アメス" in e8)
check("B 相方の語尾も載る", "〜だよ" in e8)
check("B 正本のパスを名指ししている", CHAR_A in e8)
check("B 全文は積まない(職務・見出しは持ち込まない)",
      "配下19室を見る" not in e8 and "## 人格" not in e8)
check("B 抜粋だと断って正本を読めと言っている", "正本を読み直せ" in e8)
check("B 定期だと分かる見出し", "%d便に1回" % SR.REINJECT_EVERY in e8)

# ---------------------------------------------------------------- C 前倒し
print("\n== C 崩れた次便は周期を待たない ==")
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_c.json")
SR.TONE_FEEDBACK_STATE = os.path.join(TMP, "local", "llm", "tfs_c.json")
with open(SR.TONE_AUDIT_FILE, "w", encoding="utf-8") as f:
    f.write(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "dept": DEPT, "msg_id": "9999",
        "event": "tone", "reason": "first_person_mismatch", "marker": "僕",
        "persona": "ケヴィン・デブライネ", "own_first_person": ["俺"]}, ensure_ascii=False) + "\n")
e_forced = env(msg_id="c1")                    # ★1便目= 周期では鳴らない番
check("C 崩れた次便は1便目でも載る", CORE in e_forced)
check("C 前倒しだと分かる見出し", "前の便で崩れが出た" in e_forced, e_forced[:80])
check("C 突き返し本体も同じ便に載る(二度手間にしない)", "前の便で口調が崩れた" in e_forced)
e_next = env(msg_id="c2")                      # ★同じ崩れを二度は突き返さない=次便は静か
check("C 二度は前倒ししない(2便目は素の封筒)", CORE not in e_next)
os.remove(SR.TONE_AUDIT_FILE)

# ---------------------------------------------------------------- D fail-open
print("\n== D fail-open(予防線が配送を殺さない) ==")
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_d.json")
bad = {"persona": "誰か", "character": os.path.join(TMP, "no_such_file.md")}
for i in range(1, 8):
    SR.build_envelope(rec("d%d" % i), dept=DEPT, conf=bad)
e_bad = SR.build_envelope(rec("d8"), dept=DEPT, conf=bad)
check("D characterfileが読めない= 見出しごと出さない", CORE not in e_bad)
check("D それでも封筒は組み上がる", BODY in e_bad and LANG in e_bad)
check("D confが無い部門でも落ちない",
      BODY in SR.build_envelope(rec("d9"), dept="no-such-dept", conf=None))
_old = SR.RELAY_TURN_STATE
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm")      # ★ディレクトリ=書けない
check("D 状態ファイルが書けなくても封筒は出る",
      BODY in SR.build_envelope(rec("d10"), dept=DEPT, conf=CONF))
check("D 書けない時は数えられないので黙る",
      CORE not in SR.build_envelope(rec("d11"), dept=DEPT, conf=CONF))
SR.RELAY_TURN_STATE = _old
check("D 壊れた状態ファイルでも落ちない",
      (open(SR.RELAY_TURN_STATE, "w", encoding="utf-8").write("{壊れたJSON"),
       BODY in SR.build_envelope(rec("d12"), dept=DEPT, conf=CONF))[1])

# ---------------------------------------------------------------- E 封筒の作法
print("\n== E 封筒の作法 ==")
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_e.json")
for i in range(1, 8):
    env(msg_id="e%d" % i)
e_full = env(msg_id="e8")
check("E 本文は1文字も変わっていない", BODY in e_full)
check("E 再注入は依頼文より前", e_full.index(CORE) < e_full.index(BODY))
check("E 規律・状態より後ろ(読む順で依頼文の直近)",
      e_full.index("=== Discord新着") - e_full.index(CORE) < 2000)
_quiet = env(msg_id="e9")
check("E 鳴らない便は今までと同じ長さ(毎便太らせない)",
      CORE not in _quiet and len(_quiet) < len(e_full))

# ---------------------------------------------------------------- F must-fail
print("\n== F must-fail ==")
_real_line, _real_fn = SR.LANG_LOCK_LINE, SR._persona_reinject_block

SR.LANG_LOCK_LINE = ""                              # ★① 投入前(固定文が無い状態)
red_a = sum(1 for e in (env(msg_id="f1"), env(msg_id="f2", is_work=False),
                        env(dept="", conf=None, msg_id="f3")) if LANG not in e)
SR.LANG_LOCK_LINE = _real_line
check("F ①固定文を外すと A の3項目が赤くなる", red_a == 3, "赤は%d件" % red_a)


def _boot_only(dept, conf=None, forced=False):
    """★C-053= 空実装ではなく『動く別の実装』へ戻す= 起動時(1便目)に1回だけ注入する版。
    これは"注入している"ので雑な検査は緑のまま通る。8便目に載らないことで初めて落ちる。
    """
    n = SR._bump_relay_turn(dept)
    return _real_fn(dept, conf=conf, forced=True) if n == 1 else ""


SR._persona_reinject_block = _boot_only
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_f.json")
_fired = [i for i in range(1, 17) if CORE in env(msg_id="f%d" % i)]
SR._persona_reinject_block = _real_fn
check("F ②『起動時1回だけ』へ戻すと B が赤くなる", _fired != [8, 16],
      "載ったのは %s便目" % _fired)
check("F ②でも1便目には載っている(=空実装ではない・空PASSを踏んでいない)", _fired == [1])
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_f2.json")
for i in range(1, 8):
    env(msg_id="g%d" % i)
check("F 戻したら緑に戻る", CORE in env(msg_id="g8") and LANG in env(msg_id="g9"))

# ------------------------------------------------- H レジスタ同調(相手の方言がうつる)
# ★2026-09-03 追加。種を渡したのは改善提案部門トトリ(研究室HQ経由 msg 1544753745815011444)=
#   「§2-2層1の must-fail に、この軍議便を『相手が関西弁→標準語人格が同調』の回帰ケースとして
#     1本足してほしい」。新規発注ではなく既発注 #1/§2-2層1 の中。
# ★実物(本番で出た。作り物ではない):
#   入力 = 軍議 msg 1544752273253728276 / 2026-09-03 / chami_fusoh
#          「ジェンティルドンナ:表には流しません→流しとるやないかい(ツッコミ)」
#   壊れた出力 = 標準語登録の三笘薫が「ははっ、ほんまや。…なんよ。」と関西弁で返した
#          (tone_audit.jsonl に dialect_kansai 3マーカー・tone_rewrite は ok:false=直らず届いた)
# ★見るもの= 崩れた**後**の突き返しではなく、崩れる**前**に封筒へ同調よけが載るか。
print("\n== H レジスタ同調(相手が関西弁→標準語人格が同調) ==")
KANSAI_IN = "ジェンティルドンナ:表には流しません→流しとるやないかい(ツッコミ)"
PLAIN_IN = "この構成、表に出す分と裏に置く分の線引きを整理しておいてください。"
MIRROR = "同調するな"
# ★人格は**本番の口調ルール.json に実在する三笘薫**を使う(写像は読むだけ・1文字も書かない)。
#   characterfile は再注入の素材なので検査用の1枚で足りる。
CHAR_M = os.path.join(TMP, "mitoma_test.md")
open(CHAR_M, "w", encoding="utf-8").write(
    "# characterfile: 三笘薫(検査用)\n## 声の型\n"
    "- 一人称=「俺」\n- 口調: 標準語。方言は使わない。\n")
CONF_M = {"persona": "三笘薫", "character": CHAR_M}
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_h.json")
SR.TONE_FEEDBACK_STATE = os.path.join(TMP, "local", "llm", "tfs_h.json")


def env_h(content, msg_id="h", conf=CONF_M, dept="gunji"):
    return SR.build_envelope(rec(msg_id, content), is_work=False, dept=dept, conf=conf)


_rules_h = None
try:
    import tone_gate as TG_H                                       # noqa: E402
    _rules_h = TG_H.load_tone_rules(SR.TONE_RULES_PATH)
except Exception:
    pass
_ent_h = TG_H._persona_entry(_rules_h, "三笘薫") if _rules_h else None
check("H 前提: 三笘薫は口調ルール.jsonに**標準語**で登録されている",
      bool(_ent_h) and not _ent_h.get("dialect_ok"),
      "登録が見つからない/dialect_ok が立っている= 人事側の写像が変わった(検査の前提が崩れた)")

e_k = env_h(KANSAI_IN, "h1")
check("H 相手が関西弁の便には同調よけが載る", MIRROR in e_k, e_k[:120])
check("H 何に当たったかを言う(数え直せる形で)", "やない" in e_k, e_k[:200])
check("H 相手の本文より**前**に置く(読む順で効く位置)",
      MIRROR in e_k and e_k.index(MIRROR) < e_k.index(KANSAI_IN))
check("H 崩れる前でも声の芯を前倒しで戻す(層1が受け皿・1便目から)", CORE in e_k)
check("H 本文は1文字も変わっていない", KANSAI_IN in e_k)
e_p = env_h(PLAIN_IN, "h2")
check("H 相手が標準語なら1文字も足さない(毎便太らせない)",
      MIRROR not in e_p and len(e_p) < len(e_k))

# ★方言が正の人格(人事が `dialect_ok` を立てた人格)の部屋では鳴らない= 判定材料は写像1本。
_real_entry = TG_H._persona_entry
TG_H._persona_entry = lambda rules, persona: {"first_person": ["俺"], "dialect_ok": True}
check("H dialect_ok の人格には鳴らない", MIRROR not in env_h(KANSAI_IN, "h3"))
TG_H._persona_entry = lambda rules, persona: None
check("H 未登録だけの部屋では鳴らない(tone_verdictsと同じ作法)",
      MIRROR not in env_h(KANSAI_IN, "h4"))
TG_H._persona_entry = _real_entry
check("H 戻したら鳴る", MIRROR in env_h(KANSAI_IN, "h5"))

print("\n== H fail-open / must-fail ==")
_real_rules = TG_H.load_tone_rules
TG_H.load_tone_rules = lambda p: (_ for _ in ()).throw(RuntimeError("写像が壊れている"))
_e_bad = env_h(KANSAI_IN, "h6")
check("H 写像が読めなくても封筒は組み上がる(fail-open)",
      KANSAI_IN in _e_bad and LANG in _e_bad)
check("H その時は黙る(判定材料が無いのに鳴らさない)", MIRROR not in _e_bad)
TG_H.load_tone_rules = _real_rules

_real_mirror = SR._register_mirror_hint
SR._register_mirror_hint = lambda rec, dept=None, conf=None: ""   # ★① 投入前の状態へ戻す
check("H ①予防線を外すと H の本線が赤くなる", MIRROR not in env_h(KANSAI_IN, "h7"))


def _after_the_fact(rec, dept=None, conf=None):
    """★C-053= 空実装ではなく『動く別の実装』へ戻す= **自分が既に崩れた後**に鳴らす版
    (tone_audit に自室の dialect_kansai が在る時だけ鳴らす=既設の突き返しと同じ土俵)。
    これは"鳴っている"ので雑な検査は緑のまま通る。**崩れる前の便で鳴らない**ことで初めて落ちる。
    """
    try:
        with open(SR.TONE_AUDIT_FILE, encoding="utf-8") as f:
            hit = any('"dialect_kansai"' in ln and ('"%s"' % dept) in ln for ln in f)
    except Exception:
        hit = False
    return _real_mirror(rec, dept=dept, conf=conf) if hit else ""


SR._register_mirror_hint = _after_the_fact
_e_pre = env_h(KANSAI_IN, "h8")                       # ★まだ1度も崩れていない状態
with open(SR.TONE_AUDIT_FILE, "w", encoding="utf-8") as f:        # ★崩れた後
    f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "dept": "gunji",
                        "msg_id": "1544752273253728276", "event": "tone",
                        "reason": "dialect_kansai", "marker": "ほんま",
                        "persona": "三笘薫"}, ensure_ascii=False) + "\n")
_e_post = env_h(KANSAI_IN, "h9")
check("H ②『崩れた後だけ鳴る』版へ戻すと、崩れる前の便で赤くなる", MIRROR not in _e_pre)
check("H ②でも崩れた後には鳴る(=空実装ではない・空PASSを踏んでいない)", MIRROR in _e_post)
os.remove(SR.TONE_AUDIT_FILE)
SR._register_mirror_hint = _real_mirror
check("H 戻したら緑に戻る", MIRROR in env_h(KANSAI_IN, "h10"))

# ---------------------------------------------------------------- G 本番のlocal/
print("\n== G 本番のlocal/を触っていない ==")
check("G 書き先はtempへ向いている", TMP in SR.LOCAL and TMP in SR.RELAY_TURN_STATE)
check("G 本番のturn stateを作っていない",
      not os.path.exists(os.path.join(ROOT, "local", "llm", "relay_turn_state.json"))
      or TMP not in os.path.join(ROOT, "local"))

print("\n==== %d PASS / %d FAIL ====" % (OK[0], NG[0]))
sys.exit(1 if NG[0] else 0)
