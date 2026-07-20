#!/usr/bin/env python
"""react_mark — 対話セッションの部屋に「既読/着手」を**機構で**押す。

なぜ要るか(2026-07-21 Chami指摘):
  「送信(📮)は着くけど、ちょっと前から既読と着手が着かなくなった。特に研究室HQは
   デーモンがいない。デーモンがいない部屋は既読と着手両方つくのが普通だと思う」

  実態を追うとこうなっていた:
    📮送信 = inbox_poller が**機械的に**押す        → だから今も着く
    ✅既読 = dept_daemon.handle() が押す              → **デーモンのある部屋だけ**
    👀着手 = 誰も押していない(BOOT.md に手順が書いてあるだけ)
  つまり総括本部4室(hq/aegis-gl/research-room/keiei-kikaku)は**デーモンを撤去した時に
  既読を押す主体まで一緒に失っていた**。着手に至っては最初から「セッションが手で叩く」
  運用で、実際には誰も叩いていない。

  これは ORG-08(voice方式が誰にも使われていなかった)と**完全に同型**の失敗:
  機構を置かずに手順書へ書いただけのものは、運用に乗らない。
  自分たちの原則「心がけに任せると忘れる。hookが強制する」をここにも適用する。

使い方:
  python scripts/discord/react_mark.py --dept hq [--kinds 既読,着手] [--within 7200]
  → その部屋宛てのChami発言のうち、まだ押していないものへ反応を押す。
     同じ (msg_id, 種別) は**二度押さない**(状態ファイルで記録)。

★べき等・fail-open: 何が失敗してもセッションは止めない(exit 0)。
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
STATE = os.path.join(LOCAL, "react_mark_state.json")
REACT = os.path.join(HERE, "react.py")
KEEP = 400                      # 状態に残すキー数(古い順に捨てる)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"done": []}


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        st["done"] = st.get("done", [])[-KEEP:]
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception:
        pass


def recent_messages(dept, within_sec):
    """その部屋宛ての「Chamiの発言」を新しい順に返す。[(msg_id, channel), ...]

    ★queueを見るのは、msg_id と channel を持っている唯一の場所だから。
      transcript側には msg_id が無いので、Stop hookからは引けない。
    """
    if not os.path.exists(QUEUE_DB):
        return []
    out = []
    try:
        import sqlite3
        con = sqlite3.connect(QUEUE_DB)
        con.row_factory = None
        rows = con.execute(
            "select body from queue where dept=? order by id desc limit 40", (dept,)).fetchall()
        con.close()
    except Exception:
        return []
    now = time.time()
    for (raw,) in rows:
        try:
            b = json.loads(raw)
        except Exception:
            continue
        if not str(b.get("author", "")).startswith("chami"):
            continue            # 自動投稿やbotの便には押さない
        mid, ch = str(b.get("msg_id") or ""), b.get("channel") or ""
        if not mid or not ch:
            continue
        ts = b.get("ts") or ""
        if within_sec and ts:
            try:                # ★DiscordのtsはUTC。差分を取るだけなので変換は不要
                from datetime import datetime, timezone
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if now - t.timestamp() > within_sec:
                    continue
            except Exception:
                pass
        out.append((mid, ch))
    return out


def push(ch, mid, kind):
    try:
        p = subprocess.run([sys.executable, REACT, "--channel", ch, "--msg", mid,
                            "--emoji", kind], capture_output=True, timeout=45)
        return p.returncode == 0
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", required=True)
    ap.add_argument("--kinds", default="既読,着手")
    ap.add_argument("--within", type=int, default=7200, help="秒。これより古い便は対象外")
    a = ap.parse_args()

    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()]
    st = load_state()
    done = set(st.get("done", []))
    added, pushed = [], 0
    for mid, ch in recent_messages(a.dept, a.within):
        for kind in kinds:
            key = f"{mid}:{kind}"
            if key in done:
                continue
            if push(ch, mid, kind):
                done.add(key)
                added.append(key)
                pushed += 1
            # 失敗した時はdoneへ入れない=次の発火で再試行される
    if added:
        st["done"] = st.get("done", []) + added
        save_state(st)
    print(f"react_mark dept={a.dept} pushed={pushed}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"react_mark: skip ({e})")
    sys.exit(0)                 # 何があってもセッションを止めない
