#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""床を削る= 使えないツールの定義文を毎便送るのをやめた、の検査(2026-08-23 研究室HQ)。

なぜ要るか:
  `--allowedTools` は「使ってよいか」しか決めない。**定義文(スキーマ)は全部同送されている**。
  実測(claude -p --model haiku "1" / cwd=5SecMovieMaker / 記録の assistant 行の
  input+cache_read+cache_creation の**最小値**で比較・2026-08-23 JST):
      素の起動                                     51,242
      RELAY_DROP_TOOLS の7本を外す                  40,654  = **-10,588/便**
      さらに ToolSearch も外す                      54,569  ← ★増える(遅延ツールが全部展開される)
  → 外してよいのは「もともと使えない」ものだけ。**能力を削って軽くしたのではない**、
    という不変条件をここで固定する。

★外へ出る手(claudeの起動)だけ偽物にし、**argvの組み立てと分岐は本物のまま**通す。
★must-fail 内蔵: 外し方を壊した版を同じ検査へ通し、**落ちること**を実証する。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "llm"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import dept_daemon as dd          # noqa: E402
import session_relay as sr        # noqa: E402

fails = []


def check(name, got, want):
    ok = (got == want)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        fails.append(name)


class _FakeProc:
    """claudeの代役。**起動しない**が、呼び側の分岐はすべて本物のまま動く。"""

    returncode = 0

    def communicate(self, input=None, timeout=None):   # noqa: A002
        return (json.dumps({"result": "ok", "is_error": False,
                            "session_id": "s1", "usage": {}}), "")

    def poll(self):
        return 0

    def kill(self):
        pass


def capture_argv(**kw):
    """本物の _run_claude を通し、組み立てられた argv を持ち帰る。"""
    box = {}

    def fake_popen(argv, **_):
        box["argv"] = list(argv)
        return _FakeProc()

    orig = sr.subprocess.Popen
    sr.subprocess.Popen = fake_popen
    try:
        sr._run_claude("本文", "dummy-token", **kw)
    finally:
        sr.subprocess.Popen = orig
    return box.get("argv", [])


def tools_after(argv, flag):
    """可変長フラグの直後に並ぶ値(次のフラグの手前まで)。"""
    if flag not in argv:
        return []
    i = argv.index(flag) + 1
    out = []
    while i < len(argv) and not argv[i].startswith("--"):
        out.append(argv[i])
        i += 1
    return out


# ── 1. 正本が1本であること ────────────────────────────────────────
print("=== 1. 落とすツールの正本 ===")
DROP = list(dd.RELAY_DROP_TOOLS)
check("正本は dept_daemon にある", bool(DROP), True)
check("relayは正本を引く(写しを持たない)", sr._disallowed_tools(), DROP)
# ★能力を削っていないことの不変条件= 許可ツールと1つも重ならない
check("★許可ツールと重ならない", sorted(set(DROP) & set(dd.WORK_ALLOWED_TOOLS)), [])
# ★実測で「外すと逆に増える」ToolSearch と、規律が使うと決めている道具は落とさない
for keep in ("ToolSearch", "Agent", "Skill", "Read", "Bash"):
    check(f"{keep} は落とさない", keep in DROP, False)

# ── 2. 実際に組み立てられる argv ──────────────────────────────────
print("=== 2. 起動の argv(組み立ては本物) ===")
argv = capture_argv(model="haiku")
check("--disallowedTools が付く", "--disallowedTools" in argv, True)
check("7本がそのまま並ぶ", tools_after(argv, "--disallowedTools"), DROP)
check("--allowedTools も従来どおり", tools_after(argv, "--allowedTools"), dd.WORK_ALLOWED_TOOLS)
# ★可変長フラグが次の値を飲んでいないこと(2026-07-18の実障害と同じ形の再発防止)
check("--add-dir の値が生きている", len(tools_after(argv, "--add-dir")), 1)
check("--model の値が生きている", tools_after(argv, "--model"), ["haiku"])
check("promptはargvに無い(stdin)", "本文" in argv, False)
argv_r = capture_argv(session_id="abc123", model="haiku")
check("--resume の時も付く", "--disallowedTools" in argv_r, True)
check("--resume の値が生きている", tools_after(argv_r, "--resume"), ["abc123"])

# ── 3. must-fail= 壊した版が本当に落ちること ────────────────────────
print("=== 3. must-fail(壊した版を同じ検査へ通す) ===")
_orig = dd.RELAY_DROP_TOOLS
try:
    # A: 正本が空= 何も外さない → フラグ自体が付かない(=空の可変長フラグを置かない)
    dd.RELAY_DROP_TOOLS = []
    a = capture_argv(model="haiku")
    check("mustfail_空ならフラグを置かない", "--disallowedTools" in a, False)
    check("mustfail_空でも --add-dir は無傷", len(tools_after(a, "--add-dir")), 1)
    # B: 許可ツールを混ぜた版= 上の不変条件が破れることを実証する
    dd.RELAY_DROP_TOOLS = ["Read"]
    check("mustfail_許可ツールを混ぜると重なる",
          sorted(set(dd.RELAY_DROP_TOOLS) & set(dd.WORK_ALLOWED_TOOLS)), ["Read"])
finally:
    dd.RELAY_DROP_TOOLS = _orig
check("後始末= 正本は元どおり", dd.RELAY_DROP_TOOLS, DROP)
check("後始末= relayも元どおり", sr._disallowed_tools(), DROP)

if __name__ == "__main__":
    print(f"\nFAIL — {len(fails)}件: {fails}" if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)
