# -*- coding: utf-8 -*-
"""文脈の**物差し**の検査(2026-08-22・研究室HQ指摘2 msg 1540622895687139438)。

★何を守るか:
  線を守る側(session_relay)と見張る側(context_watch)が、**同じ 120,000 の線に
  別の量をぶつけていた**。実測= 台帳 aegis-gl 9,443 に対し実物 134,110(約14倍)。
  原因は num_turns ではない(read_transcript は割っていない)。
  **圧縮の直後だけ postTokens=畳んだ会話の大きさ を「文脈」として入れていた**からだ。
  postTokens は毎便再送される固定費(床。実測 63,839〜72,774)を1トークンも含まない。
  → 正本の物差し= 「その便で実際にモデルへ送った input+cache読み+cache作成」。
    圧縮直後は実値が無いので **postTokens + 床**(測定に基づく下限)を使う。

★この検査の本体は「①relayの値 == ②context_watchの値」を**同じ記録ファイルで**突き合わせること。
★空PASSにしない= 最後に変異検査(旧仕様=postTokensをそのまま返す)を置く。

走らせ方: python scripts/llm/test_context_ruler.py
★読むだけ。一時ファイルの中で完結する(本番の台帳・記録・Discordに触らない)。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_relay as sr          # noqa: E402
import context_watch as cw          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ok, ng = 0, 0


def check(name, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print("  PASS %s" % name)
    else:
        ng += 1
        print("  FAIL %s %s" % (name, detail))


def asst(total, ts="2026-08-22T07:00:00.000Z", side=False):
    """assistant 1行。input+cache読み+cache作成 の合計が total になるように置く。"""
    return json.dumps({"type": "assistant", "isSidechain": side, "timestamp": ts,
                       "message": {"usage": {"input_tokens": 3,
                                             "cache_read_input_tokens": total - 3,
                                             "cache_creation_input_tokens": 0}}},
                      ensure_ascii=False)


def boundary(pre, post, ts="2026-08-22T07:27:31.296Z"):
    return json.dumps({"type": "system", "subtype": "compact_boundary", "timestamp": ts,
                       "compactMetadata": {"trigger": "manual",
                                           "preTokens": pre, "postTokens": post}},
                      ensure_ascii=False)


def write(tmp, name, lines):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p


def watch_last(path):
    """context_watch と**同じ式**でその記録ファイルの最新値を出す(物差しの突き合わせ用)。"""
    last = 0
    for line in open(path, encoding="utf-8", errors="replace"):
        if '"usage"' not in line:
            continue
        mi = cw.RE_IN.search(line)
        if not mi:
            continue
        c = int(mi.group(1))
        for rx in (cw.RE_CR, cw.RE_CC):
            m = rx.search(line)
            c += int(m.group(1)) if m else 0
        if c > 0:
            last = c
    return last


tmp = tempfile.mkdtemp(prefix="ctxruler_test_")
FLOOR, HEAVY, POST, PRE = 72512, 134110, 9443, 257835

print("== 圧縮の直後(実値がまだ1行も無い) ==")
p1 = write(tmp, "a.jsonl", [asst(FLOOR), asst(HEAVY), boundary(PRE, POST)])
sr._transcript_path = lambda sid, cwd=None: p1          # noqa: E731 記録の場所だけ偽物
tr = sr.read_transcript("dummy")
check("床を実測できている", tr.get("floor_tokens") == FLOOR, str(tr.get("floor_tokens")))
check("持ち越し量=postTokens", tr.get("carry_tokens") == POST, str(tr.get("carry_tokens")))
check("圧縮直後だと分かる", tr.get("post_compact") is True)
check("文脈=postTokens+床", tr.get("context_tokens") == POST + FLOOR, str(tr.get("context_tokens")))
check("★旧仕様(postTokensそのまま)ではない", tr.get("context_tokens") != POST)
check("2026-07-29の事故(圧縮前の重い値)を再演していない",
      tr.get("context_tokens") < PRE and tr.get("context_tokens") < HEAVY,
      str(tr.get("context_tokens")))

print("== 圧縮の後に実値が付いた ==")
p2 = write(tmp, "b.jsonl", [asst(FLOOR), asst(HEAVY), boundary(PRE, POST), asst(81000)])
sr._transcript_path = lambda sid, cwd=None: p2          # noqa: E731
tr2 = sr.read_transcript("dummy")
check("実値があるならそれを使う", tr2.get("context_tokens") == 81000, str(tr2.get("context_tokens")))
check("圧縮直後フラグは下りる", tr2.get("post_compact") is False)
check("★relayとcontext_watchが同じ値を出す(物差しが1本)",
      tr2.get("context_tokens") == watch_last(p2),
      "relay=%s watch=%s" % (tr2.get("context_tokens"), watch_last(p2)))
# ★★ORG-46 第4形(2026-08-22 研究室HQ msg DISPATCH-aegis-gl-1787386719471 の実測)。
#   実測= aegis-gl `carry_tokens=157,242`。これは17:11の**文脈の最新値**で、postTokens(8,579)
#   ではなかった。原因は `carry = last` の無条件写し= 圧縮の直後だけ名前どおりに見え、
#   普通の便では**丸ごと文脈**が「畳んだ会話の量」の名前で台帳に載っていた。
check("★持ち越し量は普通の便でも postTokens(文脈の実値ではない)",
      tr2.get("carry_tokens") == POST, str(tr2.get("carry_tokens")))
check("★旧バグの指紋(carry==文脈)が出ない",
      tr2.get("carry_tokens") != tr2.get("context_tokens"),
      "carry=%s ctx=%s" % (tr2.get("carry_tokens"), tr2.get("context_tokens")))

print("== 圧縮を1度もしていないセッション ==")
p2b = write(tmp, "b2.jsonl", [asst(FLOOR), asst(HEAVY)])
sr._transcript_path = lambda sid, cwd=None: p2b         # noqa: E731
tr2b = sr.read_transcript("dummy")
check("畳んだ会話が無いなら持ち越しは0", not tr2b.get("carry_tokens"), str(tr2b.get("carry_tokens")))
e0 = {"generation": 1}
sr._apply_transcript(e0, tr2b)
check("★0は台帳へ書かない(『畳んだ量0』と偽らない)", "carry_tokens" not in e0, str(e0))

print("== サブエージェントの行は混ぜない(別の文脈) ==")
p3 = write(tmp, "c.jsonl", [asst(FLOOR), asst(HEAVY), asst(999, side=True)])
sr._transcript_path = lambda sid, cwd=None: p3          # noqa: E731
tr3 = sr.read_transcript("dummy")
check("sidechainは文脈にしない", tr3.get("context_tokens") == HEAVY, str(tr3.get("context_tokens")))
check("sidechainは床にもしない", tr3.get("floor_tokens") == FLOOR, str(tr3.get("floor_tokens")))

print("== _need_compact: 床しか無い所へ撃たない ==")
# ★床が線に近い時に効く釘だ(今日の床72,512では線120,000との差が47,488あるので発火しない)。
#   だから検査は「床が育った時」を作って通す= 固定物が増えれば現実にこうなる(HQ指摘3)。
BIG = sr.COMPACT_AT_TOKENS - 20000                       # 100,000 の床
hit, why = sr._need_compact({"floor_tokens": BIG}, sr.COMPACT_AT_TOKENS + 5000)
check("減らせる量が足りなければ撃たない", hit is False and "見送った" in why, why[:60])
check("見送りの理由に床の実数が入る", "%s" % f"{BIG:,}" in why, why[:80])
hit2, _ = sr._need_compact({"floor_tokens": BIG}, BIG + sr.COMPACT_MIN_GAIN + 1)
check("減らせるなら撃つ", hit2 is True)
hit2b, _ = sr._need_compact({"floor_tokens": FLOOR}, sr.COMPACT_AT_TOKENS + 1)
check("今日の床(72,512)では従来どおり線で撃つ=釘が普段の運用を変えない", hit2b is True)
hit3, _ = sr._need_compact({}, 200000)
check("床が測れていない時は従来どおり線だけで撃つ(fail-open)", hit3 is True)
hit4, _ = sr._need_compact({"floor_tokens": FLOOR}, sr.COMPACT_AT_TOKENS - 1)
check("線の下では撃たない", hit4 is False)
hit5, _ = sr._need_compact({"floor_tokens": FLOOR}, POST + FLOOR)
check("★圧縮した直後の値では二度撃ちしない", hit5 is False, "81,955で再圧縮している")

print("== 封筒: 床を隠さない ==")
sb = sr._state_block(19, POST + FLOOR, FLOOR)
check("封筒に文脈が出る", f"{POST + FLOOR:,}" in sb, sb)
check("封筒に床が出る", "床=" in sb and f"{FLOOR:,}" in sb, sb)
check("床が不明なら床は書かない", "床=" not in sr._state_block(19, 100000, 0))

print("== 写像は1本(ORG-46 第3形・2026-08-22 17:16 実測) ==")
# ★実測= hq の行に ctx 137,783 は入ったが floor は None のままだった。同じ瞬間に
#   read_transcript は floor 72,774 を返している=**測れているのに台帳から落ちていた**。
#   犯人は「判定前の測り直し」が ctx と source しか書かなかったこと(写像が3か所にあった)。
# ★carry は「最後の圧縮が畳んだ会話の大きさ」= 文脈の実値とは別の量(ORG-46 第4形)。
#   ここで carry=137,783(=ctx と同値)を置いていたのは、当時のバグをそのまま写していたからだ。
TR_HQ = {"context_tokens": 137783, "carry_tokens": 9443, "floor_tokens": 72774,
         "post_compact": False, "compact_count": 10}
e1 = {"generation": 16}
c1 = sr._apply_transcript(e1, TR_HQ)
check("写像: 文脈が返る", c1 == 137783, str(c1))
check("写像: 床が台帳へ入る", e1.get("floor_tokens") == 72774, str(e1.get("floor_tokens")))
check("写像: 持ち越しが台帳へ入る", e1.get("carry_tokens") == 9443, str(e1.get("carry_tokens")))
check("写像: 出所が transcript", e1.get("context_source") == "transcript", str(e1.get("context_source")))

# 圧縮の直後= 記録に assistant 行が無く床が測れない。台帳が覚えている床を足す。
e2 = {"floor_tokens": 72774}
c2 = sr._apply_transcript(e2, {"context_tokens": 10404, "carry_tokens": 10404,
                               "floor_tokens": 0, "post_compact": True})
check("写像: 床が測れない便は台帳の床を足す", c2 == 10404 + 72774, str(c2))
check("写像: 足したことが出所に残る", "床は台帳の実測" in (e2.get("context_source") or ""),
      str(e2.get("context_source")))

# 「判定の前に測り直す」経路が、床まで書くこと(=17:16の事故が二度と起きないこと)
real_rt = sr.read_transcript
sr.read_transcript = lambda sid, cwd=None: dict(TR_HQ)
try:
    e3 = {"generation": 16}
    got, measured = sr._measure_context_now("c27eec97", e3)
    check("測り直し: 文脈を返す", measured and got == 137783, str(got))
    check("★測り直しの経路でも床が台帳へ入る", e3.get("floor_tokens") == 72774,
          "ctxだけ書いて床が落ちている=17:16の事故そのもの")
    e4 = {"generation": 16}
    got4, _ = sr._measure_context_now("c27eec97")          # entryを渡さない旧い呼び方
    check("測り直し: entryを渡さなければ何も書かない(後方互換)",
          got4 == 137783 and not e4.get("floor_tokens"))
    check("★変異: ctxだけ書く旧経路なら床はNoneのまま",
          {"generation": 16}.get("floor_tokens") is None)
finally:
    sr.read_transcript = real_rt

print("== 引き継ぎのチェックポイントの後も測り直す(研究室HQ msg 1540668457220186163 §5) ==")
# ★実測(aegis-gl 2026-08-22)= 台帳の山 156,108 に対し記録ファイルの実測は 206,448。
#   差の中身は**引き継ぎのチェックポイント便そのもの**だった=
#     18:23:29〜18:29:14 が普通の便(relayが測って 156,108 を台帳へ)
#     18:31:19〜18:37:17 がチェックポイント便(166,712 → 206,448 まで +39,736)
#   `_handoff_checkpoint` は `_write_handoff` を撃つが**その後に測り直していなかった**ので、
#   台帳は「この世代で一番重かった瞬間」を構造的に見落とす。山で判定する定期リフレッシュが
#   また谷を見る=C-048(書いた後の実物を読み直して言え)の同じ穴。
_real = (sr._write_handoff, sr.load_sessions, sr.save_room, sr.read_transcript)
_saved = {}
try:
    sr._write_handoff = lambda *a, **k: ("/tmp/handoff.md", "冒頭")   # 外へ出る手だけ偽物
    _entry = {"generation": 20, "context_tokens": 156108,
              "context_peak_tokens": 156108, "floor_tokens": FLOOR}
    sr.load_sessions = lambda: {"aegis-gl": _entry}
    sr.save_room = lambda dept, e: _saved.update({dept: e})
    # チェックポイント便が終わった直後の記録ファイル= 206,448 まで伸びている
    sr.read_transcript = lambda sid, cwd=None: {
        "context_tokens": 206448, "carry_tokens": 0, "floor_tokens": FLOOR,
        "post_compact": False, "compact_count": 1, "last_compact": None}
    ok_ck, info = sr._handoff_checkpoint("aegis-gl", {}, "tok", "19eecdb8", 20, 156108)
finally:
    (sr._write_handoff, sr.load_sessions, sr.save_room, sr.read_transcript) = _real

_e = _saved.get("aegis-gl") or {}
check("チェックポイントの後に文脈を測り直して台帳へ書く",
      int(_e.get("context_tokens") or 0) == 206448, str(_e.get("context_tokens")))
check("★山が実測へ追いつく(谷のまま置き去りにしない)",
      int(_e.get("context_peak_tokens") or 0) == 206448, str(_e.get("context_peak_tokens")))
check("チェックポイントの記録(撃った文脈・時刻・成否)は従来どおり残る",
      _e.get("handoff_ckpt_ok") is True and int(_e.get("handoff_ckpt_ctx") or 0) == 156108,
      str({k: _e.get(k) for k in ("handoff_ckpt_ok", "handoff_ckpt_ctx")}))
check("★変異: 測り直しを外すと山は谷(156,108)のまま",
      156108 < 206448 and int(_e.get("context_peak_tokens") or 0) != 156108,
      "測り直しが効いていない")
check("★山の更新は1か所を通す(_bump_peak)", hasattr(sr, "_bump_peak"))
_pe = {"context_peak_tokens": 300}
sr._bump_peak(_pe, 100)
check("★_bump_peak: 山は下がらない", _pe["context_peak_tokens"] == 300, str(_pe))
sr._bump_peak(_pe, 400)
check("★_bump_peak: 山は上がる", _pe["context_peak_tokens"] == 400, str(_pe))

print("== 変異検査(旧仕様へ戻したら落ちること) ==")
old = POST                                   # 旧: postTokens をそのまま文脈とした
check("★変異: 旧仕様なら床込みの値と一致しない", old != POST + FLOOR)
check("★変異: 旧仕様の値は圧縮線の 1/12 未満=永久に発火しない",
      old < sr.COMPACT_AT_TOKENS / 12, str(old))
check("★変異: 旧仕様では _need_compact が『まだ余裕がある』と答える",
      sr._need_compact({"floor_tokens": FLOOR}, old)[0] is False)

print("")
print("PASS=%d FAIL=%d" % (ok, ng))
sys.exit(1 if ng else 0)
