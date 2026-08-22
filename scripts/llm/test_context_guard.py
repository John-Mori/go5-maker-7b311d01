# -*- coding: utf-8 -*-
"""context_guard(文脈の上限を管理外セッションにも効かせるhook)の検査(2026-08-22 イージス研究室)。

発注= 研究室HQ msg 1540618940533841982「relay管理外のセッションにも文脈の上限が効く形を
入れてほしい」「モデルの文脈窓に依存しない線の引き方にしてくれ」。

この検査が固定する規則=
  ① relayの管理外で線を越えたセッションには**警告が出る**(実物のtranscriptで通す)
  ② relayが世代管理している現行セッションでは**黙る**(二重の警報は無視される=規律§3)
  ③ 線を越えていないセッションでは黙る
  ④ 同じセッションへ鳴らし続けない(WARN_EVERY_SEC の間引き)
  ⑤ ★線は**絶対トークン数**で、モデルの窓から導かない= 1M窓のセッションでも
     93万を待たず 12万/18.5万 で鳴る(これが今回の穴の本体)
  ⑥ ★変異検査= 線を天井まで上げたら鳴らない(=①は本物の判定を見ている)

★外へ出る手だけ偽物にする= 台帳と状態ファイルを一時フォルダへ向ける。
  判定(transcriptを読む・管理下か見る・線と比べる)は**本番のまま**動かす。
  ★transcriptは読むだけ。セッションには1バイトも書かない。

実行: python scripts/llm/test_context_guard.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "hooks"))
import context_guard as cg          # noqa: E402

PASS = 0
FAIL = 0
PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects",
                        "D--SougouStartFolder-5SecMovieMaker")


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL += 1
        print("  NG  %s" % name)


def transcript(prefix):
    """実物のtranscriptを1本選ぶ(先頭8桁で指定)。無ければ None。"""
    try:
        for fn in os.listdir(PROJECTS):
            if fn.startswith(prefix) and fn.endswith(".jsonl"):
                return os.path.join(PROJECTS, fn)
    except OSError:
        pass
    return None


def payload(sid, path):
    return {"session_id": sid, "transcript_path": path,
            "hook_event_name": "PostToolUse", "tool_name": "Bash"}


# --- 外へ出る手だけ一時フォルダへ(本番の台帳を汚さない) ---
tmp = tempfile.mkdtemp(prefix="ctxguard_")
cg.STATE = os.path.join(tmp, "state.json")
cg.LEDGER = os.path.join(tmp, "ledger.jsonl")

print("[1] 管理外で線を越えた実物のセッションでは鳴る")
# 研究室メイン(手動・実測 中央値486,209/最大933,992)。★relay管理外の代表。
lab = transcript("0351851c")
if not lab:
    print("  -- 見送り: 0351851c のtranscriptが無い(この機械では検証できない)")
else:
    msg, ctx, lv = cg.decide(payload("0351851c-a568-4b24-9f3f-91edba79103b", lab))
    check("警告が出る", bool(msg))
    check("文脈を実測できている(12万超)", ctx > 120000)
    check("交代の線を超えていれば rotate と判定する", lv in ("rotate", "compact"))
    check("★1M窓でも93万を待たない(=窓から線を導いていない)", ctx < 933_992 or lv == "rotate")
    check("台帳へ1行残る(鳴ったかを後から測れる)",
          os.path.exists(cg.LEDGER) and len(open(cg.LEDGER, encoding="utf-8").read().strip()) > 0)
    rec = json.loads(open(cg.LEDGER, encoding="utf-8").read().splitlines()[-1])
    check("台帳に線の値も残る(どの線で鳴ったか分かる)",
          rec.get("compact_at") == 120000 and rec.get("rotate_at") == 185000)

    print("[2] 同じセッションへ鳴らし続けない(間引き)")
    msg2, _c, _l = cg.decide(payload("0351851c-a568-4b24-9f3f-91edba79103b", lab))
    check("2回目は黙る", msg2 is None)
    check("★間引きの窓を過ぎたらまた鳴る",
          cg.decide(payload("0351851c-a568-4b24-9f3f-91edba79103b", lab),
                    now=__import__("time").time() + cg.WARN_EVERY_SEC + 1)[0] is not None)

print("[3] relayが世代管理している現行セッションでは黙る")
rooms = json.load(open(os.path.join(ROOT, "local", "llm", "room_sessions.json"), encoding="utf-8"))
cand = None
for room, v in rooms.items():
    sid = str((v or {}).get("active_session_id") or "")
    p = transcript(sid[:8]) if sid else None
    if p and cg.context_now(p) >= 120000:
        cand = (sid, p, room)
        break
if not cand:
    print("  -- 見送り: 現行のrelayセッションで12万を超えている物が今は無い")
else:
    sid, p, room = cand
    check("管理下(%s)では鳴らない" % room, cg.decide(payload(sid, p))[0] is None)
    check("★ただし文脈自体は測れている(黙るのは判定であって計測不能ではない)",
          cg.context_now(p) >= 120000)

print("[4] 線を越えていないセッションでは黙る")
small = None
try:
    for fn in sorted(os.listdir(PROJECTS)):
        if not fn.endswith(".jsonl"):
            continue
        p = os.path.join(PROJECTS, fn)
        c = cg.context_now(p)
        if 0 < c < 120000:
            small = (fn[:-6], p, c)
            break
except OSError:
    pass
if not small:
    print("  -- 見送り: 12万未満のtranscriptが見つからない")
else:
    sid, p, c = small
    check("12万未満(%s)では鳴らない" % f"{c:,}", cg.decide(payload(sid, p))[0] is None)

print("[5] ★変異検査= 線を天井まで上げたら鳴らない(①が本物の判定を見ている証明)")
if lab:
    keep = cg.lines
    cg.lines = lambda: (10_000_000, 20_000_000)
    cg.STATE = os.path.join(tmp, "state2.json")     # 間引きの影響を受けないようにする
    check("天井を上げると鳴らない", cg.decide(payload("mutant", lab))[0] is None)
    cg.lines = keep
    check("戻すとまた鳴る", cg.decide(payload("mutant", lab))[0] is not None)

print("[6] ★入口の見張り(SessionStart)= 越えてから鳴らすのでは遅い")
# 発注= 研究室HQ msg 1540697888538230886。
#   「越えた時にはもう畳む判断そのものが重い。窓が**開いた瞬間**なら文脈はまだ小さい」
#   実測の背景= 0ebedfa2(研究室メイン・手動)へ4時間10分で9回警告が出て、一度も畳まれなかった。
#   hookからも窓の中のセッション自身からも `/compact` は撃てない=**越えてからでは打つ手が無い**。
#
# ★ここで一番怖いのは①ではなく②だ= relayや常駐が開けた窓でも鳴ってしまうと、
#   **全部門の起動のたびに毎回鳴る警報**になる(共通規律§3「常に誤発火する安全網は無視される」)。
#   しかも relay が新セッションを作る時、room_sessions.json へ sid を書くのは**claudeが返った後**
#   (session_relay.py:4631 で戻り値から new_sid を取り、4683 の save_room で初めて載る)。
#   = 部門の1便目の SessionStart の時点では sid が台帳に**まだ無い**。
#   だから「台帳に載っているか」だけでは②を守れない。窓を**誰が開けたか**(親プロセス)を見る。
STARTS = os.path.join(tmp, "state_start.json")


def procs_for(parent_exe, extra_depth=0):
    """偽のプロセス表= hookのpython(100) → [bash…] → claude.exe(200) → parent_exe(300)。

    ★偽物にするのはプロセスの列挙(外の世界を覗く手)だけ。**親を辿る判定は本物のまま**通す。
    """
    t = {200: (300, "claude.exe"), 300: (400, parent_exe), 400: (0, "explorer.exe")}
    pid = 100
    for i in range(extra_depth):
        t[pid] = (pid + 1, "bash.exe")
        pid += 1
    t[pid] = (200, "python.exe")
    return t


def start(sid, parent_exe, procs=None, path=None):
    return cg.decide_start({"session_id": sid, "transcript_path": path or "",
                            "hook_event_name": "SessionStart", "source": "startup"},
                           procs=procs if procs is not None else procs_for(parent_exe),
                           my_pid=100)


cg.STATE = STARTS
cg.LEDGER = os.path.join(tmp, "ledger_start.jsonl")
# ★1 手で開いた窓(実測 2026-08-22 21:30= 生きている claude.exe 2本のうち、
#    手動の窓は親が cmd.exe、relayが開けた窓は親が python.exe だった)
msg1, why1 = start("manual-window-1", "cmd.exe")
check("★1 管理外の窓が開いたら出る(%s)" % why1, bool(msg1) and why1 == "warn")
check("★1 文面に『管理外』と畳み方が入っている",
      bool(msg1) and "管理外" in msg1 and "/compact" in msg1)

# ★2 relayが世代管理している現行セッション= 台帳に載っている側
if rooms:
    live = None
    for _room, v in rooms.items():
        s = str((v or {}).get("active_session_id") or "")
        if s:
            live = s
            break
    if live:
        m2, w2 = start(live, "cmd.exe")     # 親は手動に見せる=黙るのは台帳の枝だと分かる
        check("★2 relay管理下の窓では出ない(%s)" % w2, m2 is None and w2 == "managed")

# ★2' relayが**開けたばかり**の窓(台帳にはまだ載っていない)= 親が python
m3, w3 = start("brand-new-relay-session", "python.exe")
check("★2' 機械が開けた窓では出ない(台帳に載る前でも・%s)" % w3, m3 is None and w3 == "machine")
m3b, w3b = start("brand-new-relay-session-w", "pythonw.exe")
check("★2' pythonw(常駐)でも出ない", m3b is None and w3b == "machine")

# ★3 同じ窓で2回目(SessionStart は resume / clear / compact でも鳴る)
m4, w4 = start("manual-window-1", "cmd.exe")
check("★3 同じ窓の2回目は出ない(%s)" % w4, m4 is None and w4 == "seen")
m5, _w5 = start("manual-window-2", "cmd.exe")
check("★3 別の窓なら出る(間引きが窓ごとである証明)", bool(m5))

# 判定不能(プロセスが数えられない)は黙る
m6, w6 = start("manual-window-3", "cmd.exe", procs={})
check("プロセスが読めない時は黙る(%s)" % w6, m6 is None and w6 == "unknown")

check("台帳に1行残る(level=start)",
      os.path.exists(cg.LEDGER)
      and json.loads(open(cg.LEDGER, encoding="utf-8").read().splitlines()[-1]).get("level")
      == "start")

print("[7] ★変異検査= ②を守っている枝が本物か(片方だけ通ると『何も鳴らない見張り』になる)")
keep = cg.MACHINE_LAUNCHERS
try:
    cg.MACHINE_LAUNCHERS = ()
    cg.STATE = os.path.join(tmp, "state_mut.json")
    mm, _w = start("brand-new-relay-session-2", "python.exe")
    check("★変異: 機械の一覧を空にすると、機械が開けた窓まで鳴る(=②が落ちる)", bool(mm))
finally:
    cg.MACHINE_LAUNCHERS = keep
cg.STATE = os.path.join(tmp, "state_mut2.json")
mm2, w2m = start("brand-new-relay-session-3", "python.exe")
check("★変異の後始末: 一覧が元へ戻っている", mm2 is None and w2m == "machine")

cg.STATE = os.path.join(tmp, "state_mut3.json")      # 間引きの記憶を空にする
mm3, _w = start("manual-window-1", "cmd.exe")
check("★変異: 間引きの記憶を消すと同じ窓でまた鳴る(=③が記憶を本当に見ている)", bool(mm3))

print("[8] 配線= 実際にhookを**実行して**入口の見張りが鳴るところまで通す")
# ★ソースの文字列一致(`"decide_start" in src`)は検査ではない(共通規律§3)。
#   progress_mark.main() を本物のまま呼び、外へ出る手だけ偽物にする=
#     ① プロセスの列挙(手で開いた窓に見せる) ② react_mark の起動(Discordへ印を押しに行かせない)
#   ★payload の部屋(dept)はわざと解決できない物を渡す= **手で開いた窓は部門の部屋と対に
#     なっていない**。見張りが dept 解決より前に居ないと、狙った窓にだけ届かない。
import io                                                              # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "scripts", "hooks"))
import progress_mark as pm                                             # noqa: E402

cg.STATE = os.path.join(tmp, "state_wire.json")
cg.LEDGER = os.path.join(tmp, "ledger_wire.jsonl")
keep_launcher = cg.launcher_exe
keep_stdin, keep_stdout, keep_argv = sys.stdin, sys.stdout, sys.argv
ran = []
try:
    cg.launcher_exe = lambda procs=None, my_pid=None: "cmd.exe"
    pm.subprocess = type("F", (), {"run": staticmethod(lambda *a, **k: ran.append(a))})()
    wire_payload = {"session_id": "wire-manual-window", "transcript_path": "",
                    "cwd": os.path.join(tmp, "nowhere"),
                    "hook_event_name": "UserPromptSubmit", "prompt": "こんにちは"}
    sys.argv = ["progress_mark.py", "read"]
    sys.stdin = io.StringIO(json.dumps(wire_payload))
    sys.stdout = io.StringIO()
    pm.main()
    out = sys.stdout.getvalue()
finally:
    cg.launcher_exe = keep_launcher
    sys.stdin, sys.stdout, sys.argv = keep_stdin, keep_stdout, keep_argv
try:
    got = json.loads(out.strip().splitlines()[0]) if out.strip() else {}
except Exception:
    got = {}
check("hookが実際にJSONを1本出す", bool(got))
check("窓自身が読む側(additionalContext)に入っている",
      "管理外" in str((got.get("hookSpecificOutput") or {}).get("additionalContext") or ""))
check("端末のChamiにも見える(systemMessage)", "管理外" in str(got.get("systemMessage") or ""))
check("部屋が解決できない窓でも鳴る(=dept解決より前に居る)", bool(got))
check("印を押しに行っていない(検査がDiscordを触っていない証明)", not ran)

print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
