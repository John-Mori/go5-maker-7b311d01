# -*- coding: utf-8 -*-
"""change_log.jsonl の『触った』が実物(HEAD)へ入ったかを機械で照合する検証器。

なぜ要るか(実物=2026-08-23 06:21:02 のplatform-se便・研究室HQ実測):
  change_log は**書いた本人の申告**で、書いた時点では正しくても、並列セッションの
  commit に掃かれて実装が消えると台帳だけが取り残される(C-048と同じ形)。
  この便は commit フィールドが **空文字("")** のまま半日誰にも気づかれず、
  `git log -S"mei_shared"` = 0件(=どのcommitにも入っていない)という実測で
  研究室HQが指摘するまで「入った」と「消えた」が区別できなかった。

判定(HQ提案「語を1つ git log -S で引くだけでいい」を機械化):
  ① commit が空/プレースホルダ(例「(未commit・止血)」)→ **未検証**として報告する
     (これ自体は嘘ではない=正直な自己申告。だが古いまま放置されると危険なので拾う)。
  ② commit が実在のhashなら、そのcommitが実際に『触った』の各パスへ触れているかを
     `git show --name-only <hash>` で照合する。1つでも入っていなければ **不一致**。
  ③ commit が実在しないhash(typo等)なら **不一致**。

使い方=
  python scripts/llm/verify_change_log.py                  # 直近50件を検査
  python scripts/llm/verify_change_log.py --tail 200
  python scripts/llm/verify_change_log.py --dept platform-se
  python scripts/llm/verify_change_log.py --self-test       # 実物の事故行(1195行目)で機構を検証
標準出力に問題のある行だけを列挙する(健全な行は数えるだけで表示しない=ノイズを増やさない)。
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LEDGER = os.path.join(ROOT, "local", "llm", "change_log.jsonl")

# ★commitが「意図的に空」だと分かる正直な自己申告の形。これは嘘ではない=別枠で報告する。
_HONEST_UNCOMMITTED_MARKERS = ("未commit", "止血", "(未)", "pending")


def _touched_files(entry):
    """『触った』は list(新しい書式)/comma区切りstring(旧書式)の両方があるので正規化する。"""
    v = entry.get("触った")
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        # 旧書式= "path1, path2, path3" や "path(注記)" が混在する。注記の丸括弧以降は捨てる。
        parts = [p.strip() for p in v.split(",")]
        out = []
        for p in parts:
            p = p.split("(")[0].strip()
            if p:
                out.append(p)
        return out
    return []


def _commit_exists(commit_hash):
    r = subprocess.run(["git", "cat-file", "-e", commit_hash + "^{commit}"],
                        cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0


def _commit_touches(commit_hash, path):
    """そのcommitのdiffに path が含まれるか(先頭/末尾のフォルダ表記ゆれは緩く許容)。"""
    r = subprocess.run(["git", "show", "--name-only", "--pretty=format:", commit_hash],
                        cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return False
    changed = {ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()}
    needle = path.replace("\\", "/").lstrip("./")
    return any(needle == c or needle.endswith("/" + c) or c.endswith("/" + needle)
               for c in changed)


def _is_git_trackable(path):
    """5SecMovieMaker repo管理下のパスか(=commit diffで照合できるか)。

    ★local/ はgitignore(=絶対にcommitされない)・00_AI-HQ配下は別ディレクトリ
    (このrepoの外)なので、どちらもcommit diff照合の対象外(existsのみ見る=誤検知しない)。
    """
    p = path.replace("\\", "/").lstrip("./")
    if p.startswith("local/") or p.startswith("00_AI-HQ/") or p.startswith("../"):
        return False
    if os.path.isabs(path):
        return False
    return True


def verify_entry(entry):
    """1行を判定する。戻り値= (status, detail)。

    status ∈ {"ok", "unverified_empty_commit", "commit_not_found", "files_missing_from_commit"}
    """
    commit = str(entry.get("commit") or "").strip()
    files = _touched_files(entry)
    if not commit:
        return "unverified_empty_commit", "commitが空(申告のみ・未照合)"
    if any(m in commit for m in _HONEST_UNCOMMITTED_MARKERS):
        return "unverified_empty_commit", f"commit='{commit}'(正直な未commit申告)"
    if not files:
        return "ok", "触ったファイルの記載なし(照合対象なし)"
    if not _commit_exists(commit):
        return "commit_not_found", f"commit={commit} がgit履歴に無い"
    trackable = [f for f in files if _is_git_trackable(f)]
    outside = [f for f in files if f not in trackable]
    missing = [f for f in trackable if not _commit_touches(commit, f)]
    if missing:
        return "files_missing_from_commit", (
            f"commit={commit} に入っていないファイル: {', '.join(missing)}"
            + (f"(git管理外で照合skip: {', '.join(outside)})" if outside else ""))
    return "ok", (f"commit={commit} が{len(trackable)}件に触れている"
                   + (f"(git管理外{len(outside)}件は対象外)" if outside else ""))


def _load(tail=None, dept=None):
    rows = []
    if not os.path.exists(LEDGER):
        return rows
    with open(LEDGER, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:                     # noqa: BLE001 壊れた行は読み飛ばす(黙って落とさない=数だけ数える)
                continue
            if dept and d.get("dept") != dept:
                continue
            rows.append(d)
    return rows[-tail:] if tail else rows


def main():
    ap = argparse.ArgumentParser(description="change_log.jsonl の『触った』をHEADと照合する")
    ap.add_argument("--tail", type=int, default=50)
    ap.add_argument("--dept", default=None)
    ap.add_argument("--self-test", action="store_true",
                     help="実物の事故行(2026-08-23 06:21:02・commit空)を検出できるか検証する")
    a = ap.parse_args()

    if a.self_test:
        bad = {"ts": "2026-08-23T06:21:02+09:00", "dept": "platform-se",
               "触った": "scripts/llm/session_relay.py, scripts/llm/test_boot_reinject.py, "
                         "00_AI-HQ/departments/hr/memory/mei_shared.jsonl",
               "commit": ""}
        status, detail = verify_entry(bad)
        ok = status == "unverified_empty_commit"
        print(("  PASS  " if ok else "  FAIL  ")
              + f"実物の事故行(commit空)を検出できる → status={status} / {detail}")
        return 0 if ok else 1

    rows = _load(tail=a.tail, dept=a.dept)
    counts = {}
    problems = []
    for e in rows:
        status, detail = verify_entry(e)
        counts[status] = counts.get(status, 0) + 1
        if status != "ok":
            problems.append((e, status, detail))

    print(f"検査{len(rows)}件: " + " / ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for e, status, detail in problems:
        print(f"  [{status}] {e.get('ts','?')} {e.get('dept','?')}: "
              f"{str(e.get('何',''))[:60]}\n         {detail}")
    return 1 if any(s == "files_missing_from_commit" or s == "commit_not_found"
                     for _, s, _ in problems) else 0


if __name__ == "__main__":
    sys.exit(main())
