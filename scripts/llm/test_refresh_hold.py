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

print("[10] ★ターン数の上限(2026-09-03 封筒エコー事故の恒久化)")
#   発注= 研究室HQ msg 1544758445746421800。事故= 軍議部屋 世代8 が次の封筒を自分で書き、
#   中に**実在しないChamiの便**(msg_id 1544753080036790319 → GET が404)を入れてDiscordへ出した。
#   HQの見立ては「文脈が伸びるほど見送りやすい」だったが、実測はそれを支持しない=
#   _refresh_hold に文脈の項は無く、見送り619件の文脈は最大119,722・120,000以上は0件
#   (COMPACT_AT_TOKENS=120,000 が先に圧縮する)。危険を測っているのは**ターン数**だ。
T = sr.REFRESH_HOLD_MAX_TURNS
check("REFRESH_HOLD_MAX_TURNS は36(実測: 見送り66件のうち解放7件=10.6%に収まる線)", T == 36)
check("上限ターンは実測のp99(42)より下(=事故の前に届く)", T < 42)
check("上限ターンは実測のp95(31)より上(=普通の便を巻き込まない)", T > 31)

talk = dict(last_chami_at=NOW - 60)   # 会話の途中= 本来なら見送る場面
check("35ターン目はまだ見送る(線の内側)", sr._refresh_hold(ent(turns=T - 1, **talk), CHAMI, NOW)[0])
check("36ターン目は会話中でも交代する", not sr._refresh_hold(ent(turns=T, **talk), CHAMI, NOW)[0])
check("38ターン目(事故便そのもの)は会話中でも交代する",
      not sr._refresh_hold(ent(turns=38, **talk), CHAMI, NOW)[0])
_why = sr._refresh_hold(ent(turns=T, **talk), CHAMI, NOW)[1]
check("打ち切りの理由に実測のターン数が入る(後から読める)", "36ターン目" in _why)
check("打ち切りの理由に上限が入る", "上限36ターン" in _why)
check("見送る時の理由にも『何ターンで必ず交代するか』を書く",
      "36ターンで必ず交代する" in sr._refresh_hold(ent(turns=5, **talk), CHAMI, NOW)[1])

print("[11] ターン数を足しても既存の振る舞いを壊していない")
check("turns キーが無い台帳は今までどおり見送る(新しい世代=まだ0ターン)",
      sr._refresh_hold(ent(**talk), CHAMI, NOW)[0])
check("壊れたturnsは0へ倒す=見送りは続く(解放へ倒すと1便目から毎回交代して機構が死ぬ)",
      sr._refresh_hold(ent(turns="こわれてる", **talk), CHAMI, NOW)[0])
check("ターンが少なくても上限4時間の保険はそのまま効く",
      not sr._refresh_hold(ent(turns=1, last_chami_at=NOW - 60,
                               refresh_hold_since=NOW - MAXH - 1), CHAMI, NOW)[0])
check("沈黙の後ならターン数に関係なく交代する(判定の順番を変えていない)",
      not sr._refresh_hold(ent(turns=1, last_chami_at=NOW - (Q + 1)), CHAMI, NOW)[0])
check("_should_rotate にターン数は入れていない(退避と選択の線引きは不変)",
      sr._should_rotate(ent(turns=99))[2] == "refresh")
check("交代した世代はターンが0から積み直る(台帳を作り直している)",
      'new_entry = {"active_session_id": new_sid' in src and '"turns"' not in
      src[src.index('new_entry = {"active_session_id": new_sid'):
          src.index('new_entry = {"active_session_id": new_sid') + 900])

print("[12] ★事故の再現(local/llm/request_log.jsonl の実物の並び・軍議部屋 2026-09-03)")
#   実測した見送り5便= 01:44:07(turns=35) 01:53:15(36) 01:54:06(37) 01:55:19(38) 01:57:04(39)。
#   事故便は 01:54:06 に始まり turns=38 で完了し、msg 1544752530511106295 として出た。
REAL = [("01:44:07", 35), ("01:53:15", 36), ("01:54:06", 37), ("01:55:19", 38), ("01:57:04", 39)]
held = [t for t, n in REAL if sr._refresh_hold(ent(turns=n, **talk), CHAMI, NOW)[0]]
check("事故の直前で解放が起きる(01:53:15 以降は1便も見送らない)", held == ["01:44:07"])
check("=事故便 01:54:06 は turns=1 の新しい世代が答えていた", "01:54:06" not in held)

print("[13] ★must-fail(C-053)= 壊す側は『動く別実装』であって消した行ではない")
#   HQの提案どおり**文脈**に上限を引いた版を、ここで本当に作って走らせる。
#   これが事故を止められないことを見せる= だからターン数を選んだ、が後から検算できる。
def _hold_by_context(entry, rec, now, ceiling=110000):
    """別実装: 見送りの打ち切りを『文脈がceilingを超えたら』にした版(HQの見立てをそのまま実装)。"""
    prev = float(entry.get("last_chami_at") or 0)
    if prev <= 0 or (now - prev) > Q:
        return False, ""
    if int(entry.get("context_tokens") or 0) >= ceiling:
        return False, "文脈が上限を超えた=会話中でも交代する"
    return True, "会話の途中なので見送る"


ACC = dict(talk, context_tokens=79392, turns=37)      # 事故便の実物(01:54:06)
check("別実装(文脈上限)は動く= 上限を超えた場面ではちゃんと解放する",
      not _hold_by_context(ent(**dict(talk, context_tokens=120000)), CHAMI, NOW)[0])
check("★その別実装は事故便を止められない(文脈79,392は上限に届かない)",
      _hold_by_context(ent(**ACC), CHAMI, NOW)[0])
check("★採用した実装は同じ事故便を止める", not sr._refresh_hold(ent(**ACC), CHAMI, NOW)[0])
check("★文脈上限が空振りする理由= 見送り619件の文脈は最大119,722で、"
      "COMPACT_AT_TOKENS=120,000 が先に圧縮する", sr.COMPACT_AT_TOKENS == 120000)

print("[14] 打ち切りの解放は必ず台帳に1行残る(静かに方針を変えない)")
check("打ち切り(理由つき)の解放は見送り0便でも記録する",
      'elif entry.get("refresh_hold_n") or _hold_why:' in src)
check("打ち切りはデーモンのログにも出す", "見送りを打ち切って定期リフレッシュを実行する" in src)
check("従来の『会話の途中ではない』解放は理由が空=今までどおり黙る",
      sr._refresh_hold(ent(last_chami_at=NOW - 2 * 3600), CHAMI, NOW)[1] == "")

print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
