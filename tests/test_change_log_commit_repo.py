#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台帳のcommit hashに**どのrepoの実物か**が付くかの検査(イージス研究室 2026-08-31)。

★なぜ要るのか= repoは2つある(5SecMovieMaker / 00_AI-HQ)。
  2026-08-31、プラットフォームSEの報告にあった `6c905dc` を研究室HQが 5SecMovieMaker で
  git show して「無い」と出た。実物は 00_AI-HQ 側のcommitで実装は正しかったが、
  HQは**捏造を疑う一歩手前**まで行き、探す時間を食った(DISPATCH-aegis-gl-1788150930927)。
  「次からrepoも併記してくれ」は心がけなので次の世代へ渡らない。だから機械で付ける(C-038)。

★C-053= must-fail を1本。「壊した実装なら落ちる」ではなく、**動く別実装**
  (= 片方のrepoだけ見る。HQが手でやったのと同じ手順で、実際に動く)を並べて、
  それが正しいhashを「未検出」と呼ぶことを見せる。

★C-054= 本番の台帳(local/llm/change_log.jsonl)は**1バイトも触らない**。
  書き込みを見る検査は全部 tempfile へ向ける。

    python tests/test_change_log_commit_repo.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import session_relay as sr                                          # noqa: E402

PROD = sr.CHANGE_LOG_FILE
PROD_BEFORE = os.stat(PROD) if os.path.exists(PROD) else None
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


# --- 実物のrepoで引く(★git を本当に叩く) -----------------------------------
print("[実物] 2つのrepoの本物のhashを引き当てる")
check("5SecMovieMaker側のhashに repo名が付く(3bdd683)",
      sr.commit_repos("3bdd683") == {"3bdd683": "5SecMovieMaker"})
check("★00_AI-HQ側のhashにも付く(6c905dc= 今回の事故そのもの)",
      sr.commit_repos("6c905dc") == {"6c905dc": "00_AI-HQ"})
both = sr.commit_repos(["3bdd683", "6c905dc"])
check("報告どおり list で渡しても両方付く",
      both == {"3bdd683": "5SecMovieMaker", "6c905dc": "00_AI-HQ"})
check("本文に混ざった hash も拾う",
      sr.commit_repos("commit 3bdd683 で入れた") == {"3bdd683": "5SecMovieMaker"})

print("[実物] どちらにも無いhash= その場で見える")
ghost = "0123456789abcdef0123456789abcdef01234567"
check("★存在しないhashは『未検出』(読み手が疑う前にここで見える)",
      sr.commit_repos(ghost) == {ghost: sr.CHANGE_COMMIT_UNKNOWN})

print("[実物] hashでないものを拾わない")
check("空は何も返さない", sr.commit_repos("") == {})
check("6桁以下は hash と見ない", sr.commit_repos("abc12") == {})
check("日本語だけの commit 欄は何も返さない", sr.commit_repos("まだcommitしていない") == {})

# --- ★must-fail(C-053): 片方のrepoだけ見る「動く別実装」 ---------------------
print("[must-fail] 素朴な別実装『5SecMovieMakerで git show する』")


def naive_5sec_only(h):
    """HQが手でやったのと同じ手順。動きはするし、片方のrepoの話なら常に正しい。"""
    r = sr._commit_in_repo(h, sr.ROOT)
    return {h: "5SecMovieMaker"} if r else {h: sr.CHANGE_COMMIT_UNKNOWN}


check("★素朴案は 6c905dc を『未検出』と呼ぶ(=HQが捏造を疑いかけた地点)",
      naive_5sec_only("6c905dc") == {"6c905dc": sr.CHANGE_COMMIT_UNKNOWN})
check("★本実装は同じhashを 00_AI-HQ と正しく呼ぶ(=この改修の意味)",
      sr.commit_repos("6c905dc") == {"6c905dc": "00_AI-HQ"})
check("素朴案でも 5SecMovieMaker側は当たる(だから間違いに気づけない)",
      naive_5sec_only("3bdd683") == {"3bdd683": "5SecMovieMaker"})

# --- 判定できない時に嘘を書かない ----------------------------------------------
print("[fail-safe] 判定できなかったhashに印を付けない(★正しいhashを捏造扱いしない)")
_real = sr._commit_in_repo
try:
    sr._commit_in_repo = lambda h, root: None        # gitが無い/時間切れ/repoが見えない
    sr._COMMIT_REPO_CACHE.clear()
    check("判定不能なら『未検出』ではなく**印なし**", sr.commit_repos("3bdd683") == {})
finally:
    sr._commit_in_repo = _real
    sr._COMMIT_REPO_CACHE.clear()

check("★常駐(pythonw)から git を呼ぶので黒窓を出さない指定が居る",
      sr._NO_WINDOW != 0 if os.name == "nt" else True)

# --- 書き手① log_change ---------------------------------------------------------
print("[入口] log_change が repo名を書く(★本番の台帳は触らない)")
tmpd = tempfile.mkdtemp(prefix="clcr_")
_pf, _pl = sr.CHANGE_LOG_FILE, sr.CHANGE_LOG_LOCK
try:
    sr.CHANGE_LOG_FILE = os.path.join(tmpd, "change_log.jsonl")
    sr.CHANGE_LOG_LOCK = sr.CHANGE_LOG_FILE + ".lock"
    sr.log_change("aegis-gl", "検査", "検査", touched="なし", commit="3bdd683")
    with open(sr.CHANGE_LOG_FILE, encoding="utf-8") as f:
        rec = json.loads(f.readline())
    check("commit はそのまま残る(消さない・書き換えない)", rec["commit"] == "3bdd683")
    check("commit_repo が付く", rec.get("commit_repo") == {"3bdd683": "5SecMovieMaker"})

    # --- 書き手② 直に追記した行(規律L55の経路)を後追いで正す --------------------
    print("[後追い] セッションが自分で足した行にも付く(★log_changeを通らない行が来る)")
    lines = [
        {"ts": "2026-08-31T13:19:19+09:00", "ts_source": "machine", "dept": "x",
         "何": "済んだ行", "なぜ": "-", "触った": "-", "commit": "3bdd683"},
        {"ts": "2026-08-31T13:19:19", "dept": "platform-se", "何": "自分で足した行",
         "なぜ": "-", "触った": "-", "commit": ["3bdd683", "6c905dc"]},
    ]
    with open(sr.CHANGE_LOG_FILE, "w", encoding="utf-8") as f:
        for r in lines:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    sr.normalize_change_log()
    with open(sr.CHANGE_LOG_FILE, encoding="utf-8") as f:
        got = [json.loads(s) for s in f if s.strip()]
    check("直に足した行に commit_repo が付く",
          got[1].get("commit_repo") == {"3bdd683": "5SecMovieMaker", "6c905dc": "00_AI-HQ"})
    check("★機械が見終わった行は1バイトも触らない",
          got[0] == lines[0] and "commit_repo" not in got[0])
    before = json.dumps(got, ensure_ascii=False, sort_keys=True)
    sr.normalize_change_log()
    with open(sr.CHANGE_LOG_FILE, encoding="utf-8") as f:
        again = [json.loads(s) for s in f if s.strip()]
    check("2回舐めても変わらない(冪等)",
          json.dumps(again, ensure_ascii=False, sort_keys=True) == before)
finally:
    sr.CHANGE_LOG_FILE, sr.CHANGE_LOG_LOCK = _pf, _pl

# --- C-054: 本番の台帳を触っていないこと ----------------------------------------
print("[C-054] 本番の台帳を1バイトも触っていない")
now = os.stat(PROD) if os.path.exists(PROD) else None
check("local/llm/change_log.jsonl の大きさと時刻が変わっていない",
      (PROD_BEFORE is None and now is None) or
      (now and PROD_BEFORE and (now.st_size, now.st_mtime) == (PROD_BEFORE.st_size,
                                                               PROD_BEFORE.st_mtime)))

ok = sum(1 for _, c in results if c)
print("\n%d/%d PASS" % (ok, len(results)))
for n, c in results:
    if not c:
        print("  FAILED:", n)
sys.exit(0 if ok == len(results) else 1)
