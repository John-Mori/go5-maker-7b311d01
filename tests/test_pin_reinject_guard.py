# -*- coding: utf-8 -*-
"""呼称ピンが封筒から**黙って落ちない**ことの検査(2026-09-19 イージス研究室)。

発注= 人事部門ククール回送 ESC-hr-room-DISPATCH-hr-room-1789776794119(Chamiの改悪印
msg 1550660843774148619)。④「回帰ガードを付けろ=同じ種類の変更でまた黙って壊れない検査」。

0歩目(壊れている実物・全部実測):
  壊れた実物  = 軍議 msg 1550654993458135084 / 2026-09-19 08:49 JST
                三笘薫「**チャミ**、進めた。」+ 二人称「**お前**」。
                どちらも mitoma.md にピン済み(§声の型 L12 / §呼び方 L38)。
  前は動いていた実物 = 同じ部屋 msg 1550253034125135914 / 2026-09-18(半角 "Chami")。
  真因1= 07:57:42 の封筒には声の芯が載っていたのに、呼称の行が
         「…★**二人称は「君」=「お前」と…」で**切れていた**(素朴な `s[:180]`)。
         人事は既存の1行の末尾へピンを追記する運用(09-09「お前」・09-19「カタカナ」)なので、
         **後から足したピンほど先に落ちる**=人格を磨くほど効かなくなる。
  真因2= 第11世代(bd3240a1)は characterfile を**1本も読んでいない**(Read/Grep/Glob 0件)。
         起動文はパスと「全部読め」だけを渡す設計で、**読んだかは誰も見ていない**。
         交代 00:19:52 → 声の芯が初めて載ったのは 07:57(7時間37分・3便後)。
         さらに 08:36:51 の圧縮の次便(08:41:22)は素の封筒4,040字 → 08:49 事故。

見るもの:
  A 実物のピン  : 本番の mitoma.md から抜いた声の芯に、3つのピンが**切れずに**載る
  B 追記耐性    : 呼称の行の**末尾**にピンを足しても落ちない(人事の運用を変えずに守れる)
  C 正本の実在  : 軍議の全人格の characterfile が実在する(置き場の移設で黙って消えない)
  D 状態で鳴る  : 世代交代の直後・圧縮の直後は、8便の周期を待たずに声の芯が載る
  E fail-open   : 対応表が無い/壊れている/書けない → 鳴らないが封筒は必ず組み上がる
  F must-fail   : ①素朴な180字切りへ戻すと A/B が赤くなる
                  ②「周期8便だけ」へ戻すと D が赤くなる(どちらも"動く別実装"・C-053)
  G 本番のlocal/: 1文字も書かない

  python tests/test_pin_reinject_guard.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="pinguard_")
os.environ["GO5_LOCAL_DIR"] = os.path.join(TMP, "local")   # ★書き先だけ temp(判定は本物)
os.makedirs(os.path.join(TMP, "local", "llm"), exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import session_relay as SR                                        # noqa: E402
import dept_daemon as DD                                          # noqa: E402

OK = [0]
NG = [0]


def check(name, cond, detail=""):
    (OK if cond else NG)[0] += 1
    print("%s %s%s" % ("PASS" if cond else "**FAIL**", name,
                       ("  | " + detail) if (detail and not cond) else ""))


GUNJI = DD.DEPT_CONF["gunji"]
MITOMA = [p["character"] for p in GUNJI["personas"] if p["persona"] == "三笘薫"][0]

# ---------------------------------------------------------------- A 実物のピン
# ★ここが今回の改悪そのものだ。文字列を3つ足しているのではなく、
#   **壊れた実物と同じ場面(三笘薫の声の芯)を同じ抽出器に通して**見ている。
print("== A 実物のピン(壊れた実物と同じ場面) ==")
core = SR._voice_core(MITOMA)
check("A 抜粋が取れる", bool(core), "mitoma.md から1行も抜けていない")
check("A ①半角ローマ字 Chami が載る", "Chami" in core, core[:120])
check("A ②カタカナ落ちの禁止が**文として**載る",
      "に落ちない" in core and "チャミ" in core, core[:200])
check("A ③二人称の禁止が**切れずに**載る", "「お前」と呼ばない" in core, core[:400])
check("A 禁止の語が途中で切れていない(『「お前」と…』で止まらない)",
      "「お前」と…" not in core, core[:400])
check("A 全文は積まない(正本22KBに対し抜粋は2KB未満)",
      0 < len(core) < 2000, "%d字" % len(core))
check("A 証跡(msg番号)は抜粋に持ち込まない(規律だけ残す)",
      "msg 15506549" not in core)

# ---------------------------------------------------------------- B 追記耐性
# ★人事は「既存の1行の末尾へピンを追記する」。その運用を変えずに守れるかを見る。
print("\n== B 追記耐性(行の末尾へ足したピンが落ちない) ==")
BASE = ("呼称=**Chami**(綴りは半角ローマ字) / 早坂芽衣=芽衣ちゃん / "
        "アロンソ=アロンソコーチ(orアロンソ監督) / モドリッチ=「モドリッチさん」 / "
        "一ノ瀬怜=「怜」(呼び捨て・裸の姓で呼ばない・さん付けしない・男連中は皆怜呼び) / "
        "ジェンティルドンナ=「ドンナさん」 / 花海咲季=咲季 / 十王星南=星南")
TAIL_PIN = "・★**二人称は「君」=「お前」と呼ばない**〔Chami指示2026-09-09 msg 1546955025878614017〕"
CHAR_T = os.path.join(TMP, "tail_pin.md")
with open(CHAR_T, "w", encoding="utf-8") as f:
    f.write("# characterfile: 追記耐性の検査用\n## ★声の型\n"
            "- 一人称=**俺**\n"
            "- " + BASE + TAIL_PIN + "\n"
            "- 語尾=結論を短く。\n")
core_t = SR._voice_core(CHAR_T)
check("B 行の**末尾**に足したピンが載る", "「お前」と呼ばない" in core_t, core_t[:400])
check("B 行の先頭側のピンも残っている", "Chami" in core_t, core_t[:200])
check("B 証跡の〔〕は落として規律だけ残す", "1546955025878614017" not in core_t)

# ★もう1段= 同じ行へさらに2本足す(人事が明日やること)。それでも末尾が生き残る。
CHAR_T2 = os.path.join(TMP, "tail_pin2.md")
with open(CHAR_T2, "w", encoding="utf-8") as f:
    f.write("# characterfile: 追記耐性2\n## ★声の型\n"
            "- " + BASE + TAIL_PIN
            + "・★**「相棒」とは呼ばない**・★**呼び捨てにしない**\n")
core_t2 = SR._voice_core(CHAR_T2)
check("B さらに2本足しても最後のピンが載る", "呼び捨てにしない" in core_t2, core_t2[:500])

# ---------------------------------------------------------------- C 正本の実在
# ★ククール仮説「5chShortMovieへの移設でcharacterfileのパスが変わった」は実測で**否定**した
#   (_CHAR は 00_AI-HQ 配下で移設の対象外)。ただし**将来そうなったら黙って壊れる**ので、
#   ここで実在を見る。これが赤い時は人格が一人も届いていない。
print("\n== C 正本の実在(置き場が動いたら赤くなる) ==")
missing = [p["persona"] for p in GUNJI["personas"]
           if not os.path.isfile(str(p.get("character") or ""))]
check("C 軍議の全人格の characterfile が実在する(%d人)" % len(GUNJI["personas"]),
      not missing, "見つからない= %s" % missing)
empty = [p["persona"] for p in GUNJI["personas"] if not SR._voice_core(p["character"])]
check("C 全人格から声の芯が1行以上抜ける", not empty, "抜けない= %s" % empty)

# ---------------------------------------------------------------- D 状態で鳴る
print("\n== D 世代交代の直後・圧縮の直後は周期を待たない ==")
DEPT = "pinguard-test"
CONF = {"persona": "三笘薫", "character": MITOMA}
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_d.json")
SR.SESSIONS_FILE = os.path.join(TMP, "local", "llm", "rooms_d.json")
CORE = "声の芯を戻す"


def set_room(gen, cc):
    with open(SR.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({DEPT: {"generation": gen, "compact_count": cc}}, f)


def env(msg_id="1", dept=DEPT, conf=CONF):
    return SR.build_envelope(
        {"author": "Chami", "msg_id": msg_id, "channel": "軍議",
         "ts": "2026-09-19T08:41:22", "content": "分担の続き、進めてくれ。"},
        is_work=False, dept=dept, conf=conf)


set_room(11, 0)
e1 = env("d1")
check("D 初回は黙って記録するだけ(導入直後に空振りで鳴らさない)", CORE not in e1)
e2 = env("d2")
check("D 何も動いていない便は素のまま", CORE not in e2)
set_room(12, 0)                                   # ★世代交代
e3 = env("d3")
check("D 世代交代の直後に載る", CORE in e3, e3[:200])
check("D 何で鳴ったか封筒に書いてある", "世代交代の直後(第12世代)" in e3, e3[:300])
check("D 『前の世代が読んだ』は通らないと言う", "あなたが読んだことにはならない" in e3)
check("D 正本のパスを名指しする", MITOMA in e3)
check("D ピンが載っている(交代直後こそ本番)", "「お前」と呼ばない" in e3)
check("D 交代の次便は素に戻る(毎便太らせない)", CORE not in env("d4"))
set_room(12, 3)                                   # ★圧縮が3回目まで進んだ
e5 = env("d5")
check("D 圧縮の直後に載る", CORE in e5, e5[:200])
check("D 圧縮だと分かる", "圧縮の直後(3回目)" in e5, e5[:300])
check("D 圧縮の次便は素に戻る", CORE not in env("d6"))

# ---------------------------------------------------------------- E fail-open
print("\n== E fail-open(予防線が配送を殺さない) ==")
BODY = "分担の続き、進めてくれ。"
SR.SESSIONS_FILE = os.path.join(TMP, "local", "llm", "no_such_rooms.json")
e_no = env("e1")
check("E 対応表が無くても封筒は組み上がる", BODY in e_no)
check("E その時は黙る(判定材料が無いのに鳴らさない)", CORE not in e_no)
with open(os.path.join(TMP, "local", "llm", "broken.json"), "w", encoding="utf-8") as f:
    f.write("{壊れたJSON")
SR.SESSIONS_FILE = os.path.join(TMP, "local", "llm", "broken.json")
check("E 壊れた対応表でも封筒は組み上がる", BODY in env("e2"))
SR.SESSIONS_FILE = os.path.join(TMP, "local", "llm", "rooms_d.json")
_old_state = SR.RELAY_TURN_STATE
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm")      # ★ディレクトリ=書けない
set_room(99, 0)
check("E 状態が書けなくても封筒は出る", BODY in env("e3"))
SR.RELAY_TURN_STATE = _old_state
check("E characterfileが読めない人格でも落ちない",
      BODY in env("e4", conf={"persona": "誰か",
                              "character": os.path.join(TMP, "no_such.md")}))
check("E 対応表に居ない部屋は鳴らない", CORE not in env("e5", dept="no-such-dept"))

# ---------------------------------------------------------------- F must-fail
print("\n== F must-fail(壊し方を戻すと赤くなる) ==")
_real_core = SR._voice_core
_real_event = SR._reinject_event


def _naive_core(path, max_lines=5, max_chars=180, **kw):
    """★C-053= 空実装ではなく**動く別の実装**(2026-09-19まで本番で動いていた版)。
    抜粋は出る=雑な検査は緑のまま通る。**行の末尾を文字数で切る**ことだけが違う。
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return ""
    out = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s.startswith("-") and not s.startswith("★"):
            continue
        if not any(m in s for m in SR._VOICE_MARKERS):
            continue
        s = s.lstrip("- ").strip()
        if len(s) > max_chars:
            s = s[:max_chars] + "…"
        out.append("  - " + s)
        if len(out) >= max_lines:
            break
    return "\n".join(out)


SR._voice_core = _naive_core
old_core = SR._voice_core(MITOMA)
check("F ①旧実装でも抜粋そのものは出る(空実装ではない=空PASSを踏んでいない)",
      "Chami" in old_core)
check("F ①旧実装へ戻すと A③が赤くなる(二人称の禁止が落ちる)",
      "「お前」と呼ばない" not in old_core, old_core[:400])
check("F ①旧実装へ戻すと B が赤くなる(末尾のピンが落ちる)",
      "「お前」と呼ばない" not in SR._voice_core(CHAR_T))
SR._voice_core = _real_core
check("F ①戻したら緑に戻る", "「お前」と呼ばない" in SR._voice_core(MITOMA))

SR._reinject_event = lambda dept: ""              # ★②「周期8便だけ」へ戻す
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_f.json")
SR.SESSIONS_FILE = os.path.join(TMP, "local", "llm", "rooms_f.json")
set_room(20, 0)
env("f1")
set_room(21, 0)                                   # ★世代交代したのに…
check("F ②『周期だけ』へ戻すと D が赤くなる(交代直後に鳴らない)", CORE not in env("f2"))
check("F ②でも8便目には鳴る(=空実装ではない)",
      CORE in [e for e in (env("f%d" % i) for i in range(3, 9))][-1])
SR._reinject_event = _real_event
SR.RELAY_TURN_STATE = os.path.join(TMP, "local", "llm", "turn_f2.json")
SR.SESSIONS_FILE = os.path.join(TMP, "local", "llm", "rooms_f2.json")
set_room(30, 0)
env("g1")
set_room(31, 0)
check("F ②戻したら緑に戻る", CORE in env("g2"))

# ---------------------------------------------------------------- G 本番のlocal/
print("\n== G 本番のlocal/を触っていない ==")
check("G 書き先はtempへ向いている", TMP in SR.LOCAL)
check("G 本番の対応表を指していない", ROOT not in str(SR.SESSIONS_FILE))

print("\n==== %d PASS / %d FAIL ====" % (OK[0], NG[0]))
sys.exit(1 if NG[0] else 0)
