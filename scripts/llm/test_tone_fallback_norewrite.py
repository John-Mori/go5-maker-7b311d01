# -*- coding: utf-8 -*-
"""must-fail 検査= 既定人格へ落ちた便に **D-2(tone_rewrite)を乗せない**(2026-09-20 改悪の恒久)。

0歩目の実物(Chami改悪スタンプ msg 1551217685986017425・指した実物 msg 1551214483240656967):
  copy-director(台本及び訴求創造)で、三笘薫の作業報告が **早坂芽衣[webhook]の名義**で出た上に、
  語尾が全文「検算OKなんだ！！」「直したよ〜」「💕」へ機械的に上塗りされた。
  実測(tone_audit.jsonl / msg 1551212546915172415)=
    21:52:28 persona_fallback_default(persona=早坂芽衣・other_names={})  ← F-3は掴んでいた
    21:52:28 signature_absent(芽衣の指紋語尾が0件)
    21:52:32 tone_rewrite ok=true (D-2が芽衣語尾で書き直した)
  F-3は「本文の一人称が別人格のものなら止める」しか見ていなかった。この便は一人称そのものが
  無い= `contradicted` が空=**素通り**し、既定人格の写像で本文が洗われた。

  → 直し= 止める条件を **fell_back(名義が既定へ落ちた便すべて)** へ広げる
     (`dept_daemon.tone_rewrite_blocked`)。名義も本文も動かさない・便は止めない。

★§3の作法= **外へ出る手だけ**偽物にする。判定・分岐・配線は本物を実行で通す
  (`Daemon.handle()` を本物のまま1回通す=「入れたが呼ばれていない」を潰す層)。
★本文は打ち込まない= tone_audit.jsonl の実測行(excerpt/excerpt_after)から引く(§1)。

使い方:
    python scripts/llm/test_tone_fallback_norewrite.py             # 本物 → 全部 PASS
    python scripts/llm/test_tone_fallback_norewrite.py --mutant old     # 直す前の条件 → 赤
    python scripts/llm/test_tone_fallback_norewrite.py --mutant blind   # F-3を殺す     → 赤
    python scripts/llm/test_tone_fallback_norewrite.py --mutant notag   # 解決器を渡さない → 赤
"""
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

MUTANT = ""
if "--mutant" in sys.argv:
    _i = sys.argv.index("--mutant")
    MUTANT = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else "old"

TMPDIR = tempfile.mkdtemp(prefix="f3_fallback_norewrite_")
TMP_AUDIT = os.path.join(TMPDIR, "tone_audit.jsonl")

import dept_daemon        # noqa: E402

DEPT = "copy-director"
CONF = dept_daemon.DEPT_CONF[DEPT]
ROSTER = [p["persona"] for p in CONF["personas"]]        # ['早坂芽衣', '三笘薫']
FALLBACK = CONF["persona"]                               # '早坂芽衣'(既定=落ちる先)
OTHER = "三笘薫"
INCIDENT = "1551212546915172415"                         # 壊れた便(着信)のmsg_id
CHANNEL = "台本及び訴求創造-三笘さん•芽衣"                 # local/discord_channels.json 実測
TONE_AUDIT_REAL = os.path.join(ROOT, "local", "llm", "tone_audit.jsonl")

OK = [0]
NG = [0]


def check(name, cond):
    print(("  PASS: " if cond else "  FAIL: ") + name)
    OK[0] += 1 if cond else 0
    NG[0] += 0 if cond else 1


def real_rows():
    out = []
    for line in io.open(TONE_AUDIT_REAL, encoding="utf-8", errors="replace"):
        if INCIDENT not in line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


_REAL = real_rows()
_RW_ROW = [r for r in _REAL if r.get("event") == "tone_rewrite"]
BODY = (_RW_ROW[-1].get("excerpt") if _RW_ROW else "")        # 書き直される**前**の実物
AFTER = (_RW_ROW[-1].get("excerpt_after") if _RW_ROW else "")  # 芽衣語尾で塗られた**後**

if not BODY or not AFTER:
    print("  SKIP: 壊れた実物が tone_audit.jsonl に無い(推測で代用しない=§1)")
    sys.exit(0)

# --- 外へ出る手だけ偽物にする --------------------------------------------------
_LOGGED = []
dept_daemon.log = lambda dept, msg, *a, **k: _LOGGED.append(str(msg))
dept_daemon.TONE_AUDIT = TMP_AUDIT
dept_daemon.PROCESSED = os.path.join(TMPDIR, "processed.jsonl")
dept_daemon.LOCAL = TMPDIR               # 返信の下書き `_daemon_reply_copy-director.txt` の置き場

# D-2(LLMへの1往復)= 当日の実測行から作った答えを返す(APIを叩かない)。
#   ★止まっていなければ**この本文が出てしまう**= 事故の再現がそのまま変異体の赤になる。
_REWRITE_REAL = {"attempted": True, "ok": bool((_RW_ROW[-1] or {}).get("ok")),
                 "targets": (_RW_ROW[-1] or {}).get("targets") or [],
                 "after": (_RW_ROW[-1] or {}).get("after") or [],
                 "why": (_RW_ROW[-1] or {}).get("why") or "",
                 "elapsed_ms": (_RW_ROW[-1] or {}).get("elapsed_ms", 0),
                 "text": AFTER}
if getattr(dept_daemon, "_tone_rewrite", None) is not None:
    dept_daemon._tone_rewrite.rewrite_once = (lambda *a, **k: dict(_REWRITE_REAL))
if getattr(dept_daemon, "_liveblog", None) is not None:
    # ゲートG(実況漏れの包み直し)もLLMへ1往復する口= 外へ出させない(包み直しは不採用で返す)。
    dept_daemon._liveblog.wrap_once = (lambda *a, **k: {"attempted": True, "ok": False,
                                                        "why": "検査=外へ出さない", "text": ""})


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


# --- 変異体= 直しを外す(動く別実装へ変える。C-053) ------------------------------
if MUTANT == "old":
    # 2026-09-20 22時台より前の条件= 「別人格の一人称が在る時だけ止める」
    dept_daemon.tone_rewrite_blocked = lambda fb: bool((fb or {}).get("contradicted"))
elif MUTANT == "blind":
    dept_daemon.audit_persona_fallback = (lambda *a, **k: {"fell_back": False,
                                                           "contradicted": "", "tag_names": {}})
elif MUTANT == "notag":
    _real_f3 = dept_daemon.audit_persona_fallback
    dept_daemon.audit_persona_fallback = (
        lambda dept, persona, text, roster, rec=None, resolve=None:
        _real_f3(dept, persona, text, roster, rec))       # 解決器を渡し忘れた姿
elif MUTANT:
    print("未知の変異体: " + MUTANT)
    sys.exit(2)
if MUTANT:
    print("★変異体 '%s' で同じ検査を流す(赤になるのが正しい)" % MUTANT)

# =============================================================================
# 層1= 判定(なぜ旧条件が素通りしたのか、を実測で固定する)
# =============================================================================
print("-- 層1= 判定: 壊れた実物(tone_audit 21:52:32 の書き直し前の本文)")
reset_audit()
_blocks = dept_daemon.split_persona_blocks(
    BODY, (lambda nm: dept_daemon.resolve_persona_tag(CONF, nm)), dept=DEPT, names=ROSTER)
check("1行目に名乗りが無い= ブロックの話者は None(既定の%s へ落ちる) 実測=%r"
      % (FALLBACK, [w for w, _ in _blocks]), [w for w, _ in _blocks] == [None])
check("F-2(本文中の名乗り)は空振りする",
      dept_daemon.audit_self_named(DEPT, FALLBACK, BODY, ROSTER, {"msg_id": INCIDENT}) is None)
_fb = dept_daemon.audit_persona_fallback(
    DEPT, FALLBACK, BODY, ROSTER, {"msg_id": INCIDENT},
    resolve=(lambda nm: dept_daemon.resolve_persona_tag(CONF, nm)))
check("F-3= 既定へ落ちたことを掴む(fell_back) 実測=%r" % (_fb.get("fell_back"),),
      bool(_fb.get("fell_back")))
check("★この便には別人格の一人称が無い= contradicted は空(=旧条件なら素通りした) 実測=%r"
      % (_fb.get("contradicted"),), not _fb.get("contradicted"))
check("★決定= 書き直しを止める(tone_rewrite_blocked) 実測=%r"
      % (dept_daemon.tone_rewrite_blocked(_fb),), dept_daemon.tone_rewrite_blocked(_fb) is True)
check("本文の `[三笘]` を %s として数える(名義は動かさない) 実測=%r" % (OTHER, _fb.get("tag_names")),
      (_fb.get("tag_names") or {}).get(OTHER, 0) >= 1)
_lines = audit_lines()
check("tone_audit へ1行だけ残す 実測=%d行" % len(_lines), len(_lines) == 1)
check("理由= persona_fallback_default / 既定=%s" % FALLBACK,
      bool(_lines) and _lines[0].get("reason") == "persona_fallback_default"
      and _lines[0].get("persona") == FALLBACK)
check("突き返す marker に `[%s]` が載る(生成側が直すべき所が読める) 実測=%r"
      % (OTHER, (_lines[0].get("marker") if _lines else "")),
      bool(_lines) and OTHER in str(_lines[0].get("marker") or "")
      and str(_lines[0].get("tag_names") or {}) != "{}")

# 止めすぎていないことの裏側= 名義が確定している便は従来どおり
check("名義が落ちていない便(fell_back=False)は止めない",
      dept_daemon.tone_rewrite_blocked({"fell_back": False, "contradicted": ""}) is False)
reset_audit()
_solo = dept_daemon.audit_persona_fallback(DEPT, FALLBACK, BODY, [FALLBACK], {"msg_id": INCIDENT})
check("単独人格の部屋では何もしない(誤発火しない) 実測=%r" % (_solo,),
      not _solo.get("fell_back") and not _LOGGED and not audit_lines())

# =============================================================================
# 層2= 対比(止めなければ何が起きるか= 事故の再現)
# =============================================================================
print("-- 層2= 対比: ゲートD単体に同じ本文を当てる(止めなかった時の点火条件)")
reset_audit()
_after, _tfix, _tone = dept_daemon.audit_tone(DEPT, FALLBACK, BODY, {"msg_id": INCIDENT})
check("既定の%s の写像で見ると signature_absent が残る= D-2 の点火条件が立つ 実測=%r"
      % (FALLBACK, [r.get("reason") for r in _tone]),
      any(r.get("reason") == "signature_absent" for r in _tone))

# =============================================================================
# 層3= 実走(Daemon.handle を本物のまま通す= 配線が効いていることを見る)
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
          os.path.join(ROOT, "local", "_daemon_reply_copy-director.txt"),
          os.path.join(ROOT, "local", "queue", "inbox.db")]
_BEFORE = {p: (os.path.getmtime(p), os.path.getsize(p)) for p in _GUARD if os.path.exists(p)}

reset_audit()
REC = {"channel": CHANNEL, "msg_id": INCIDENT, "author": "Chami", "content": "続きお願い"}
_ok = dept_daemon.Daemon(DEPT).handle(REC, json.dumps(REC, ensure_ascii=False))

_sends = [s for s in _SENT if "--persona" in s["argv"]]
check("便は止めずに1通出る(沈黙させない) 実測=%d通 / handle=%r" % (len(_sends), _ok), len(_sends) == 1)
_body = _sends[0]["body"] if _sends else ""
_persona = (_sends[0]["argv"][_sends[0]["argv"].index("--persona") + 1] if _sends else "")
check("★本文を1文字も書き換えていない(芽衣語尾で塗られていない) 実測=%r" % (_body[:24],),
      _body.strip().startswith(BODY[:40].strip()) and "なんだ！！" not in _body
      and "💕" not in _body and _body.strip() != AFTER.strip())
check("名義は推測で動かさない= 既定の %s のまま出る 実測=%r" % (FALLBACK, _persona),
      _persona == FALLBACK)
_ev = audit_lines()
check("書き直しの記録(tone_fix/tone_rewrite)が1行も無い 実測=%r" % ([e.get("event") for e in _ev],),
      not [e for e in _ev if e.get("event") in ("tone_fix", "tone_rewrite")])
check("F-3の1行が実走でも残る(=配線が呼ばれている)",
      any(e.get("reason") == "persona_fallback_default" for e in _ev))
check("実走でも `[%s]` が marker に載る(突き返しで生成側が直せる)" % OTHER,
      any(OTHER in str(e.get("marker") or "") for e in _ev
          if e.get("reason") == "persona_fallback_default"))

# --- 層3b= 止めすぎていない(1行目に名乗りが在る便は従来どおり) --------------------
print("-- 層3b= 回帰: 同じ本文の1行目に `[三笘]` を置いた便(=生成側が直した姿)")
reset_audit()
_SENT[:] = []
dept_daemon.session_relay.relay = lambda *a, **k: ("[三笘]\n" + BODY, True)
dept_daemon.Daemon(DEPT).handle(REC, json.dumps(REC, ensure_ascii=False))
_sends2 = [s for s in _SENT if "--persona" in s["argv"]]
_persona2 = (_sends2[0]["argv"][_sends2[0]["argv"].index("--persona") + 1] if _sends2 else "")
check("名義は %s で出る(F-3の対象外) 実測=%r" % (OTHER, _persona2), _persona2 == OTHER)
check("F-3の行は立たない= 書き直しの抑止は名義が落ちた便だけ 実測=%r"
      % ([e.get("reason") for e in audit_lines()],),
      not [e for e in audit_lines() if e.get("reason") == "persona_fallback_default"])

_AFTER_STAT = {p: (os.path.getmtime(p), os.path.getsize(p)) for p in _GUARD if os.path.exists(p)}
check("本番の台帳・下書き・キューへ1バイトも書いていない", _BEFORE == _AFTER_STAT)

print("")
print("== %s ==  PASS=%d FAIL=%d%s"
      % ("緑" if not NG[0] else "★赤", OK[0], NG[0], ("  (変異体%s)" % MUTANT) if MUTANT else ""))
sys.exit(1 if NG[0] else 0)
