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


def run_envelope(ns, dry):
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


# ────────────────────────────────────────────────────────────────────────
# 持続する呼称ドリフト(2026-08-31 追加・改善提案部門の回送 msg 1543872521093521478)
#
# なぜここへ相乗りするか:
#   「一ノ瀬」(裸の姓)呼びが組織横断で居座っている、とトトリが実測して回してきた。
#   ★当室で取り直したら**回送の根因は1つ違っていた**= 22件は素通りしていない。
#   呼称ゲートは全部 `override_allowed / expected=["怜"]` で**違反と判定して台帳へ書いていた**。
#   素通りしていたのは判定ではなく**読み手**だ= `naming_audit.jsonl` を読む機構が1つも無い。
#   → 足りないのは新しい判定ではなく**読む口**。だから新しい常駐は作らない。
#     ここは既に登録され・既に配達の手を持ち・既に「顔ぶれが変わった時だけ鳴らす」を
#     持っている見張りだ。同じ作法の見張りを2本に増やす方が事故る(C-052)。
#
# 判定はここに書かない:
#   正本は `scripts/llm/naming_drift_check.scan()` 1つ。しきい値の根拠もあちらの docstring。
#
# 宛先は人事部門(hr-room)1つ:
#   直せるのは呼称ルール.json と人格文脈= どちらも人事の持ち物。研究室HQへは出さない
#   (両方へ出すと、両方が「相手が見る」と思って誰も見ない)。
#
# ★状態は**別ファイル**に置く:
#   封筒側の `write_state()` は辞書ごと差し替える= 同居させるとドリフトの記憶が
#   封筒側の書き込みで黙って消え、鳴り直す。見張りが2つなら記憶も2つ。
STATE_DRIFT = os.path.join(PJ, "local", "_state", "naming_drift_watch.json")
DRIFT_DEPT = "hr-room"


def _read_json(path):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_json(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_drift():
    if LLM_DIR not in sys.path:
        sys.path.insert(0, LLM_DIR)
    import naming_drift_check as ndc
    return ndc


def drift_material(ndc):
    """材料の版= 台帳と判定そのもの。台帳が伸びていなければドリフトは変わり得ない。"""
    out = []
    for p in (ndc.AUDIT, os.path.join(LLM_DIR, "naming_drift_check.py")):
        try:
            out.append("%s:%d:%d" % (os.path.basename(p), int(os.path.getmtime(p)),
                                     os.path.getsize(p)))
        except OSError:
            out.append("%s:-" % os.path.basename(p))
    return "|".join(out)


def build_drift_body(ndc, drifts, un, dup=None, fn=None, focus=None):
    # ★見出しは `ndc.SELF_REPORT_HEAD` から組む。ここを直書きすると、文言を変えた日に
    #   「この便を台帳から外す」判定(ndc.is_self_report)が黙って外れ、また自分の警報で
    #   自分の目盛りを押し上げる(2026-09-06 実測の自己汚染30行)。同じ文字列を2箇所に置かない。
    #
    # ★2026-09-08= **全数を毎回展開しない**(発注= 人事部門ククール msg 1546651338312523827)。
    #   この便は1本 2,316字/44行(実測)。毎時撃つと有人部屋の文脈へ1日 約55,000字積む=
    #   「常に鳴る安全網は無視される」の物量版だ。**鳴った理由の組だけを開き、既報は1行に畳む。**
    #   focus = ndc.diff_pairs() の戻り(fresh / rebanned)。None なら従来どおり全部開く
    #   (手で叩いた時・古い呼び出し元のため)。
    key = set((focus or {}).get("fresh", [])) | set((focus or {}).get("rebanned", []))
    lines = [ndc.SELF_REPORT_HEAD + "**持続ドリフト**が %d件 居座っている" % len(drifts), ""]
    lines.append("`local/llm/naming_audit.jsonl` の直近%d日を読んだ。"
                 "★件数だけでは鳴らさない= 「%d件以上 / %d日以上にまたがる / %d人格以上が使う」の"
                 "3つが揃った形だけを持続ドリフトと呼ぶ(常に鳴る安全網は無視されるから)。"
                 "★数えるのは**相手へ呼びかけた行だけ**だ(2026-09-20 改修・発注=人事部門ククール)="
                 "「Chami直令」のような地の文・足場メタの言及は件数にも日数にも人格数にも入れない。"
                 % (ndc.WINDOW_DAYS, ndc.MIN_COUNT, ndc.MIN_DAYS, ndc.MIN_PERSONAS))
    if focus:
        lines.append("")
        lines.append("■★この便を出した理由(★これが無い時刻は**鳴らさない**)")
        if focus.get("fresh"):
            lines.append("- **初めて立った組 %d**= %s"
                         % (len(focus["fresh"]), "、".join(focus["fresh"])))
        if focus.get("rebanned"):
            lines.append("- **禁止後の再発へ変わった組 %d**= %s"
                         % (len(focus["rebanned"]), "、".join(focus["rebanned"])))
        lines.append("- 残り %d組は**既報**= 下に1行で畳んだ(件数の増減だけでは鳴らし直さない)。"
                     % max(0, len(drifts) - len(key)))
    lines.append("")
    old = []
    for d in drifts:
        if key and ndc.pair_key(d) not in key:
            old.append("%s%s" % (ndc.pair_key(d), "!" if ndc.banned(d) else ""))
            continue
        lines.append("- %s**%s** を「%s」と呼んでいる(正=**%s**): **呼びかけ%d件** / %d日 / %d人格"
                     " [%s〜%s](地の文の言及%d件は数えていない・台帳の生の行は%d)"
                     % ("★【禁止後の再発】" if ndc.banned(d) else "",
                        d["target"], d["found"], "・".join(d["expected"]) or "?",
                        d["count"], d["days"], len(d["personas"]),
                        d["first"][:10], d["last"][:10],
                        d.get("mention", 0), d.get("count_all", d["count"])))
        lines.append("    使っている人格= %s" % "、".join(d["personas"]))
    if old:
        lines.append("- (既報 %d組= %s ★末尾の「!」=禁止後の再発。内訳は下のコマンドで見られる)"
                     % (len(old), "、".join(old)))
    if any(ndc.banned(d) for d in drifts):
        lines += [
            "",
            "★【禁止後の再発】= `呼称ルール.json` の `forbidden` に**名指しで載せた後も出ている**形だ。",
            "  ゲートは禁止を読んでラベルを `forbidden` へ変えるが、**文面は直さない**"
            "(当室で前後を実測= `naming_corrections()` の `applied` は空のまま)。",
            "  つまりこれは**再ピンが生成側を押し戻せていない**という報せで、"
            "forbidden を足し直しても件数は動かない。",
        ]
    lines += [
        "",
        "■直す先(★機構側では直さない)",
        "呼称ゲートは**警告のみ**で自動修正しない(アロンソ型と敬称抜けの2種だけが例外)。",
        "つまりここから先は人事部門の持ち物だ=",
        "  1. `呼称ルール.json` の該当ペアへ `forbidden` を足す → **鳴る理由が変わるだけ**で止まりはしない。",
        "  2. 使っている人格の文脈へ正しい呼び方を再ピン → **こちらが本命**(生成側を押し戻す)。",
        "★C-035= 名指しされたペアだけ直せ。全体の呼称規則へ広げるな。",
        "",
        "■自動置換はしない",
        "正しい形は文脈で変わる(「一ノ瀬怜さんが」と紹介する文まで潰す)。この見張りは**数えて見せるだけ**だ。",
        "",
        "■手元で今の状態を見る",
        "    python 5SecMovieMaker\\scripts\\llm\\naming_drift_check.py",
    ]
    if un:
        lines += [
            "",
            "■★鳴らせなかった分(人事の宿題ではなく**当室の宿題**)= %d件"
            % sum(u["count"] for u in un),
            "  " + "、".join("%s>%s" % (u["target"], u["found"]) for u in un),
            "  台帳の `found` は「見つかった土台の形」で、**実際に使われた形が残っていない**。",
            "  例=「モドリッチさん」(呼び捨てが正)が found=\"モドリッチ\" / expected=[\"モドリッチ\"] と残り、",
            "  読むと「モドリッチをモドリッチと呼ぶな」になる。直す先が読めない警報は出さない。",
            "  ゲート側で実際の形を残す改修は当室で持つ(まだ**入れていない**)。",
        ]
    # ★2026-09-08= **この数字から何を引いたか**を便の中に必ず書く(発注= 人事部門ククール
    #   msg 1546607734349111418)。除外を画面(naming_drift_check の標準出力)にだけ出して
    #   便に書かないと、受け手は「元から少なかった」と読む= 減った理由を追えない。
    # ★2026-09-08 その2= **答えの出た問いを毎回書き直さない**(発注= 同じククール
    #   msg 1546651338312523827)。引いた分は「何をどれだけ引いたか」の1行だけ残す=
    #   0件に見せない義務は果たしつつ、裁定の依頼は**二度と出さない**(C-046=閉じ方の
    #   決まった案件を鳴らし続けるな)。理屈の全文は当室の docstring と change_log に在る。
    if dup:
        lines += [
            "",
            "■引いた分①= 重複 %d件(同じ一箇所を関門が2度書いた分・当室の集計側で畳んだ)。"
            "生成側は 2026-09-06 に塞いだ〈`dispatch.py` の `already_gated`〉= 窓14日が"
            "入れ替われば0へ落ちる過去行だ。" % sum(d["count"] for d in dup),
        ]
    if fn:
        lines += [
            "",
            "■引いた分②= 正しいフル名を書いただけ %d件。**2026-09-08 人事部門の裁定=違反ではない**"
            "(msg 1546621749406203976)= **足し戻さない・もう裁定は頼まない**。生成側も同日に"
            "塞いだ〈`naming_gate` の `CROSS_SPEAKER_SPAN_EXEMPTION`〉= これも窓が入れ替われば"
            "0へ落ちる過去行だ。" % sum(f["count"] for f in fn),
        ]
    return "\n".join(lines)


def notify_drift(body, dry):
    """人事部門へ1便。★外へ出る手はここだけ= selftest ではここだけ偽物にする。"""
    tmp = os.path.join(PJ, "local", "_work", "naming_drift_alert.md")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    if dry:
        print("--- selftest: ここで人事部門へ出すはずだった本文 ---")
        print(body)
        print("--- (dispatchは呼んでいない) ---")
        return "selftest"
    r = subprocess.run([sys.executable, DISPATCH, "--dept", DRIFT_DEPT, "--direct",
                        "--audience", "ai", "--from", "ケヴィン・デブライネ",
                        "--from-dept", "aegis-gl", "--body-file", tmp],
                       capture_output=True, timeout=120)
    print((r.stdout or b"").decode("utf-8", "replace").strip())
    return "sent" if r.returncode == 0 else "failed:%d" % r.returncode


def run_drift(ns, dry):
    try:
        ndc = load_drift()
        st = _read_json(STATE_DRIFT)
        sig = drift_material(ndc)
        if not (dry or ns.force) and st.get("material") == sig:
            return 0                              # 台帳が伸びていない= 何もしない
        rows = ndc.load_rows(ns.drift_ledger or None)
        drifts = ndc.scan(rows)
        un = ndc.unreadable(rows)
        # ★引いた分は**便にも**書く(理由は build_drift_body の中)。台帳のパスは
        #   ns.drift_ledger を必ず渡す= selftest が本番台帳を読みに行かないように。
        led = ns.drift_ledger or None
        dup = ndc.duplicates(led)
        fn = ndc.full_name_hits(led)
    except Exception as e:
        _log({"event": "error", "何": "ドリフト検査が落ちた",
              "err": "%s: %s" % (type(e).__name__, e)})
        return 0                                  # ★fail-open
    if not drifts:
        if not dry:
            _write_json(STATE_DRIFT, dict(st, material=sig, drift="", checked=_now()))
        print("持続ドリフトなし")
        return 0

    ds = ndc.sig(drifts)
    # ★鳴らすかどうかの判定は `ndc.diff_pairs()` 1つ(理由はあちらのブロック)。
    #   ここに条件を書くと、判定が2箇所に散って必ず片方が古くなる。
    #   ★旧 state(顔ぶれ文字列)からの移行= `seed_pairs` で既報の組を先に埋める。
    #     埋めないと、静かにする改修の初回が「8組が全部初出」で full-dump を1本余計に撃つ。
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    prev_pairs = st.get("pairs")
    if not isinstance(prev_pairs, dict):
        prev_pairs = ndc.seed_pairs(st.get("drift") or "", today)
    diff = ndc.diff_pairs(prev_pairs, drifts, today)
    # ★`--dry` でも**この分岐は本物のまま**通す(共通規律§3= 偽物にするのは外へ出る手だけ)。
    #   本文を見たい時は `--force`= 「mtimeが同じでも見る / 黙る条件も越えて出す」のつまみ。
    if not ns.force and not diff["fresh"] and not diff["rebanned"]:
        # ★黙る回も**黙って通り過ぎない**= 何回黙ったかを state に持つ(jsonl へは積まない=
        #   毎時1行の警報面を作らないため)。見張りが生きている証拠はここで読む。
        if not dry:
            _write_json(STATE_DRIFT, dict(st, material=sig, drift=ds, pairs=diff["pairs"],
                                          checked=_now(),
                                          quiet_rounds=int(st.get("quiet_rounds") or 0) + 1,
                                          quiet_since=st.get("quiet_since") or _now()))
        print("持続ドリフト %d件(初出の組も禁止後の再発も無い=鳴らさない・連続%d回)"
              % (len(drifts), int(st.get("quiet_rounds") or 0) + 1))
        return 0

    res = notify_drift(build_drift_body(ndc, drifts, un, dup, fn, diff), dry)
    _log({"event": "drift_alert", "件数": len(drifts), "結果": res, "sig": ds[:200],
          "初出": diff["fresh"], "再発": diff["rebanned"]})
    if not dry:
        _write_json(STATE_DRIFT, {"material": sig, "drift": ds, "pairs": diff["pairs"],
                                  "checked": _now(), "last": res,
                                  "quiet_rounds": 0, "quiet_since": ""})
    print("持続ドリフト %d件(初出%d・再発%d) → 人事部門へ %s"
          % (len(drifts), len(diff["fresh"]), len(diff["rebanned"]), res))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", default="",
                    help="裁定カタログをこのパスへ差し替えて通す(dispatchは呼ばない)")
    ap.add_argument("--drift-ledger", default="",
                    help="呼称台帳をこのパスへ差し替える(--dry と併せて使う)")
    ap.add_argument("--dry", action="store_true",
                    help="判定と分岐は本物のまま・外へ出る手(dispatch)だけ止める")
    ap.add_argument("--force", action="store_true",
                    help="mtimeが同じでも見る/『初出の組が無いから黙る』も越えて本文を出す")
    ns = ap.parse_args(argv)
    dry = bool(ns.selftest) or ns.dry
    # ★2つは**別々に fail-open**する= 片方が落ちても、もう片方の見張りは今日も回る。
    #   (相乗りさせた側の事故で、先に居た封筒の見張りを黙って殺さないため)
    for name, fn in (("envelope", run_envelope), ("drift", run_drift)):
        try:
            fn(ns, dry)
        except Exception as e:
            _log({"event": "error", "何": "%s が落ちた" % name,
                  "err": "%s: %s" % (type(e).__name__, e)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
