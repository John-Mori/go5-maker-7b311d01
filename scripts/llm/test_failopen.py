# -*- coding: utf-8 -*-
"""relay無人時 fail-open(§3.1)の封筒条件テスト(2026-08-02 イージス研究室)。

HQ裁定 msg=1533226514794025081 の封筒4条件のうち、LLMを呼ばずに検証できる部分
(kill-switch / カナリア / 二重応答ガード前 / fail-openのfail-open / owner室除外)を固める。
実LLMを要するAC1(消費者を落として1本返る)はカナリア活性化で別途・実物確認する。
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import dept_daemon as d  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  NG  {name}: got={got!r} want={want!r}")


def _env(failopen=None, depts=None):
    for k in ("RELAY_FAILOPEN", "RELAY_FAILOPEN_DEPTS"):
        os.environ.pop(k, None)
    if failopen is not None:
        os.environ["RELAY_FAILOPEN"] = failopen
    if depts is not None:
        os.environ["RELAY_FAILOPEN_DEPTS"] = depts


# ---- 1) kill-switch: 既定OFF(未設定/off/false/0)は必ず False ----
print("[1] kill-switch 既定OFF")
_env()  # 未設定
check("unset→False", d.failopen_enabled("system-engineer-b", {}), False)
for v in ("off", "OFF", "0", "false", "no", ""):
    _env(failopen=v, depts="system-engineer-b")
    check(f"{v!r}→False(allowlistに居ても発火しない)",
          d.failopen_enabled("system-engineer-b", {}), False)

# ---- 2) カナリア: ONでも対象を絞る ----
print("[2] カナリア(ONでも全19へ広げない)")
_env(failopen="on", depts="")            # ON・allowlist空
check("ON+allowlist空→対象外部門はFalse",
      d.failopen_enabled("system-engineer-b", {}), False)
check("ON+test:true→True(検証便は常に対象)",
      d.failopen_enabled("system-engineer-b", {"test": True}), True)
_env(failopen="on", depts="system-engineer-b, foo")
check("ON+allowlistに居る→True",
      d.failopen_enabled("system-engineer-b", {}), True)
check("ON+allowlistに居ない→False",
      d.failopen_enabled("copy-director", {}), False)
_env(failopen="on", depts="*")
check("ON+'*'→全部門True(最終段)",
      d.failopen_enabled("copy-director", {}), True)
_env(failopen="1", depts="all")
check("'1'+'all'→True", d.failopen_enabled("copy-director", {}), True)

# ---- 3) _failopen_reply の門番(実LLMを呼ばずにガードだけ検証) ----
print("[3] _failopen_reply のガード")


def make_fake(dept="system-engineer-b", owner_room=False, owner="relay",
              gen=("キャラ応答本文", False)):
    f = types.SimpleNamespace()
    f.dept = dept
    f.owner_room = owner_room
    f.owner_of_room = lambda: owner
    if isinstance(gen, Exception):
        def _g(rec):
            raise gen
        f.generate = _g
    else:
        f.generate = lambda rec: gen
    return f


call = d.Daemon._failopen_reply

# 3a: kill-switch OFF → 何があっても None
_env()
check("OFF→None", call(make_fake(), {}, "m1"), None)

# 以降は ON にして門番だけ見る
_env(failopen="on", depts="system-engineer-b")

# 3b: 正常 → 生成本文を返す
check("ON+対象+生成成功→本文", call(make_fake(), {}, "m2"), "キャラ応答本文")

# 3c: owner室(SESSION_OWNED_DEPTS)は触らない → None
for od in d.SESSION_OWNED_DEPTS:
    _env(failopen="on", depts=od)
    check(f"owner室 {od}→None(§3.1除外)", call(make_fake(dept=od), {}, "m3"), None)

# 3d: 窓が所有者(二重応答ガード前)→ None
_env(failopen="on", depts="system-engineer-b")
check("窓が所有者→None(二重応答ガード前)",
      call(make_fake(owner_room=True, owner="window"), {}, "m4"), None)
check("owner_roomだが窓でない(relay)→本文を返す",
      call(make_fake(owner_room=True, owner="relay"), {}, "m5"), "キャラ応答本文")

# 3e: fail-openのfail-open= 生成が例外 → None(従来の失敗経路へ素通し)
check("生成が例外→None(fail-openのfail-open)",
      call(make_fake(gen=RuntimeError("boom")), {}, "m6"), None)

# 3f: 生成が空/空白 → None(空文を送って壊さない)
check("生成が空→None", call(make_fake(gen=("", False)), {}, "m7"), None)
check("生成が空白のみ→None", call(make_fake(gen=("   \n  ", False)), {}, "m8"), None)

# 3g: <<WIP>> は落として本文だけ返す(合流点の split_wip_marker と同じ)
check("<<WIP>>は除去して返す",
      call(make_fake(gen=("本文\n<<WIP>>", False)), {}, "m9"), "本文")

_env()  # 後片付け
print(f"\n{PASS} passed / {FAIL} failed")
sys.exit(1 if FAIL else 0)
