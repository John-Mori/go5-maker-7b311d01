#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""dispatch — 部門へ「指令」を直接キューへ投函する(組織内の伝達路)。

★2026-07-21 Chami指摘(ORG-21)で新設:
  「私の発言に対しては動くが、**転送された内容には反応しない**。他部門が研究室へ上げてきた時も
   反応が無かった。私以外の発言で転送されてきた内容にも対応できるようにしてほしい。
   そうでないと**どこも動かない**。アロンソ監督のこの全体連絡も結局意味がないかもしれない」

  →**指摘は完全に正しかった**。実測:
    `discord_gateway.on_message` は `if m.author.bot or m.webhook_id: return` で
    **bot/webhookの発言を全部捨てる**(自分の返信でループしないための正しい設計)。
    ところが部門への連絡は `persona_send`(=webhook)で送っていたため、
    **Discordには見えているのにキューに1行も入らない=どの部門も動かない**。
    HQが「全体連絡した」と思っていたものは、**誰にも配られていなかった**。

★なぜ「gatewayでwebhookを通す」ようにしないのか:
  それをやると**デーモン自身の返信も拾って無限ループ**する(gatewayのコメントが警告している)。
  Discordは**人が読む窓**であって配送路ではない。配送路は最初からキューだった。
  だから**キューへ直接入れる**のが正しい。ループの余地が構造的に無い。

使い方:
  python scripts/llm/dispatch.py --dept research-room --from "シャビ・アロンソ(研究室HQ)" \
      --body-file brief.txt [--also-post] [--dry-run]
  python scripts/llm/dispatch.py --dept a,b,c ...      # 複数部門へ同報

  --also-post を付けると Discord にも投稿する(Chamiが経緯を追えるように)。
  ★キュー投函が本体で、Discord投稿は**人向けの写し**。順序は「キュー→Discord」。

★2026-07-22 ORG-43(研究室HQ発注・Chami「じゃあ治しといて」)で **同報ガード** を新設:
  宛先が3部門以上のときは `--broadcast "<理由>"` を必須にする(1〜2部門は従来どおり無変更)。
  経緯= HQが `00_AI-HQ/departments/00_common/全部門共通規律.md` に規約を1行足した時点で、
  そのファイルは**毎便すべての部門のプロンプトへ自動注入される(再起動不要)**ため
  **19部門への配布はすでに完了していた**。にもかかわらずHQは同じ内容を dispatch で
  **26通ばら撒いた**(しかも本文に「今この瞬間から効いている」と自分で書きながら)。
  Chami原文=「全部門に伝えてとは言ったけど、**わざわざチャットじゃなくて裏で手配できない?**
   すごいメタ的なこと言うと、**1つのAIエージェントでしょ? そんな表で流さないと把握できないの?**」
  → 心がけでは再発する。**癖でばら撒けないように機械で止める。**
"""
import argparse
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
QUEUE_DB = os.path.join(LOCAL, "queue", "inbox.db")
CHANNELS = os.path.join(LOCAL, "discord_channels.json")
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")


# ★3階梯のガード(2026-07-21 ORG-34・Chami指摘で新設)
#   RULES §6.4=「カテゴリ=部門、その部門長=そのカテゴリの『研究室』。**飛び級しない**」。
#   Chami原文=「今回の件が研究室HQ→システム改修部門って流れだったから、
#   **間の部門長のモドリッチ(AD研究室)が通ってない**。…**まずAD研究室を通すこと**」
#   ★HQはX切替の指令を system-engineer / frontend へ**直接**投げていた=②を飛ばした運用ミス。
#     部門長が把握しないまま配下が動くと、部門長が事業の全体像を持てなくなる。
#   → 事業層/組織層の配下へ直接投げようとしたら**止めて部門長を教える**。
#     `--direct` を明示した時だけ通す(緊急時の逃げ道。理由を添えて使うこと)。
CATEGORY_HEAD = {
    # 配下dept → その部門長(② カテゴリの研究室)
    "ADAFI事業部": "research-room",
    "イージス AegisConciel": "aegis-gl",
}
# Discordの実カテゴリを正とする(registryのcategoryは15室で未設定のため使えない)。
LAYER_OF = {
    "1528674269285060731": "イージス AegisConciel",
    "1525644847346880713": "ADAFI事業部",
}


def head_of(dept):
    """その部門の「部門長」を返す。部門長自身・最上位・判定不能は None(=素通し)。"""
    if dept in ("hq", "research-room", "aegis-gl", "keiei-kikaku"):
        return None                 # 部門長自身と最上位、横から支える経営企画は対象外
    try:
        import urllib.request
        tok = open(os.path.join(LOCAL, "discord_bot_token.txt"), encoding="utf-8").read().strip()
        cid = None
        for c in json.load(open(CHANNELS, encoding="utf-8")):
            if c.get("dept") == dept:
                cid = c["id"]
                break
        if not cid:
            return None
        req = urllib.request.Request(f"https://discord.com/api/v10/channels/{cid}",
                                     headers={"Authorization": f"Bot {tok}", "User-Agent": "go5/1.0"})
        parent = json.load(urllib.request.urlopen(req, timeout=15)).get("parent_id")
        return CATEGORY_HEAD.get(LAYER_OF.get(str(parent)))
    except Exception:
        return None                 # ★判定できない時は止めない(配達を殺さない=fail-open)


# ★同報ガード(2026-07-22 ORG-43)。3部門以上=「同報」とみなす閾値。
#   1〜2部門は日常の発注なので**一切邪魔しない**(誤発火する安全網は無視される=ORG-42の教訓)。
BROADCAST_MIN = 3

BROADCAST_DENY_MSG = """★3部門以上への同時送信には --broadcast "<理由>" が要る。
  ★規約・規律の周知が目的なら、そもそも配る必要は無い。
    00_AI-HQ/departments/00_common/全部門共通規律.md を編集すれば
    毎便すべての部門のプロンプトへ自動注入される(再起動不要)= それで配布は完了している。
    規約=編集して終わり(配らない) / 依頼=その部門にだけ出す。
    迷ったら「相手が何か作業をするか?」で分ける。しないなら配るな。"""


def log_broadcast(reason, depts, sender, dry_run):
    """同報の理由を残す。標準出力が正(dry-runでも見える)＋実送信時のみ台帳へ追記。"""
    print(f"★同報({len(depts)}部門) 理由: {reason}")
    print(f"  宛先: {','.join(depts)}")
    if dry_run:
        return                        # dry-runは台帳を汚さない(実測が本番の記録に混ざらないように)
    try:
        path = os.path.join(LOCAL, "llm", "broadcast_audit.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "from": sender,
                "depts": depts,
                "reason": reason,
            }, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"  (台帳への記録に失敗: {type(e).__name__}: {e})")   # 記録失敗で配達は止めない


def channel_name_of(dept):
    try:
        for c in json.load(open(CHANNELS, encoding="utf-8")):
            if c.get("dept") == dept:
                return c.get("name", "")
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────────────────
# ★C-023(2026-07-30)= 部門間「実依頼」の可視化。以下は**純粋関数**(副作用なし)。
#   本番/Discord/queueに触れないのでGOLDENテストで固定できる(tests/test_dept_request_visibility.py)。
# ─────────────────────────────────────────────────────────────────────

def build_work_header(sender, work):
    """実依頼(--work)を表に出す時の見出しを1行で作る。
    ★Chamiが「① 渡ったか ② 何を頼んだか」を一目で分かるようにするための行。"""
    who = (sender or "").split("(")[0].strip() or "不明"
    line = (work or "").strip().replace("\n", " ")
    return f"【実依頼 / from {who}】{line}"


# ★2026-08-23 Chami指示(msg 1540775762117009438)=
#   「研究室HQと各研究室の長すぎるやり取りは裏で組んでくれればいいよ、実際自分読んでないし、
#    長すぎるから。なんか結果だけ返してくれればいいし、トーク履歴が汚れるというか長すぎるからいらん。
#    ほんとに必要そうなもんだけ表でやりとりしといて。」
#   → C-023(実依頼を表に出す)は**廃止しない**。「渡ったか/何を頼んだか」の1行は残す。
#     変えるのは**表へ流す量**だけ= 見出し + 要点まで。本体の全文は便(キュー)にだけ載る=裏。
#   ★配送は無傷: 相手部門が読むのは queue の content であって表の写しではない
#     (dispatch() は rec["content"] に body 全文を入れて enqueue する)。表を削っても仕事は届く。
FRONT_LIMIT = 280


def front_digest(body, limit=FRONT_LIMIT):
    """表(Discord)へ出す本文を要点まで削る。★純粋関数。

    limit以下ならそのまま(短い便を邪魔しない)。超えたら先頭limit字で切り、
    **何字を裏へ回したか**を1行で明示する(黙って落とすと「途中で切れた」に見えるため)。
    """
    s = (body or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + f"…\n(以下 {len(s) - limit}字は裏の便へ。表は要点まで)"


# ─────────────────────────────────────────────────────────────────────
# ★★C-050の恒久= **便を出す側が宛先(誰が読む本文か)を宣言する**
#   (2026-08-23 研究室HQ→イージス研究室 回送 msg DISPATCH-aegis-gl-1787431376034)
#
#   止血までの形は受け手(dept_daemon)が**差出人の名前の文字列**を見て当てていた
#   (「トリガー」「巡回」「監視」…を含むか)。当て推量なので、新しいトリガーの名前が
#   その一覧に当たらなければ**またChamiの字が消える**。実際に消した実物=
#   8/22の振り返り1,646字(author「定刻トリガー(朝5時)」・via=dispatch)。
#
#   → 判定の材料を「名前」から「宣言」へ移す。宣言は**差出人にしか分からない事実**だ。
#     - `--audience ai`    = AI同士の便。相手の返信は表を要点まで削ってよい。
#     - `--audience chami` = 出来上がる本文をChami本人が読む。**1字も削らない**。
#     - 宣言なし           = 削らない(fail-open)。★「分からないから削る」を構造から消す。
#   ★宣言は便に必ず載せる(値が空でも key は載せる)= 台帳から「宣言の無い便が何通あるか」を
#     数えられる形にしておく(検査= tests/test_c050_audience_declaration.py)。
AUDIENCE_AI = "ai"
AUDIENCE_CHAMI = "chami"
AUDIENCE_CHOICES = (AUDIENCE_AI, AUDIENCE_CHAMI)
AUDIENCE_WARN = (
    "  ★宛先の宣言が無い便= 表は削らない(C-050は効かない)。\n"
    "    AI同士の長いやり取りなら --audience ai / Chami本人が読む本文なら --audience chami")


def audience_fields(audience):
    """便へ載せる宛先の宣言を組み立てる。★純粋関数。

    戻り値の dict をそのまま rec へ merge する。`audience` は**必ず載る**(宣言なしは "")。
    `front_full` は研究室HQが止血で入れた掛け金= Chami向けの時だけ True で立てる
    (受け手の古い版でも「削るな」が伝わる=載せ替えの途中でも字が消えない)。
    """
    a = (audience or "").strip().lower()
    if a not in AUDIENCE_CHOICES:
        a = ""
    out = {"audience": a}
    if a == AUDIENCE_CHAMI:
        out["front_full"] = True
    return out


def build_work_post(sender, work, body):
    """相手部門チャンネルへ出す投稿本文=見出し + 要点(全文ではない)。"""
    return build_work_header(sender, work) + "\n\n" + front_digest(body)


def is_work_request(work):
    """--work が実質的な値を持つ=実依頼=表に出す、か。空/空白は False(=裏のまま)。"""
    return bool((work or "").strip())


def pick_msg_id(synthetic_id, posted_id):
    """キューへ載せる msg_id を決める。実Discord id が取れたらそれ(=リアクションが実投稿へ載る)、
    取れなければ従来の合成id(=便は必ず届く。Part 2は空振りするが配送は無傷)。"""
    p = str(posted_id or "").strip()
    return p if p.isdigit() else synthetic_id


def post_work_to_channel(dept, persona, post_body, timeout=90):
    """相手部門チャンネルへ実依頼を投稿し、**実Discord message_id を返す**(取れなければ "")。

    ★best-effort: 何が起きても例外を投げない(呼び側=dispatch は投稿失敗でも便を届ける)。
    ★実IDを得るため persona_send に --print-id を渡す(want_id=?wait=true を強制。
      通常のdept投稿はwait無しでIDを返さないため、この経路専用の口を足した)。
    """
    try:
        p = subprocess.run([sys.executable, PERSONA_SEND, "--dept", dept,
                            "--persona", persona, "--print-id", "--body", post_body],
                           capture_output=True, timeout=timeout, text=True,
                           encoding="utf-8", errors="replace")
        import re
        m = re.findall(r"msg=(\d+)", (p.stdout or ""))
        return m[-1] if m else ""
    except Exception:
        return ""              # 投稿失敗は握り潰す。便はこの後(実は既に)enqueue される


def dispatch(dept, sender, body, also_post=False, dry_run=False, work="", audience=""):
    """1部門へ指令を投函する。戻り値=(ok, msg_id)。

    ★C-023: work(=--workの一行)が実質値を持つ時だけ「実依頼」として相手部門チャンネルへ表投稿する。
      workが空なら従来と1ミリも変わらない(投稿経路に入らない=裏のまま)。
    ★順序と fail-open: 便のenqueueが本体。実依頼のときは「表投稿→実ID取得→その実IDで便を載せる」
      が理想だが、**投稿が失敗しても便は必ず届く**ように、実IDが取れなければ合成idで enqueue する。
      投稿の失敗は dispatch の失敗にしない(便のenqueue成否だけで判定)。
    """
    ch = channel_name_of(dept)
    if not ch:
        print(f"  [{dept}] ★台帳にチャンネルが無い=投函先不明。スキップ")
        return False, ""
    synthetic = f"DISPATCH-{dept}-{int(time.time() * 1000)}"
    is_work = is_work_request(work)
    aud = audience_fields(audience)

    if dry_run:
        if is_work:
            print(f"  [dry-run] {dept} <- 実依頼(表投稿あり) {len(body)}字 (ch={ch})")
            print(f"    見出し: {build_work_header(sender, work)}")
        else:
            print(f"  [dry-run] {dept} <- {len(body)}字 (ch={ch})")
        print(f"    宛先の宣言= {aud['audience'] or '(無し)'}")
        if not aud["audience"]:
            print(AUDIENCE_WARN)
        return True, synthetic

    # ★実依頼=先に相手部門チャンネルへ表投稿し、実IDを得る(best-effort・失敗しても続行)。
    #   これを enqueue の前に置く理由= 便の msg_id にその実IDを載せ、デーモンの既読/着手印を
    #   実投稿へ着弾させるため(Part 2)。投稿が失敗しても下の enqueue は必ず走る=便は届く。
    posted_id = ""
    if is_work:
        posted_id = post_work_to_channel(dept, sender.split("(")[0], build_work_post(sender, work, body))

    mid = pick_msg_id(synthetic, posted_id)
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dept": dept,
        "channel": ch,
        # ★送信者を明示する。デーモンが「誰の指示か」を判断できるようにするため。
        #   Chami本人ではないので `chami_fusoh` を騙らない(騙ると人事の記録が汚れる)。
        "author": sender,
        "content": body,
        "msg_id": mid,
        "via": "dispatch",           # 組織内伝達であることの目印
    }
    # ★宛先の宣言(C-050恒久)。key は常に載せる= 宣言の無い便を後から数えられる形にする。
    rec.update(aud)
    if is_work:
        rec["work"] = work.strip()   # 何を頼んだかを便にも残す(後追い可能に)
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        q = LeaseQueue(QUEUE_DB)
        q.enqueue(json.dumps(rec, ensure_ascii=False), msg_id=mid, dept=dept)
        q.close()
    except Exception as e:
        print(f"  [{dept}] ★キュー投函に失敗: {type(e).__name__}: {e}")
        return False, mid
    if is_work:
        seen = "表投稿OK" if str(posted_id).isdigit() else "表投稿は失敗(便は届いた)"
        print(f"  [{dept}] 実依頼をキューへ投函 msg={mid} (ch={ch}) [{seen}] 宛先={aud['audience'] or '(無し)'}")
    else:
        print(f"  [{dept}] キューへ投函 msg={mid} (ch={ch}) 宛先={aud['audience'] or '(無し)'}")
    if not aud["audience"]:
        print(AUDIENCE_WARN)
    if also_post and not is_work:
        # ★--also-post は従来どおり(任意の便の人間向け写し)。実依頼は既に表投稿済みなので
        #   二重投稿しない(--work と --also-post が両方来ても表は1回だけ)。
        # ★2026-08-23 C-050(イージス研究室)= ここも front_digest を通す。
        #   理由= --work の表投稿だけ削っても、**同じ全文が --also-post で表へ出る抜け道**が
        #   残っていたら C-050 はザルになる(HQの依頼 msg 1540778224659988543 の宿題2)。
        #   全文は上の enqueue で rec["content"] へ既に載っている=**裏に完本がある**ので
        #   表を削っても失われない(この「裏に完本がある時だけ削る」が front_digest の適用条件)。
        try:
            subprocess.run([sys.executable, PERSONA_SEND, "--dept", dept,
                            "--persona", sender.split("(")[0], front_digest(body)],
                           capture_output=True, timeout=90)
        except Exception:
            pass          # 写しの失敗で本体(キュー投函)を巻き添えにしない
    return True, mid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", required=True, help="カンマ区切りで複数可")
    ap.add_argument("--from", dest="sender", default="シャビ・アロンソ(研究室HQ)")
    ap.add_argument("--body-file")
    ap.add_argument("--body")
    ap.add_argument("--also-post", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--broadcast", default="",
                    help="3部門以上へ同時送信する理由(3部門以上のときは必須)。"
                         "★規約の周知は配らずに 00_common/全部門共通規律.md を編集する")
    ap.add_argument("--direct", action="store_true",
                    help="3階梯を飛ばして配下へ直接投函する(緊急時のみ・理由を本文に書く)")
    ap.add_argument("--from-dept", dest="from_dept", default="hq",
                    help="送信元の部門(既定=hq)。★部門長が自分の配下へ出す時は自分のdeptを指定する"
                         "(例 --from-dept research-room)。正規の下り(②→①)はブロックしない")
    ap.add_argument("--work", default="",
                    help="★C-023: 実依頼(相手が実作業をする=作業/エラー/バグ/調査/改修の引き渡し)の"
                         "一行サマリ。付けると相手部門チャンネルへ**表**投稿する(Chamiが①渡ったか"
                         "②何を頼んだかを追える)。付けなければ従来どおり裏(相槌/通達/配布)。")
    ap.add_argument("--audience", default="", choices=["", AUDIENCE_AI, AUDIENCE_CHAMI],
                    help="★C-050: この便が頼む本文を**誰が読むか**の宣言。"
                         "ai=AI同士の便(相手の返信は表を要点まで削ってよい) / "
                         "chami=Chami本人が読む本文(1字も削らない)。"
                         "★宣言なしは削らない(fail-open)=名前で当てるのをやめた。")
    a = ap.parse_args()

    body = a.body or ""
    if a.body_file:
        body = open(a.body_file, encoding="utf-8").read().strip()
    if not body:
        print("本文が空。--body か --body-file を指定する。")
        return 1

    depts = [d.strip() for d in a.dept.split(",") if d.strip()]

    # ★同報ガード(2026-07-22 ORG-43)。--direct とは別物なので混ぜない(両方指定できる)。
    #   dry-run も同じ判定を通す=送る前に気づけるようにするため。
    if len(depts) >= BROADCAST_MIN and not a.broadcast.strip():
        print(BROADCAST_DENY_MSG)
        print(f"  (今回の宛先 {len(depts)}部門: {','.join(depts)})")
        return 2
    if len(depts) >= BROADCAST_MIN:
        log_broadcast(a.broadcast.strip(), depts, a.sender, a.dry_run)

    # ★3階梯チェック(RULES §6.4「飛び級しない」)
    if not a.direct:
        blocked = {}
        for d in depts:
            h = head_of(d)
            # ★送信元が「その部門の部門長本人」なら正規の下り=止めない(2026-07-22 ORG-42)。
            #   AD-GL(モドリッチ)の指摘: 差出人を見ずに配下deptを一律ブロックしていたため、
            #   **部門長が自分の配下へ出す正規の経路まで止まっていた**。
            #   結果「部門長が毎回 --direct を使う」ことになり、緊急用の逃げ道が日常運用になって
            #   ガードが形骸化する。モドリッチの言葉=
            #   「発火しない安全網は検証されない、の逆で、**常に誤発火する安全網は無視される**」。
            #   ORG-34で止めたかったのは **③HQ→①配下 の飛び級**であって、②→①ではない。
            if h and h == a.from_dept:
                continue
            if h and h not in depts:
                blocked[d] = h
        if blocked:
            print("★3階梯に反しています(RULES §6.4「飛び級しない」)。投函を中止しました。")
            for d, h in blocked.items():
                print(f"  '{d}' の部門長は '{h}' です。まず '{h}' へ通してください。")
            heads = sorted(set(blocked.values()))
            print(f"  推奨: --dept {','.join(heads)} へ出し、配下への割り振りは部門長に任せる。")
            print("  どうしても直接出す必要がある時だけ --direct を付ける(理由を本文に書くこと)。")
            return 2

    ok = 0
    for d in depts:
        good, _ = dispatch(d, a.sender, body, a.also_post, a.dry_run, a.work, a.audience)
        ok += 1 if good else 0
    print(f"投函 {ok}/{len(depts)} 部門")
    return 0 if ok == len(depts) else 1


if __name__ == "__main__":
    sys.exit(main())
