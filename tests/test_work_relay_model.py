#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""②(work の上書き)が **relay の実行経路で本当に効くか** の検査(イージス研究室 2026-08-23)。

★なぜ別に要るのか= `tests/test_model_override.py` は **20/20 PASS していたのに、
  ②は1便も効いていなかった**(研究室HQ msg 1540971856662888560 の実測)。
  あの検査が見ていたのは `work_model_for()` という**読み口の中身**だけで、
  「その読み口が実行経路に居るか」は誰も見ていなかった。
  実際には 2026-07-26 の Chami指示で作業便も relay へ渡るようになり、
  DEPT_CONF 32室すべてが `session_relay=True`= **work agent 経路は0本**。
  読み口は正しく動くのに、誰も呼んでいなかった。**これは緑の嘘だ。**

★だからこの検査は「述語が正しいか」ではなく **「relay() が実際に使うモデルは何か」** を見る。
  外へ出る手(`_run_claude` = claude CLIの起動)だけ偽物にして**渡されたモデル名を捕まえる**。
  判定・分岐(is_work / 名簿 / Chami / 🔥 / 手1との優先順)は**全部本物**を通す。

★C-054= 本番の台帳(`room_sessions.json` / `request_log.jsonl` / `work_audit.jsonl`)は
  **1バイトも触らない**。差し替えは全部この検査の中の偽物へ向ける。触っていないことは §D が測る。

    python tests/test_work_relay_model.py
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
        print("  PASS %-62s = %s" % (label, got))
    else:
        ng += 1
        print("  FAIL %-62s = %r (期待 %r)" % (label, got, want))


TMP = os.path.join(tempfile.gettempdir(), "go5_test_work_relay_override.json")
dd.MODEL_OVERRIDE_PATH = TMP                        # ★本番の local/_model_override.json を触らない


def stat(p):
    """本番の台帳の「触られていなさ」を1つの値にする(存在しない場合も含む)。"""
    try:
        s = os.stat(p)
        return (True, s.st_size, round(s.st_mtime, 3))
    except OSError:
        return (False, -1, -1)


# ★C-054= 何かを回す**前に**本番の台帳の姿を控える。最後の §D で同じ値かを測る。
REAL = {
    "room_sessions.json": sr.SESSIONS_FILE,
    "request_log.jsonl": sr.REQUEST_LOG,
    "work_audit.jsonl": dd.WORK_AUDIT,
    "_model_override.json": os.path.join(ROOT, "local", "_model_override.json"),
}
BEFORE = {k: stat(v) for k, v in REAL.items()}

# ★★2026-08-25 ⑤(切替の採算・min_work_sec)が入ったので、この検査にも**履歴**が要る。
#   本番の `work_audit.jsonl` を読ませると結果が環境で変わる(=緑が偶然になる)ので、
#   台帳そのものを使い捨てへ差し替え、「元が取れる差出人」を1人だけ仕込む。
#   ★C-054= 本番の台帳は読みも書きもしない。上の BEFORE を取った**後**に差し替える。
TMP_AUDIT = os.path.join(tempfile.gettempdir(), "go5_test_work_audit.jsonl")
with open(TMP_AUDIT, "w", encoding="utf-8") as _f:
    for _d in ("platform-se", "aegis-gl", "hq", "system-engineer"):
        for _i in range(3):
            _f.write(json.dumps({"ts": "2026-08-25T00:00:00", "dept": _d,
                                 "author": "一ノ瀬怜", "sec": 300.0}) + "\n")
dd.WORK_AUDIT = TMP_AUDIT
dd._WORK_SEC_CACHE["mtime"] = None


def write_override(doc):
    with open(TMP, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    dd._MODEL_OVERRIDE_CACHE["mtime"] = None        # 同一秒の書き換えでも読み直させる


def clear_override():
    if os.path.exists(TMP):
        os.remove(TMP)
    dd._MODEL_OVERRIDE_CACHE["mtime"] = None


def rec(author="一ノ瀬怜", content="この常駐を直して", msg_id="TEST-1"):
    return {"author": author, "content": content, "msg_id": msg_id,
            "channel": "テスト部屋", "ts": "2026-08-23T16:00:00+00:00"}


# ============================================================================
print("== A. 述語 work_relay_model の真理値表(本物のJSONを実ファイルで読ませる) ==")
write_override({"enabled": True, "work": {"platform-se": "sonnet"}})

check("作業便 かつ 名指しの部屋 → 落とす",
      dd.work_relay_model(rec(), "platform-se", True), "sonnet")
check("★会話便(is_work=False)は落とさない= 人格の演技は Opus のまま(C-045)",
      dd.work_relay_model(rec(), "platform-se", False), None)
check("名簿に無い部屋は巻き添えにしない(C-035)",
      dd.work_relay_model(rec(), "aegis-gl", True), None)
check("★Chami本人の便は落とさない",
      dd.work_relay_model(rec(author="Chami"), "platform-se", True), None)
check("★🔥を含む便は落とさない(C-040)",
      dd.work_relay_model(rec(content="🔥これ直して"), "platform-se", True), None)
check("★『インシデント』を含む便は落とさない",
      dd.work_relay_model(rec(content="インシデントの対応をして"), "platform-se", True), None)
check("enabled:false で1行で全部戻る",
      (write_override({"enabled": False, "work": {"platform-se": "sonnet"}}) or
       dd.work_relay_model(rec(), "platform-se", True)), None)
clear_override()
check("上書きファイルが無ければ従来どおり(何も落ちない)",
      dd.work_relay_model(rec(), "platform-se", True), None)
check("recが壊れていても落とさない(判定不能=品質側へ倒す)",
      dd.work_relay_model(None, "platform-se", True), None)

# ============================================================================
print("== B. ★relay() が実際に claude へ渡すモデル名(=②が死んでいた所) ==")


def relay_model_used(dept, is_work, r, override):
    """外へ出る手だけ偽物にして relay() を1回通し、**渡されたモデル名**を返す。

    ★偽物にするのは「外へ出る/本番の台帳へ書く」手だけ。
      判定(is_work・名簿・Chami・🔥・手1との優先順)と分岐は本物を通る。
    """
    if override is None:
        clear_override()
    else:
        write_override(override)

    seen = {}
    keep = {k: getattr(sr, k) for k in
            ("_run_claude", "load_sessions", "save_sessions", "_record",
             "_work_snapshot", "_work_audit", "_join_maintenance")}

    def fake_run(prompt, token, session_id=None, model=None, timeout=None,
                 hard_timeout=None, on_soft=None, **kw):
        seen["model"] = model
        return ({"result": "テストの返事", "session_id": "test-sid"}, 0, "", 0.1)

    sr._run_claude = fake_run
    sr.load_sessions = lambda: {}                 # 常に「初回」= 本番の対応表を読まない
    sr.save_sessions = lambda table: None         # ★本番の room_sessions.json へ書かない
    sr._record = lambda *a, **k: None             # ★本番の request_log.jsonl へ書かない
    sr._work_snapshot = lambda: {}                # git walk を回さない
    sr._work_audit = lambda *a, **k: None         # ★本番の work_audit.jsonl へ書かない
    sr._join_maintenance = lambda d, timeout=None: 0.0
    try:
        sr.relay(dept, r, dd.DEPT_CONF[dept], "TEST-TOKEN", is_work=is_work)
    except Exception as e:                        # noqa: BLE001
        seen.setdefault("error", "%s: %s" % (type(e).__name__, e))
    finally:
        for k, v in keep.items():
            setattr(sr, k, v)
    return seen.get("model") or seen.get("error")


BASE = sr.relay_model(dd.DEPT_CONF["platform-se"])
print("  (上書き無しの既定 relay モデル= %s)" % BASE)

check("★作業便+名指し → relayが渡すモデルが sonnet になる",
      relay_model_used("platform-se", True, rec(),
                       {"enabled": True, "work": {"platform-se": "sonnet"}}), "sonnet")
check("★同じ部屋でも会話便は既定のまま(会話を安くしない)",
      relay_model_used("platform-se", False, rec(),
                       {"enabled": True, "work": {"platform-se": "sonnet"}}), BASE)
check("Chamiの作業便は既定のまま",
      relay_model_used("platform-se", True, rec(author="Chami"),
                       {"enabled": True, "work": {"platform-se": "sonnet"}}), BASE)
check("名簿に無い部屋の作業便は既定のまま",
      relay_model_used("aegis-gl", True, rec(), {"enabled": True, "work": {"platform-se": "sonnet"}}),
      sr.relay_model(dd.DEPT_CONF["aegis-gl"]))
check("上書きが無ければ既定のまま(=入れる前と1文字も変わらない)",
      relay_model_used("platform-se", True, rec(), None), BASE)

# ============================================================================
print("== C. ★must-fail: 足した配線だけを『動く別の実装』へ戻すと B が落ちること(C-053) ==")
# ★2026-08-23 変異させる先を `work_relay_decide` へ移した(イージス研究室)。
#   理由= 呼び口(session_relay)が decide を呼ぶ形に変わったので、`work_relay_model` を
#   差し替えても**もう噛まない**= 変異させても緑のまま通る「空PASS」になっていた。
#   ★実際にこの検査が1回落ちて教えてくれた(FAIL 1)。変異の先は**呼ばれている物**でなければ
#     ならない、という当たり前を、道具の側が守らせた形だ。
_orig = dd.work_relay_decide
dd.work_relay_decide = lambda rec_, dept_, is_work_: (None, "not_work")   # ← 旧仕様=常に落とさない
mutant = relay_model_used("platform-se", True, rec(),
                          {"enabled": True, "work": {"platform-se": "sonnet"}})
dd.work_relay_decide = _orig
check("旧仕様(配線なし)では sonnet に**ならない**= この検査は実際に見ている", mutant != "sonnet", True)
check("配線を戻せば B は再び通る",
      relay_model_used("platform-se", True, rec(),
                       {"enabled": True, "work": {"platform-se": "sonnet"}}), "sonnet")

# ============================================================================
# ★2026-08-23 研究室HQ発注(msg DISPATCH-aegis-gl-1787469264964)。
#   「None が全部同じ沈黙で『配線が死んでいる』と『守りが食った』が区別できない」への答え。
#   ★理由の語が**取り違えられていない**ことを見る= 語が全部同じなら足した意味が無い。
print("== E. ★落とさなかった理由の1語(8/24の判定を『0か4〜6割か』で切り分ける物) ==")
write_override({"enabled": True, "work": {"platform-se": "sonnet"}})
check("落とした時は ok", dd.work_relay_decide(rec(), "platform-se", True), ("sonnet", "ok"))
check("会話便は not_work", dd.work_relay_decide(rec(), "platform-se", False), (None, "not_work"))
check("名簿に無い部屋は not_listed",
      dd.work_relay_decide(rec(), "aegis-gl", True), (None, "not_listed"))
check("Chami本人の便は chami",
      dd.work_relay_decide(rec(author="Chami"), "platform-se", True), (None, "chami"))
check("🔥を含む便は marker",
      dd.work_relay_decide(rec(content="🔥これ直して"), "platform-se", True), (None, "marker"))
check("★理由の語が全部違う(=どれか1つに潰れていない)",
      len({dd.work_relay_decide(rec(), "platform-se", True)[1],
           dd.work_relay_decide(rec(), "platform-se", False)[1],
           dd.work_relay_decide(rec(), "aegis-gl", True)[1],
           dd.work_relay_decide(rec(author="Chami"), "platform-se", True)[1],
           dd.work_relay_decide(rec(content="🔥直して"), "platform-se", True)[1]}), 5)
check("★モデル名だけを返す旧い呼び口は1文字も変わっていない(既存の呼び出し元を壊さない)",
      dd.work_relay_model(rec(), "platform-se", True), "sonnet")

# ★台帳へ実際に語が載るか= 本番の work_audit.jsonl は触らず、書き先だけ写しへ向ける(C-054)。
_audit_tmp = os.path.join(tempfile.gettempdir(), "go5_test_work_audit.jsonl")
if os.path.exists(_audit_tmp):
    os.remove(_audit_tmp)
_real_audit = dd.WORK_AUDIT
dd.WORK_AUDIT = _audit_tmp
dd._audit_work("platform-se", "TEST-9", {}, {}, 0, 1.0, "sonnet", "", "marker")
dd._audit_work("platform-se", "TEST-8", {}, {}, 0, 1.0, "sonnet", "", None)
dd._audit_work("platform-se", "TEST-7", {}, {}, 0, 1.0, "sonnet", "", "でっちあげ")
dd.WORK_AUDIT = _real_audit
_rows = [json.loads(l) for l in open(_audit_tmp, encoding="utf-8") if l.strip()]
check("台帳の行に理由が載る", _rows[0].get("relay_reason"), "marker")
check("★渡さなければ今までと同じ行(キー自体が生えない=古い行と混ざらない)",
      "relay_reason" in _rows[1], False)
check("★知らない語は書かない(語彙は _WORK_RELAY_REASONS の6語だけ)",
      "relay_reason" in _rows[2], False)
os.remove(_audit_tmp)
clear_override()

# ============================================================================
print("== D. ★C-054: この検査は本番の台帳を1バイトも触っていない ==")
clear_override()
for name, path in REAL.items():
    check("本番の %s を触っていない" % name, stat(path) == BEFORE[name], True)
print()
print("PASS %d / FAIL %d" % (ok, ng))
sys.exit(1 if ng else 0)
