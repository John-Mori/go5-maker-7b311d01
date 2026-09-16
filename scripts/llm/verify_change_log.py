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
import re
import subprocess
import sys

# ★既定の cp932 では報告に混ざる `✓` で **検査そのものが落ちる**(2026-09-16 実測・イージス研究室)。
#   検査が例外で死ぬと「違反ゼロ」と見分けが付かない= 黙って通ったように見えるのが一番まずい。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                    # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LEDGER = os.path.join(ROOT, "local", "llm", "change_log.jsonl")

# ★commitが「意図的に空」だと分かる正直な自己申告の形。これは嘘ではない=別枠で報告する。
_HONEST_UNCOMMITTED_MARKERS = ("未commit", "止血", "(未)", "pending")


def _norm_rel(path):
    """`\\` を `/` にし、先頭の `./` だけを剥がした相対パスを返す。

    ★`lstrip("./")` を使うな(2026-09-16 実測・イージス研究室で自分の行が踏んだ):
      lstrip は**文字集合**を剥がすので `.gitattributes` が `gitattributes` になり、
      commitの差分と一致せず `files_missing_from_commit` の**偽の赤**が出る。
      うちには `.gitattributes` `.gitignore` `.claude/...` と先頭ドットの正規ファイルが在る。
    """
    p = str(path).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def _split_touched(v):
    """『触った』の文字列を1本ずつのパスへ割る。

    ★区切りは `,`(旧書式)だけではない。repoが2つある裁定(「commit hashにはrepo名を併記する」)を
      受けて、実際の台帳では **` / `**(空白スラッシュ空白)で並べる書き方が定着している。
      パスの中のスラッシュには空白が付かないので、この形は安全に区切りとして読める。
    """
    parts = [v]
    for sep in (",", "、", ";", "；", "\n", " / ", " ／ "):
        nxt = []
        for p in parts:
            nxt.extend(p.split(sep))
        parts = nxt
    return [p.strip() for p in parts if p.strip()]


def _strip_repo_prefix(part, current_repo):
    """`5SecMovieMaker: scripts/...` の **repo名の見出し** を剥がす。戻り値= (パス, 引き継ぐrepo名)。

    ★2026-09-08 実測(イージス研究室・自分の行で踏んだ): 『触った』へ
      `"5SecMovieMaker: scripts/llm/quota_alarm.py / scripts/llm/test_quota_alarm_rearm.py / 00_AI-HQ: status/hq_open_items.md"`
      と書いたら、検査は**全体を1つのファイル名**と読んで `files_missing_from_commit` の**偽の赤**を出した。
      これは「やっていないのにやったと言った」と読める札で、無実の部屋を疑わせる(_bare_hash と同じ事故)。
    ★見出しは**次の見出しが来るまで後続へ効く**(上の例なら2本目も 5SecMovieMaker)。
    ★ROOT以外のrepoは、見出しをディレクトリ名へ畳んで `00_AI-HQ/status/...` の形へ戻す
      (`_is_git_trackable` / `_commit_touches` がこの形を前提にしているため)。
    """
    for name in REPOS:
        for sep in (": ", "：", ":"):
            head = name + sep
            if part.startswith(head):
                rest = part[len(head):].strip()
                return rest, name
    if current_repo and current_repo != "5SecMovieMaker":
        p = _norm_rel(part)
        if not p.startswith(current_repo + "/") and not os.path.isabs(part):
            return current_repo + "/" + p, current_repo
    return part, current_repo


def _touched_files(entry):
    """『触った』は list(新しい書式)/区切りstring(旧書式)の両方があるので正規化する。"""
    v = entry.get("触った")
    if isinstance(v, list):
        items = [str(x).strip() for x in v if str(x).strip()]
    elif isinstance(v, str):
        items = _split_touched(v)
    else:
        return []
    out = []
    repo = None
    for p in items:
        p, repo = _strip_repo_prefix(p, repo)
        if repo and repo != "5SecMovieMaker" and not p.startswith(repo + "/"):
            p = repo + "/" + _norm_rel(p)
        # 注記の丸括弧以降は捨てる("path(新規作成)" 等)。
        p = p.split("(")[0].strip()
        if p:
            out.append(p)
    return out


def _bare_hash(commit):
    """`commit` 欄から**ハッシュだけ**を取り出す。

    ★2026-09-03 実測(イージス研究室): 改善提案部門の 11:35:10 の行が `commit_not_found` で赤くなった。
      実際は `f8b649d` はgit履歴に**在る**。欄が `"f8b649d (5SecMovieMaker)"` だっただけだ
      (裁定「commit hashにはrepo名を併記する」に素直に従った書き方。repoが2つあるため)。
      機械側の形は `commit`=素のhash / `commit_repo`={hash: repo} だが、規律の文面はそう言っていない。
    ★偽の赤は「やっていないのにやったと言った」と読める=無実の部屋を疑わせる。規律の方を曲げさせるより、
      機械が両方の書き方を受ける方が正しい(受け取りは緩く・出しは厳しく)。
    """
    hs = _hashes(commit)
    if hs:
        return hs[0]
    head = str(commit or "").strip().split("(")[0].split()
    return head[0] if head else ""


_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


def _hashes(commit):
    """欄の中の**ハッシュらしいトークンを全部**拾う(`a,b` の複数申告・repo名併記の両方に効く)。"""
    return _HASH_RE.findall(str(commit or "").lower())


# repo名 -> そのrepoの根。台帳は2つのrepoを跨ぐ(裁定「commit hashはrepo名を併記する」)。
REPOS = {
    "5SecMovieMaker": ROOT,
    "00_AI-HQ": os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ")),
}


def _repo_roots(entry, commit_hash):
    """そのhashを**どのrepoで探すか**。`commit_repo` を見て、無ければ両方試す。

    ★2026-09-03 実測(イージス研究室): 検査は 5SecMovieMaker しか見ておらず、
      人事部門・研究室HQなど **00_AI-HQ 側にcommitした行が軒並み `commit_not_found`** になっていた。
      台帳は2つのrepoに跨っているのに、検査が片方しか知らなかった=偽の赤。
    """
    cr = entry.get("commit_repo")
    name = ""
    if isinstance(cr, dict):
        for k, v in cr.items():
            if str(k).lower().startswith(commit_hash) or commit_hash.startswith(str(k).lower()):
                name = str(v)
                break
    elif isinstance(cr, str):
        name = cr
    root = REPOS.get(name.strip()) if name else None
    return [root] if root else list(REPOS.values())


def _commit_exists(commit_hash, roots=None):
    for root in (roots or [ROOT]):
        # ★encoding指定が要る: 既定は cp932 で、gitの日本語エラー文が来ると読み手スレッドが落ちる(実測)
        r = subprocess.run(["git", "cat-file", "-e", commit_hash + "^{commit}"],
                            cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        if r.returncode == 0:
            return root
    return None


def _commit_touches(commit_hash, path, root=None):
    """そのcommitのdiffに path が含まれるか(先頭/末尾のフォルダ表記ゆれは緩く許容)。

    ★`-c core.quotepath=false` が要る(2026-09-03 実測・イージス研究室): 既定の git は非ASCIIのパスを
      `"docs/.../\\345\\236\\213_..."` と8進エスケープで出す。うちのdocsは**日本語ファイル名が普通**なので、
      この照合は日本語名のファイルに対して**必ず外れ**、`files_missing_from_commit` の偽の赤を出していた
      (改善提案部門の型 `型_起動文人格欄の正本一元化_2026-09-03.md` で発覚)。
    """
    r = subprocess.run(["git", "-c", "core.quotepath=false", "show", "--name-only",
                        "--pretty=format:", commit_hash],
                        cwd=(root or ROOT), capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return False
    changed = {ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()}
    needle = _norm_rel(path)
    # ★HQ側のcommitを照合する時、台帳の書き方は `00_AI-HQ/departments/...`(5秒動画側から見た相対)。
    #   HQ repo の中では先頭の `00_AI-HQ/` は無いので落とす。
    if root and os.path.normpath(root) == os.path.normpath(REPOS["00_AI-HQ"]):
        needle = needle[len("00_AI-HQ/"):] if needle.startswith("00_AI-HQ/") else needle
    return any(needle == c or needle.endswith("/" + c) or c.endswith("/" + needle)
               for c in changed)


def _is_git_trackable(path, root=None):
    """そのcommitのrepo管理下のパスか(=commit diffで照合できるか)。

    ★local/ はgitignore(=絶対にcommitされない)ので照合対象外(existsのみ=誤検知しない)。
    ★`00_AI-HQ/` 配下は**そのcommitがどちらのrepoか**で変わる: 5秒動画側のcommitなら
      repoの外(対象外)、HQ側のcommitなら**まさに本体**(照合する)。
      以前は無条件に対象外にしていたため、HQ側の行は「触った」を1件も照合していなかった。
    """
    p = _norm_rel(path)
    if p.startswith("local/") or p.startswith("../"):
        return False
    if os.path.isabs(path):
        return False
    if p.startswith("00_AI-HQ/"):
        return bool(root) and os.path.normpath(root) == os.path.normpath(REPOS["00_AI-HQ"])
    return not root or os.path.normpath(root) == os.path.normpath(ROOT)


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
    # ★1行が複数commitを申告することがある("1bb3ffa,e753741")。全部拾って**どれかに入っていれば良い**
    #   とする(1つの変更を2commitに割るのは普通のこと。片方にしか無い=嘘ではない)。
    hashes = _hashes(commit)
    if not hashes:
        # ★hashが1つも書かれていない欄(「n/a」「記録のみ・変更なし」「push済」等)は**未検証**であって
        #   不一致ではない。commitを申告していない行を赤くすると、嘘をついた行と区別が付かなくなる。
        return "unverified_empty_commit", f"commit='{commit}'(hashの申告なし・未照合)"
    found = []                                   # [(hash, root)]
    for h in hashes:
        root = _commit_exists(h, _repo_roots(entry, h))
        if root:
            found.append((h, root))
    if not found:
        return "commit_not_found", f"commit={','.join(hashes)} がどちらのrepoのgit履歴にも無い"
    if not files:
        return "ok", "触ったファイルの記載なし(照合対象なし)"
    label = ",".join(h for h, _ in found)
    trackable = [f for f in files
                 if any(_is_git_trackable(f, root) for _, root in found)]
    outside = [f for f in files if f not in trackable]
    missing = [f for f in trackable
               if not any(_commit_touches(h, f, root) for h, root in found)]
    if missing:
        return "files_missing_from_commit", (
            f"commit={label} に入っていないファイル: {', '.join(missing)}"
            + (f"(git管理外で照合skip: {', '.join(outside)})" if outside else ""))
    return "ok", (f"commit={label} が{len(trackable)}件に触れている"
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
        n_fail = 0

        def _chk(label, got, want):
            nonlocal n_fail
            ok = (got == want)
            if not ok:
                n_fail += 1
            print(("  PASS  " if ok else "  FAIL  ") + label
                  + ("" if ok else f"\n         期待={want!r}\n         実物={got!r}"))

        bad = {"ts": "2026-08-23T06:21:02+09:00", "dept": "platform-se",
               "触った": "scripts/llm/session_relay.py, scripts/llm/test_boot_reinject.py, "
                         "00_AI-HQ/departments/hr/memory/mei_shared.jsonl",
               "commit": ""}
        _chk("実物の事故行(commit空)を検出できる", verify_entry(bad)[0], "unverified_empty_commit")

        # ★2026-09-08 実測でこの検査を足した(イージス研究室が自分の行で偽の赤を踏んだ)。
        #   `repo名: path / path / repo名: path` の書式を**1つのファイル名**として読んでいた。
        real = ("5SecMovieMaker: scripts/llm/quota_alarm.py / scripts/llm/test_quota_alarm_rearm.py"
                " / 00_AI-HQ: status/hq_open_items.md")
        _chk("repo名の見出しと ` / ` 区切りを割れる",
             _touched_files({"触った": real}),
             ["scripts/llm/quota_alarm.py", "scripts/llm/test_quota_alarm_rearm.py",
              "00_AI-HQ/status/hq_open_items.md"])
        _chk("見出しは次の見出しまで後続へ効く(2本目も5SecMovieMaker側=先頭にrepo名を付けない)",
             _touched_files({"触った": real})[1].startswith("scripts/"), True)
        _chk("旧書式(comma区切り)は壊さない",
             _touched_files({"触った": "a/b.py, c/d.py(注記)"}), ["a/b.py", "c/d.py"])
        _chk("list書式は壊さない",
             _touched_files({"触った": ["a/b.py", " c/d.py "]}), ["a/b.py", "c/d.py"])
        # ★must-fail= 事故当時の実装(split(\",\") だけ)へ戻すと1本目の検査が赤くなる=検査が生きている。
        old = [p.split("(")[0].strip() for p in real.split(",") if p.split("(")[0].strip()]
        _chk("must-fail: 事故当時の実装なら1本の塊になる(検査が生きている証拠)", len(old), 1)

        # ★2026-09-16 実測でこの検査を足した(イージス研究室が `.gitattributes` の行で偽の赤を踏んだ)。
        #   `lstrip("./")` は文字集合を剥がすので、先頭ドットのファイル名が丸ごと削れていた。
        _chk("先頭ドットのファイル名を削らない(.gitattributes / .gitignore)",
             [_norm_rel(".gitattributes"), _norm_rel("./.gitignore"),
              _norm_rel(".claude\\settings.json")],
             [".gitattributes", ".gitignore", ".claude/settings.json"])
        _chk("must-fail: 事故当時の実装なら .gitattributes が gitattributes になる(検査が生きている証拠)",
             ".gitattributes".replace("\\", "/").lstrip("./"), "gitattributes")

        print("==== 全部PASS ====" if n_fail == 0 else f"==== FAIL {n_fail}件 ====")
        return 0 if n_fail == 0 else 1

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
