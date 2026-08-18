#!/usr/bin/env python3
"""audit_marks — Chamiの便に「生存の合図(送信📮/既読✅/着手👀)」が実際に付いたかを**Discord側から**測る。

なぜ要るか(2026-08-18・イージス研究室 第19世代):
  Chamiの苦情 REQ-aegis-gl-13fcea00f4「1528653749747191882 1番困る部類の出来事。反応がない。」
  = 2026-08-06 08:03:07 にプラットフォームSEの部屋へ投稿し、**66秒後**に別の部屋へこう書いた。
  実測するとその便は 08:07:26 leased / 08:12:37 replied= **便は落ちていない。9分半で返っている**。
  つまり不満は「返事が無い」ではなく **その9分間、画面に何の印も出ていなかった** ことだった。

  ところが「印が付いたか」を測る手段が**どこにも無かった**:
    - `progress_mark.py`(hook)はログを一切残さない
    - `react_mark.py` の状態ファイル `local/react_mark_state.json` は**成功した押下しか**書かない
      (失敗はdoneへ入れない設計= 静かに落ちても記録が増えないだけで区別が付かない)
    - `dept_daemon` は `react.py` を直接呼ぶので、その状態ファイルにも載らない
  = 台帳を見る検査は「押せていない」を検出できない。**Chamiに見える面を直接見る必要がある。**

  → この道具は Discord API から**メッセージに実際に付いている reaction** を読む。
    台帳を経由しないので、押す側の機構が丸ごと死んでいても正しく「付いていない」と言える。

使い方:
  python scripts/discord/audit_marks.py                      # 全部屋・直近48時間
  python scripts/discord/audit_marks.py --dept platform-se --hours 24
  python scripts/discord/audit_marks.py --dept all --hours 72 --record
  出力は UTF-8。端末が cp932 の時は `--out <path>` でファイルへ書いてから読む。

オプション:
  --dept    部門スラッグ(複数可・既定 all)。local/discord_channels.json の dept と一致させる
  --hours   さかのぼる時間(既定48)
  --limit   1部屋あたりの取得メッセージ数(既定100・Discord APIの上限)
  --record  結果の1行要約を local/llm/mark_audit.jsonl へ追記(履歴として残す)
  --out     出力先ファイル(UTF-8)。既定は標準出力

★読むだけ。Discordへは一切書き込まない(押し直しはしない)。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
API = "https://discord.com/api/v10"
JST = timezone(timedelta(hours=9))

# react.py と**同じ**呼び名→絵文字の対応表を持つ(あちらが押し、こちらが読む)。
# サーバー絵文字(chakusyu等)とUnicode代用(👀等)の**両方**を1つの印として数える。
MARKS = {
    "送信": ("sendms", "送信", "📮"),
    "既読": ("kidoku", "既読", "✅"),
    "着手": ("chakusyu", "着手", "👀"),
    "即答": ("sokutou", "即答", "💬"),
}
CHAMI_ID_FILE = os.path.join(LOCAL, "chami_discord_id.txt")


def read_token():
    with open(os.path.join(LOCAL, "discord_bot_token.txt"), encoding="utf-8") as f:
        return f.read().strip()


def chami_id():
    try:
        with open(CHAMI_ID_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def channels():
    with open(os.path.join(LOCAL, "discord_channels.json"), encoding="utf-8") as f:
        return json.load(f)


def api_get(path, token):
    req = urllib.request.Request(
        API + path,
        headers={"Authorization": "Bot " + token, "User-Agent": "go5-org-audit (personal, v1)"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 1))
                except Exception:
                    wait = 1.0
                time.sleep(min(wait, 10) + 0.3)
                continue
            return {"__error__": f"HTTP {e.code}"}
        except Exception as e:
            return {"__error__": type(e).__name__}
    return {"__error__": "retry"}


def is_chami(m, cid_self):
    """Chami本人の便か。★webhookのミラー(Chami(from Claude) 等)も本人の便として数える
    (Chamiの画面ではどちらも自分の発言に見えるため。inbox_poller と同じ見立て)。"""
    a = m.get("author") or {}
    if cid_self and str(a.get("id", "")) == cid_self:
        return True
    if m.get("webhook_id") and str(a.get("username", "")).startswith("Chami("):
        return True
    return False


def marks_on(m):
    """そのメッセージに付いている印の集合。名前でもUnicodeでも拾う。"""
    got = set()
    for r in (m.get("reactions") or []):
        name = str(((r.get("emoji") or {}).get("name")) or "")
        for label, aliases in MARKS.items():
            if name in aliases:
                got.add(label)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", nargs="*", default=["all"])
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    buf = []
    def out(s=""):
        buf.append(s)

    token, me = read_token(), chami_id()
    want = set(a.dept)
    since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    rows, totals = [], {"msgs": 0, "送信": 0, "既読": 0, "着手": 0, "無印": 0}

    for ch in channels():
        dept = ch.get("dept") or "?"
        if "all" not in want and dept not in want:
            continue
        cid = str(ch.get("id"))
        msgs = api_get(f"/channels/{cid}/messages?limit={min(a.limit,100)}", token)
        if isinstance(msgs, dict):
            out(f"[{dept}] 取得できず: {msgs.get('__error__')}")
            continue
        mine = []
        for m in msgs:
            if not is_chami(m, me):
                continue
            try:
                t = datetime.fromisoformat(str(m.get("timestamp", "")).replace("Z", "+00:00"))
            except Exception:
                continue
            if t < since:
                continue
            mine.append((t, m))
        if not mine:
            continue
        mine.sort(key=lambda x: x[0])
        got_counts = {"送信": 0, "既読": 0, "着手": 0}
        bare = []
        for t, m in mine:
            g = marks_on(m)
            for k in got_counts:
                if k in g:
                    got_counts[k] += 1
            if not ({"既読", "着手", "即答"} & g):
                bare.append((t, m))
        totals["msgs"] += len(mine)
        for k in got_counts:
            totals[k] += got_counts[k]
        totals["無印"] += len(bare)
        rows.append((dept, len(mine), got_counts, bare, ch.get("name", "")))

    out(f"== 進捗印の実測(Discord側の reaction を直読み) / 直近{a.hours:g}時間 / "
        f"{datetime.now(JST):%Y-%m-%d %H:%M} JST ==")
    out(f"{'部門':<18}{'Chami便':>7}{'送信':>6}{'既読':>6}{'着手':>6}{'生存印なし':>10}")
    for dept, n, g, bare, _name in sorted(rows, key=lambda r: -len(r[3])):
        out(f"{dept:<18}{n:>7}{g['送信']:>6}{g['既読']:>6}{g['着手']:>6}{len(bare):>10}")
    out(f"{'合計':<18}{totals['msgs']:>7}{totals['送信']:>6}{totals['既読']:>6}"
        f"{totals['着手']:>6}{totals['無印']:>10}")

    out("")
    out("-- 生存の合図(既読/着手/即答)が1つも付いていない便 --")
    any_bare = False
    for dept, _n, _g, bare, _name in rows:
        for t, m in bare:
            any_bare = True
            body = " ".join(str(m.get("content", "")).split())[:44]
            out(f"  {t.astimezone(JST):%m/%d %H:%M} [{dept}] {m['id']} {body}")
    if not any_bare:
        out("  なし(この窓のChami便には全て生存の合図が付いている)")

    text = "\n".join(buf)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"書き出した: {a.out}")
    else:
        print(text)

    if a.record:
        # ★履歴を残す= 「今日は付いていた/付いていなかった」を後から測り直せるようにする。
        #   追記のみ。既存行は書き換えない。
        rec = {"ts": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S"), "hours": a.hours,
               "totals": totals,
               "bare": [{"dept": d, "msg_id": m["id"],
                         "ts": t.astimezone(JST).strftime("%Y-%m-%dT%H:%M:%S")}
                        for d, _n, _g, bare, _nm in rows for t, m in bare]}
        p = os.path.join(LOCAL, "llm", "mark_audit.jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
