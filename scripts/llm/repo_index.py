# -*- coding: utf-8 -*-
"""部屋別の「よく読む実物」の索引を作る(丸ごと読みを範囲読みへ落とすため)。

★★2026-09-05 実測の判定= **この索引は運用に載せない。実物への直接 Grep に負けた。**
  同じ目的(completion_notify.py 580行の already_replied の判定を読む)を3経路で撃って字数を測った:
    (a) 丸ごと読み                     25,123字
    (b) 索引を Grep → 範囲 Read          5,051字(索引の当該節 2,430 + 範囲読み 2,621)
    (c) 実物へ直接 Grep → 範囲 Read      3,146字(Grep返り 525 + 範囲読み 2,621)
  → 効いていたのは索引ではなく**「丸ごと読むのをやめる」**の方だった((a)比で 80〜88%減)。
    索引は (c) より 1,905字**高い**。しかも行番号は実物が動けば腐る。**入れる理由が無い。**
  ★このファイルは道具として残す(判定の再現用・測定の材料)。**索引を封筒や運用へ入れるな。**
  実測の台帳= local/_work/_index_bench.py / _reducible.py / _reread_overlap.py / _reread_compact.py

以下は、その判定へ至るまでの経緯(残す)。

なぜ要ると考えたか(C-059= 誰の何がどれだけ減るか):
  2026-09-05 実測。当日の入力トークン 785,053,218 のうち探索と全読みが 39.8%。
  その中で Read の 40.8% が「同じセッションで一度読んだファイルの読み直し」だった。
  イージス研究室の直近7日では、上位6ファイルだけで Read 全体 3,306,092字の 54% を焼いている
  (dept_daemon.py 161回 / handoff_aegis-gl.md 59回 / naming_gate.py 58回 …)。
  毎回「どこに何があるか」を探すために丸ごと読んでいる。索引があれば範囲読みで足りる。

なぜ手書きの索引にしないか:
  手で書いた地図は実物が動いた瞬間に嘘になる(共通規律§3= 人手の入口を要件にした機構は実測0件になる)。
  ★対象ファイルは**ハーネスの生ログから実測で選ぶ**。中身は**実物から機械で抜く**。走らせ直せば必ず最新。

使い方:
  python scripts/llm/repo_index.py --dept aegis-gl            # 索引を作る
  python scripts/llm/repo_index.py --dept aegis-gl --dry-run  # 出さずに中身と字数だけ見る

★C-035= これは今イージス研究室でだけ試す。全部屋へ一斉に配るな。前後の実測が出るまでは1部屋。
"""
from __future__ import annotations

import argparse
import ast
import collections
import datetime
import glob
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HQ = os.path.join(os.path.dirname(REPO), "00_AI-HQ")
LOGS = os.path.join(os.path.expanduser("~"), ".claude", "projects",
                    "D--SougouStartFolder-5SecMovieMaker")
IMGEXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf")
SKIP_DIRS = ("__pycache__", ".git", "node_modules")


# ---------------------------------------------------------------- 実測で対象を選ぶ
def hot_files(dept: str, days: int) -> list[tuple[str, int, int]]:
    """その部屋が実際によく読んでいるファイルを (絶対パス, 回数, 字数) で返す。"""
    cut = datetime.datetime.now() - datetime.timedelta(days=days)
    n = collections.Counter()
    chars = collections.Counter()
    for path in glob.glob(os.path.join(LOGS, "*.jsonl")):
        try:
            if datetime.datetime.fromtimestamp(os.path.getmtime(path)) < cut:
                continue
        except OSError:
            continue
        tool: dict[str, tuple[str, dict]] = {}
        room = None
        first = True
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for ln in fh:
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                if o.get("type") == "assistant":
                    for b in ((o.get("message") or {}).get("content") or []):
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            tool[b.get("id")] = (b.get("name"), b.get("input") or {})
                elif o.get("type") == "user":
                    cont = (o.get("message") or {}).get("content")
                    if first:
                        s = cont if isinstance(cont, str) else json.dumps(cont, ensure_ascii=False)
                        if "Discordの部屋 " in s:
                            room = s.split("Discordの部屋 ", 1)[1].split("(", 1)[0].strip()
                        first = False
                    if room != dept or not isinstance(cont, list):
                        continue
                    for b in cont:
                        if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                            continue
                        name, inp = tool.get(b.get("tool_use_id"), ("?", {}))
                        if name != "Read":
                            continue
                        fp = str(inp.get("file_path") or "")
                        if not fp or fp.lower().endswith(IMGEXT):
                            continue
                        c = b.get("content")
                        body = c if isinstance(c, str) else "\n".join(
                            x.get("text", "") for x in c
                            if isinstance(x, dict) and x.get("type") == "text")
                        key = os.path.normcase(os.path.abspath(fp))
                        n[key] += 1
                        chars[key] += len(body)
    out = []
    for key, cnt in n.most_common():
        if any(d in key for d in SKIP_DIRS) or key.endswith(".bak"):
            continue
        if os.path.normcase(LOGS) in key:      # 生ログ自体は索引にしない
            continue
        if os.path.isfile(key):
            out.append((key, cnt, chars[key]))
    return out


# ---------------------------------------------------------------- 中身を実物から抜く
def outline_py(path: str) -> list[tuple[int, str]]:
    src = open(path, encoding="utf-8", errors="replace").read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(getattr(e, "lineno", 1) or 1, f"(構文解析できず: {e.msg})")]
    rows: list[tuple[int, str]] = []

    def doc1(node) -> str:
        d = ast.get_docstring(node) or ""
        return d.strip().splitlines()[0][:60] if d.strip() else ""

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rows.append((node.lineno, f"def {node.name}()  {doc1(node)}".rstrip()))
        elif isinstance(node, ast.ClassDef):
            rows.append((node.lineno, f"class {node.name}  {doc1(node)}".rstrip()))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    rows.append((sub.lineno, f"  .{sub.name}()  {doc1(sub)}".rstrip()))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in tgts:
                if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) > 2:
                    rows.append((node.lineno, f"{t.id} =  (定数)"))
    return rows


def outline_md(path: str) -> list[tuple[int, str]]:
    rows = []
    for i, ln in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        m = re.match(r"^(#{1,4})\s+(.+?)\s*$", ln)
        if m:
            rows.append((i, "  " * (len(m.group(1)) - 1) + m.group(2)[:70]))
    return rows


def outline_text(path: str) -> list[tuple[int, str]]:
    """.ps1 / .gs / .js など= function 定義らしき行を拾う。"""
    pat = re.compile(r"^\s*(?:function\s+([A-Za-z_][\w-]*)|([A-Za-z_]\w*)\s*[:=]\s*function"
                     r"|def\s+([A-Za-z_]\w*))")
    rows = []
    for i, ln in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        m = pat.match(ln)
        if m:
            rows.append((i, "function " + next(g for g in m.groups() if g)))
    return rows


def outline(path: str) -> list[tuple[int, str]]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".py":
        return outline_py(path)
    if ext in (".md", ".markdown"):
        return outline_md(path)
    if ext in (".json", ".jsonl", ".yaml", ".yml", ".txt", ".csv", ".db", ".toml"):
        return []                                  # 構造を機械で抜けない物は行数だけ載せる
    return outline_text(path)


def rel(path: str) -> str:
    for base, tag in ((REPO, ""), (os.path.dirname(REPO), "")):
        try:
            r = os.path.relpath(path, base)
        except ValueError:
            continue
        if not r.startswith(".."):
            return r.replace("\\", "/")
    return path.replace("\\", "/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", required=True, help="部屋のslug(例: aegis-gl)")
    ap.add_argument("--days", type=int, default=7, help="何日分の生ログから対象を選ぶか")
    ap.add_argument("--top", type=int, default=20, help="上位いくつのファイルを索引に載せるか")
    ap.add_argument("--min-reads", type=int, default=3, help="この回数以上読まれた物だけ")
    ap.add_argument("--max-rows", type=int, default=0,
                    help="1ファイルあたりの見出し行の上限(0=間引かない。索引はGrepで引く物なので既定は0)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    hot = [h for h in hot_files(a.dept, a.days) if h[1] >= a.min_reads][:a.top]
    if not hot:
        print(f"[index] {a.dept}: 直近{a.days}日に {a.min_reads}回以上読まれたファイルが無い。索引は作らない。")
        return 0

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total_reads = sum(h[1] for h in hot)
    total_chars = sum(h[2] for h in hot)
    L: list[str] = []
    L.append(f"# {a.dept} がよく読む実物の索引(機械生成・{now})")
    L.append("")
    L.append("★**この索引は丸ごと読む物ではない。`Grep` で引く物だ。**")
    L.append(f"   例= `Grep pattern:\"def audit_english\" path:\"local/llm/index_{a.dept}.md\"`")
    L.append("   → `L5718 def audit_english() …` が返る → 実物を `Read offset:5700 limit:80` で読む。")
    L.append("   **これで「どこに在るか探すための丸ごと読み」が消える。**")
    L.append(f"★対象は直近{a.days}日の生ログで {a.min_reads}回以上読まれた上位{len(hot)}件"
             f"(実測= 合計 {total_reads}回 / {total_chars:,}字)。")
    L.append(f"★作り直し= `python scripts/llm/repo_index.py --dept {a.dept}`。"
             "**行番号は実物が動けばズレる。索引の行に実物が無ければ、それは索引が古い。作り直せ。**")
    L.append("")
    for path, cnt, ch in hot:
        try:
            nlines = sum(1 for _ in open(path, encoding="utf-8", errors="replace"))
        except OSError:
            continue
        rows = outline(path)
        L.append(f"## {rel(path)}  ({nlines}行 / 直近{a.days}日に {cnt}回・{ch:,}字)")
        if not rows:
            L.append("  (構造を機械で抜けない形式。行数だけ載せる)")
        else:
            step = 1 if a.max_rows <= 0 else max(1, (len(rows) + a.max_rows - 1) // a.max_rows)
            for i in range(0, len(rows), step):
                ln, txt = rows[i]
                L.append(f"  L{ln:<5} {txt}")
            if step > 1:
                L.append(f"  … 見出し {len(rows)}件を {a.max_rows}件へ間引いた(全部要るなら実物を範囲読み)")
        L.append("")
    body = "\n".join(L)

    out = os.path.join(REPO, "local", "llm", f"index_{a.dept}.md")
    print(f"[index] {a.dept}: 対象 {len(hot)}件 / 索引 {len(body):,}字")
    print(f"[index] この索引1枚が、直近{a.days}日で {total_chars:,}字の丸ごと読みに対応している"
          f"(= 索引の {total_chars/max(1,len(body)):.0f}倍)")
    if a.dry_run:
        print("--- dry-run: 書き込まない ---")
        print(body[:3000])
        return 0
    if os.path.exists(out):                       # C-003= 消さずに退避
        bak = out + ".bak"
        with open(bak, "w", encoding="utf-8") as f:
            f.write(open(out, encoding="utf-8", errors="replace").read())
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    print(f"[index] 書いた= {rel(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
