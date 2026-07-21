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


def channel_name_of(dept):
    try:
        for c in json.load(open(CHANNELS, encoding="utf-8")):
            if c.get("dept") == dept:
                return c.get("name", "")
    except Exception:
        pass
    return ""


def dispatch(dept, sender, body, also_post=False, dry_run=False):
    """1部門へ指令を投函する。戻り値=(ok, msg_id)。"""
    ch = channel_name_of(dept)
    if not ch:
        print(f"  [{dept}] ★台帳にチャンネルが無い=投函先不明。スキップ")
        return False, ""
    mid = f"DISPATCH-{dept}-{int(time.time() * 1000)}"
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
    if dry_run:
        print(f"  [dry-run] {dept} <- {len(body)}字 (ch={ch})")
        return True, mid
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        q = LeaseQueue(QUEUE_DB)
        q.enqueue(json.dumps(rec, ensure_ascii=False), msg_id=mid, dept=dept)
        q.close()
    except Exception as e:
        print(f"  [{dept}] ★キュー投函に失敗: {type(e).__name__}: {e}")
        return False, mid
    print(f"  [{dept}] キューへ投函 msg={mid} (ch={ch})")
    if also_post:
        try:
            subprocess.run([sys.executable, PERSONA_SEND, "--dept", dept,
                            "--persona", sender.split("(")[0], body],
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
    ap.add_argument("--direct", action="store_true",
                    help="3階梯を飛ばして配下へ直接投函する(緊急時のみ・理由を本文に書く)")
    a = ap.parse_args()

    body = a.body or ""
    if a.body_file:
        body = open(a.body_file, encoding="utf-8").read().strip()
    if not body:
        print("本文が空。--body か --body-file を指定する。")
        return 1

    depts = [d.strip() for d in a.dept.split(",") if d.strip()]

    # ★3階梯チェック(RULES §6.4「飛び級しない」)
    if not a.direct:
        blocked = {}
        for d in depts:
            h = head_of(d)
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
        good, _ = dispatch(d, a.sender, body, a.also_post, a.dry_run)
        ok += 1 if good else 0
    print(f"投函 {ok}/{len(depts)} 部門")
    return 0 if ok == len(depts) else 1


if __name__ == "__main__":
    sys.exit(main())
