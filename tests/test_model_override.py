#!/usr/bin/env python3
"""モデルの外付け上書き(`local/_model_override.json`)の検査。

★何のための検査か(2026-08-23 イージス研究室 / 発注= 研究室HQ msg 1540938360464474273)
  週の課金枠が時間比 2.25倍で燃えていて、C-014 の「安いモデルへ落とすのは節約できる時だけの
  例外」が成立した。落とす/戻すを **常駐を止めずに** できる形にしたのがこの上書き。
  ここで守りたい性質は2つだけだ:
    ① 上書きが**在る時だけ**落ちる(既定の Opus を黙って壊さない)
    ② 読めない・壊れている・切ってある時は **Opus 側へ倒れる**(安い方へ黙って落ちない)

★空PASS禁止(共通規律§3・skills/test-must-fail)。
  最後の E 節で **判定そのものを旧仕様(上書き無し)へ戻して、同じ検体が落ちる**ことを見せる。
  戻して落ちないなら、この検査は何も見ていない。
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


def write_override(doc_or_text):
    """検体を実物のファイルとして置き、mtimeキャッシュを無効化して**本物の読み口**を通す。"""
    with open(TMP, "w", encoding="utf-8") as f:
        if isinstance(doc_or_text, str):
            f.write(doc_or_text)
        else:
            json.dump(doc_or_text, f, ensure_ascii=False)
    dd._MODEL_OVERRIDE_CACHE["mtime"] = None        # 同一秒の書き換えでも必ず読み直させる


def clear_override():
    if os.path.exists(TMP):
        os.remove(TMP)
    dd._MODEL_OVERRIDE_CACHE["mtime"] = None


TMP = os.path.join(tempfile.gettempdir(), "go5_test_model_override.json")
dd.MODEL_OVERRIDE_PATH = TMP                        # 本番の local/ を触らない

AEGIS = dd.DEPT_CONF["aegis-gl"]                    # relay/work とも claude-opus-5 明示
SHORTS = dd.DEPT_CONF["shorts-analyst"]

print("== A. conf に部門スラッグが入っているか(上書きを引く前提) ==")
check("DEPT_CONF['aegis-gl']['dept']", AEGIS.get("dept"), "aegis-gl")
check("DEPT_CONF['shorts-analyst']['dept']", SHORTS.get("dept"), "shorts-analyst")

print("== B. 上書きファイルが無い時= 従来どおり(1ミリも変えていない) ==")
clear_override()
BASE_W_AEGIS = dd.work_model_for(AEGIS)
BASE_R_AEGIS = sr.relay_model(AEGIS)
BASE_W_SHORTS = dd.work_model_for(SHORTS)
BASE_R_SHORTS = sr.relay_model(SHORTS)
check("work  aegis-gl (上書き無し)", BASE_W_AEGIS, "claude-opus-5")
check("relay aegis-gl (上書き無し)", BASE_R_AEGIS, "claude-opus-5")
check("work  shorts-analyst (上書き無し)", BASE_W_SHORTS, "claude-opus-4-8")
check("relay shorts-analyst (上書き無し)", BASE_R_SHORTS, "claude-opus-4-8")

print("== C. 上書きが効く。名指しした部屋だけ(C-035=名指しを全体へ広げない) ==")
write_override({"enabled": True,
                "work": {"shorts-analyst": "sonnet"},
                "relay": {"shorts-analyst": "sonnet"}})
check("work  shorts-analyst (上書き有り)", dd.work_model_for(SHORTS), "sonnet")
check("relay shorts-analyst (上書き有り)", sr.relay_model(SHORTS), "sonnet")
check("work  aegis-gl は巻き添えにならない", dd.work_model_for(AEGIS), BASE_W_AEGIS)
check("relay aegis-gl は巻き添えにならない", sr.relay_model(AEGIS), BASE_R_AEGIS)

print("== C-2. work と relay は別に落とせる(会話だけ Opus に残す形が要る) ==")
write_override({"enabled": True, "work": {"shorts-analyst": "sonnet"}})
check("work  だけ落ちる", dd.work_model_for(SHORTS), "sonnet")
check("relay は据え置き", sr.relay_model(SHORTS), BASE_R_SHORTS)

print("== D. 戻し口。ここが効かないと『落としたら戻せない』になる ==")
write_override({"enabled": False,
                "work": {"shorts-analyst": "sonnet"},
                "relay": {"shorts-analyst": "sonnet"}})
check("enabled:false で1行で全部戻る(work)", dd.work_model_for(SHORTS), BASE_W_SHORTS)
check("enabled:false で1行で全部戻る(relay)", sr.relay_model(SHORTS), BASE_R_SHORTS)

write_override("{ これは壊れたJSON ")
check("壊れたJSON= 上書き無し(安い方へ黙って落ちない)", dd.work_model_for(SHORTS), BASE_W_SHORTS)

write_override({"enabled": True, "work": {"shorts-analyst": "   "}})
check("空文字の値= 上書き無し", dd.work_model_for(SHORTS), BASE_W_SHORTS)

write_override({"enabled": True, "work": {"存在しない部門": "sonnet"}})
check("知らない部門名= どこも落ちない", dd.work_model_for(SHORTS), BASE_W_SHORTS)

print("== E. must-fail: 判定を旧仕様(上書き無し)へ戻すと C が落ちること ==")
write_override({"enabled": True,
                "work": {"shorts-analyst": "sonnet"},
                "relay": {"shorts-analyst": "sonnet"}})
_orig = dd.model_override_for
dd.model_override_for = lambda dept, kind: None      # ← 足した述語だけを殺す
mf_work = dd.work_model_for(SHORTS)
mf_relay = sr.relay_model(SHORTS)
dd.model_override_for = _orig
check("旧仕様では work が sonnet に**ならない**", mf_work != "sonnet", True)
check("旧仕様では relay が sonnet に**ならない**", mf_relay != "sonnet", True)
check("述語を戻せば C は再び通る", dd.work_model_for(SHORTS), "sonnet")

clear_override()
print()
print("PASS %d / FAIL %d" % (ok, ng))
sys.exit(1 if ng else 0)
