# -*- coding: utf-8 -*-
"""封筒に載る文章の人名の綴りを**無人で**見張る(イージス研究室 / 2026-08-23)。

なぜ要るか:
  裁定カタログの見出し4件が旧綴り「ケヴィン・デ・ブライネ」のままで、**毎便×全部屋の封筒**が
  誤った綴りを教え続けていた。研究室HQが綴りを直し、検査 `envelope_naming_check.py` を作り、
  「`relay_health.py` の検査列へ吊るしてくれ」とイージス研究室へ回してきた(DISPATCH-aegis-gl-1787459939764)。

  検査15として吊るした。★だがそれだけでは**無人では一度も鳴らない**=
  `relay_health.py` を定期実行している登録タスクは **0本**(全タスクのアクションを走査して実測。
  同じ実測を `codever_sample.py` のdocstringにも書いた)。手で叩いた時だけ鳴る計器だ。
  封筒が汚れてから誰かが健康診断を思い出すまで、旧綴りは全部屋へ流れ続ける。
  → 「心がけに任せない。機構に載せる」(共通規律§3)。この見張りが無人側の半分を持つ。

判定はここに書かない:
  正本は `scripts/llm/envelope_naming_check.py` の `scan()` **1つだけ**。
  検査15もここも**同じ関数を呼ぶ**= 判定を2箇所に置くと必ず片方が古くなる。

鳴らし方(★常に鳴る安全網は無視される・§3):
  ① 材料(規律 / 裁定カタログ / 呼称ルール.json / 検査そのもの)の mtime が前回と同じなら**何もしない**。
     ★文字列や件数ではなく**材料が変わった時だけ**見る= ほぼ無料で、同じ違反を毎時鳴らさない。
  ② 違反が在り、かつ**前回知らせた違反の顔ぶれと違う**時だけ研究室HQへ1便出す(C-052=宛先は1つ)。
  ③ 綺麗な時は**何も書かない・何も出さない**(沈黙が正常)。

fail-open:
  例外は握って exit 0。**見張りが落ちても配達も他の常駐も止めない。**
  ただし黙って落ちない= `local/_state/envelope_naming_watch.jsonl` に理由を1行残す。

使い方:
    python scripts/_daemons/envelope_naming_watch.py
    python scripts/_daemons/envelope_naming_watch.py --selftest <差し替える裁定カタログのパス>
        → 材料を差し替えて**判定と分岐は本物のまま**通す。外へ出る手(dispatch)だけ止め、
          出すはずだった本文を画面に出す(共通規律§3の must-fail の作法)。
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime

# ★pythonw.exe で起動されると sys.stdout / sys.stderr は **None** になる。
#   借りてくる `envelope_naming_check.py` は取り込み時に `sys.stdout.reconfigure(...)` を
#   **裸で**呼ぶので、そのままだと `AttributeError: 'NoneType' ...` で毎時 fail-open し、
#   **登録されているのに一度も検査しない見張り**になる(2026-08-23 実測= 登録した直後に
#   タスクを1回起こしたら、まさにこれで空振りした。「登録済み≠動く」C-041)。
#   ★HQの持ち物である検査本体は触らない。**呼ぶ側で口を用意する**のが自室で閉じる直し方。
def _ensure_std():
    for nm in ("stdout", "stderr"):
        if getattr(sys, nm, None) is None:
            try:
                setattr(sys, nm, io.TextIOWrapper(io.open(os.devnull, "wb"),
                                                  encoding="utf-8", errors="replace"))
            except Exception:
                pass
    for nm in ("stdout", "stderr"):
        try:
            getattr(sys, nm).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_ensure_std()

PJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LLM_DIR = os.path.join(PJ, "scripts", "llm")
STATE = os.path.join(PJ, "local", "_state", "envelope_naming_watch.json")
LOG = os.path.join(PJ, "local", "_state", "envelope_naming_watch.jsonl")
DISPATCH = os.path.join(LLM_DIR, "dispatch.py")


def _now():
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def _log(row):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(row, ts=_now()), ensure_ascii=False) + "\n")
    except Exception:
        pass                      # ★記録に失敗しても見張りは落とさない


def load_check():
    if LLM_DIR not in sys.path:
        sys.path.insert(0, LLM_DIR)
    import envelope_naming_check as enc
    return enc


def material_sig(enc):
    """材料の版。mtimeが1つでも動いたら見直す。★検査そのものの版も混ぜる。

    (検査を賢くしたのに材料が動いていないから見送る、を防ぐ)
    """
    paths = [enc.RULES, enc.CATALOG, enc.NAMES_JSON,
             os.path.join(LLM_DIR, "envelope_naming_check.py")]
    out = []
    for p in paths:
        try:
            out.append("%s:%d" % (os.path.basename(p), int(os.path.getmtime(p))))
        except OSError:
            out.append("%s:-" % os.path.basename(p))
    return "|".join(out)


def bad_sig(bad):
    """違反の顔ぶれ。同じ顔ぶれを二度知らせない(★常に鳴る安全網にしない)。"""
    return "|".join(sorted("%s:%s:%s" % (os.path.basename(b[0]), b[1], b[3]) for b in bad))


def read_state():
    try:
        with io.open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def build_body(bad):
    lines = ["【イージス研究室(無人の見張り) → 研究室HQ】封筒に旧綴りが載っている(%d件)" % len(bad), ""]
    lines.append("材料が変わったので `envelope_naming_check.scan()` を回した。違反が出た=")
    for path, no, name, v, ln in bad[:20]:
        lines.append("- `%s:%s` 出ている綴り=**%s** / 正=**%s**" % (os.path.basename(path), no, v, name))
        lines.append("    %s" % ln)
    if len(bad) > 20:
        lines.append("- …ほか %d件" % (len(bad) - 20))
    lines += [
        "",
        "★直す先は**封筒に載る側**だけ= 共通規律の全文 / 裁定カタログの `### C-` と `| C-` の行。",
        "本文と更新履歴は封筒に載らない=過去の記録なので触るな(綴りを直すと記録が変わる)。",
        "",
        "★この見張りは**材料(規律/カタログ/呼称ルール.json/検査本体)のmtimeが動いた時だけ**回る。",
        "同じ顔ぶれの違反は二度知らせない。手元で今の状態を見るなら:",
        "    python 00_AI-HQ\\scripts\\relay_health.py   (検査15)",
        "    python 5SecMovieMaker\\scripts\\llm\\envelope_naming_check.py",
    ]
    return "\n".join(lines)


def notify(body, dry):
    """研究室HQへ1便。★外へ出る手はここだけ= selftest ではここだけ偽物にする。"""
    tmp = os.path.join(PJ, "local", "_work", "envelope_naming_alert.md")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    if dry:
        print("--- selftest: ここで研究室HQへ出すはずだった本文 ---")
        print(body)
        print("--- (dispatchは呼んでいない) ---")
        return "selftest"
    r = subprocess.run([sys.executable, DISPATCH, "--dept", "hq", "--direct",
                        "--audience", "ai", "--from", "ケヴィン・デブライネ",
                        "--from-dept", "aegis-gl", "--body-file", tmp],
                       capture_output=True, timeout=120)
    out = (r.stdout or b"").decode("utf-8", "replace")
    print(out.strip())
    return "sent" if r.returncode == 0 else "failed:%d" % r.returncode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", default="",
                    help="裁定カタログをこのパスへ差し替えて通す(dispatchは呼ばない)")
    ap.add_argument("--force", action="store_true", help="mtimeが同じでも見る")
    ns = ap.parse_args(argv)
    dry = bool(ns.selftest)

    try:
        enc = load_check()
    except Exception as e:
        _log({"event": "error", "何": "検査を借りられない", "err": "%s: %s" % (type(e).__name__, e)})
        return 0                                  # ★fail-open

    if ns.selftest:
        enc.CATALOG = ns.selftest                 # ★材料だけ差し替え。判定と分岐は本物のまま

    st = read_state()
    try:
        sig = material_sig(enc)
        if not (dry or ns.force) and st.get("material") == sig:
            return 0                              # 材料が動いていない= 何もしない(沈黙が正常)
        names, bad = enc.scan()
    except Exception as e:
        _log({"event": "error", "何": "scanが落ちた", "err": "%s: %s" % (type(e).__name__, e)})
        return 0                                  # ★fail-open

    if not bad:
        if not dry:
            write_state({"material": sig, "bad": "", "checked": _now()})
        print("違反なし(正本の人名 %d件)" % len(names))
        return 0

    bs = bad_sig(bad)
    if not dry and st.get("bad") == bs:
        write_state(dict(st, material=sig, checked=_now()))
        print("違反 %d件(前回と同じ顔ぶれ=知らせ直さない)" % len(bad))
        return 0

    res = notify(build_body(bad), dry)
    _log({"event": "alert", "件数": len(bad), "結果": res, "sig": bs[:200]})
    if not dry:
        write_state({"material": sig, "bad": bs, "checked": _now(), "last": res})
    print("違反 %d件 → 研究室HQへ %s" % (len(bad), res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
