# -*- coding: utf-8 -*-
"""whatis.py — Discordの便が「急に出てきたこれ何?」になった時の出所解決。

Chamiは前日24hで「これ何?」を2回聞いている(2026-09-02 11:30 / 16:57「急に出てきたこれ何?」)。
どちらも別チャンネルに出た便を指して"何の便か分からない"という手数。
この道具は msg_id(またはDiscordリンク)を1本渡すと、どの部門・人格・何のための便か・
どのチャンネル・いつ を台帳(send_audit / work_audit / discord_inbox)から引いて1画面で返す。
=「これ何?」を調査でなく1コマンドの照会に落とし、司令塔とChamiの往復手数を削る。

使い方:
  python scripts/discord/whatis.py 1544752530511106295
  python scripts/discord/whatis.py https://discord.com/channels/G/C/<msg_id>

出所が台帳に無い時は「未記録(webhook直投稿の疑い)」と正直に返す(茶番にしない)。
出力は local/表示のみ・実名や本文の中身は出さず、部門/人格/目的(head)/チャンネルの骨格だけ。
"""
import json, os, re, sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

LEDGERS = [
    ("send_audit", "local/llm/send_audit.jsonl"),   # 我々が撃った便(msg_id+dept+persona+head+channel)
    ("work_audit", "local/llm/work_audit.jsonl"),    # 部門作業の便(msg_id+dept+author)
    ("inbox",      "local/discord_inbox.jsonl"),     # 表に着地した便(dept+author+content)
]


def extract_id(arg):
    """引数からmsg_idを取り出す(生ID / Discordリンク末尾 の両対応)。
    リンクは .../channels/<guild>/<channel>/<msg_id> なので、必ず末尾のIDを採る
    (先頭を採るとguild_idを掴む=実測バグ 2026-09-03)。"""
    nums = re.findall(r"\d{15,25}", arg or "")
    return nums[-1] if nums else ""


def scan(msg_id):
    hits = []
    for label, rel in LEDGERS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        try:
            for line in open(path, encoding="utf-8"):
                if msg_id not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if str(d.get("msg_id") or d.get("id") or "") != msg_id:
                    continue
                hits.append((label, d))
        except Exception:
            continue
    return hits


def summarize(label, d):
    dept = d.get("dept") or "(不明)"
    persona = d.get("persona") or d.get("author") or d.get("who") or ""
    head = d.get("head") or d.get("何") or d.get("what") or ""
    ch = d.get("channel") or d.get("channel_id") or ""
    ts = str(d.get("ts") or "")[:19]
    head = (head or "").replace("\n", " ")[:80]
    return f"[{label}] {ts} / 部門={dept} / 人格={persona or '(記載なし)'} / ch={ch}\n         目的: {head or '(head記載なし)'}"


def main():
    if len(sys.argv) < 2:
        print("使い方: python scripts/discord/whatis.py <msg_id または Discordリンク>")
        return 2
    msg_id = extract_id(sys.argv[1])
    if not msg_id:
        print("msg_id を取り出せなかった(15桁以上の数字が要る)")
        return 2
    hits = scan(msg_id)
    print(f"■ whatis {msg_id}")
    if not hits:
        print("  台帳に無い= 未記録の便(webhook直投稿の疑い / 古い便)。send_audit・work_audit・inbox のどれにも msg_id が無い。")
        print("  → この便は出所を機械で辿れない。webhook投稿口に msg_id 記録を足すのが次の一手。")
        return 1
    for label, d in hits:
        print("  " + summarize(label, d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
