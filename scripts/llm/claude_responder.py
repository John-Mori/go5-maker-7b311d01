#!/usr/bin/env python3
"""研究室セッション不在時の、AIを使わない機械受付係。

main箱を研究室セッションが処理できない間だけ見張り、既読印と固定の受領文を
PythonからDiscordへ送る。本対応用のfollowupは従来どおりmain箱へ残す。

以前はこの固定文1通のために毎回 ``claude --print`` を起動していたが、文章判断も
実作業もさせていなかった。現在はClaude/OpenAI/Geminiを一切呼ばない。
機微部屋・セッション専有部屋・専任デーモンのガード、重複防止、巡回上限は維持する。

使い方:
  python scripts/llm/claude_responder.py --once   # 1巡回で終了(点検/テスト)
  python scripts/llm/claude_responder.py          # 常駐(POLL秒間隔)
"""
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
INBOX = os.path.join(LOCAL, "discord_inbox.jsonl")
PROCESSED = os.path.join(LOCAL, "discord_processed.jsonl")
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
REACT = os.path.join(ROOT, "scripts", "discord", "react.py")
PERSONA = "研究室(無人代打)"
ACK_TEXT = "受領。本対応は担当セッションへ引き継ぎます。"

POLL_SEC = 20
# ★生存判定(2信号)は共有ヘルパ scripts/llm/presence.py へ一本化(2026-07-18 INC対策)。
#   readiness(waiter脈) OR liveness(hook脈)+HARD_CAP。閾値と設計理由はpresence.pyに集約。
#   以前はここに実装があり、local/gemini responderへ横展開されず drift → 代打暴発を招いた。
MAX_PER_CYCLE = 3              # 1巡回で処理する上限(暴走と費用の歯止め)
SENSITIVE_DEPTS = ("dream-care", "past-room", "health-log")


sys.path.insert(0, HERE)
from presence import lab_alive  # noqa: E402  生存判定(2信号)は全responder共通の1関数へ一本化


# 総括本部4室= Chami裁定(2026-07-20)でデーモンを撤去し、**人格を持つ本人(セッション)が
# 応対する**と決めた部屋。ここは留守なら沈黙してよい(watchdogが15分で鳴らす)。
# ★session_rooms.PAIRS は引かない: PAIRSは「ミラー先が配線済みの部屋」であって
#   「担当がセッションの部屋」ではない(実際 research-room / keiei-kikaku はPAIRSに無い)。
#   別の目的の表を流用すると、片方を増やした時に静かにズレる(ORG-06と同型)。
#
# ★2026-07-26 `kaizen-analyst` を追加(実弾のログで見つけた穴)。
#   Chamiが改善提案部門の窓を開けてアスナが着任したが、**あの部屋には精霊(dept_daemon)が居ない**。
#   → `room_has_own_responder()` が False を返し、代打が「無人だ」と判断して
#     **アスナ本人のセッション宛の便へ、使い捨ての --print で答えてしまう**。
#   実際にログへ痕跡が残っていた= `応答 [改善提案部門-アスナ•トトリ] rc=1 "You've hit your weekly limit"`。
#   **ORG-12(代打が本人セッション向けの便を食う)と同じ形が、別の部屋で再生していた。**
#   ★「精霊が居ない」と「担当が居ない」は別。**セッションが担当している部屋は、精霊の有無に関わらず代打が触らない。**
# ★2026-09-16 hr-room を追加(Chami直・msg 1549628315248230543「引き継ぐなほんで」)。
#   実害= 研究室(無人代打)が hr-room の便へ「受領。本対応は担当セッションへ引き継ぎます。」を投稿していた。
#   hr-room の担当は対話セッション(ククール/アメス)本人=「引き継ぐ」先の別担当は存在しない
#   → 上の ORG-04 と寸分違わぬ嘘。session-owned として一次ackを打たない(便はfollowupで残り本人が処理)。
#   ★名指し1件に留める(C-035)= 他室へは広げない。
SESSION_OWNED_DEPTS = ("hq", "aegis-gl", "research-room", "keiei-kikaku", "kaizen-analyst", "hr-room")


def room_is_session_owned(dept):
    """その部屋の担当が**対話セッション本人**か(=総括本部4室)。

    ★2026-07-21 Chamiのスクショで発覚。02:17の便に 02:23 `研究室(無人代打)` が
      **「受領(既読/着手リアクション欠落)。担当の起床後に返答。」**と返していた。
      これは ORG-04 で「悪質」と判定したのと**寸分違わぬ嘘**——担当は対話セッション(私)で、
      「起床」するイベントは存在しない。私はターンの合間に居ただけで、在席(TTL150秒)が
      枯れたので代打が起きた。

    ★ORG-03の対処は「専任デーモンが居れば一次ackを省く」だったが、
      **デーモンが居ない部屋(=総括本部4室)は素通りしていた**。
      Chami裁定でデーモンを撤去した4室こそ、この嘘が出る場所だった=対処が穴を1つ残していた。

    → これらの部屋では**一次ackを打たない**。便はfollowupとして残り、
      15分で absence_watchdog が鳴らす。**偽の返事より沈黙が良い**(Chami既決の原則)。
    """
    return bool(dept) and dept in SESSION_OWNED_DEPTS


def room_has_own_responder(dept):
    """その部屋に**自前の応答者**(専任dept_daemon)が生きているか。

    ★これは「代打すべきか」ではなく「**一次ackを打つべきか**」の判定(2026-07-21 研究室HQ Vol.4)。

    背景= `forward_all` の部門は1便で2つのことが起きる: ①部屋のキャラが返信する
    ②main箱へ回送される。研究室が寝ていると代打がそのmain箱の便を処理して**Discordへ返信する**
    ため、**Chamiが同じ部屋で2回返事をもらう**(1回目=キャラ・2回目=代打の一次ack)。
    実測= `プラットホームse` 21:04 の1便に platform-se デーモンが応答済みなのに、
    main箱の写しにも代打が反応した。2026-07-21 00:52時点でmain箱に溜まっていた followup 5件は
    **全て部屋の側で既に応答済み**だった=代打の一次ackは1件も必要が無かった。

    判定は dept_daemon が公開している `/live`(127.0.0.1:<port>)へのTCP接続で行う。
    ログのmtime推定にしないのは、デーモンは無通信だとログを書かない=**静かに誤判定する**ため。

    ★fail-open(判定不能・DEPT_CONF読めない・dept未指定は全て False=従来どおり一次ackを打つ)。
      沈黙が最悪の事故なので、**迷ったら喋る側へ倒す**。この関数が壊れても代打は止まらない。
    """
    if not dept:
        return False
    try:
        import socket
        from dept_daemon import DEPT_CONF
        conf = DEPT_CONF.get(dept)
        if not conf or not conf.get("port"):
            return False
        with socket.create_connection(("127.0.0.1", int(conf["port"])), timeout=0.3):
            return True
    except Exception:
        return False  # ★必ず従来動作へ倒す(黙らせない)


def processed_ids():
    ids = set()
    if not os.path.exists(PROCESSED):
        return ids
    for line in open(PROCESSED, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line).get("msg_id")
            if m:
                ids.add(str(m))
        except Exception:
            continue
    return ids


def _channel_name(rec):
    """現在のchannel_idから最新の表示名を引く。旧便だけ記録済み名称へ戻る。"""
    channel_id = str(rec.get("channel_id") or "").strip()
    if channel_id.isdigit():
        try:
            path = os.path.join(LOCAL, "discord_channels.json")
            for row in json.load(open(path, encoding="utf-8")):
                if str(row.get("id") or "") == channel_id:
                    return str(row.get("name") or "").strip()
        except Exception:
            pass
    return str(rec.get("channel") or "").strip()


def handle(rec, token=None):
    """既読印と固定受領文をPythonで送る。token引数は旧呼び出し互換で未使用。"""
    channel = _channel_name(rec)
    reaction_target = str(rec.get("channel_id") or channel).strip()
    msg_id = str(rec.get("msg_id") or "").strip()

    if reaction_target and msg_id:
        try:
            subprocess.run(
                [sys.executable, REACT, "--channel", reaction_target,
                 "--msg", msg_id, "--emoji", "既読"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
        except Exception:
            pass  # 印の失敗で受領本文まで止めない

    if not channel:
        print("  機械受付失敗 [チャンネル不明]")
        return False
    try:
        p = subprocess.run(
            [sys.executable, PERSONA_SEND, "--channel", channel,
             "--persona", PERSONA, "--body", ACK_TEXT],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        print(f"  Python機械受付 [{channel}] rc={p.returncode}")
        return p.returncode == 0
    except Exception as e:
        print(f"  機械受付失敗 [{channel}] {type(e).__name__}")
        return False


def append_processed(line):
    with open(PROCESSED, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


QUEUE_DB = os.path.join(LOCAL, "queue", "inbox.db")
# ★research-roomを外した(2026-07-20 Chami裁定B)。あの部屋に専任dept_daemon(アメス・port18815)を
#   置いたため、両方がclaimしに行くと**勝った方で名乗りが変わる**(アメス or「研究室(無人代打)」)
#   =応答が非決定的になる。1領域1オーナー(RULES §3)を消費者にも適用し、部屋の主をデーモンに一本化する。
#   デーモン死亡時はdaemon_keeperが数秒で復帰させるので、可用性は落ちない
#   (むしろ代打より速い)。研究室Vol.9の対話窓が開いている間はデーモンが待機するのは従来どおり。
QUEUE_DEPTS = ("router", "main")  # main宛て=waiterデュアル監視と同じ


def cycle_queue(token=None):
    """段階2(2026-07-18): queue経路の代打。研究室死亡時にLeaseQueueのmain系宛てをclaim→処理→ack。

    切替後はjsonlに新着が来ないため、これが無いと「絶対応対の最後の受け皿」が盲目になる
    (手順書_受信基盤切替_段階2 §1-0)。DB/モジュールが無い間は何もしない=fail-open。
    機微deptはQUEUE_DEPTSに含まれない(dream-care等は部門dept付きでenqueueされ、ここでは触らない)。
    """
    if not os.path.exists(QUEUE_DB):
        return
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        q = LeaseQueue(QUEUE_DB)
    except Exception:
        return
    try:
        done = processed_ids()
        sent = 0
        held = []  # 機微でclaimしたまま保留したid(リース中=再claimされない→頭詰まりせず先へ進める)
        for dept in QUEUE_DEPTS:
            while sent < MAX_PER_CYCLE:
                if lab_alive():
                    break  # 研究室が起きた=即引く(多重応答防止。保留分はfinallyで返す)
                c = q.claim(dept=dept, who="claude_responder")
                if c is None:
                    break
                rec = c["body"] if isinstance(c["body"], dict) else {}
                mid = str(rec.get("msg_id", c["msg_id"] or ""))
                if mid in done:
                    q.ack(c["id"], result="skip(jsonl経路で処理済)")
                    continue
                if rec.get("dept") in SENSITIVE_DEPTS or room_is_session_owned(rec.get("dept")):
                    # 機微=PROTOCOL管轄で内容に触れない / 総括本部4室=本人セッションが処理する部屋。
                    # ★どちらもここでack(done化)してはいけない。done化すると次にセッションが開いても
                    #   waiterに出てこない=依頼が消える(ORG-12=Chamiの10時間放置の真因)。
                    #   held→末尾でnack=pendingへ戻し、セッションの起床を待つ。偽ackより沈黙。
                    held.append(c["id"])
                    continue
                if room_has_own_responder(rec.get("dept")):
                    # 部屋の専任デーモンが既に応答済み=一次ackは二重応答にしかならない。
                    # ★followupは下で必ず投函する(=本対応は落とさない。消すのは「重複した声」だけ)。
                    q.ack(c["id"], result="一次ack省略(部屋の専任デーモンが応答済み)")
                    print(f"{time.strftime('%H:%M:%S')} 一次ack省略: {rec.get('dept')} は専任デーモン稼働中")
                else:
                    ok = handle(rec)
                    q.ack(c["id"], result="代打応答" if ok else "代打失敗(再試行なし)")
                append_processed(json.dumps(rec, ensure_ascii=False))
                sent += 1
                # ★followup投函(jsonl経路と同じ穴の対。研究室の本対応へ必ず届ける)
                with open(INBOX, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "type": "followup", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "dept": rec.get("dept"), "channel": rec.get("channel"),
                        "author": rec.get("author"), "content": rec.get("content"),
                        "orig_msg_id": mid, "msg_id": mid + "-fu",
                        "note": "無人代打が一次ack済み(queue経路)。研究室が本対応すること",
                    }, ensure_ascii=False) + "\n")
        for qid in held:
            q.nack(qid)  # サイクル末尾でpendingへ返す(研究室が起きたら本人が読む)
        if sent:
            print(f"{time.strftime('%H:%M:%S')} 無人代打(queue経路)で {sent} 件処理")
    finally:
        q.close()


def cycle(token=None):
    if lab_alive():
        print("研究室が生存=代打しない(多重応答防止)")
        return
    cycle_queue()  # 段階2: queue経路(jsonlと並行して見る。切替後はこちらが主)
    if not os.path.exists(INBOX) or os.path.getsize(INBOX) == 0:
        return
    done = processed_ids()
    lines = [l for l in open(INBOX, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    remaining, sent = [], 0
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            remaining.append(line)
            continue
        if rec.get("type") in ("followup", "session-note"):
            remaining.append(line)  # ★followup/session-noteは研究室宛て。代打は触らない
            # (session-noteはセッション間連絡=Discord返信不要。代打が--printを浪費し
            #  followupを量産するだけ=2026-07-19実測で確認)
            continue
        mid = str(rec.get("msg_id", ""))
        # ★この判定は「処理済みか」より**前**に置く(2026-07-21 ORG-20)。
        #   実害= hqデーモンが便を捌く→PROCESSEDへ記帳→**その直後にここの `mid in done` が
        #   一致して箱から落とす**、という経路で、Chamiが「最優先」と明示したコンサル情報
        #   (Bluesky凍結の全体連絡)がセッションに一度も届かなかった。
        #   ★「デーモンが答えた」と「セッションが読んだ」は**別の完了**。前者で後者を消してはいけない。
        #   総括本部4室はセッション本人が最終処理する部屋なので、処理済みでも箱に残す。
        if rec.get("dept") in SENSITIVE_DEPTS or room_is_session_owned(rec.get("dept")):
            remaining.append(line)  # 機微 / 総括本部4室は本人セッションが応対。箱に残して待たせる。
            continue                # ★processedへ送らない=次のセッションが箱で必ず見る(ORG-12)
        if mid in done:
            continue  # 二重処理しない(main箱からは落とす)
        if sent >= MAX_PER_CYCLE:
            remaining.append(line)  # 上限。次巡回へ
            continue
        # 処理直前に研究室が起きていないか再確認(競合防止)
        if lab_alive():
            remaining.append(line)
            continue
        if room_has_own_responder(rec.get("dept")):
            # 部屋の専任デーモンが既に応答済み=一次ackは二重応答にしかならない(下でfollowupは残す)。
            print(f"{time.strftime('%H:%M:%S')} 一次ack省略: {rec.get('dept')} は専任デーモン稼働中")
        else:
            handle(rec)
        append_processed(line)  # 成否に関わらず台帳へ(暴走・無限再試行を防ぐ)
        sent += 1
        # ★followup投函(2026-07-18: 「担当の起床後に返答」が構造的に嘘だった穴の修正。
        #   実害=Chami「人事部門がずっと死んでるんやけど…」(研究室HQ 20:35)が代打ackのみで
        #   本対応されず放置。代打は台帳記帳+箱から除去するため、担当には永遠に届かなかった)。
        #   本対応が要る便はfollowupレコードとして箱へ残す→waiterが鳴り研究室が本対応する。
        #   msg_idを変える(-fu)ので台帳dedupeに食われない。代打自身は上のtype判定で素通り。
        remaining.append(json.dumps({
            "type": "followup", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dept": rec.get("dept"), "channel": rec.get("channel"),
            "author": rec.get("author"), "content": rec.get("content"),
            "orig_msg_id": mid, "msg_id": mid + "-fu",
            "note": "無人代打が一次ack済み。研究室が本対応すること",
        }, ensure_ascii=False))
    # main箱を「残す分」だけに書き戻す(処理済み+機微以外は消える)
    with open(INBOX, "w", encoding="utf-8") as f:
        for line in remaining:
            f.write(line + "\n")
    if sent:
        print(f"{time.strftime('%H:%M:%S')} 無人代打で {sent} 件処理")


def main():
    once = "--once" in sys.argv
    print(f"AI不使用の機械受付 起動 ({'--once' if once else f'{POLL_SEC}秒間隔'}・研究室が死んでいる間のみ動く)")
    while True:
        try:
            cycle()
        except Exception as e:
            print(f"巡回失敗: {type(e).__name__}")
        if once:
            break
        time.sleep(POLL_SEC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
