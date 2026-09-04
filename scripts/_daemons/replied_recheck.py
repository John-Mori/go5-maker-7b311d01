#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`replied_unverified` を**後から**読み返して、本当の不着だけを残す(2026-08-05)。

なぜ要るか(実測):
  dept_daemon は返信を送った直後に verify_replied で実在確認し、確認できないと
  `replied_unverified` を記帳する。2026-07-29 に「少し待ってから数回試す」対策
  (REPLIED_VERIFY_TRIES=3 / WAIT=2秒 = 最大約4秒)が入った。**それでも止まらなかった。**

  今日(08-05)、修正日以降の unverified 7件を Discord API で1件ずつ引き当てた結果=
    07-31 22:00 改修部門α    → 投稿は **+22秒** 後
    07-31 22:10 質問(llm-qa)  → **+7秒**
    07-31 22:35 コンサル情報   → **+26秒**
    08-01 04:13 イージス研究室 → **+3秒**
    08-03 00:17 ad研究室      → **+237秒**
    08-03 01:19 改修部門α     → **+90秒**
    08-03 01:20 研究室HQ      → **+59秒**
  **7件すべて実在した(真の不着ゼロ)。** ズレは3秒〜237秒で、4秒の同期リトライでは
  原理的に届かない。かつ、これ以上待たせると**返信の経路そのものを詰まらせる**
  (デーモンが1件の確認で最大4分止まる)。

  → 同期で決めるのをやめる。**送った直後は「まだ分からない」で通し、時間が経ってから
    別の目で読み返す。** これが「心がけでなく機構に載せる」形(共通規律§3)。

  ★なぜ放置してはいけないか= **嘘の未確認は、本物の未配送を埋もれさせる**(ORG-42)。
    台帳に33件の `replied_unverified` が積まれていると、本当に消えた1件が見えない。

★2026-08-05 追記(初版の誤り2つ・プラットフォームSE 一ノ瀬怜の指摘で実物照合して判明):
  初版は「本物の不着2件」を出したが、**2件とも着地していた**(誤警報)。原因は突合鍵ではなく
  **探した部屋を間違えていた**こと=
    (a) `{dept: channel}` の辞書にしたため、部屋を2つ持つ `learning-coach` の片方が消えていた
        → 実物は msg 1531736985369186398(質問-…ルーム1 / 07-29 03:55:55 / 記帳との差+2秒)。
    (b) 記帳の `dept` と着地した部屋が違う便がある(dept=llm-edu → 『ローカルllm成長進捗』)
        → 実物は msg 1531138019258531912(07-27 12:15:50 / 記帳との差 0秒=同秒)。
    (c) 走査を `after=` の前送りでやっていた。Discord は `after` でも新しい順に返し、繁忙部屋では
        **アンカー直後を飛ばす**(実測=イージス研究室 after=07-27 12:00 → 07-28 00:35 から返る)。
  → 部屋は evidence の `部屋=` で引き、外れたら全室を掃く。走査は `before` で古い方へ降りる。
  ★教訓= **不着の札は、全室を掃いてからでないと貼ってはいけない。**偽の警報は本物を埋める。

やること:
  request_log の `replied_unverified` のうち、まだ後追い判定が付いていないものを
  Discord API で広い窓(既定=記帳の+30分から-3分まで)を走査して突き合わせ、
    見つかった   → `replied_late_confirmed`(=空騒ぎだった)
    見つからない → `replied_missing`(**これが本物の不着=警報を出すべき唯一の状態**)
  を**追記**する。★既存行は1行も書き換えない(追記のみ)。★再送はしない(二重投稿を作らない)。

使い方:
  python scripts/_daemons/replied_recheck.py            # 判定して追記(既定)
  python scripts/_daemons/replied_recheck.py --dry-run  # 判定だけ・台帳へ書かない
  python scripts/_daemons/replied_recheck.py --min-age-min 10
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
REQUEST_LOG = os.path.join(LOCAL, "llm", "request_log.jsonl")
CHANNELS_JSON = os.path.join(LOCAL, "discord_channels.json")
API = "https://discord.com/api/v10"
DISCORD_EPOCH = 1420070400000
JST = dt.timezone(dt.timedelta(hours=9))

# 後追いで付く状態(これが付いている request_id は二度判定しない=冪等)
RESOLVED = ("replied", "replied_late_confirmed", "replied_missing")


def token():
    with open(os.path.join(LOCAL, "discord_bot_token.txt"), encoding="utf-8") as f:
        return f.read().strip()


def api(path, tok):
    req = urllib.request.Request(
        API + path, headers={"Authorization": "Bot " + tok,
                             "User-Agent": "go5-replied-recheck/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def to_sf(d):
    return (int(d.timestamp() * 1000) - DISCORD_EPOCH) << 22


def jst_of(mid):
    return dt.datetime.fromtimestamp(((int(mid) >> 22) + DISCORD_EPOCH) / 1000.0, JST)


def all_channels():
    """[(dept, name, id), ...] を**全行**返す。

    ★2026-08-05 実測の落とし穴= `{dept: id}` の辞書にしてはいけない。
      ① `learning-coach` は**部屋を2つ持つ**(質問-…ルーム1 / ルーム2)。辞書にすると後勝ちで
         片方が消え、消えた側に着地した返信を「不着」と誤判定する(実例= msg 1531736985369186398)。
      ② 記帳の `dept` と**実際に投稿された部屋が違う**ことがある
         (実例= dept=llm-edu の便が『ローカルllm成長進捗』へ着地 / msg 1531138019258531912)。
      → 部屋の特定は **evidence の `部屋=…` を第一の手がかり**にし、外れたら全室を掃く。
    """
    with open(CHANNELS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    rows = data if isinstance(data, list) else data.get("channels", list(data.values()))
    return [(r.get("dept"), r.get("name") or "", str(r["id"]))
            for r in rows if isinstance(r, dict) and r.get("id")]


def room_of(evidence):
    """evidence の「部屋=…」から部屋名を取り出す(次が空白で終わる)。"""
    ev = evidence or ""
    i = ev.find("部屋=")
    if i < 0:
        return ""
    return ev[i + 3:].split(" 先頭")[0].strip()


def candidate_channels(chans, dept, room):
    """探す順番= ①evidence の部屋名に一致 ②同じdeptの部屋(複数可) ③残り全部。

    ★③を必ず持つ= **『無い』と言い切る前に全室を掃く**。部屋を1つ間違えただけで
      『本物の不着』の札を貼ると、偽の警報が本物を埋もれさせる(ORG-42の逆)。
    """
    first = [c for c in chans if room and c[1] == room]
    second = [c for c in chans if c[0] == dept and c not in first]
    rest = [c for c in chans if c not in first and c not in second]
    return first + second + rest


_HEAD_RE = re.compile(r"先頭\d+字='(.*)'\s*$", re.S)
_WS_RE = re.compile(r"\s+")


def norm(s):
    """突合用に空白(改行・全角空白含む)を全部落とす。"""
    return _WS_RE.sub("", (s or "").replace("　", " "))


def head_of(evidence):
    """evidence 文字列から「先頭N字='…'」の中身を取り出す(突合の鍵)。

    ★2026-08-05 実測= 桁は40固定ではない。本文が短いと `先頭36字=` `先頭16字=` で記帳される。
      `先頭40字=` 決め打ちだと、その2件が「突合鍵が無い」=判定不能に落ちていた。
    """
    m = _HEAD_RE.search(evidence or "")
    return m.group(1) if m else ""


def load_rows(redo_missing=False):
    """(未解決の unverified 行, 解決済み request_id 集合) を返す。

    redo_missing=True のときは、過去に `replied_missing`(=本物の不着)と札を貼った行を
    **もう一度**判定し直す。★誤って貼った札を剥がす経路が無いと、偽の警報が台帳に残り続ける。
    """
    pend, resolved = [], set()
    resolved_states = tuple(s for s in RESOLVED if not (redo_missing and s == "replied_missing"))
    if not os.path.exists(REQUEST_LOG):
        return pend, resolved
    with open(REQUEST_LOG, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if '"state"' not in ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            st, rid = r.get("state"), r.get("request_id")
            if not rid:
                continue
            if st in resolved_states:
                resolved.add(rid)
            elif st == "replied_unverified":
                pend.append(r)
    return [r for r in pend if r.get("request_id") not in resolved], resolved


def match_keys(head):
    """突合キーの候補を作る。**先頭20字だけでは足りない**(実測)。

    理由= 多人格の部屋では返信が `[名前] 本文` のブロックごとに別メッセージで出るのに、
    verify_replied の突合キーは「文字数で割った最後の塊の先頭」から作られている。
    さらに前置き(『採点完了。フィードバックを出す。』のような実況)が頭に混ざる。
    その結果、**実在するのに一致しない**。この誤判定を `replied_missing`(=本物の不着)
    として書いてしまうと、ORG-42 の逆をやることになる=偽の警報で本物を埋もれさせる。

    → 名義タグ `[…]` で割り、12字以上の断片も候補に足す。**どれか1つでも当たれば実在**。
    """
    # ★2026-08-05 実測= 記帳の突合鍵は改行が半角スペースに潰れて入る
    #   (記帳='……言わない。 結果で判断して。' / 実物='……言わない。\n結果で判断して。')。
    #   そのまま突き合わせると**実在するのに一致しない**ので、両側とも空白を全部落として比べる。
    ks, h = [], norm(head or "")
    # ★先頭固定では当たらない実測がある(投稿側の頭に装飾や名義が付く)。
    #   40字の突合鍵の中を**ずらしながら**見る=どこか14字が一致すれば実在とみなす。
    for i in range(0, max(1, len(h) - 13), 6):
        frag = h[i:i + 16].strip()
        if len(frag) >= 12:
            ks.append(frag)
    for frag in h.replace("］", "]").split("]"):
        frag = frag.strip()
        if len(frag) >= 12:
            ks.append(frag[:20])
    seen, out = set(), []
    for k in ks:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def scan_window(tok, cid, keys, base, pages, back_min, fwd_min):
    """[base-back_min, base+fwd_min] の窓を**後ろから前へ**走査して一致を探す。

    ★2026-08-05 実測の落とし穴= `after=` で前へ送ってはいけない。
      Discord は `after` でも**新しい順**に返し、しかも繁忙部屋では
      **アンカー直後を丸ごと飛ばして最新側の100件**を返す
      (実測= イージス研究室で after=07-27 12:00 を指定 → 返ってきたのは 07-28 00:35〜07-31 08:03。
       つまり 07-27 12:00〜07-28 00:35 が窓から消える。狙いの返信はまさにそこに居る)。
      → `before` を「記帳時刻＋fwd_min」に固定して**古い方へ**降りる。これは順番が保証される。
    """
    cursor = str(to_sf(base + dt.timedelta(minutes=fwd_min)))
    floor_ms = (base - dt.timedelta(minutes=back_min)).timestamp() * 1000
    for _ in range(pages):
        try:
            msgs = api(f"/channels/{cid}/messages?limit=100&before={cursor}", tok)
        except urllib.error.HTTPError as e:
            return {"_http": e.code}
        if not msgs:
            return None
        msgs = sorted(msgs, key=lambda m: int(m["id"]), reverse=True)
        for m in msgs:
            c = norm(m.get("content") or "")
            if any(k in c for k in keys):
                return m
        oldest = int(msgs[-1]["id"])
        if ((oldest >> 22) + DISCORD_EPOCH) < floor_ms:
            return None          # 窓の下端まで降りた=この部屋には無い
        cursor = msgs[-1]["id"]
        time.sleep(0.3)
    return None


def find_landed(tok, chans, dept, room, head, base, pages, back_min, fwd_min):
    """候補の部屋を順に掃く。見つけた部屋も一緒に返す。"""
    keys = match_keys(head)
    if not keys:
        return None, None
    http = None
    for cdept, cname, cid in candidate_channels(chans, dept, room):
        m = scan_window(tok, cid, keys, base, pages, back_min, fwd_min)
        if isinstance(m, dict) and m.get("_http"):
            http = m
            continue
        if m:
            return m, cname or cdept
    return (http, None) if http else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="判定だけして台帳へ書かない")
    ap.add_argument("--min-age-min", type=int, default=10,
                    help="この分数より新しい記帳は触らない(生の経路と競合しないため)")
    ap.add_argument("--pages", type=int, default=5, help="1部屋あたり最大ページ数(1ページ100件)")
    ap.add_argument("--back-min", type=int, default=3, help="記帳の何分前まで降りるか")
    ap.add_argument("--fwd-min", type=int, default=30, help="記帳の何分後から降り始めるか")
    ap.add_argument("--redo-missing", action="store_true",
                    help="過去に『本物の不着』と札を貼った行を判定し直す(誤りを剥がすため)")
    a = ap.parse_args()

    pend, _resolved = load_rows(redo_missing=a.redo_missing)
    now = dt.datetime.now(JST)
    pend = [r for r in pend
            if (now - dt.datetime.fromisoformat(r["ts"]).replace(tzinfo=JST)).total_seconds()
            >= a.min_age_min * 60]
    print(f"後追い判定の対象: {len(pend)}件(min-age={a.min_age_min}分)")
    if not pend:
        return 0

    tok = token()
    chans = all_channels()
    out, late, missing, skip = [], 0, 0, 0
    for r in pend:
        rid, dept, ts = r.get("request_id"), r.get("dept"), r.get("ts")
        head = head_of(r.get("evidence"))
        room = room_of(r.get("evidence"))
        if not head:
            skip += 1
            print(f"  [判定不能] {ts} {dept} (突合鍵が記帳に無い)")
            continue
        base = dt.datetime.fromisoformat(ts).replace(tzinfo=JST)
        m, found_room = find_landed(tok, chans, dept, room, head, base,
                                    a.pages, a.back_min, a.fwd_min)
        if isinstance(m, dict) and m.get("_http"):
            skip += 1
            print(f"  [読めない] {ts} {dept} HTTP {m['_http']}")
            continue
        if m:
            gap = (jst_of(m["id"]) - base).total_seconds()
            elsewhere = ("" if not room or found_room == room
                         else f" ★記帳の部屋({room})ではなく『{found_room}』に着地")
            ev = (f"後追い確認OK discord_msg={m['id']} 投稿={jst_of(m['id']).strftime('%Y-%m-%d %H:%M:%S')} "
                  f"記帳との差={gap:+.0f}秒(同期確認が早すぎただけ=不着ではない){elsewhere}")
            out.append({"ts": now.strftime("%Y-%m-%dT%H:%M:%S"), "request_id": rid,
                        "dept": dept, "state": "replied_late_confirmed", "evidence": ev})
            late += 1
            print(f"  [空騒ぎ] {ts} {dept} → msg={m['id']} 差={gap:+.0f}秒{elsewhere}")
        else:
            ev = (f"後追いでも見つからない(記帳{ts}の+{a.fwd_min}分から-{a.back_min}分の窓を"
                  f"全{len(chans)}室×最大{a.pages * 100}件走査) ★これは本物の不着=Chamiに届いていない")
            out.append({"ts": now.strftime("%Y-%m-%dT%H:%M:%S"), "request_id": rid,
                        "dept": dept, "state": "replied_missing", "evidence": ev})
            missing += 1
            print(f"  ★[本物の不着] {ts} {dept} req={rid}")

    print(f"\n空騒ぎ {late} / ★本物の不着 {missing} / 判定不能 {skip}")
    if a.dry_run:
        print("(--dry-run なので台帳へは書いていない)")
        return 0
    if out:
        with open(REQUEST_LOG, "a", encoding="utf-8") as f:
            for row in out:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"request_log へ {len(out)}行 追記した(既存行は書き換えていない)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
