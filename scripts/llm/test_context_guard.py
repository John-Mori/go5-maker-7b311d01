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

print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
