#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⑤ モデル切替の**採算の上限**(min_work_sec)の検査(イージス研究室 2026-08-25)。

★何を守る検査か= キャッシュはモデルごとなので、Opusの流れの中でSonnetへ寄り道すると
  前置きの全書き直しを2回払う(落ちる時=Sonnet価格 / 戻る時=**Opus価格**)。
  実測(直近24h・`local/_work/probe_model_flap_20260825.py`)= 寄り道12件のうち
  **赤字5件は全部37秒以下で終わった便**、黒字4件は65秒以上。→ 短い便は下げるほど高くつく。
  この検査は「短い便では下がらない / 元が取れる便では今までどおり下がる」を実行で通す。

★検査の作法(§3)= ソースの文字列一致では見ない。**判定と分岐は本物のまま**回し、
  外へ出る手(claude CLIの起動・本番台帳への書き込み)だけ偽物にする。
★C-054= 本番の `work_audit.jsonl` / `_model_override.json` は読みも書きもしない
  (両方とも使い捨てへ差し替える)。触っていないことは §F が測る。

    python tests/test_model_switch_cap.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import dept_daemon as dd            # noqa: E402
import session_relay as sr          # noqa: E402

ok = 0
ng = 0


def check(label, got, want):
    global ok, ng
    if got == want:
        ok += 1
        print("  PASS %-58s = %s" % (label, got))
    else:
        ng += 1
        print("  FAIL %-58s = %r (期待 %r)" % (label, got, want))


def stat(p):
    try:
        s = os.stat(p)
        return (True, s.st_size, round(s.st_mtime, 3))
    except OSError:
        return (False, -1, -1)


REAL = {
    "work_audit.jsonl": dd.WORK_AUDIT,
    "_model_override.json": os.path.join(ROOT, "local", "_model_override.json"),
    "room_sessions.json": sr.SESSIONS_FILE,
    "request_log.jsonl": sr.REQUEST_LOG,
}
BEFORE = {k: stat(v) for k, v in REAL.items()}     # ★差し替えの**前**に控える

TMP_OV = os.path.join(tempfile.gettempdir(), "go5_test_switchcap_override.json")
TMP_AUDIT = os.path.join(tempfile.gettempdir(), "go5_test_switchcap_audit.jsonl")
dd.MODEL_OVERRIDE_PATH = TMP_OV
dd.WORK_AUDIT = TMP_AUDIT

LONG = "シャビ・アロンソ(研究室HQ)"       # 過去の作業便が長い差出人(=元が取れる)
SHORT = "オーケストレーション(機構)"        # 自動催促。実測10〜37秒で終わる(=赤字)
NEW = "はじめての差出人"                   # 履歴なし


def write_audit(rows):
    with open(TMP_AUDIT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    dd._WORK_SEC_CACHE["mtime"] = None            # 同一秒の書き換えでも読み直させる


def row(dept, author, sec, **kw):
    d = {"ts": "2026-08-25T00:00:00", "dept": dept, "author": author, "sec": sec}
    d.update(kw)
    return d


def write_override(doc):
    with open(TMP_OV, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    dd._MODEL_OVERRIDE_CACHE["mtime"] = None


def rec(author=LONG, content="この常駐を直して", msg_id="TEST-CAP"):
    return {"author": author, "content": content, "msg_id": msg_id,
            "channel": "テスト部屋", "ts": "2026-08-25T00:00:00+00:00"}


BASE_AUDIT = ([row("system-engineer", LONG, 404.0), row("system-engineer", LONG, 523.0),
               row("system-engineer", LONG, 173.0)]
              + [row("system-engineer", SHORT, s) for s in (37.0, 10.0, 13.0)]
              + [row("platform-se", LONG, 300.0)] * 3
              + [row("hq", SHORT, 20.0)] * 3)
OV = {"enabled": True, "work": {"system-engineer": "sonnet", "platform-se": "sonnet",
                                "hq": "sonnet"}}
write_audit(BASE_AUDIT)
write_override(OV)

# ============================================================================
print("== A. 履歴の読み(work_audit.jsonl の末尾から (部屋,差出人) で拾う) ==")
check("長い差出人の秒数が拾える", sorted(dd._work_sec_history("system-engineer", LONG)),
      [173.0, 404.0, 523.0])
check("★部屋が違えば混ざらない", dd._work_sec_history("platform-se", SHORT), [])
check("★差出人が違えば混ざらない", sorted(dd._work_sec_history("system-engineer", SHORT)),
      [10.0, 13.0, 37.0])
check("履歴の無い差出人は空", dd._work_sec_history("system-engineer", NEW), [])
write_audit(BASE_AUDIT + [row("system-engineer", None, 999.0),
                          {"ts": "x", "dept": "system-engineer", "author": LONG}])
check("★author の無い古い行・sec の無い行は数えない",
      sorted(dd._work_sec_history("system-engineer", LONG)), [173.0, 404.0, 523.0])
write_audit(BASE_AUDIT + [row("system-engineer", LONG, float(n)) for n in range(1, 8)])
check("★見るのは直近n件だけ(既定5)", len(dd._work_sec_history("system-engineer", LONG)), 5)
check("★n件は『新しい方』から取る(古い長い便で誤魔化されない)",
      dd._work_sec_history("system-engineer", LONG), [3.0, 4.0, 5.0, 6.0, 7.0])
write_audit(BASE_AUDIT)

# ============================================================================
print("== B. 採算の判定 _switch_pays_off ==")
check("元が取れる差出人は通す", dd._switch_pays_off("system-engineer", LONG), (True, "ok"))
check("★短い便の差出人は止める", dd._switch_pays_off("system-engineer", SHORT),
      (False, "too_short"))
check("★履歴が無ければ止める(fail-quality)", dd._switch_pays_off("system-engineer", NEW),
      (False, "no_history"))
write_override(dict(OV, min_work_sec=0))
check("min_work_sec:0 で1行で無効化できる(8/23の挙動へ戻る)",
      dd._switch_pays_off("system-engineer", SHORT), (True, "ok"))
write_override(dict(OV, min_work_sec=600))
check("閾値を上げれば長い差出人も止まる(値が本当に読まれている)",
      dd._switch_pays_off("system-engineer", LONG), (False, "too_short"))
write_override(OV)
check("中央値で見る(1本だけ長くても通らない)",
      (write_audit(BASE_AUDIT + [row("platform-se", SHORT, s) for s in (5.0, 5.0, 900.0)])
       or dd._switch_pays_off("platform-se", SHORT)), (False, "too_short"))
write_audit(BASE_AUDIT)

# ============================================================================
print("== C. 述語 work_relay_decide(理由の1語まで) ==")
check("元が取れる作業便は今までどおり落ちる",
      dd.work_relay_decide(rec(), "system-engineer", True), ("sonnet", "ok"))
check("★短い便は落とさない=理由 too_short",
      dd.work_relay_decide(rec(author=SHORT), "system-engineer", True), (None, "too_short"))
check("★初めての差出人は落とさない=理由 no_history",
      dd.work_relay_decide(rec(author=NEW), "system-engineer", True), (None, "no_history"))
check("★守り(🔥)の方が先に効く(採算の判定より前)",
      dd.work_relay_decide(rec(content="🔥これ直して"), "system-engineer", True),
      (None, "marker"))
check("会話便は今までどおり not_work(採算の判定まで行かない)",
      dd.work_relay_decide(rec(), "system-engineer", False), (None, "not_work"))
check("★理由の語は台帳の語彙に載っている(載っていないと監査から消える)",
      all(w in dd._WORK_RELAY_REASONS for w in ("too_short", "no_history")), True)

# ============================================================================
print("== D. ★relay() が実際に claude へ渡すモデル名 ==")


def relay_model_used(dept, is_work, r):
    seen = {}
    keep = {k: getattr(sr, k) for k in
            ("_run_claude", "load_sessions", "save_sessions", "_record",
             "_work_snapshot", "_work_audit", "_join_maintenance")}

    def fake_run(prompt, token, session_id=None, model=None, timeout=None,
                 hard_timeout=None, on_soft=None, **kw):
        seen["model"] = model
        return ({"result": "テストの返事", "session_id": "test-sid"}, 0, "", 0.1)

    sr._run_claude = fake_run
    sr.load_sessions = lambda: {}
    sr.save_sessions = lambda table: None
    sr._record = lambda *a, **k: None
    sr._work_snapshot = lambda: {}
    sr._work_audit = lambda *a, **k: None
    sr._join_maintenance = lambda d, timeout=None: 0.0
    try:
        sr.relay(dept, r, dd.DEPT_CONF[dept], "TEST-TOKEN", is_work=is_work)
    except Exception as e:                        # noqa: BLE001
        seen.setdefault("error", "%s: %s" % (type(e).__name__, e))
    finally:
        for k, v in keep.items():
            setattr(sr, k, v)
    return seen.get("model") or seen.get("error")


BASE = sr.relay_model(dd.DEPT_CONF["system-engineer"])
print("  (上書き無しの既定 relay モデル= %s)" % BASE)
check("★元が取れる作業便は sonnet で回る", relay_model_used("system-engineer", True, rec()),
      "sonnet")
check("★短い便は既定(Opus)のまま回る",
      relay_model_used("system-engineer", True, rec(author=SHORT)), BASE)
check("★初めての差出人も既定のまま回る",
      relay_model_used("system-engineer", True, rec(author=NEW)), BASE)

# ============================================================================
print("== E. 台帳へ差出人が載る(=次の判定の材料が貯まる) ==")
os.remove(TMP_AUDIT)
dd._audit_work("system-engineer", "M1", {}, {}, 0, 12.3, "sonnet", "", "ok", LONG)
dd._audit_work("system-engineer", "M2", {}, {}, 0, 45.6, "claude-opus-5", "", "too_short",
               SHORT)
dd._audit_work("system-engineer", "M3", {}, {}, 0, 7.0, "claude-opus-5", "", None, None)
rows = [json.loads(x) for x in open(TMP_AUDIT, encoding="utf-8") if x.strip()]
check("落とした便に差出人が載る", rows[0].get("author"), LONG)
check("★落とさなかった便にも載る(=止めたまま再開できなくならない)", rows[1].get("author"), SHORT)
check("差出人が無ければ列自体を生やさない(古い行と混ざらない)", "author" in rows[2], False)
check("★理由 too_short が台帳に残る", rows[1].get("relay_reason"), "too_short")
dd._WORK_SEC_CACHE["mtime"] = None
check("★書いた行がそのまま次の履歴になる(往復で閉じている)",
      dd._work_sec_history("system-engineer", SHORT), [45.6])
write_audit(BASE_AUDIT)

# ============================================================================
print("== F. ★must-fail: 上限を『動く別の実装』へ戻すと C/D が落ちること(C-053) ==")
_orig_pays = dd._switch_pays_off
dd._switch_pays_off = lambda dept, author: (True, "ok")      # 旧仕様=採算を見ない
_m1 = dd.work_relay_decide(rec(author=SHORT), "system-engineer", True)
_m2 = relay_model_used("system-engineer", True, rec(author=SHORT))
dd._switch_pays_off = _orig_pays
check("★上限を外すと短い便が sonnet に落ちる(=この検査は実際に見ている)",
      (_m1, _m2), (("sonnet", "ok"), "sonnet"))
check("戻せば C は再び通る",
      dd.work_relay_decide(rec(author=SHORT), "system-engineer", True), (None, "too_short"))

_orig_hist = dd._work_sec_history
dd._work_sec_history = lambda dept, author, n=5: [    # 別実装=部屋ぜんぶを1つの履歴として見る
    float(r["sec"]) for r in BASE_AUDIT if r.get("dept") == dept]
_m3 = dd._switch_pays_off("system-engineer", SHORT)
dd._work_sec_history = _orig_hist
check("★差出人で割らない実装に戻すと、短い差出人が長い便の履歴に紛れて通る",
      _m3, (True, "ok"))
check("戻せば止まる", dd._switch_pays_off("system-engineer", SHORT), (False, "too_short"))

# ============================================================================
print("== G. ★C-054: 本番の台帳を1バイトも触っていない ==")
for k, v in REAL.items():
    check("本番の %s を触っていない" % k, stat(v) == BEFORE[k], True)

print("\n%s %d / FAIL %d" % ("PASS", ok, ng))
sys.exit(1 if ng else 0)
