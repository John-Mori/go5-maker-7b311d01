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
CHANNELS = "local/discord_channels.json"  # チャンネルID→部屋名/部門の登録簿


def load_channels():
    """チャンネル登録簿を {id: (name, dept)} で返す。
    ChamiはmsgIDでなく"チャンネルID"を裸で落として指すことが多い
    (2026-09-04実測=前日24hで落とした4IDは全部チャンネルID)。
    だからmsgIDとして見つからない前に、まずチャンネルIDかを照合する。"""
    path = os.path.join(ROOT, CHANNELS)
    m = {}
    if not os.path.exists(path):
        return m
    try:
        for row in json.load(open(path, encoding="utf-8")):
            cid = str(row.get("id") or "")
            if cid:
                m[cid] = (row.get("name") or "(名称なし)", row.get("dept") or "(不明)")
    except Exception:
        pass
    return m


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


def live_body(msg_id, channel_id=""):
    """台帳に本文が無い時、Discordの実物から読んで印字する(2026-09-05・経営企画依頼)。

    役割分担= whatis は台帳(通信しない)、read_msg は実物(通信する)。
    読めなければ False を返す(=呼び側がコマンドの案内に落ちる)。トークンが無い環境でも死なない。
    """
    try:
        from read_msg import fetch, jst
        res = fetch(msg_id, channel_id=channel_id or None, scan=False)
    except Exception as e:
        print(f"      (実物を読めない: {type(e).__name__})")
        return False
    if not res.get("ok"):
        return False
    m = res["msg"]
    # ★content だけだと embed で出た部屋の便が「0字」に見え、照会そのものが茶番になる
    #   (便6-3)。正本 msg_text() で content+embeds を読む。
    sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
    try:
        from msg_text import msg_text
        body = msg_text(m)
    except Exception as e:                     # noqa: BLE001
        print(f"      (警告: msg_text.py を読めない({type(e).__name__})= content だけで表示する)")
        body = m.get("content") or ""
    a = m.get("author") or {}
    print(f"      Discord実物 {len(body)}字 / 投稿者={a.get('global_name') or a.get('username')}"
          f" / {jst(m.get('timestamp'))}")
    for line in body.split("\n"):
        print("  | " + line)
    return True


def main():
    # ★--body= 台帳に残っている**本文の全文**を出す(2026-09-04・DEF-manga-shorts-ccd93dc601)。
    #   既定は今まで通り骨格だけ。「Chamiが『1 b 2 a』で確定した、その選択肢の本文は何だったか」を
    #   後から引くための口で、send_audit が 2026-09-04 以降に残す `body` 列を読む。
    #   それ以前の便は head(120字)しか無い= その時は正直にそう言う(茶番にしない)。
    argv = [a for a in sys.argv[1:] if a != "--body"]
    want_body = len(argv) != len(sys.argv[1:])
    if not argv:
        print("使い方: python scripts/discord/whatis.py <msg_id または Discordリンク> [--body]")
        return 2
    msg_id = extract_id(argv[0])
    if not msg_id:
        print("msg_id を取り出せなかった(15桁以上の数字が要る)")
        return 2
    hits = scan(msg_id)
    ch = load_channels().get(msg_id)
    print(f"■ whatis {msg_id}")
    if ch:
        # ★これは「便(メッセージ)」ではなく「チャンネルID」だった。
        # Chamiが「1533… ここ」「またエラー」と指すのはこの形。webhook便と誤答しない。
        name, dept = ch
        print(f"  = チャンネルID(便ではない): {name} / 部門={dept}")
        if not hits:
            return 0
        print("  ↓ 同じ数字が便のmsg_idとしても台帳に有り:")
    if not hits:
        if not ch:
            print("  台帳に無い= 未記録の便(webhook直投稿の疑い / 古い便)。send_audit・work_audit・inbox のどれにも msg_id が無い。")
            print("  → この便は出所を機械で辿れない。webhook投稿口に msg_id 記録を足すのが次の一手。")
            print(f"  → 本文そのものはDiscordの実物から読める: python scripts/discord/read_msg.py {msg_id}")
            return 1
        return 0
    for label, d in hits:
        print("  " + summarize(label, d))
        if want_body:
            body = d.get("body") or d.get("content") or ""
            if body:
                cut = "(★全文が入り切らず切られている)" if d.get("body_truncated") else ""
                print(f"  --- 本文の全文 {cut}({len(body)}字)")
                for line in str(body).split("\n"):
                    print("  | " + line)
            else:
                # ★「無い」を「短い」で埋めない。head しか無いなら head しか無いと言う。
                #   ただし黙って諦めない= 2026-09-05 から読み取り口(read_msg.py)がある。
                #   台帳に本文が無い便(2026-09-04より前 / 他室・他botの発言)はDiscordの実物から読む。
                print("  --- 本文の全文= この台帳には無い(2026-09-04より前の便は head120字まで)。"
                      "\n      → Discordの実物から読む:")
                if not live_body(msg_id, d.get("channel_id") or ""):
                    print(f"        python scripts/discord/read_msg.py {msg_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
