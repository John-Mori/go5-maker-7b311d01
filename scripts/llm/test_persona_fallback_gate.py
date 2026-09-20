# -*- coding: utf-8 -*-
"""must-fail 検査= 出力ゲートF-3(名義が既定へ落ちた便の検知)。

見張っているもの(2026-09-20 研究室HQの名義事故・msg 1551160925845721130):
  1行目の `[シャビ・アロンソ]` がコード柵の中にあった/名乗り行が落ちた便は、
  `split_persona_blocks` が `[(None, 本文)]` を返し、名義は `DEPT_CONF['hq']['persona']`
  = **アメス**へ黙って落ちる。落ちたこと自体がどのログにも残らず、さらに口調ゲートが
  「話者はアメス」と信じて **俺→あたし** を書き換えた(実測 tone_fix 18:20:42 / tone_rewrite 18:20:47)。

  → F-3= 「名乗りが無い(=既定へ落ちた)」+「本文の一人称は別人格のもの」を同時に見たら
     **1行残して、呼称/口調の書き直しだけを止める**。名義も本文も動かさない。便は止めない。

★§3 の作法どおり、**外へ出る手だけ**を偽物にする(判定と分岐は本物を実行で通す):
    - `log` / `TONE_AUDIT` / `PROCESSED` / `LOCAL`(返信の下書き置き場) … 一時ディレクトリへ逃がす
    - `subprocess.run`            … Discordへ撃つ口(persona_send/react)。argv と本文だけ捕まえる
    - `session_relay.relay`       … 生きたClaudeセッション。事故当時の本文をそのまま返す
    - `session_relay._record` / `verify_replied` / `memory_append` / 台帳系 … 記録だけして書かない
  **`Daemon.handle()` は本物をそのまま呼ぶ**= 配線(F-2 の空振り→F-3→ゲートC/Dの抑止)を
  実行で通す。「入れたが呼ばれていない」を潰すのがこの層の目的。

★本文は打ち込まない。`local/llm/tone_audit.jsonl` の 2026-09-20T18:20:42 tone_fix 行の
  `excerpt`(=**書き直される前の実物**の先頭200字)を引く(§1)。

使い方:
    python scripts/llm/test_persona_fallback_gate.py            # 本物 → 全部 PASS
    python scripts/llm/test_persona_fallback_gate.py --mutant   # 変異体1 → **赤くなるはず**
    python scripts/llm/test_persona_fallback_gate.py --mutant 2 # 変異体2 → **赤くなるはず**

変異体= 1: F-3 が名義の矛盾を見ない(contradicted を常に空)= 直す前の姿
        2: `tone_gate.misattributed_speaker` を常に None にする(判定器を殺す)
これで赤くならない検査は、何も見張っていない(C-053)。
"""
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

MUTANT = 0
if "--mutant" in sys.argv:
    _i = sys.argv.index("--mutant")
    MUTANT = 1
    if len(sys.argv) > _i + 1 and sys.argv[_i + 1].isdigit():
        MUTANT = int(sys.argv[_i + 1])

TMPDIR = tempfile.mkdtemp(prefix="f3_mustfail_")
TMP_AUDIT = os.path.join(TMPDIR, "tone_audit.jsonl")

import tone_gate          # noqa: E402
import dept_daemon        # noqa: E402

DEPT = "hq"
CONF = dept_daemon.DEPT_CONF[DEPT]
ROSTER = [p["persona"] for p in CONF["personas"]]        # ['シャビ・アロンソ', 'アメス']
FALLBACK = CONF["persona"]                               # 'アメス'(既定=落ちる先)
OTHER = "シャビ・アロンソ"
INCIDENT_LETTER = "1551160925845721130"                  # 事故便(着信)のmsg_id
CHANNEL = "🏛研究室hq-コーチングルーム-アロンソ•アメス"

# --- 事故の実物を引く(打ち込まない) ------------------------------------------
TONE_AUDIT_REAL = os.path.join(ROOT, "local", "llm", "tone_audit.jsonl")


def load_rewrite_result():
    """2026-09-20T18:20:47 の tone_rewrite 行= **事故当時のLLM書き直しの実物**。

    D-2(LLMへの往復)も外へ出る手なので偽物にする。中身は打ち込まず、この実測行から作る=
    変異体が本物と同じ出力(「…すまんわね。」)を出す。
    """
    d = None
    for line in io.open(TONE_AUDIT_REAL, encoding="utf-8", errors="replace"):
        if INCIDENT_LETTER not in line or '"tone_rewrite"' not in line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("ts") == "2026-09-20T18:20:47" and o.get("event") == "tone_rewrite":
            d = o
    if not d:
        return None
    return {"attempted": True, "ok": bool(d.get("ok")), "targets": d.get("targets") or [],
            "after": d.get("after") or [], "why": d.get("why") or "",
            "elapsed_ms": d.get("elapsed_ms", 0), "text": d.get("excerpt_after") or ""}


def load_pregate_body():
    """2026-09-20T18:20:42 の tone_fix 行= **書き直される前**の本文(先頭200字)。"""
    body = None
    for line in io.open(TONE_AUDIT_REAL, encoding="utf-8", errors="replace"):
        if INCIDENT_LETTER not in line or '"tone_fix"' not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("ts") == "2026-09-20T18:20:42" and d.get("event") == "tone_fix":
            body = d.get("excerpt")
    return body


BODY = load_pregate_body()

OK = [0]
NG = [0]


def check(name, cond):
    print(("  PASS: " if cond else "  FAIL: ") + name)
    OK[0] += 1 if cond else 0
    NG[0] += 0 if cond else 1


if not BODY:
    print("  SKIP: 事故当時の本文が tone_audit.jsonl に無い(推測で代用しない=§1)")
    sys.exit(0)

# --- 外へ出る手だけ偽物にする --------------------------------------------------
_LOGGED = []
dept_daemon.log = lambda dept, msg, *a, **k: _LOGGED.append(str(msg))
dept_daemon.TONE_AUDIT = TMP_AUDIT
dept_daemon.PROCESSED = os.path.join(TMPDIR, "processed.jsonl")
dept_daemon.LOCAL = TMPDIR               # 返信の下書き `_daemon_reply_hq.txt` の置き場
# D-2(LLMへの1往復)も外へ出る手= 事故当時の実測行から作った答えを返す(APIを叩かない)
_REWRITE_REAL = load_rewrite_result()
if getattr(dept_daemon, "_tone_rewrite", None) is not None:
    dept_daemon._tone_rewrite.rewrite_once = (lambda *a, **k: dict(_REWRITE_REAL or {}))


def audit_lines():
    if not os.path.exists(TMP_AUDIT):
        return []
    out = []
    for line in io.open(TMP_AUDIT, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def reset_audit():
    _LOGGED[:] = []
    if os.path.exists(TMP_AUDIT):
        os.remove(TMP_AUDIT)


# --- 変異体= 直しを外す --------------------------------------------------------
if MUTANT == 1:
    _real_f3 = dept_daemon.audit_persona_fallback

    def _blind_f3(dept, persona, text, roster, rec=None):
        r = _real_f3(dept, persona, text, roster, rec)
        return {"fell_back": bool(r.get("fell_back")), "contradicted": ""}
    dept_daemon.audit_persona_fallback = _blind_f3
elif MUTANT == 2:
    tone_gate.misattributed_speaker = lambda *a, **k: None

# =============================================================================
# 層1= 判定(F-2が空振りし、F-3が「既定へ落ちた+本文は別人格」を捕まえる)
# =============================================================================
print("-- 層1= 判定: 事故当時の本文(tone_audit 18:20:42 の実物)")
reset_audit()
_blocks = dept_daemon.split_persona_blocks(BODY, CONF)
check("名乗りが引けない= ブロックの話者は None(=既定へ落ちる) 実測=%r"
      % ([w for w, _ in _blocks],), [w for w, _ in _blocks] == [None])
check("F-2(本文中の名乗り)は空振りする",
      dept_daemon.audit_self_named(DEPT, FALLBACK, BODY, ROSTER,
                                   {"msg_id": INCIDENT_LETTER}) is None)
_fb = dept_daemon.audit_persona_fallback(DEPT, FALLBACK, BODY, ROSTER,
                                         {"msg_id": INCIDENT_LETTER})
check("F-3= 既定へ落ちたことを掴む(fell_back) 実測=%r" % (_fb,), bool(_fb.get("fell_back")))
check("F-3= 本文が指す別人格を %s と読む 実測=%r" % (OTHER, _fb.get("contradicted")),
      _fb.get("contradicted") == OTHER)
_lines = audit_lines()
check("tone_audit へ1行だけ残す 実測=%d行" % len(_lines), len(_lines) == 1)
check("理由= speaker_contradicts_fallback / 既定=%s / 指す先=%s" % (FALLBACK, OTHER),
      bool(_lines) and _lines[0].get("reason") == "speaker_contradicts_fallback"
      and _lines[0].get("persona") == FALLBACK and _lines[0].get("to") == OTHER)
check("ログにも1行残る", any("F-3" in m for m in _LOGGED))

# --- (A)の側= 矛盾が無くても「既定へ落ちた」こと自体は1行残す --------------------
# 実物= 同じ事故の連投2通目(msg 1551161203479420941・send_audit.jsonl)。名乗り行は無く、
# 本文はアメス自身の声(別人格の一人称が無い)= 書き直しを止める理由は無いが、
# **名義が既定へ落ちた事実**はどこにも残っていなかった。そこを埋めるのがこの1行。
SEND_AUDIT = os.path.join(ROOT, "local", "llm", "send_audit.jsonl")


def load_sent_body(msg_id):
    body = None
    for line in io.open(SEND_AUDIT, encoding="utf-8", errors="replace"):
        if msg_id not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if str(d.get("msg_id")) == msg_id:
            body = d.get("body")
    return body


_PLAIN = load_sent_body("1551161203479420941")
if not _PLAIN:
    print("  SKIP: 連投2通目の実物が send_audit.jsonl に無い(推測で代用しない=§1)")
else:
    print("-- 層1b= 矛盾なしで既定へ落ちた便(同じ事故の連投2通目の実物)")
    reset_audit()
    _fb2 = dept_daemon.audit_persona_fallback(DEPT, FALLBACK, _PLAIN, ROSTER,
                                              {"msg_id": INCIDENT_LETTER})
    _l2 = audit_lines()
    check("落ちたことは掴むが、書き直しは止めない 実測=%r" % (_fb2,),
          _fb2.get("fell_back") and not _fb2.get("contradicted"))
    check("理由= persona_fallback_default で1行残る 実測=%r"
          % ([e.get("reason") for e in _l2],),
          len(_l2) == 1 and _l2[0].get("reason") == "persona_fallback_default")

# 単独人格の部屋(roster1人)は既定名義が正常= 1バイトも触らない
reset_audit()
_solo = dept_daemon.audit_persona_fallback(DEPT, FALLBACK, BODY, [FALLBACK],
                                           {"msg_id": INCIDENT_LETTER})
check("単独人格の部屋では何もしない(誤発火しない) 実測=%r" % (_solo,),
      not _solo.get("fell_back") and not _solo.get("contradicted")
      and not _LOGGED and not audit_lines())

# =============================================================================
# 層2= 対比(止めなければ何が起きるか。事故の再現)
# =============================================================================
print("-- 層2= 対比: F-3が止めなかった場合(=事故当時の挙動)")
reset_audit()
_after, _fixes, _remain = dept_daemon.audit_tone(DEPT, FALLBACK, BODY,
                                                 {"msg_id": INCIDENT_LETTER})
check("ゲートD単体なら本文を書き換えてしまう(俺→あたし) 実測=%r"
      % ([(f.get("marker"), f.get("to"), f.get("count")) for f in _fixes],),
      _after != BODY and any(f.get("marker") == "俺" for f in _fixes))
check("さらに signature_absent が残る= D-2(LLM書き直し)の点火条件が立つ",
      any(r.get("reason") == "signature_absent" for r in _remain))

# =============================================================================
# 層3= 実走(Daemon.handle を本物のまま通し、配線が効くことを見る)
# =============================================================================
print("-- 層3= 実走: 壊れた実物と同じ場面を handle() へ1回通す(外へは撃たない)")


class _R(object):
    returncode = 0
    stdout = ""
    stderr = ""


_SENT = []


def _fake_run(argv, *a, **k):
    argv = list(argv)
    rec = {"argv": argv, "body": ""}
    if "--body-file" in argv:
        p = argv[argv.index("--body-file") + 1]
        try:
            rec["body"] = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            pass
    _SENT.append(rec)
    return _R()


dept_daemon.subprocess.run = _fake_run
dept_daemon.verify_replied = lambda *a, **k: (True, "検査=実在確認は偽物")
dept_daemon.session_relay._record = lambda *a, **k: None
dept_daemon.session_relay.relay = lambda *a, **k: (BODY, True)
dept_daemon._record_loaded_roster = lambda *a, **k: None
dept_daemon.Daemon.memory_append = lambda self, rec, reply: None
dept_daemon.Daemon.memory_note_unanswered = lambda self, rec, why="": None
dept_daemon.Daemon._coalesce_after_run = lambda self, rec, mid, reply: reply
dept_daemon.Daemon._start_live_mark = lambda self, rec: None
dept_daemon.Daemon.owner_of_room = lambda self: "relay"
dept_daemon.Daemon._stack_from_letter = lambda self, *a, **k: None
dept_daemon.Daemon._note_waiting = lambda self, *a, **k: None

# 本番の台帳へ1バイトも書いていないことを、実測で確かめる(印の控え)
_GUARD = [os.path.join(ROOT, "local", "llm", "tone_audit.jsonl"),
          os.path.join(ROOT, "local", "llm", "send_audit.jsonl"),
          os.path.join(ROOT, "local", "llm", "request_log.jsonl"),
          os.path.join(ROOT, "local", "_daemon_reply_hq.txt"),
          os.path.join(ROOT, "local", "queue", "inbox.db")]
_BEFORE = {p: (os.path.getmtime(p), os.path.getsize(p))
           for p in _GUARD if os.path.exists(p)}

reset_audit()
REC = {"channel": CHANNEL, "msg_id": INCIDENT_LETTER, "author": "Chami",
       "content": "インシデントです"}
_ok = dept_daemon.Daemon(DEPT).handle(REC, json.dumps(REC, ensure_ascii=False))

_persona_sends = [s for s in _SENT if "--persona" in s["argv"]]
check("便は止めずに1通出る(沈黙させない) 実測=%d通 / handle=%r" % (len(_persona_sends), _ok),
      len(_persona_sends) == 1)
_sent_body = _persona_sends[0]["body"] if _persona_sends else ""
_sent_persona = (_persona_sends[0]["argv"][_persona_sends[0]["argv"].index("--persona") + 1]
                 if _persona_sends else "")
check("本文を1文字も書き換えていない(俺のまま) 実測=%r" % (_sent_body[:24],),
      _sent_body.startswith(BODY[:40]) and "あたしのミス" not in _sent_body)
check("名義は推測で動かさない= 既定の %s のまま出る 実測=%r" % (FALLBACK, _sent_persona),
      _sent_persona == FALLBACK)
_ev = audit_lines()
check("書き直しの記録(tone_fix/tone_rewrite)が1行も無い 実測=%r"
      % ([e.get("event") for e in _ev],),
      not [e for e in _ev if e.get("event") in ("tone_fix", "tone_rewrite")])
check("F-3の1行が実走でも残る(=配線が呼ばれている)",
      any(e.get("reason") == "speaker_contradicts_fallback" for e in _ev))

_AFTER = {p: (os.path.getmtime(p), os.path.getsize(p))
          for p in _GUARD if os.path.exists(p)}
check("本番の台帳・下書き・キューへ1バイトも書いていない", _BEFORE == _AFTER)

# =============================================================================
# 層4= 突き返しの言葉(次の封筒へ日本語で出る。英語のまま漏らさない)
# =============================================================================
print("-- 層4= 突き返しの理由ラベル(session_relay)")
import session_relay as _sr            # noqa: E402
_JA = getattr(_sr, "_TONE_REASON_JA", {})
for _reason in ("persona_fallback_default", "speaker_contradicts_fallback"):
    check("%s に日本語の説明がある(英語のまま封筒へ出さない)" % _reason,
          bool(str(_JA.get(_reason) or "").strip()))

print("")
print("== %s ==  PASS=%d FAIL=%d%s"
      % ("緑" if not NG[0] else "★赤", OK[0], NG[0],
         ("  (変異体%d)" % MUTANT) if MUTANT else ""))
sys.exit(1 if NG[0] else 0)
