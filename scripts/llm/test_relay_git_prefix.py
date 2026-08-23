# -*- coding: utf-8 -*-
"""中継が起こす `claude` の前置きから**可変物(gitStatus)を外している**ことの検査。

実行: python scripts/llm/test_relay_git_prefix.py

★なぜ要るか(2026-08-23・研究室HQ msg DISPATCH-aegis-gl-1787493567341 の発注を受けた実験の結果)
  `claude -p --resume` は便ごとに別プロセス= **システムプロンプトを毎回組み直す**。
  そこへ入る `gitStatus` はこの作業ツリーでは常に動いている(実測 変更349件/直近24hのcommit99本)。
  実験(`scripts/llm/cache_prefix_probe.py`)=
    既定       : 無変更で2便=書込 230/394 → **間に空commitを1本挟むと書込 29,303**
                 (読込 50,987 → 22,173 = そこが壊れた位置)
    変数=1     : 同じ手順で 書込 345 / 読込 48,075(**壊れない**)
  → `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1` を子プロセスへ渡すのが対策。
  ★これは**env 1行**だ= 誰かが `_run_claude` の env 組み立てを整理した日に、黙って戻る。
    戻っても症状は「なんとなく重い」だけで、誰も気づかない。だから機械に数えさせる。

★検査の作法(共通規律§3)= ソースの文字列一致では見ない。
  **外へ出る手(Popen)だけ偽物**にして `_run_claude` を実行で通し、
  子へ実際に渡された env を読む。
★must-fail(C-053)= 「動く別の実装」= **対策が入る前の env 組み立て**(白名単+トークンだけ)へ
  差し替えて、検査が赤くなることを確かめる。行を消して文法を壊すのは偽の緑だ。
"""
import json
import os
import subprocess as _real_subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_relay as sr   # noqa: E402

VAR = "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS"
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


# --- ① env を組む関数そのもの -------------------------------------------------
env = sr._child_env("tok-xyz")
check("① gitStatus を外す指定が入っている", env.get(VAR) == "1")
check("① トークンは渡している", env.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok-xyz")
check("① PATH は残している(claude が起動できる)", bool(env.get("PATH")))

os.environ["CLAUDE_CODE_ZZZ_TEST_ONLY"] = "親から漏れてはいけない値"
try:
    env2 = sr._child_env("t")
    check("① 親の CLAUDE_CODE_* は継がない(2026-07-26の口座事故の再発防止)",
          "CLAUDE_CODE_ZZZ_TEST_ONLY" not in env2)
finally:
    os.environ.pop("CLAUDE_CODE_ZZZ_TEST_ONLY", None)


# --- ② 配線= `_run_claude` を実行で通し、子へ渡された env を読む ----------------
class _FakeProc(object):
    def __init__(self):
        self.returncode = 0

    def communicate(self, input=None, timeout=None):
        return (json.dumps({"result": "あ", "is_error": False}), "")

    def poll(self):
        return 0

    def kill(self):
        pass


class _PopenShim(object):
    DEVNULL = _real_subprocess.DEVNULL
    PIPE = _real_subprocess.PIPE
    TimeoutExpired = _real_subprocess.TimeoutExpired
    seen = []

    def __getattr__(self, k):
        return getattr(_real_subprocess, k)

    def Popen(self, argv, **kw):
        _PopenShim.seen.append({"argv": argv, "env": dict(kw.get("env") or {})})
        return _FakeProc()               # ★外へ出る手だけ偽物= 本物の claude は起こさない


def run_once():
    prev = sr.subprocess
    sr.subprocess = _PopenShim()
    try:
        return sr._run_claude("てすと", "tok-abc", session_id="sid-123", timeout=5)
    finally:
        sr.subprocess = prev


_PopenShim.seen = []
data, rc, out, waited = run_once()
check("② 便が通った(rc=0・本文が取れる)", rc == 0 and sr._reply_of(data) == "あ")
check("② claude を `--resume` で起こそうとした(経路を通った)",
      len(_PopenShim.seen) == 1 and "--resume" in _PopenShim.seen[0]["argv"])
check("② ★子へ渡された env に gitStatus を外す指定が在る",
      _PopenShim.seen[0]["env"].get(VAR) == "1")


# --- ③ must-fail= 対策が入る前の「動く別の実装」へ戻すと赤くなるか --------------
def _child_env_before_fix(token):
    """★対策が入る前の実装そのもの= 白名単+トークンだけ(動く。ただ gitStatus を外さない)。"""
    keep = ("SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "USERNAME", "HOMEDRIVE",
            "HOMEPATH", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PYTHONIOENCODING",
            "GO5_LOCAL_DIR")
    e = {k: v for k, v in os.environ.items() if k.upper() in keep}
    e["CLAUDE_CODE_OAUTH_TOKEN"] = token or ""
    return e


_prev = sr._child_env
sr._child_env = _child_env_before_fix
try:
    _PopenShim.seen = []
    d2, rc2, _o2, _w2 = run_once()
    _regressed = (rc2 == 0
                  and len(_PopenShim.seen) == 1
                  and VAR not in _PopenShim.seen[0]["env"])
finally:
    sr._child_env = _prev
check("③ must-fail: 対策前の env 組み立てへ戻すと、子へ指定が渡らない(=②が赤くなる)",
      _regressed)

_PopenShim.seen = []
run_once()
check("③ 復元済み: 本物へ戻すとまた指定が渡る",
      sr._child_env is _prev and _PopenShim.seen[0]["env"].get(VAR) == "1")
check("③ 本物の subprocess を戻し忘れていない", sr.subprocess is _real_subprocess)

ng = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(ng)}/{len(results)} PASS")
if ng:
    print("FAILED: " + " / ".join(ng))
sys.exit(1 if ng else 0)
