# -*- coding: utf-8 -*-
"""交代の巻き戻し(ORG-46)と、定期リフレッシュが谷を見ている件の検査
(2026-08-22・研究室HQ msg 1540625015832055809)。

★何を守るか(3つとも、実測された事故そのものを型にしてある):
  ① `--rotate-now` を**その部屋の便の中から**叩くと、便の終わりの save_room が
     便の入口で読んだ古い entry を書き戻し、交代が数秒後に静かに巻き戻っていた。
     CLIは「OK 第16世代→第17世代」と表示する=**成功と表示して失敗する**型。
  ② 圧縮が走ると記録ファイルが新しくなり assistant 行が消えるので**床が測れない**。
     実測 16:45 の圧縮で、台帳へ入ったのは 10,430(持ち越し量だけ)で床は0だった。
  ③ 定期リフレッシュ(K=5)の判定が context_tokens を見ていた。この値は圧縮の便で
     必ずその世代の**谷**へ落ちるので、圧縮するほど交代しなくなる逆立ちだった
     (実測 hq: 圧縮8回・リフレッシュ0回・台帳8,114 / 実物104,627 / 山167,667)。

★空PASSにしない= 各節の最後に**変異検査**(旧仕様へ戻したら落ちる)を置く。
走らせ方: python scripts/llm/test_relay_rotate_guard.py
★一時ファイルの中だけで完結する(本番の対応表・記録・Discordに触らない)。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_relay as sr          # noqa: E402

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


tmp = tempfile.mkdtemp(prefix="relay_guard_test_")
sr.SESSIONS_FILE = os.path.join(tmp, "room_sessions.json")   # ★本番の対応表を触らない
sr.SESSIONS_LOCK = sr.SESSIONS_FILE + ".lock"


def disk():
    return sr.load_sessions()


print("== ORG-46: 便の中で交代が終わっていたら、書き戻しで消さない ==")
sr.save_sessions({"hq": {"active_session_id": "old00000", "generation": 16,
                         "context_tokens": 8114},
                  "other": {"active_session_id": "zzz", "generation": 3}})
entry_in_turn = dict(disk()["hq"])                       # ★便の入口で読んだスナップショット
# --- ここで外のプロセスが --rotate-now を通した(世代が進む) ---
sr.save_room("hq", {"active_session_id": "new11111", "generation": 17,
                    "context_tokens": 0})
# --- 便が終わり、入口で読んだ古い entry を書き戻そうとする ---
entry_in_turn["context_tokens"] = 93727
wrote = sr.save_room("hq", entry_in_turn)
check("巻き戻しの書き戻しは保存しない", wrote is False, str(wrote))
check("ディスクは新しい世代のまま", disk()["hq"]["generation"] == 17, json.dumps(disk()["hq"]))
check("ディスクは新しいセッションのまま", disk()["hq"]["active_session_id"] == "new11111")
check("他の部屋を巻き添えにしない", disk()["other"]["generation"] == 3)

# 正常系= 交代が起きていない普通の便は今までどおり書ける
e2 = dict(disk()["hq"])
e2["context_tokens"] = 120001
check("普通の便は保存できる", sr.save_room("hq", e2) is True)
check("値が入っている", disk()["hq"]["context_tokens"] == 120001)

# 圧縮で sid だけ変わる便は**止めない**(止めると実測が台帳へ入らなくなる)
e3 = dict(disk()["hq"])
e3["active_session_id"] = "cmpct222"
e3["context_tokens"] = 81955
check("圧縮によるsidの差し替えは通す", sr.save_room("hq", e3) is True)
check("差し替えが入っている", disk()["hq"]["active_session_id"] == "cmpct222")

print("== ORG-46 第2形: 同じ世代のまま、進んだ列を書き戻しで巻き戻さない ==")
# 実測(17:05)= 山198,549 が便の終わりに消えて None へ戻り、圧縮回数は7→9へ増えていた。
sr.save_sessions({"hq": {"active_session_id": "cmpct222", "generation": 17,
                         "context_peak_tokens": 198549, "compact_count": 9,
                         "floor_tokens": 72774, "context_tokens": 9039}})
stale = {"active_session_id": "cmpct222", "generation": 17, "context_tokens": 9039,
         "compact_count": 7}                      # ★便の入口で読んだ古い行(山も床も無い)
sr.save_room("hq", stale)
check("山は消えない", disk()["hq"].get("context_peak_tokens") == 198549,
      json.dumps(disk()["hq"]))
check("圧縮回数は戻らない", disk()["hq"].get("compact_count") == 9)
check("床も残る", disk()["hq"].get("floor_tokens") == 72774)
check("その便が測った直近の値はちゃんと入る", disk()["hq"].get("context_tokens") == 9039)
up = dict(disk()["hq"], context_peak_tokens=210000, compact_count=10)
sr.save_room("hq", up)
check("増える方向は素通し", disk()["hq"]["context_peak_tokens"] == 210000
      and disk()["hq"]["compact_count"] == 10)
gen_up = {"active_session_id": "n3", "generation": 18, "compact_count": 0}
sr.save_room("hq", gen_up)
check("世代が変わる書き込みでは混ぜない(新世代は0から数え直す)",
      disk()["hq"].get("compact_count") == 0
      and not disk()["hq"].get("context_peak_tokens"), json.dumps(disk()["hq"]))
print("== 変異検査(ORG-46 第2形) ==")
e_m, why_m = sr._keep_from_disk({"generation": 17, "context_peak_tokens": 198549},
                                {"generation": 17})
check("★変異: マージを外すと山がNoneのまま書かれる(=17:05に実測した消え方)",
      e_m.get("context_peak_tokens") == 198549 and "ORG-46" in why_m, why_m)

sr.save_sessions({"hq": {"active_session_id": "cmpct222", "generation": 17}})
skip, why = sr._stale_write("hq", {"generation": 17, "active_session_id": "a"},
                            {"generation": 16, "active_session_id": "b"})
check("判定の理由文にORG-46の目印が入る", skip is True and "ORG-46" in why, why[:60])
skip0, _ = sr._stale_write("hq", {}, {"generation": 16})
check("ディスクに行が無ければ通す(初回)", skip0 is False)

print("== 変異検査(旧仕様=検知だけで書き戻していた) ==")
sr.save_sessions({"hq": {"active_session_id": "new11111", "generation": 17}})
table = sr.load_sessions()
table["hq"] = {"active_session_id": "old00000", "generation": 16}     # ★旧= 素通しで上書き
sr.save_sessions(table)
check("★変異: 旧仕様なら第16世代へ巻き戻る", disk()["hq"]["generation"] == 16,
      "巻き戻らない=この検査は何も守っていない")


print("== 床が測れない便でも、台帳が覚えている床を当てる ==")


def asst(total, ts="2026-08-22T07:00:00.000Z"):
    return json.dumps({"type": "assistant", "isSidechain": False, "timestamp": ts,
                       "message": {"usage": {"input_tokens": 3,
                                             "cache_read_input_tokens": total - 3,
                                             "cache_creation_input_tokens": 0}}},
                      ensure_ascii=False)


def boundary(pre, post, ts="2026-08-22T07:45:28.430Z"):
    return json.dumps({"type": "system", "subtype": "compact_boundary", "timestamp": ts,
                       "compactMetadata": {"trigger": "manual",
                                           "preTokens": pre, "postTokens": post}},
                      ensure_ascii=False)


FLOOR, POST = 72512, 10430
p_new = os.path.join(tmp, "fresh.jsonl")                 # ★圧縮の直後の新しい記録
with open(p_new, "w", encoding="utf-8") as f:
    f.write(boundary(189258, POST) + "\n")               # assistant行が1行も無い=床が測れない
sr._transcript_path = lambda sid, cwd=None: p_new        # noqa: E731
tr = sr.read_transcript("dummy")
check("この記録では床が測れない(0)", tr.get("floor_tokens") == 0, str(tr.get("floor_tokens")))
check("記録だけでは持ち越し量しか出ない", tr.get("context_tokens") == POST, str(tr.get("context_tokens")))

e = {"floor_tokens": FLOOR}                              # ★台帳が前に測った床を覚えている
ctx = sr._note_usage(e, {"usage": {}, "num_turns": 1}, "2026-08-22T16:45:29", sid="dummy")
check("台帳の床を当てて『次の便が払う量』になる", ctx == POST + FLOOR, str(ctx))
check("台帳にも同じ値が入る", e.get("context_tokens") == POST + FLOOR, str(e.get("context_tokens")))
check("どちらの床を使ったか出所が残る", "床は台帳の実測" in str(e.get("context_source")),
      str(e.get("context_source")))
check("持ち越し量は別名で残る", e.get("carry_tokens") == POST, str(e.get("carry_tokens")))
check("★変異: 旧仕様(記録の値そのまま)なら 10,430=圧縮線の10分の1未満",
      POST * 10 < sr.COMPACT_AT_TOKENS, "%s vs %s" % (POST, sr.COMPACT_AT_TOKENS))

e_nofloor = {}
ctx2 = sr._note_usage(e_nofloor, {"usage": {}, "num_turns": 1}, "t", sid="dummy")
check("床を知らない部屋は従来どおり(推測で埋めない)", ctx2 == POST, str(ctx2))


print("== 定期リフレッシュは谷ではなく山で判定する ==")
# hq 第16世代の実測をそのまま型にする
gen16 = {"context_tokens": 8114, "compact_count": 8, "refresh_rotated_at_compacts": 0,
         "floor_tokens": 72774}
rot_old_shape, why_old, kind_old = sr._should_rotate(gen16)
check("山を知らないうちは今までどおり見送る(暴発しない)", rot_old_shape is False, why_old[:60])

gen16["context_peak_tokens"] = 167667                    # ★その世代で実際に出ていた最大
rot, why, kind = sr._should_rotate(gen16)
check("山が線を超えていれば定期リフレッシュが撃てる", rot is True and kind == "refresh", why[:80])
check("理由に山と直近の両方を書く", "167,667" in why and "8,114" in why, why)

defer, dwhy = sr._refresh_deferred(gen16)
check("撃てる状態では見送りにならない", defer is False, dwhy[:60])

light = {"context_tokens": 30000, "context_peak_tokens": 41000, "compact_count": 9,
         "refresh_rotated_at_compacts": 0, "floor_tokens": 25000}
lrot, _, _ = sr._should_rotate(light)
check("本当に軽い部屋は山でも撃たない(趣旨は壊さない)", lrot is False)
ldefer, ldwhy = sr._refresh_deferred(light)
check("軽い部屋は見送りとして1行残る", ldefer is True and "41,000" in ldwhy, ldwhy[:80])
check("見送りの理由文に床を併記する", "25,000" in ldwhy, ldwhy)

heavy = {"context_tokens": 200000, "compact_count": 1, "refresh_rotated_at_compacts": 0}
hrot, _, hkind = sr._should_rotate(heavy)
check("交代線超は今までどおり最優先", hrot is True and hkind == "over_line")
fail = {"context_tokens": 5000, "compact_failed": True}
frot, _, fkind = sr._should_rotate(fail)
check("圧縮失敗も今までどおり", frot is True and fkind == "compact_failed")

print("== 変異検査(旧仕様=谷で判定) ==")
check("★変異: 旧仕様は 8,114 < 100,000 で永久に見送る",
      gen16["context_tokens"] < sr.REFRESH_MIN_CONTEXT_TOKENS)
check("★変異: 山を消すと撃てなくなる",
      sr._should_rotate({k: v for k, v in gen16.items() if k != "context_peak_tokens"})[0] is False)


print("== C-048: 測っていない数字の上に見送りの理由を書かない ==")
# 山を1度も測れていない部屋(圧縮の直後=谷しか無い)。数字は代用してよいが、言葉は代用と書く。
unmeasured = {"context_tokens": 10430, "compact_count": 7,
              "refresh_rotated_at_compacts": 0, "floor_tokens": 72774}
check("山が無ければ『測れていない』と判定される", sr._peak_measured(unmeasured) is False)
check("山が有れば『測れている』", sr._peak_measured(dict(unmeasured, context_peak_tokens=167667)))
udefer, uwhy = sr._refresh_deferred(unmeasured)
check("見送りは今までどおり出る(黙らない)", udefer is True)
check("理由文は『まだ測れていない』と言う", "まだ測れていない" in uwhy, uwhy)
check("代用した数字だと明示する", "代用" in uwhy, uwhy)
check("★測っていない断定をしない= 『最大文脈10,430が』とは書かない",
      "最大文脈10,430" not in uwhy, uwhy)
_, mwhy = sr._refresh_deferred(dict(unmeasured, context_peak_tokens=41000))
check("測れている部屋は今までどおり山を断定してよい",
      "41,000" in mwhy and "まだ測れていない" not in mwhy, mwhy)


print("== ORG-47: 決着行が無い手動交代を、実物を読み直して閉じる ==")
sr.REQUEST_LOG = os.path.join(tmp, "request_log.jsonl")     # ★本番の台帳に書かない
OLD_SID, NEW_SID = "c27eec97-aaaa", "ffffffff-bbbb"


def put(rid, dept, state, ev):
    with open(sr.REQUEST_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"request_id": rid, "dept": dept, "state": state,
                            "ts": "t", "evidence": ev}, ensure_ascii=False) + "\n")


NOW = 1787400000
put("rotate-now-1787384087", "hq", "rotated", "手動交代 reason=cli old=%s gen=16" % OLD_SID)
put("rotate-now-1787384677", "hq", "rotated", "手動交代 reason=cli old=%s gen=16" % OLD_SID)
put("rotate-now-1787384999", "hq", "rotated", "手動交代 reason=cli old=%s gen=14" % OLD_SID)
put("rotate-now-1787384999", "hq", "completed", "手動交代 gen=14→15")
put("rotate-now-1787399900", "hq", "rotated", "手動交代 reason=cli old=%s gen=16" % OLD_SID)
put("rotate-now-1787384088", "other-room", "rotated", "手動交代 reason=cli old=zzz gen=2")
sr.save_sessions({"hq": {"active_session_id": OLD_SID, "generation": 16},
                  "other-room": {"active_session_id": "zzz", "generation": 9}})

closed = sr._reap_stranded_rotations("hq", now=NOW)
check("実物が『交代していない』と言う2件を閉じる",
      sorted(closed) == ["rotate-now-1787384087", "rotate-now-1787384677"], str(closed))
check("既に決着している行は触らない", "rotate-now-1787384999" not in closed)
check("走っている最中かもしれない新しい行は触らない", "rotate-now-1787399900" not in closed)
check("他の部屋を巻き添えにしない", sr._reap_stranded_rotations("other-room", now=NOW) == [],
      "世代が9=交代が乗ったかもしれない行は閉じない")
body = open(sr.REQUEST_LOG, encoding="utf-8").read()
check("閉じ方は failed(completed と嘘をつかない)", '"state": "failed"' in body)
check("何を読み直して決めたか理由文に残る", "対応表の実物を読み直して" in body and "ORG-47" in body)
check("2度目は何も閉じない(冪等)", sr._reap_stranded_rotations("hq", now=NOW) == [])

print("== 変異検査(ORG-47) ==")
sr.save_sessions({"hq": {"active_session_id": NEW_SID, "generation": 17}})
put("rotate-now-1787384100", "hq", "rotated", "手動交代 reason=cli old=%s gen=16" % OLD_SID)
check("★変異: 世代が進んでいる=乗ったか分からない行は**開けたまま残す**",
      sr._reap_stranded_rotations("hq", now=NOW) == [],
      "ここで閉じる実装は『分からないものを分かった顔で閉じる』=C-048違反")
put("rotate-now-1787384101", "hq", "rotated", "手動交代 reason=cli old=%s" % OLD_SID)
check("★変異: 世代が読めない行も閉じない",
      sr._reap_stranded_rotations("hq", now=NOW) == [])

print("")
print("PASS=%d FAIL=%d" % (ok, ng))
sys.exit(1 if ng else 0)
