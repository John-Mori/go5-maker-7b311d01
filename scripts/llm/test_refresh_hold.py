# -*- coding: utf-8 -*-
"""定期リフレッシュの「会話の途中は見送る」のテスト(2026-08-13 イージス研究室)。

発注= 研究室HQ DISPATCH 1537458828541698139 論点2。
Chamiの原文(msg 1537450341426266162)= コピー部門とローカルllm教育部門が「急に文脈読まなくなった」。

なぜこの形にしたか(実測。全部 local/llm/request_log.jsonl と local/queue/inbox.db を数え直した):
  定期リフレッシュの事前交代 92件(2026-07-29〜08-13)のうち
    ・別部門の定期リフレッシュが前後15分以内にあった      = 30件(33%)
    ・Chamiが直前15分にどこかの部屋へ便を出していた        = **73件(79%)**
    ・**その部屋でChamiが会話の途中だった**(直前15分に同じ部屋へ別のChami便)= **55件(60%)**
  → 部屋どうしが揃うのは時計の位相ではなく**Chamiが一気に喋る**という共通の駆動源のせい。
    位相をずらしても駆動源は残る=誰かが必ず当たる。しかも「同時多発」は33%で、
    残り67%は単独で同じ被害を出している= **ずらしでは6割の被害が残る。**
  → 見るのを時計から**その部屋の会話の状態**へ変えた。

この検査が固定する規則=
  ① 会話の途中(直前15分に同じ部屋へChami便)なら定期リフレッシュは**見送る**
  ② 沈黙の後の新しい話題では**見送らない**(そこが一番安全な交代点)
  ③ ★圧縮失敗・185,000超は**退避**であって選択ではない= 会話中でも必ず交代する
  ④ 見送りは永久にしない= 上限4時間で必ず交代する / Chamiが15分黙れば次の便で交代する
  ⑤ 「今この便がChamiか」ではなく「**その前に**Chamiが喋っていたか」で判定する
     (自分自身と比べると必ず会話中になり、定期リフレッシュが二度と発火しなくなる)
  ⑥ 判定不能・記録なしは**交代する側**へ倒す(fail-open。見送り側へ倒すと機構が静かに死ぬ)

実行: python scripts/llm/test_refresh_hold.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import session_relay as sr           # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL += 1
        print("  NG  %s" % name)


NOW = 1786630000.0
Q = sr.REFRESH_QUIET_SEC
MAXH = sr.REFRESH_HOLD_MAX_SEC


def ent(**kw):
    """定期リフレッシュの条件を満たした部屋の台帳(圧縮5回・文脈11万)。"""
    e = {"compact_count": 5, "refresh_rotated_at_compacts": 0,
         "context_tokens": 110000}
    e.update(kw)
    return e


CHAMI = {"author": "chami_fusoh", "content": "続きだけど"}
HQ = {"author": "シャビ・アロンソ(研究室HQ)", "content": "通達"}

print("[1] 定数と土台")
check("REFRESH_QUIET_SEC は15分(会話の途中とみなす窓)", Q == 900)
check("REFRESH_HOLD_MAX_SEC は4時間(見送りを永久にしない保険)", MAXH == 4 * 3600)
check("見送りの窓 < 見送りの上限(逆だと1便も見送れない)", Q < MAXH)

print("[2] Chamiの判定はここ1箇所(dept_daemon と同じ式)")
check("chami_fusoh はChami", sr.is_from_chami(CHAMI))
check("研究室HQはChamiではない", not sr.is_from_chami(HQ))
check("機構の便はChamiではない", not sr.is_from_chami({"author": "オーケストレーション(機構)"}))
check("authorが無い便で落ちない(Chamiではない側へ倒す)", not sr.is_from_chami({}))
check("recがNoneでも落ちない", not sr.is_from_chami(None))

print("[3] 会話の途中なら見送る(今回の事故そのもの)")
hold, why = sr._refresh_hold(ent(last_chami_at=NOW - 120), CHAMI, NOW)
check("2分前にChamiが喋っている部屋では見送る", hold)
check("理由に実測の秒数が入る(『なぜ見送ったか』が後から読める)", "120秒前" in why)
hold2, _ = sr._refresh_hold(ent(last_chami_at=NOW - (Q - 1)), CHAMI, NOW)
check("窓のぎりぎり内側(899秒前)は見送る", hold2)

print("[4] 沈黙の後の新しい話題では見送らない(一番安全な交代点)")
check("窓のぎりぎり外側(901秒前)は交代する",
      not sr._refresh_hold(ent(last_chami_at=NOW - (Q + 1)), CHAMI, NOW)[0])
check("3時間黙っていた部屋への新しい話題は交代する",
      not sr._refresh_hold(ent(last_chami_at=NOW - 3 * 3600), CHAMI, NOW)[0])
check("Chami便の記録が無い部屋は交代する(fail-open=機構を殺さない)",
      not sr._refresh_hold(ent(), CHAMI, NOW)[0])
check("壊れた値(数字でない)でも交代する側へ倒す",
      not sr._refresh_hold(ent(last_chami_at="こわれてる"), CHAMI, NOW)[0])

print("[5] 判定は『その前にChamiが喋っていたか』であって『この便がChamiか』ではない")
check("会話中に届いた研究室HQの便でも見送る(替えるとChamiの次の便が新世代に当たる)",
      sr._refresh_hold(ent(last_chami_at=NOW - 60), HQ, NOW)[0])
check("静かな部屋へ届いた研究室HQの便では交代する",
      not sr._refresh_hold(ent(last_chami_at=NOW - 2 * 3600), HQ, NOW)[0])

print("[6] 見送りを永久にしない(2026-07-29『条件を足したつもりで廃止した』の再発防止)")
old = ent(last_chami_at=NOW - 60, refresh_hold_since=NOW - MAXH - 1)
check("見送りが上限4時間を超えたら、会話中でも交代する", not sr._refresh_hold(old, CHAMI, NOW)[0])
check("その時も理由を残す(黙って方針を変えない)", "見送りが" in sr._refresh_hold(old, CHAMI, NOW)[1])
young = ent(last_chami_at=NOW - 60, refresh_hold_since=NOW - 60)
check("上限に達していない見送りは続く", sr._refresh_hold(young, CHAMI, NOW)[0])

print("[7] ★触るのは refresh の枝だけ= 退避の交代は会話中でも止めない")
#   _should_rotate は台帳しか見ない= 会話の状態で判定を変えていないことをここで固定する。
mid = ent(last_chami_at=NOW - 60)
rot, why, kind = sr._should_rotate(dict(mid, compact_failed=True))
check("圧縮失敗は交代のまま(種別=compact_failed)", rot and kind == "compact_failed")
rot2, _, kind2 = sr._should_rotate(dict(mid, context_tokens=sr.ROTATE_AT_TOKENS + 1))
check("185,000超は交代のまま(種別=over_line)", rot2 and kind2 == "over_line")
rot3, _, kind3 = sr._should_rotate(mid)
check("定期リフレッシュの判定そのものは変えていない(種別=refresh)", rot3 and kind3 == "refresh")
check("会話中かどうかで _should_rotate の答えは変わらない(見送りは呼び元の仕事)",
      sr._should_rotate(ent())[2] == "refresh")

print("[8] 見送っても取り消しではない(次に交代できる状態が残る)")
e = ent(last_chami_at=NOW - 60)
sr._refresh_hold(e, CHAMI, NOW)
check("見送っても compact_count は減らない", e.get("compact_count") == 5)
check("見送っても refresh_rotated_at_compacts は動かない",
      e.get("refresh_rotated_at_compacts") == 0)
check("=Chamiが15分黙った次の便でそのまま交代する",
      sr._should_rotate(e)[0] and not sr._refresh_hold(e, CHAMI, NOW + Q + 1)[0])

print("[9] 実装が呼び元に繋がっている(検査が空振りしていない)")
src = open(os.path.join(HERE, "session_relay.py"), encoding="utf-8").read()
check("relay が _refresh_hold を呼んでいる", "_refresh_hold(entry, rec, _now_ts)" in src)
check("見送りは refresh の枝でだけ効く", '_rot_kind == "refresh"' in src)
check("last_chami_at は交代の判定より後で更新している(自分自身と比べない)",
      src.index("_refresh_hold(entry, rec, _now_ts)") < src.index('entry["last_chami_at"] = _now_ts'))
check("last_chami_at は世代を跨いで引き継ぐ", 'new_entry["last_chami_at"]' in src)
check("見送りを台帳へ1行残す(沈黙を作らない)", "会話の途中なので**見送った" in src)

print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
