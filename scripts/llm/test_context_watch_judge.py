# -*- coding: utf-8 -*-
"""context_watch の「線超の判定」検査(2026-08-22・研究室HQ指摘1 msg 1540622895687139438)。

★何を守る検査か:
  初版の見張りは over の条件に `not managed` を入れていた=**relay管理下のセッションは
  線を越えても1件も数えず、--alert も撃たなかった**。その時いちばん文脈を食っていたのが
  管理下の 2f7b8457(中央値 215,522=交代線を30,522超)で、見張りに1件も映らなかった。
  → この検査は「管理下の線超が拾われること」を**壊したら落ちる**形で固定する。

★空PASSにしない= 最後に**変異検査**を置く。judge() を旧仕様(管理外だけ)へ差し替えたら
  検査が落ちることをその場で確認する(test-must-fail)。

走らせ方: python scripts/llm/test_context_watch_judge.py
★読むだけ。Discordにもキューにも本番の台帳にも書かない(alertの検査は subprocess を偽物に差し替える)。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_watch as cw          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

COMPACT, ROTATE = 120000, 185000
NOW = 1_700_000_000.0
ok, ng = 0, 0


def check(name, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print("  PASS %s" % name)
    else:
        ng += 1
        print("  FAIL %s %s" % (name, detail))


def row(sid, dept, median, last_epoch=NOW, n=50):
    return {"sid": sid, "dept": dept, "model": "claude-x", "n": n, "last": median,
            "median": median, "max": median, "last_ts": "08/22 16:00", "last_epoch": last_epoch}


def sample():
    """HQが実測した盤面をそのまま型にする(2026-08-22 16:22 の測定)。"""
    return [
        row("2f7b8457", "aegis-gl", 215522),          # relay現行・交代線超 ←初版が落としていた本体
        row("c27eec97", "hq", 129706),                # relay現行・圧縮線超
        row("0351851c", "研究室メイン", 259153, NOW - 90000),   # 手動・停止済
        row("eb3904a8", "研究室メイン", 134867),      # 手動・稼働中
        row("cb16530d", "platform-se", 91516),        # 線の下
        row("old01234", "future-room", 190000, NOW - 60),      # 旧世代だが書き込みが続いている
        row("old56789", "system-engineer", 190000, NOW - 7200),  # 旧世代・停止済
    ]


def managed_map():
    return {"2f7b8457-aaaa": "aegis-gl", "c27eec97-bbbb": "hq", "cb16530d-cccc": "platform-se"}


print("== context_watch.judge / mark_managed ==")
rows = cw.mark_managed(sample(), managed_map())
by = {r["sid"]: r for r in rows}

check("relayが立てた現行世代は relay:現行", by["2f7b8457"]["managed"] == "relay:現行",
      by["2f7b8457"]["managed"])
check("relayが立てた旧世代は relay:旧世代", by["old01234"]["managed"] == "relay:旧世代",
      by["old01234"]["managed"])
check("手で開いた窓は管理外(空)", by["eb3904a8"]["managed"] == "", by["eb3904a8"]["managed"])

over = cw.judge(rows, COMPACT, ROTATE, now=NOW)
o = {r["sid"]: r for r in over}

# ★これがHQ指摘1の本体。ここが拾えなければ検査は落ちる。
check("管理下の線超が拾われる(未発火)", "2f7b8457" in o and o["2f7b8457"]["over_kind"] == "未発火",
      str(o.get("2f7b8457")))
check("管理下の線超は通知に載る", bool(o.get("2f7b8457", {}).get("alert")))
check("交代線を越えたら交代線超", o.get("2f7b8457", {}).get("level") == "交代線超")
check("圧縮線だけ越えたら圧縮線超", o.get("c27eec97", {}).get("level") == "圧縮線超")
check("管理外の線超は管理外", o.get("0351851c", {}).get("over_kind") == "管理外")
check("手動で稼働中の窓も拾う", o.get("eb3904a8", {}).get("over_kind") == "管理外")
check("旧世代でも書き込みが続いていれば見失い", o.get("old01234", {}).get("over_kind") == "見失い")
check("交代済の旧世代は鳴らさない",
      o.get("old56789", {}).get("over_kind") == "交代済" and not o["old56789"]["alert"])
check("線の下は1件も入らない", "cb16530d" not in o)
check("拾った件数=6(全7本のうち線の下1本を除く)", len(over) == 6, str(len(over)))


print("== alert(): 種類ごとに分けて書く / 交代済は載せない ==")


class _FakeSub(object):
    def __init__(self):
        self.calls = []

    def run(self, argv, **kw):
        self.calls.append(argv)

        class R(object):
            returncode = 0
        return R()


tmp = tempfile.mkdtemp(prefix="ctxwatch_test_")
cw.STATE = os.path.join(tmp, "state.json")      # ★本番の状態ファイルを触らない
real_sub = cw.subprocess
cw.subprocess = _FakeSub()
try:
    n = cw.alert(over, COMPACT, ROTATE)
    body = ""
    if cw.subprocess.calls:
        argv = cw.subprocess.calls[0]
        body = argv[argv.index("--body") + 1] if "--body" in argv else ""
    check("通知は1本だけ出す", len(cw.subprocess.calls) == 1, str(len(cw.subprocess.calls)))
    check("通知した件数=5(交代済を除く)", n == 5, str(n))
    check("宛先はHQ", "--dept" in (cw.subprocess.calls[0] if cw.subprocess.calls else [])
          and cw.subprocess.calls[0][cw.subprocess.calls[0].index("--dept") + 1] == "hq")
    check("Discordへは出さない(--also-postを付けない)",
          "--also-post" not in (cw.subprocess.calls[0] if cw.subprocess.calls else []))
    check("本文に未発火の見出しがある", "■未発火" in body)
    check("本文に管理外の見出しがある", "■管理外" in body)
    check("本文に見失いの見出しがある", "■見失い" in body)
    check("本文に管理下のセッションIDが載る", "2f7b8457" in body, body[:200])
    check("交代済のセッションIDは載らない", "old56789" not in body)
    # 2回目= 冷却中なので鳴らない(常に誤発火する安全網は無視される=共通規律§3)
    n2 = cw.alert(over, COMPACT, ROTATE)
    check("冷却中は再送しない", n2 == 0 and len(cw.subprocess.calls) == 1, "%s/%s" % (n2, len(cw.subprocess.calls)))
finally:
    cw.subprocess = real_sub


print("== 変異検査(旧仕様へ戻したら落ちること) ==")
real_judge = cw.judge


def _old_judge(rows, compact_at, rotate_at, now=None):
    """初版の判定= `not managed` 付き(管理外しか数えない)。"""
    out = []
    for r in rows:
        if not r.get("managed") and r["median"] >= compact_at:
            r["over_kind"], r["level"], r["alert"] = "管理外", "圧縮線超", True
            out.append(r)
    return out


cw.judge = _old_judge
mrows = cw.mark_managed(sample(), managed_map())
mover = {r["sid"]: r for r in cw.judge(mrows, COMPACT, ROTATE, now=NOW)}
cw.judge = real_judge
check("★変異: 旧仕様では管理下の線超(2f7b8457)が消える", "2f7b8457" not in mover,
      "旧仕様でも拾えている=この検査は何も守っていない")
check("★変異: 旧仕様の件数は2件だけ", len(mover) == 2, str(len(mover)))

print("")
print("PASS=%d FAIL=%d" % (ok, ng))
sys.exit(1 if ng else 0)
