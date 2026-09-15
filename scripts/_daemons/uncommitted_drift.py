#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""未コミットのまま**寝ている**コードを、日次1行で名指しする道具(C-079)。

なぜ要るか= 2026-09-16 の裁定 C-079。
  イージス研究室の上申「常駐が読んでいるコードが git に無い」に対してHQが決めた形は
  **触った部門自身が、change_log.jsonl へ1行書くその同じ手番で畳む**(代行は禁止・日次にはしない・
  push はしない・溜まった分は一括では畳まず、次に触った部門が自然消化)。
  執行形は「**commit 欄へ実在する hash を書けないコード変更は、change_log へ書くな**」。
  ここはその執行を**見張るだけ**の目= 畳む手は持たない。

★この道具は git へ書かない。叩くのは `git diff --numstat` / `git log -1` / `git status` の
  **読む3つだけ**。add も commit も push もしない(C-079「読むだけ・コミットしない形で合っている」)。

★件数だけの通知は作らない(C-079)。1行に必ず次の4つを載せる=
  ① 未コミット tracked の **件数 / +行 / -行**
  ② そのうち **常駐が実際に読み込んでいるファイル**の名指し
  ③ 各ファイルの **滞留日数(age)**
  ④ **持ち主** = change_log.jsonl の `触った` / `触った所` を**後ろから**引いて最初に当たった dept

②の出し方= 手で監視リストを書かない。`daemon_code_version.closure()` で各常駐の
  **推移的 import 閉包**を辿り、未コミット集合と突き合わせる(dept_daemon.py のように
  supervise_daemons.ps1 の7本に名前が出ない相手も、閉包に入っていれば必ず拾える)。

③の測り方(ここは正直に境界を出す)=
  git は「未コミットの編集がいつ始まったか」を**持っていない**。判るのは2つだけ=
    ・そのファイルの**最後のコミット時刻** → 未コミット変更はそれより後に起きた
      = 滞留は長くても `now - 最終コミット` (**age_max**)
    ・そのファイルの **mtime** → 最後に書いた瞬間なので、最古の変更はそれより前
      = 滞留は少なくとも `now - mtime` (**age_min**)
  よって真の age は [age_min, age_max] の中にある。**表に出す age は age_max**(＝最悪側)。
  片方だけ出すと嘘になるので、明細には両方書く。

使い方=
  python scripts/_daemons/uncommitted_drift.py            # 1行＋明細を出す
  python scripts/_daemons/uncommitted_drift.py --quiet    # 1行だけ
  python scripts/_daemons/uncommitted_drift.py --json     # 機械向け
  履歴= local/llm/uncommitted_drift.jsonl (追記のみ)
検査= python scripts/_daemons/test_uncommitted_drift.py
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import daemon_code_version as dcv                          # noqa: E402

CHANGE_LOG = os.path.join(ROOT, "local", "llm", "change_log.jsonl")
HISTORY = os.path.join(ROOT, "local", "llm", "uncommitted_drift.jsonl")
# 持ち主を引く時に見る欄(change_log は書式が揺れているので複数見る)。
TOUCH_KEYS = ("触った", "触った所", "touched", "files")
DAY = 86400.0


def _git(args, timeout=60):
    """読むだけの git。失敗しても例外は投げず空文字を返す(見張りが落ちない事を優先)。"""
    try:
        r = subprocess.run(["git", "-C", ROOT] + args,
                           capture_output=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except Exception:                                      # noqa: BLE001
        return ""
    return r.stdout or ""


def uncommitted():
    """HEAD と違う **tracked** ファイル = {relpath(スラッシュ): (追加行, 削除行)}。

    ★untracked は入れない= git が中身を知らない物に「未コミットの滞留」は測れない
      (HQ実測の 997件は untracked 込みの数字で、124件がこちらの数字)。
    ★バイナリは numstat が `-` を返すので 0 行として数える(件数には入る)。
    """
    out = {}
    for line in _git(["diff", "--numstat", "HEAD"]).splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        add, dele, path = parts[0], parts[1], parts[2]
        out[path.replace("\\", "/")] = (int(add) if add.isdigit() else 0,
                                        int(dele) if dele.isdigit() else 0)
    return out


def resident_map():
    """{relpath: [その相手を読み込んでいる常駐名, ...]} を **閉包から実測**して返す。"""
    who = {}
    for name, entry in dcv.SUPERVISED:
        for p in dcv.closure(os.path.join(ROOT, entry)):
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            who.setdefault(rel, [])
            if name not in who[rel]:
                who[rel].append(name)
    return who


def age_bounds(rel, now=None):
    """(age_max日, age_min日) を返す。age_max= 最終コミットから / age_min= 最終書込から。

    ★未コミット変更の開始時刻は git に無い。だから1つの数字に潰さず、両端で言う。
      最終コミットが引けない(新規 add 済み等)相手は age_max=None。
    """
    now = time.time() if now is None else now
    ct = _git(["log", "-1", "--format=%ct", "--", rel]).strip().splitlines()
    age_max = None
    if ct:
        try:
            age_max = max(0.0, (now - float(ct[0])) / DAY)
        except ValueError:
            age_max = None
    try:
        age_min = max(0.0, (now - os.path.getmtime(os.path.join(ROOT, rel))) / DAY)
    except OSError:
        age_min = None
    return age_max, age_min


def _load_change_log():
    """change_log.jsonl を**古い順のまま**読む(引く時に後ろから走る)。壊れ行は飛ばす。"""
    rows = []
    try:
        with open(CHANGE_LOG, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:                          # noqa: BLE001
                    continue
    except OSError:
        return []
    return rows


def owner_of(rel, rows):
    """持ち主= `触った`/`触った所` を**後ろから**引いて最初に当たった dept。

    引き方は2段= ①フルパス(スラッシュ/円マーク両方)で当てる ②当たらなければ basename。
    ②は別ディレクトリの同名ファイルを誤って掴み得るので、どちらで当たったかを返して区別する。
    返り値 = (dept or None, 'path'|'name'|None, その行のts)
    """
    base = rel.rsplit("/", 1)[-1]
    win = rel.replace("/", "\\")
    for row in reversed(rows):
        dept = row.get("dept")
        if not dept:
            continue
        blob = " ".join(str(row.get(k, "")) for k in TOUCH_KEYS)
        if not blob.strip():
            continue
        if rel in blob or win in blob:
            return dept, "path", row.get("ts", "")
        if base in blob:
            return dept, "name", row.get("ts", "")
    return None, None, ""


def scan(now=None):
    """測って構造で返す(印刷はしない)。"""
    now = time.time() if now is None else now
    dirty = uncommitted()
    residents = resident_map()
    rows = _load_change_log()

    pyc = [p for p in dirty if p.endswith(".pyc")]
    total_add = sum(a for a, _ in dirty.values())
    total_del = sum(d for _, d in dirty.values())

    hits = []
    for rel in sorted(set(dirty) & set(residents)):
        add, dele = dirty[rel]
        age_max, age_min = age_bounds(rel, now)
        dept, how, ts = owner_of(rel, rows)
        hits.append({"file": rel, "daemons": residents[rel], "add": add, "del": dele,
                     "age_max_days": None if age_max is None else round(age_max, 2),
                     "age_min_days": None if age_min is None else round(age_min, 2),
                     "owner": dept, "owner_by": how, "owner_ts": ts})
    # 古い順(age_max 降順)= 一番寝ている物を先頭へ。件数ではなく age で並べる(C-079)。
    hits.sort(key=lambda h: (-(h["age_max_days"] or 0.0), h["file"]))

    unknown = [h["file"] for h in hits if not h["owner"]]
    return {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "tracked_files": len(dirty), "added": total_add, "deleted": total_del,
            "pyc_files": len(pyc),
            "resident_files": len(hits), "resident": hits,
            "owner_unknown": unknown,
            "closed": len(hits) == 0}


def one_line(r):
    """日次に出す1行。件数・名指し・age・持ち主を**全部**載せる(C-079)。"""
    head = ("[未コミット滞留] tracked %d本 +%d/-%d"
            % (r["tracked_files"], r["added"], r["deleted"]))
    if not r["resident"]:
        return head + " / 常駐が読んでいるファイルの未コミットは **0件** = C-079の閉じ条件を満たす日"
    parts = []
    for h in r["resident"]:
        age = "?" if h["age_max_days"] is None else ("%.1fd" % h["age_max_days"])
        own = h["owner"] or "持ち主不明"
        if h["owner_by"] == "name":
            own += "?"
        parts.append("%s age<=%s 持ち主=%s(%s)"
                     % (h["file"].rsplit("/", 1)[-1], age, own, "/".join(h["daemons"])))
    tail = ""
    if r["owner_unknown"]:
        tail = " / 持ち主不明 %d本→HQへ" % len(r["owner_unknown"])
    return "%s / 常駐が読んでいるのは %d本: %s%s" % (head, r["resident_files"],
                                                    " | ".join(parts), tail)


def detail(r):
    lines = []
    for h in r["resident"]:
        amin = "?" if h["age_min_days"] is None else ("%.2f" % h["age_min_days"])
        amax = "?" if h["age_max_days"] is None else ("%.2f" % h["age_max_days"])
        lines.append("  %-44s +%-5d -%-5d age %s〜%s日 持ち主=%s(%s %s) 常駐=%s"
                     % (h["file"], h["add"], h["del"], amin, amax,
                        h["owner"] or "不明", h["owner_by"] or "-", h["owner_ts"],
                        ",".join(h["daemons"])))
    lines.append("  ※ age は [最終書込から, 最終コミットから]。未コミット変更の開始時刻は"
                 " git に無いので、表の age は最悪側(最終コミットから)を出している。")
    if r["pyc_files"]:
        lines.append("  ※ tracked の .pyc が %d本ある(.gitignore 済みなのに追跡中)。C-079の対象外。"
                     % r["pyc_files"])
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="未コミット滞留の日次1行(読むだけ / C-079)")
    ap.add_argument("--quiet", action="store_true", help="1行だけ出す")
    ap.add_argument("--json", action="store_true", help="測った物をJSONで出す")
    ap.add_argument("--no-history", action="store_true", help="履歴へ追記しない")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                      # noqa: BLE001
        pass

    r = scan()
    # 日次の1行を**そのまま**履歴へ残す(pythonw 起動では stdout が誰にも見えないので、
    # 「その日に何と出たか」は JSONL の line 欄が正本になる)。
    r["line"] = one_line(r)
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(one_line(r))
        if not a.quiet and r["resident"]:
            print(detail(r))
    if not a.no_history:
        try:
            os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
            with open(HISTORY, "a", encoding="utf-8") as f:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
