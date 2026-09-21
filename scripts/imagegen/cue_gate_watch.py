# -*- coding: utf-8 -*-
"""合図ゲートの見張り(2026-09-22 イージス研究室)。

依頼= 研究室HQ シャビ・アロンソ便 DISPATCH-aegis-gl-1790022388784 の手番(2)
  「常駐の再読込後、responder_log.jsonl に mode=image_no_cue が出ているかを見る導線」。
  止血そのものは研究室HQが入れた(rooms.cue_required を dept in ROOMS へ)。ここは**恒久側**=
  入れた物が本番で効いているかを、実物のログから何度でも見直せる口にする。
  ★★その後 Chami直令が2回動いた(下の訂正)。**HQ便が書いた `CUE_REQUIRED_DEPTS = tuple(ROOMS)`
    は今の姿ではない**= 現物は `d in ROOMS and d not in NO_CUE_DEPTS` で、実在の描画室で合図が
    要る部屋は今ゼロだ。要否は必ず rooms.cue_required() に訊く(この文も写しで、写しは遅れる)。

★見るのは3つ。
  ①常駐(local_responder)が新しいコードで上がっているか(codever の保存値と今の閉包ハッシュ)
  ②再読込の**あと**、描画室の便がどう捌かれたか(描いた/合図なしで捨てた/合図だけ)
  ③★漏れ= **合図が要る部屋で、合図なしの便を描いてしまった1行**。2026-09-22 05:06:18 の実害
    (Chamiの指示文そのものが絵になった)と同じ形を、ログ側から名指しで拾う。
    mode=image_no_cue が「出ている」ことの裏返しが、これが「0件である」こと。
    ★同日05:37の直令(msg 1551692713425117314)で3室は合図不要になった= そこの cue=False は
      正常。要否は rooms.cue_required にその場で訊く=この道具に室名を書き写さない。
    ★★訂正(2026-09-22 05:49 Chami msg 1551692776859631629「違う、4部屋か」)= itsumono も含む
      **4室**。上の「3室」は30秒で古くなった記述だ。数を覚えずに台帳へ訊け。

★観測専用= 何も書かない・送らない。exit 0=漏れ無し / 1=漏れ有り / 2=常駐が旧コード。

    python scripts/imagegen/cue_gate_watch.py              # 常駐の再読込時刻から今まで
    python scripts/imagegen/cue_gate_watch.py --hours 24   # 直近24時間
    python scripts/imagegen/cue_gate_watch.py --all        # 全期間
"""
import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)

import rooms  # noqa: E402

LOG = os.path.join(ROOT, "local", "llm", "responder_log.jsonl")
CODEVER = os.path.join(ROOT, "local", "_daemon_codever", "local_responder.txt")
RESPONDER = os.path.join(ROOT, "scripts", "llm", "local_responder.py")
DREW_MARK = "[画像生成"          # local_chain が返す本文の頭。これが付いた便は実際に描いている


def _truthy(v):
    return v is True or (isinstance(v, str) and v.strip().lower() == "true")


def parse_ts(ts):
    """responder_log の ts("2026-09-22T05:06:18"・ローカル時刻)を epoch へ。読めなければ None。"""
    try:
        return time.mktime(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


def dept_of(row):
    """行の dept。古い行は dept を持たず channel しか無いので台帳から引き直す。"""
    d = row.get("dept")
    if d:
        return d
    return rooms.dept_of_channel(row.get("channel"))


def classify(row):
    """描画室の1行を4つに仕分ける。判定はログの実値だけで決める(推測しない)。"""
    mode = row.get("mode")
    if mode in ("image_no_cue", "image_cue_only"):
        return mode
    if _truthy(row.get("image")) and str(row.get("a") or "").startswith(DREW_MARK):
        return "drew"
    return "other"


def read_rows(path=LOG, since=None):
    """描画室の行だけを (epoch, dept, kind, row) で返す。since=epoch 未満は捨てる。"""
    out = []
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            dept = dept_of(row)
            if not dept or dept not in rooms.ROOMS:
                continue
            at = parse_ts(row.get("ts"))
            if since is not None and (at is None or at < since):
                continue
            out.append((at, dept, classify(row), row))
    return out


def leaks(rows):
    """★漏れ= **合図が要る部屋なのに**ゲートが掛からないまま描いた行(= 退行の実物)。

    判定は local_responder が描いた瞬間に残す `cue` の実値だけで決める。
    ★q(本文)から合図の有無を読もうとしてはいけない= ログへ載る本文は**合図を剥がした後**で、
      正しく通った注文も「合図が無い」ように見える(2026-09-22 この見張りの初版がそれで誤報した)。
    ★★2026-09-22 05:37 Chami直令 msg 1551692713425117314 で imagegen / fusoh-v0 / fusoh-v2 の
      3室、★★続く 05:49 msg 1551692776859631629「違う、4部屋か」で itsumono も加えた**4室**が
      **合図が要らなくなった**(rooms.NO_CUE_DEPTS)。そこでの cue=False は正常な姿で、
      漏れではない。どの部屋が要るかは台帳(rooms.cue_required)にその場で訊く=ここに室名を
      書き写さない。合図の要否がまた変わっても、この見張りは黙って追従する。
    """
    return [r for r in rows
            if r[2] == "drew" and r[3].get("cue") is False and rooms.cue_required(r[1])]


def cue_free_draws(rows):
    """合図が要らない部屋で描いた行= 漏れではない。数だけ別に出して混ぜない。"""
    return [r for r in rows
            if r[2] == "drew" and not rooms.cue_required(r[1])]


def undecidable(rows):
    """`cue` を持たない古い描画行(2026-09-22 の記録追加より前)= 漏れとも無事とも言えない。

    ★合図が要らない部屋の行はここに入れない= そこには元から掛かるゲートが無い。
    """
    return [r for r in rows
            if r[2] == "drew" and "cue" not in r[3] and rooms.cue_required(r[1])]


def reload_info():
    """常駐の版。返り= (保存値, 今の値, 載せ替え時刻epoch or None)。"""
    saved = ""
    at = None
    try:
        with open(CODEVER, encoding="utf-8") as f:
            saved = f.read().strip()
        at = os.path.getmtime(CODEVER)
    except OSError:
        pass
    now = ""
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))
        import daemon_code_version as dcv
        now = dcv.code_hash(RESPONDER)
    except Exception as e:
        now = "(算出不能: %s)" % type(e).__name__
    return saved, now, at


def _fmt(at):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at)) if at else "(不明)"


def report(since=None, log=LOG, check_code=True):
    """★check_code= 生きている常駐の版を見るか。

    既定(本番)は見る。検査では False= この機械で常駐が今どうなっているかに判定を
    引きずられないため(ログの読み方を固めるのが検査の仕事で、常駐の生死は別の見張りの仕事)。
    """
    saved, now, at = ("", "", None)
    if check_code:
        saved, now, at = reload_info()
    stale = bool(saved) and bool(now) and not now.startswith("(") and saved != now
    if since is None:
        since = at                      # 既定= 常駐が新コードで上がった時刻から
    rows = read_rows(log, since)
    kinds = {}
    for r in rows:
        kinds[r[2]] = kinds.get(r[2], 0) + 1
    lk = leaks(rows)
    nd = undecidable(rows)
    cf = cue_free_draws(rows)
    lines = ["合図ゲートの見張り  " + time.strftime("%Y-%m-%d %H:%M:%S")]
    if check_code:
        lines.append("  常駐 local_responder: 保存値=%s / 今=%s  載せ替え=%s%s"
                     % (saved or "(無)", now or "(無)", _fmt(at),
                        "  ★旧コードで動いている" if stale else ""))
    lines += ["  合図が要る部屋: " + (", ".join(sorted(rooms.CUE_REQUIRED_DEPTS)) or "(無)"),
              "  合図が要らない部屋(Chami直令 msg 1551692713425117314): "
              + (", ".join(sorted(rooms.NO_CUE_DEPTS)) or "(無)"),
              "  数える範囲: %s 以降 / 描画室の便 %d 件" % (_fmt(since), len(rows)),
             "    描いた=%d  合図なしで捨てた(image_no_cue)=%d  合図だけ(image_cue_only)=%d  その他=%d"
             % (kinds.get("drew", 0), kinds.get("image_no_cue", 0),
                kinds.get("cue_only", 0) + kinds.get("image_cue_only", 0), kinds.get("other", 0))]
    if cf:
        lines.append("    ↑のうち %d 件は合図の要らない部屋で描いた行= ゲートの対象外"
                     "(漏れとして数えない)" % len(cf))
    if nd:
        lines.append("    ↑のうち %d 件は `cue` を持たない古い記録= 判定不能"
                     "(2026-09-22 の記録追加より前に描いた行)" % len(nd))
    if lk:
        lines.append("  ★漏れ %d 件= ゲートが掛からないまま描いている(止血が効いていない)" % len(lk))
        for at_, dept, _k, row in lk[-10:]:
            lines.append("    %s [%s] %r" % (_fmt(at_), dept, str(row.get("q"))[:60]))
        rc = 1
    elif not rows:
        lines.append("  この範囲に描画室の便がまだ1件も無い= ゲートは**未通電**(確認待ち)")
        rc = 0
    elif not kinds.get("image_no_cue"):
        lines.append("  漏れ0件。ただし合図なしの便がまだ来ていない"
                     "(image_no_cue=0)= 捨てる側の実物は未確認")
        rc = 0
    else:
        lines.append("  漏れ0件。合図なしの便は image_no_cue で捨てられている(実物あり)")
        rc = 0
    if stale:
        rc = 2
    return "\n".join(lines), rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=None, help="直近N時間で数える")
    ap.add_argument("--all", action="store_true", help="全期間で数える")
    ap.add_argument("--log", default=LOG)
    a = ap.parse_args()
    since = None
    if a.all:
        since = 0
    elif a.hours:
        since = time.time() - a.hours * 3600
    text, rc = report(since, a.log)
    print(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
