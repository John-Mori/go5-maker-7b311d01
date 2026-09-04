#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""依頼が完遂したら、**発注元の部屋へ1行だけ**自動で返す(2026-09-04・aegis-gl)。

なぜ要るか(実物・HQアロンソ発注 msg=1545275628134072442):
  2026-09-04 03:15、ad研究室が2部門へ発注した。
    分析部門(骨格)= msg 1545135253847277648 / コピー部(文言)= msg 1545135261816717432
  **両部門とも同日03:2xに完遂して `local/consult_intel/` へ成果を置いていた。**
  それでも発注元のad研究室は **12:00まで知らなかった**。8時間半、実在する完遂を未達として
  持ち回った。見えなかった理由は3つ重なっている=
    ① 成果は便ではなく**置き場**に落ちる(誰も鳴らさない)
    ② `local/` は gitignore なので `git log` にも出ない
    ③ `request_log.jsonl` には `completed`/`replied` と着地msg_idが**両方入っていた**
  → **機械は完遂を知っていて、発注元だけが知らなかった。**

  HQは共通規律§3.8へ「請けた側は問われる前に発注元へ1行返せ」を入れて止血した(commit
  2a4e69d / repo=00_AI-HQ)。だがそれは人手を規律で縛っただけで、**請けた部門が忘れれば
  同じ穴がまた開く**。恒久は機械側にしか置けない=これがその機械だ。

★設計で一番効いた実測= **発注元が機械のどこにも記録されていなかった。**
    - `request_log.jsonl` の項目は {request_id, dept, state, ts, evidence} だけ
    - `dispatch.py` は `--from-dept` を受け取るのに**便レコードへ載せていなかった**
      (呼称ゲートに渡して捨てていた)
    - `local/discord_processed.jsonl` の dispatch 便**1721件すべてに from_dept が無い**
    - 発注元は本文に**人間の言葉でだけ**書かれていた(「■戻し先 結果は consult-intel へ」)
  → 先に `dispatch.py` の便レコードへ `from_dept` / `from_dept_explicit` を足した
    (2026-09-04・新規キーの追加のみ=既存を壊さない)。**この常駐は、それ以降の便にしか
    効かない。**過去の便に発注元は書かれていないので、遡って救うことはできない。

やらないこと(意図して):
  - **本体を運ばない**(C-023/C-050の線)。出すのは「完遂した」「何の依頼だったか」
    「請けた部屋のどのメッセージに着地したか」だけ。成果そのものは置き場にある。
  - **置き場のパスは名乗らない**= 機械が知らないからだ。発注元(HQ)は「置き場のパスと要旨」を
    求めたが、置き場を知っているのは請けた部門だけで、機械が持っているのは着地msg_idまで。
    知らないものを書けば、それは**測っていない数字を語る**のと同じになる。着地msg_idを指せば
    発注元はそこから置き場へ辿れる。
  - **推定で宛先を決めない。**`author`(人格名)から部門を逆引きする案は捨てた=同じ人格が
    複数の部屋に居るので静かに誤配する。発注元が決まらない便は**鳴らさず**、標準出力へ残す。

冪等(要件2「同じ依頼で二度鳴らすな」):
  鳴らしたら request_log へ `completion_notified` を**追記**する。既存行は1行も書き換えない。
  次回はその request_id を対象から外す。★鳴らせなかった件は追記しない=状況が変われば拾える。

二重の抑制(要件3):
  請けた部門が自分で発注元の部屋へ1行返していたら鳴らさない。判定は
  「完遂時刻より後に、`dept=発注元` かつ `from_dept=請けた側` の dispatch 便がある」。
  ★dispatch を通さず部屋で直に返した場合は見えない=そのときは二重に鳴る(害は小さい方を採る)。

fail-open(要件4):
  1件の失敗は他を止めない。全体の例外も握って exit 0 で終わる。**鳴らないことより、
  他を巻き込んで止まることの方が高くつく。**

使い方:
  python scripts/_daemons/completion_notify.py --dry-run   # 判定だけ・投函も追記もしない
  python scripts/_daemons/completion_notify.py             # 本番
  python scripts/_daemons/completion_notify.py --min-age-min 15 --since-hours 24
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
REQUEST_LOG = os.path.join(LOCAL, "llm", "request_log.jsonl")
PROCESSED = os.path.join(LOCAL, "discord_processed.jsonl")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
JST = dt.timezone(dt.timedelta(hours=9))

DONE_STATES = ("completed", "replied")
NOTIFIED_STATE = "completion_notified"


def parse_ts(s):
    """request_log の ts は tz なしの JST 表記。失敗したら None(その行は触らない)。"""
    try:
        return dt.datetime.fromisoformat(str(s)).replace(tzinfo=JST)
    except Exception:
        return None


def load_requests():
    """request_log を1回だけ舐めて (完遂した依頼, 通知済みID) を返す。

    完遂= {request_id: {"dept":…, "ts":…(最初のcompleted/replied), "evidence":…}}
    ★`replied` の evidence には請けた側の着地 `discord_msg=` が入っている。あとで
      「どこに落ちたか」を1行に入れるために、replied を見たら evidence を優先で採る。
    """
    done, notified = {}, set()
    if not os.path.exists(REQUEST_LOG):
        return done, notified
    with open(REQUEST_LOG, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if '"state"' not in ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue          # 壊れた行は黙って飛ばす(台帳全体を止めない)
            rid, st = r.get("request_id"), r.get("state")
            if not rid:
                continue
            if st == NOTIFIED_STATE:
                notified.add(rid)
                continue
            if st not in DONE_STATES:
                continue
            cur = done.get(rid)
            if cur is None:
                done[rid] = {"dept": r.get("dept") or "", "ts": r.get("ts") or "",
                             "evidence": r.get("evidence") or "", "state": st}
            elif st == "replied" and cur.get("state") != "replied":
                # 着地msg_idを持っている方(replied)を採る。時刻は最初の完遂のまま残す。
                cur["evidence"] = r.get("evidence") or cur["evidence"]
                cur["state"] = "replied"
    return done, notified


def load_letters(want_ids):
    """discord_processed から、欲しい msg_id の便レコードと「返した形跡」を集める。

    返り値 = (letters, replies)
      letters[msg_id] = 便レコード(発注そのもの。ここから from_dept を採る)
      replies = {(宛先dept, 送り主dept): [ts, …]}   ← 要件3の抑制に使う
    ★1回の走査で両方を作る(8MBを2度読まない)。
    """
    letters, replies = {}, {}
    if not os.path.exists(PROCESSED):
        return letters, replies
    with open(PROCESSED, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if '"via"' not in ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            mid = str(r.get("msg_id") or "")
            if mid and mid in want_ids:
                letters[mid] = r
            fd = (r.get("from_dept") or "").strip()
            if fd and r.get("dept"):
                replies.setdefault((r["dept"], fd), []).append(r.get("ts") or "")
    return letters, replies


def landed_msg(evidence):
    """evidence の `discord_msg=…` を取り出す(請けた側の返信の着地先)。"""
    ev = evidence or ""
    i = ev.find("discord_msg=")
    if i < 0:
        return ""
    return ev[i + 12:].split()[0].strip() if ev[i + 12:].split() else ""


def already_replied(replies, to_dept, from_dept, after):
    """請けた側(from_dept)が発注元(to_dept)へ、完遂の**後**に自分で便を出しているか。"""
    for ts in replies.get((to_dept, from_dept), []):
        t = parse_ts(ts)
        if t and t >= after:
            return True
    return False


def build_body(rid, dept, letter, done, landed):
    """発注元の部屋へ出す本文。★短く。本体は運ばない(C-023/C-050)。"""
    work = (letter.get("work") or "").strip()
    lines = [f"[完遂通知] {dept} が請けた依頼が**完遂**した(自動・request_log発)。"]
    if work:
        lines.append(f"■依頼= {work}")
    lines.append(f"■記帳= request_id `{rid}` / state `{done['state']}` / {done['ts']}")
    if landed:
        lines.append(f"■請けた側の返信= msg `{landed}`(**成果の在りかはそこに書いてある**)")
    else:
        lines.append("■請けた側の返信= 記帳に着地msg_idが無い(部屋を直接見てくれ)")
    lines.append("★本体はここへ運んでいない(C-023/C-050)。**この便は完遂を知らせるだけだ。**")
    lines.append("※これは往路の**復路**なので3階梯を通していない(自動通知・completion_notify)。")
    return "\n".join(lines)


def send(to_dept, from_dept, body, dry_run):
    """dispatch.py で1行返す。戻り値=(ok, 出力). ★--also-post は付けない(裏=キューだけ)。"""
    fd, path = tempfile.mkstemp(suffix=".md", prefix="completion_notify_", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        cmd = [sys.executable, DISPATCH, "--dept", to_dept, "--from-dept", from_dept,
               "--from", "完遂通知(自動)", "--audience", "ai", "--direct",
               "--body-file", path]
        if dry_run:
            cmd.append("--dry-run")
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode == 0, out.strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="判定だけ・投函も追記もしない")
    ap.add_argument("--min-age-min", type=int, default=15,
                   help="完遂からこの分数は待つ(請けた側が自分で返す猶予・既定15分)")
    ap.add_argument("--since-hours", type=int, default=24,
                   help="この時間より古い完遂は触らない(既定24時間)")
    ap.add_argument("--limit", type=int, default=5,
                   help="1回に鳴らす上限(暴走の頭を押さえる・既定5)")
    ap.add_argument("--verbose", action="store_true",
                   help="鳴らせなかった件も全部並べる(既定は先頭数件だけ=常駐ログを埋めない)")
    a = ap.parse_args()
    quiet_after = 3 if not a.verbose else 10 ** 9

    now = dt.datetime.now(JST)
    done, notified = load_requests()

    # ★窓で絞る。過去の完遂を全部拾うと、入れた瞬間に何百通も鳴る。
    targets = {}
    for rid, d in done.items():
        if rid in notified:
            continue
        t = parse_ts(d["ts"])
        if not t:
            continue
        age = (now - t).total_seconds()
        if age < a.min_age_min * 60 or age > a.since_hours * 3600:
            continue
        d["done_at"] = t
        targets[rid] = d

    print(f"完遂で未通知の依頼: {len(targets)}件"
          f"(窓={a.since_hours}時間 / 猶予={a.min_age_min}分 / 通知済み={len(notified)}件)")
    if not targets:
        return 0

    letters, replies = load_letters(set(targets))
    sent, skipped, unknown, failed, rows = 0, 0, 0, 0, []

    for rid, d in sorted(targets.items(), key=lambda kv: kv[1]["done_at"]):
        if sent >= a.limit:
            print(f"  (上限{a.limit}件に達した。残りは次の回)")
            break
        try:
            letter = letters.get(rid)
            if letter is None:
                unknown += 1
                if unknown <= quiet_after:
                    print(f"  [便が無い] req={rid} dept={d['dept']} "
                          "(discord_processed に見当たらない=Chami発など dispatch を通らない依頼)")
                continue
            to_dept = (letter.get("from_dept") or "").strip()
            if not to_dept or not letter.get("from_dept_explicit"):
                unknown += 1
                if unknown <= quiet_after:
                    print(f"  [発注元が無い] req={rid} dept={d['dept']} "
                          "(--from-dept が明示されていない便=宛先を推定しない)")
                continue
            if to_dept == d["dept"]:
                skipped += 1
                print(f"  [自室完結] req={rid} dept={d['dept']}")
                continue
            if already_replied(replies, to_dept, d["dept"], d["done_at"]):
                skipped += 1
                print(f"  [請けた側が返済み] req={rid} {d['dept']} → {to_dept}")
                continue

            landed = landed_msg(d["evidence"])
            body = build_body(rid, d["dept"], letter, d, landed)
            ok, out = send(to_dept, d["dept"], body, a.dry_run)
            if ok:
                sent += 1
                print(f"  ★[通知] req={rid} {d['dept']} → {to_dept}"
                      f"{' (dry-run)' if a.dry_run else ''}")
                rows.append({"ts": now.strftime("%Y-%m-%dT%H:%M:%S"), "request_id": rid,
                             "dept": d["dept"], "state": NOTIFIED_STATE,
                             "evidence": f"完遂を発注元へ自動通知 to_dept={to_dept} "
                                         f"landed={landed or '(無し)'} via=completion_notify"})
            else:
                failed += 1
                print(f"  [投函に失敗] req={rid} → {to_dept}: {out[:200]}")
        except Exception as e:
            # ★1件の事故で他を巻き込まない(fail-open)。
            failed += 1
            print(f"  [例外] req={rid}: {type(e).__name__}: {e}")

    if unknown > quiet_after:
        print(f"  (…ほか {unknown - quiet_after}件も発注元が取れない。全部見るなら --verbose)")
    print(f"\n通知 {sent} / 抑制 {skipped} / 発注元不明 {unknown} / 失敗 {failed}")
    if a.dry_run:
        print("(--dry-run なので投函も追記もしていない)")
        return 0
    if rows:
        try:
            with open(REQUEST_LOG, "a", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"request_log へ {len(rows)}行 追記した(既存行は書き換えていない)")
        except Exception as e:
            # ★ここで落ちると同じ依頼で二度鳴る。鳴ってしまった事実は消せないので声を上げる。
            print(f"★追記に失敗した= 次回このIDでもう一度鳴る恐れがある: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:      # ★常駐が他を巻き込んで止まらないように、最後も握る。
        print(f"★completion_notify が落ちた(他には波及しない): {type(e).__name__}: {e}")
        sys.exit(0)
