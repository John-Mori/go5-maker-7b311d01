#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chami無応答検知(absence_watchdog.check_unanswered_chami)のテスト。

★ソースの文字列一致で済ませない(共通規律§3)。
  ①純関数 unanswered_verdict を境界値ごとに通す。
  ②`--live` を付けると **本物のDiscordから取った実データ**を判定へ流し、
    外へ出る手(bot_send)だけ偽物にして経路をまるごと実行する。

使い方:
  python scripts/discord/test_unanswered_chami.py          … 純関数のみ(オフラインで走る)
  python scripts/discord/test_unanswered_chami.py --live   … 実データで経路まで通す
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import absence_watchdog as aw   # noqa: E402

NOW = 1_800_000_000.0


def msg(mid, user, ago_sec, body=""):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - ago_sec))
    return {"id": str(mid), "author": {"username": user}, "timestamp": ts, "content": body}


ok = 0
ng = 0


def chk(name, got, want):
    global ok, ng
    if got == want:
        ok += 1
        print(f"  PASS {name}")
    else:
        ng += 1
        print(f"  FAIL {name}: got={got!r} want={want!r}")


print("=== 1. 純関数 unanswered_verdict ===")
# Discord APIは新しい順で返す
chk("空", aw.unanswered_verdict([], NOW)[0], False)
chk("Chamiの発言が無い",
    aw.unanswered_verdict([msg(1, "オタコン", 60)], NOW)[0], False)
chk("Chamiが最新・25分未満=まだ鳴らさない",
    aw.unanswered_verdict([msg(2, "chami_fusoh", 24 * 60, "まだ？")], NOW)[0], False)
chk("Chamiが最新・25分ちょうど=候補",
    aw.unanswered_verdict([msg(2, "chami_fusoh", 25 * 60, "まだ？")], NOW)[0], True)
chk("候補のmsg_idを返す",
    aw.unanswered_verdict([msg(7, "chami_fusoh", 30 * 60, "反応がない")], NOW)[1], "7")
chk("経過秒を返す",
    aw.unanswered_verdict([msg(7, "chami_fusoh", 30 * 60)], NOW)[2], 1800)
chk("本文の抜粋を返す",
    aw.unanswered_verdict([msg(7, "chami_fusoh", 30 * 60, "不要な窓は閉じといて")], NOW)[3],
    "不要な窓は閉じといて")
chk("誰かが返している=対象外",
    aw.unanswered_verdict([msg(3, "一ノ瀬怜", 5 * 60), msg(2, "chami_fusoh", 30 * 60)], NOW)[0],
    False)
chk("機械の投稿も返事に数える(鳴る条件を厳しくする側)",
    aw.unanswered_verdict([msg(3, "メタルギアMk.II", 5 * 60, "【実依頼】…"),
                           msg(2, "chami_fusoh", 30 * 60)], NOW)[0], False)
chk("★この検査自身の警報は返事に数えない(自己消火の防止)",
    aw.unanswered_verdict([msg(3, "メタルギアMk.II", 5 * 60, aw.UNANSWERED_MARK + "(自動監視): …"),
                           msg(2, "chami_fusoh", 30 * 60)], NOW)[0], True)
chk("Chami連投は最新の1件で見る(古い方は対象にしない)",
    aw.unanswered_verdict([msg(9, "chami_fusoh", 26 * 60, "2通目"),
                           msg(8, "chami_fusoh", 90 * 60, "1通目")], NOW)[1], "9")
chk("Chami連投の後に返事=対象外",
    aw.unanswered_verdict([msg(10, "オタコン", 60), msg(9, "chami_fusoh", 26 * 60),
                           msg(8, "chami_fusoh", 90 * 60)], NOW)[0], False)
chk("時刻が壊れている行は鳴らさない(fail-open)",
    aw.unanswered_verdict([{"id": "1", "author": {"username": "chami_fusoh"},
                            "timestamp": "こわれている", "content": "x"}], NOW)[0], False)

print("\n=== 1.5 純関数 answered_since(★解消の判定) ===")
# ★2026-09-03 の嘘報告(Chami「これ嘘報告」)。1分shorts漫画紹介部門の実データそのもの。
#   07:39 のChamiの便に誰も返さないまま、16:32 にChami自身が「できた？」と催促した。
#   旧実装は「候補で無くなった」を解消と読んで ✅ を出した= 8時間53分の沈黙を解消と報告した。
REAL = "1544839258118946877"
chk("★Chami自身の催促は返事ではない(実データ:漫画紹介部門)",
    aw.answered_since([msg(1544973415448846467, "chami_fusoh", 60, "できた？"),
                       msg(int(REAL), "chami_fusoh", 9 * 3600, "1 b 2 a")], REAL), False)
chk("誰かが返していれば解消",
    aw.answered_since([msg(1544973415448846467, "ヴィルシーナ", 60, "できたわよ"),
                       msg(int(REAL), "chami_fusoh", 9 * 3600, "1 b 2 a")], REAL), True)
chk("★この検査自身の警報は解消の根拠にならない",
    aw.answered_since([msg(1544973415448846467, "メタルギアMk.II", 60,
                           aw.UNANSWERED_MARK + "(自動監視): …")], REAL), False)
chk("★この検査自身の✅も解消の根拠にならない",
    aw.answered_since([msg(1544973415448846467, "メタルギアMk.II", 60,
                           aw.UNANSWERED_OK_MARK + ": … は解消。")], REAL), False)
chk("警報した便より古い投稿は返事に数えない",
    aw.answered_since([msg(1544838786066686074, "ヴィルシーナ", 10 * 3600, "承知したわ")], REAL),
    False)
chk("警報した便が窓から流れていてもidで判定できる",
    aw.answered_since([msg(1544973415448846467, "三笘薫", 60, "できたよ")], REAL), True)
chk("印が壊れている時は抱え込まない(fail-open)", aw.answered_since([], "こわれた印"), True)

print("\n=== 2. 経路の実行(bot_sendだけ偽物) ===")
sent = []
aw.bot_send = lambda ch, body, dry, by_dept=False: (sent.append((ch, body)), True)[1]

if "--live" in sys.argv:
    print("  (実データ: Discordから各室の最新5件を取得して判定へ流す)")
    st = {}
    aw.check_unanswered_chami(st, dry_run=False)
    u = st.get("unanswered") or {}
    rooms = [k for k in u if k != "_last_run"]
    print(f"  巡回した部屋: {len(rooms)}室 / 警報: {len(sent)}件")
    for ch, body in sent:
        print(f"  --- 送信先={ch} ---\n{body}\n")
    # C-041: 1回目の観測では鳴らないこと(consec=2が要る)
    fired_first = [b for _, b in sent if b.startswith(aw.UNANSWERED_MARK)]
    chk("★C-041: 1巡目では警報を出さない", fired_first, [])
    # 2巡目(ゲートを開けて同じ判定を再度)で初めて鳴る条件が揃う
    u["_last_run"] = 0
    aw.check_unanswered_chami(st, dry_run=False)
    fired = [b for _, b in sent if b.startswith(aw.UNANSWERED_MARK)]
    print(f"  2巡目までの警報: {len(fired)}件")
    for b in fired:
        print(f"  --- 実文面 ---\n{b}\n")
    cand = [k for k in u if k != "_last_run" and (u[k].get("msg_id") or "")]
    chk("2巡目で候補があれば警報が出ている(候補0なら警報0)",
        bool(fired) == bool(cand), True)
elif "--force" in sys.argv:
    # ★「いま候補が0件だから警報文が一度も動いていない」を放置しない(規律§3)。
    #   その状態が無いなら**作って渡す**= 実在の名簿を回しつつ、1室だけ
    #   「30分前のChami発言が最新」というデータを差し込んで、警報文の生成まで通す。
    print("  (候補を人工的に作って警報文の生成まで通す。Discordへは出さない)")
    target = "1528675307245010984"    # イージス研究室
    real_get = aw._discord_get

    def msg_now(mid, user, ago_sec, body=""):
        """本番経路は time.time() で判定するので、実時刻を基準に作る。"""
        ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - ago_sec))
        return {"id": str(mid), "author": {"username": user}, "timestamp": ts, "content": body}

    def fake_get(path, timeout=15):
        if target in path:
            return [msg_now(999999, "chami_fusoh", 31 * 60, "反応がない。1番困る部類の出来事。")]
        return []                      # 他室は「発言なし」=対象外にして雑音を消す
    aw._discord_get = fake_get
    st = {}
    aw.check_unanswered_chami(st, dry_run=False)
    chk("★C-041: 1巡目では鳴らない", sent, [])
    (st["unanswered"])["_last_run"] = 0
    aw.check_unanswered_chami(st, dry_run=False)
    chk("2巡目で1件だけ鳴る", len(sent), 1)
    ch, body = sent[0]
    chk("鳴らす先=イージス研究室", ch, aw.UNANSWERED_ALERT_DEPT)
    chk("警報文に目印が付く", body.startswith(aw.UNANSWERED_MARK), True)
    chk("警報文に部屋名が入る(転送されても意味が保たれる)", "イージス" in body, True)
    chk("警報文にDiscordリンクが入る", f"/{target}/999999" in body, True)
    print(f"  --- 実文面 ---\n{body}\n")
    # 3巡目: 同じ便に対して二度は鳴らない(生涯1回)
    (st["unanswered"])["_last_run"] = 0
    aw.check_unanswered_chami(st, dry_run=False)
    chk("同じ便で二度鳴らない(生涯1回)", len(sent), 1)
    # 返事が付いた= ✅が1回出て状態が閉じる(C-046の閉じ方A)
    aw._discord_get = lambda path, timeout=15: (
        [msg_now(1000000, "ケヴィン・デブライネ", 60, "受けた"),
         msg_now(999999, "chami_fusoh", 33 * 60, "反応がない。")] if target in path else [])
    (st["unanswered"])["_last_run"] = 0
    aw.check_unanswered_chami(st, dry_run=False)
    chk("返事が付いたら✅が1回出る", len(sent), 2)
    chk("✅の文面", sent[1][1].startswith("✅返事が付きました"), True)
    chk("状態が閉じる(alertedが消える)", (st["unanswered"].get(target) or {}).get("alerted"), "")
    (st["unanswered"])["_last_run"] = 0
    aw.check_unanswered_chami(st, dry_run=False)
    chk("✅も二度は出ない", len(sent), 2)

    # ★★2026-09-03 の嘘報告の再現(Chami「これ嘘報告」)。経路をまるごと通す。
    #   警報を出した便に誰も返さないまま、**Chami自身が催促**を重ねた場合。
    #   旧実装は最新のChami発言(=催促・25分未満)を見て「候補ではない」→ ✅ を出していた。
    del sent[:]
    st2 = {}
    aw._discord_get = lambda path, timeout=15: (
        [msg_now(999999, "chami_fusoh", 31 * 60, "1 b 2 a")] if target in path else [])
    aw.check_unanswered_chami(st2, dry_run=False)
    (st2["unanswered"])["_last_run"] = 0
    aw.check_unanswered_chami(st2, dry_run=False)
    chk("(前提)まず警報が1件出ている", len(sent), 1)
    # ここでChamiが催促を重ねる= 誰も返していないのに「候補」ではなくなる
    aw._discord_get = lambda path, timeout=15: (
        [msg_now(1000001, "chami_fusoh", 2 * 60, "できた？"),
         msg_now(999999, "chami_fusoh", 40 * 60, "1 b 2 a")] if target in path else [])
    (st2["unanswered"])["_last_run"] = 0
    aw.check_unanswered_chami(st2, dry_run=False)
    chk("★Chamiの催促で✅を出さない(嘘報告の再現)", len(sent), 1)
    chk("★未応答を抱えたまま(alertedが消えない)",
        (st2["unanswered"].get(target) or {}).get("alerted"), "999999")
    # 警報した便が窓から流れた場合も、返事が無い限り解消しない
    aw._discord_get = lambda path, timeout=15: (
        [msg_now(1000004, "chami_fusoh", 1 * 60, "おい"),
         msg_now(1000003, "chami_fusoh", 2 * 60, "まだ？"),
         msg_now(1000002, "chami_fusoh", 3 * 60, "…")] if target in path else [])
    (st2["unanswered"])["_last_run"] = 0
    aw.check_unanswered_chami(st2, dry_run=False)
    chk("★窓から流れても✅を出さない", len(sent), 1)
    # 本物の返事が付いて初めて解消する
    aw._discord_get = lambda path, timeout=15: (
        [msg_now(1000005, "ヴィルシーナ", 30, "できたわよ"),
         msg_now(1000001, "chami_fusoh", 45 * 60, "できた？")] if target in path else [])
    (st2["unanswered"])["_last_run"] = 0
    aw.check_unanswered_chami(st2, dry_run=False)
    chk("本物の返事が付いたら✅が出る", len(sent), 2)
    chk("その時だけalertedが消える",
        (st2["unanswered"].get(target) or {}).get("alerted"), "")

    # ★C-053 must-fail= 「動く別の実装」(=2026-09-03まで実際に動いていた版)へ戻して落ちるか見る。
    #   旧版は解消の判定を持たず、候補で無くなればそのまま✅を出していた= answered_since が常にTrue。
    print("\n=== 3. must-fail(旧実装へ差し戻して、上の検査が本当に落ちるか) ===")
    real_as = aw.answered_since
    fails_before = ng
    try:
        aw.answered_since = lambda msgs, alerted_id: True
        del sent[:]
        st3 = {}
        aw._discord_get = lambda path, timeout=15: (
            [msg_now(999999, "chami_fusoh", 31 * 60, "1 b 2 a")] if target in path else [])
        aw.check_unanswered_chami(st3, dry_run=False)
        (st3["unanswered"])["_last_run"] = 0
        aw.check_unanswered_chami(st3, dry_run=False)
        n_alert = len(sent)
        aw._discord_get = lambda path, timeout=15: (
            [msg_now(1000001, "chami_fusoh", 2 * 60, "できた？"),
             msg_now(999999, "chami_fusoh", 40 * 60, "1 b 2 a")] if target in path else [])
        (st3["unanswered"])["_last_run"] = 0
        aw.check_unanswered_chami(st3, dry_run=False)
        leaked = [b for _, b in sent[n_alert:] if b.startswith(aw.UNANSWERED_OK_MARK)]
        chk("★旧実装ではChamiの催促で✅が出てしまう(=検査が効いている証拠)",
            len(leaked), 1)
        if leaked:
            print(f"  --- 旧実装が出していた嘘報告 ---\n  {leaked[0]}")
    finally:
        aw.answered_since = real_as
    chk("must-fail自体で新たなFAILを増やしていない", ng - fails_before, 0)
    aw._discord_get = real_get
else:
    print("  (--live 未指定のためDiscordへは行かない。名簿が読めない時に落ちないことだけ確認)")
    aw.CHANNELS_FILE = os.path.join(os.path.dirname(aw.CHANNELS_FILE), "__no_such_file__.json")
    st = {}
    aw.check_unanswered_chami(st, dry_run=False)
    chk("名簿が読めなくても例外を投げない(watchdogを殺さない)", sent, [])

print(f"\n合計: PASS {ok} / FAIL {ng}")
sys.exit(1 if ng else 0)
