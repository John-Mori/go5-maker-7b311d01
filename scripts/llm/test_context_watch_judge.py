# -*- coding: utf-8 -*-
"""context_watch の「線超の判定」検査(2026-08-22・研究室HQ指摘1 msg 1540622895687139438)。

★何を守る検査か:
  初版の見張りは over の条件に `not managed` を入れていた=**relay管理下のセッションは
  線を越えても1件も数えず、--alert も撃たなかった**。その時いちばん文脈を食っていたのが
  管理下の 2f7b8457(中央値 215,522=交代線を30,522超)で、見張りに1件も映らなかった。
  → この検査は「管理下の線超が拾われること」を**壊したら落ちる**形で固定する。

★空PASSにしない= 最後に**変異検査**を置く。judge() を旧仕様(管理外だけ)へ差し替えたら
  検査が落ちることをその場で確認する(test-must-fail)。

走らせ方: python scripts/llm/test_context_watch_judge.py
★読むだけ。Discordにもキューにも本番の台帳にも書かない(alertの検査は subprocess を偽物に差し替える)。
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_watch as cw          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

COMPACT, ROTATE = 120000, 185000
NOW = 1_700_000_000.0
ok, ng = 0, 0


def check(name, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print("  PASS %s" % name)
    else:
        ng += 1
        print("  FAIL %s %s" % (name, detail))


def row(sid, dept, median, last_epoch=NOW, n=50):
    return {"sid": sid, "dept": dept, "model": "claude-x", "n": n, "last": median,
            "median": median, "max": median, "last_ts": "08/22 16:00", "last_epoch": last_epoch}


def sample():
    """HQが実測した盤面をそのまま型にする(2026-08-22 16:22 の測定)。"""
    return [
        row("2f7b8457", "aegis-gl", 215522),          # relay現行・交代線超 ←初版が落としていた本体
        row("c27eec97", "hq", 129706),                # relay現行・圧縮線超
        row("0351851c", "研究室メイン", 259153, NOW - 90000),   # 手動・停止済
        row("eb3904a8", "研究室メイン", 134867),      # 手動・稼働中
        row("cb16530d", "platform-se", 91516),        # 線の下
        row("old01234", "future-room", 190000, NOW - 60),      # 旧世代だが書き込みが続いている
        row("old56789", "system-engineer", 190000, NOW - 7200),  # 旧世代・停止済
    ]


def managed_map():
    return {"2f7b8457-aaaa": "aegis-gl", "c27eec97-bbbb": "hq", "cb16530d-cccc": "platform-se"}


print("== context_watch.judge / mark_managed ==")
rows = cw.mark_managed(sample(), managed_map())
by = {r["sid"]: r for r in rows}

check("relayが立てた現行世代は relay:現行", by["2f7b8457"]["managed"] == "relay:現行",
      by["2f7b8457"]["managed"])
check("relayが立てた旧世代は relay:旧世代", by["old01234"]["managed"] == "relay:旧世代",
      by["old01234"]["managed"])
check("手で開いた窓は管理外(空)", by["eb3904a8"]["managed"] == "", by["eb3904a8"]["managed"])

over = cw.judge(rows, COMPACT, ROTATE, now=NOW)
o = {r["sid"]: r for r in over}

# ★これがHQ指摘1の本体。ここが拾えなければ検査は落ちる。
check("管理下の線超が拾われる(未発火)", "2f7b8457" in o and o["2f7b8457"]["over_kind"] == "未発火",
      str(o.get("2f7b8457")))
check("管理下の線超は通知に載る", bool(o.get("2f7b8457", {}).get("alert")))
check("交代線を越えたら交代線超", o.get("2f7b8457", {}).get("level") == "交代線超")
check("圧縮線だけ越えたら圧縮線超", o.get("c27eec97", {}).get("level") == "圧縮線超")
check("管理外でも書き込みが止まっていれば鳴らさない(停止窓)",
      o.get("0351851c", {}).get("over_kind") == "停止窓"
      and not o.get("0351851c", {}).get("alert"), str(o.get("0351851c")))
check("手動で稼働中の窓も拾う", o.get("eb3904a8", {}).get("over_kind") == "管理外")
check("旧世代でも書き込みが続いていれば見失い", o.get("old01234", {}).get("over_kind") == "見失い")
check("交代済の旧世代は鳴らさない",
      o.get("old56789", {}).get("over_kind") == "交代済" and not o["old56789"]["alert"])
check("線の下は1件も入らない", "cb16530d" not in o)
check("拾った件数=6(全7本のうち線の下1本を除く)", len(over) == 6, str(len(over)))


print("== alert(): 種類ごとに分けて書く / 交代済は載せない ==")


class _FakeSub(object):
    def __init__(self):
        self.calls = []

    def run(self, argv, **kw):
        self.calls.append(argv)

        class R(object):
            returncode = 0
        return R()


tmp = tempfile.mkdtemp(prefix="ctxwatch_test_")
cw.STATE = os.path.join(tmp, "state.json")      # ★本番の状態ファイルを触らない
real_sub = cw.subprocess
cw.subprocess = _FakeSub()
try:
    n = cw.alert(over, COMPACT, ROTATE)
    body = ""
    if cw.subprocess.calls:
        argv = cw.subprocess.calls[0]
        body = argv[argv.index("--body") + 1] if "--body" in argv else ""
    check("通知は1本だけ出す", len(cw.subprocess.calls) == 1, str(len(cw.subprocess.calls)))
    # 6件拾って、交代済(old56789)と停止窓(0351851c=25時間無音)の2件が黙る
    check("通知した件数=4(交代済・停止窓を除く)", n == 4, str(n))
    check("停止窓のセッションIDは載らない", "0351851c" not in body, body[:400])
    check("宛先はHQ", "--dept" in (cw.subprocess.calls[0] if cw.subprocess.calls else [])
          and cw.subprocess.calls[0][cw.subprocess.calls[0].index("--dept") + 1] == "hq")
    check("Discordへは出さない(--also-postを付けない)",
          "--also-post" not in (cw.subprocess.calls[0] if cw.subprocess.calls else []))
    check("本文に未発火の見出しがある", "■未発火" in body)
    check("本文に管理外の見出しがある", "■管理外" in body)
    check("本文に見失いの見出しがある", "■見失い" in body)
    check("本文に管理下のセッションIDが載る", "2f7b8457" in body, body[:200])
    check("交代済のセッションIDは載らない", "old56789" not in body)
    # 2回目= 冷却中なので鳴らない(常に誤発火する安全網は無視される=共通規律§3)
    n2 = cw.alert(over, COMPACT, ROTATE)
    check("冷却中は再送しない", n2 == 0 and len(cw.subprocess.calls) == 1, "%s/%s" % (n2, len(cw.subprocess.calls)))
finally:
    cw.subprocess = real_sub


print("== 「未発火」は時系列で測る(2026-08-22 2回目・研究室HQ msg DISPATCH-aegis-gl-1787386532882) ==")
# ★実測の再現= hq c27eec97 は「未発火」と表示されたが、同じ12時間に relay は4回撃っていた
#   (local/llm/dept_daemon_hq.log 16:30 / 16:45 / 17:02 / 17:12)。
#   圧縮は 120,000 で撃つので、正常な部屋の記録には必ず 120,000 超の行が並ぶ=
#   中央値と線を比べる形では**撃つほど未発火に見える**。


def tl(sid, dept, samples, bounds, last_epoch=NOW):
    """(時刻ずれ, 文脈量) の並びと圧縮の区切りから、scan() が作る行と同じ形を作る。"""
    ctxs = [c for _, c in samples]
    stamps = [NOW + d for d, _ in samples]
    r = row(sid, dept, int(sorted(ctxs)[len(ctxs) // 2]), last_epoch=last_epoch, n=len(ctxs))
    r.update({"ctxs": ctxs, "stamps": stamps, "bounds": [NOW + d for d in bounds],
              "last": ctxs[-1], "max": max(ctxs)})
    return r


healthy = tl("c27eec97", "hq",
             # 越える→撃つ→また越える→また撃つ。最後の区切りの後は軽い行しか無い。
             [(-3600, 124149), (-3000, 171240), (-2400, 171799), (-1200, 129472), (-60, 10404)],
             [-3300, -2700, -1500, -100])
stuck = tl("dead0001", "future-room",
           [(-7200, 150000), (-5000, 190000), (-3000, 191000)], [-9000])
pending = tl("busy0002", "platform-se",
             [(-4000, 130000), (-120, 152299)], [-3500])
blind = row("nodata03", "kaizen-analyst", 150000)          # ctxs/stamps/bounds が無い行

rows2 = cw.mark_managed([healthy, stuck, pending, blind], {
    "c27eec97": "hq", "dead0001": "future-room",
    "busy0002": "platform-se", "nodata03": "kaizen-analyst"})
for r in rows2:
    r["managed"] = "relay:現行"                            # 起動文を持たない作り物なのでここで固定
o2 = {r["sid"]: r for r in cw.judge(rows2, COMPACT, ROTATE, now=NOW)}
check("撃っている部屋は未発火にしない(圧縮済)", o2["c27eec97"]["over_kind"] == "圧縮済",
      o2["c27eec97"]["over_kind"])
check("撃っている部屋は通知に載せない", o2["c27eec97"]["alert"] is False)
check("越えたまま撃っていない部屋は未発火のまま", o2["dead0001"]["over_kind"] == "未発火",
      o2["dead0001"]["over_kind"])
check("越えたまま撃っていない部屋は通知に載る", o2["dead0001"]["alert"] is True)
check("越えた便がまだ新しい部屋は処理中", o2["busy0002"]["over_kind"] == "処理中",
      o2["busy0002"]["over_kind"])
check("処理中は鳴らさない", o2["busy0002"]["alert"] is False)
check("測れない行は未発火へ倒す(黙らない)", o2["nodata03"]["over_kind"] == "未発火",
      o2["nodata03"]["over_kind"])
check("★変異: 圧縮の区切りを消すと同じ部屋が未発火に戻る",
      cw._fired_since(dict(healthy, bounds=[]), COMPACT, NOW) == "未発火")
check("★変異: 猶予を0にすると処理中は未発火になる",
      cw._fired_since(pending, COMPACT, NOW + cw.COMPACT_LAG_SEC) == "未発火")
check("★変異: 中央値だけ見る旧判定なら、撃っている部屋も線超で拾われてしまう",
      healthy["median"] >= COMPACT, str(healthy["median"]))

print("== 旧世代=『交代の最後の一筆』を暴走と読まない(研究室HQ msg 1540652585805942875) ==")
# ★実データをそのまま入れる= hq 2026-08-22。
#   台帳の差し替え(交代の完了)17:58 / 旧セッション c27eec97 の最終行 17:57:06 / 測ったのが 18:21:14。
#   旧判定は「最後の書き込みが30分以内」だけを見ていたので 24分06秒 → **見失い**と鳴った。
ROT = NOW - (23 * 60)                    # 交代が終わった時刻(=引き継ぎの書き出しの直後)
LAST_HANDOFF = NOW - (24 * 60 + 6)       # 旧セッションの最終行= 交代より前(引き継ぎそのもの)
LAST_RUNAWAY = ROT + cw.ROTATE_GRACE_SEC + 60   # 交代の後、猶予を越えてまだ書いている

settled = row("c27eec97", "hq", 150000, last_epoch=LAST_HANDOFF)
settled["managed"], settled["rotated_at"] = "relay:旧世代", ROT
runaway = row("dead0009", "future-room", 150000, last_epoch=LAST_RUNAWAY)
runaway["managed"], runaway["rotated_at"] = "relay:旧世代", ROT
nomark = row("old00010", "llm-edu", 150000, last_epoch=NOW - 60)
nomark["managed"], nomark["rotated_at"] = "relay:旧世代", 0.0   # rotated_at を持たない古い行

o3 = {r["sid"]: r for r in cw.judge([settled, runaway, nomark], COMPACT, ROTATE, now=NOW)}
check("★交代の最後の一筆は『交代済』=鳴らさない", o3["c27eec97"]["over_kind"] == "交代済",
      o3["c27eec97"]["over_kind"] + " last=%.0f rot=%.0f" % (LAST_HANDOFF, ROT))
check("★交代の最後の一筆は通知に載せない", o3["c27eec97"]["alert"] is False)
check("★交代の後にも書いていれば『見失い』", o3["dead0009"]["over_kind"] == "見失い",
      o3["dead0009"]["over_kind"])
check("★本物の見失いは通知に載る", o3["dead0009"]["alert"] is True)
check("rotated_atが無い行は従来どおり経過時間で判定(黙らせすぎない)",
      o3["old00010"]["over_kind"] == "見失い", o3["old00010"]["over_kind"])
check("★変異: 旧仕様(経過時間だけ)なら交代の最後の一筆が『見失い』になる",
      (NOW - LAST_HANDOFF) < cw.STALE_SEC,
      "24分06秒が30分より短い=旧判定では必ず鳴る、が再現できていない")
check("★変異: rotated_at を消すと同じ行が『見失い』へ戻る",
      cw._old_gen_kind(dict(settled, rotated_at=0.0), NOW) == "見失い")
check("★変異: 猶予を0にしても交代前の書き込みは黙る(境界の向きが逆でない)",
      cw._old_gen_kind(settled, NOW) == "交代済")

# 実物の配線= relay が実際に rotated_at を残すか(名前を1か所でしか知らない状態にしない)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_relay as _sr          # noqa: E402
_e = {}
_sr._stamp_rotation(_e, "old-sid-1234")
check("★relay側: 交代で rotated_at を残す", float(_e.get("rotated_at") or 0) > 0, str(_e))
check("★relay側: 直前の世代のIDも残す", _e.get("prev_session_id") == "old-sid-1234", str(_e))
check("★relay側: 見張りが読む名前と一致している(rotation_marks が拾える形)",
      "rotated_at" in _e and isinstance(_e["rotated_at"], float), str(type(_e.get("rotated_at"))))

print("== 「未発火」も経過時間で決めない=便が閉じたかで決める(研究室HQ msg 1540668457220186163) ==")
# ★実データをそのまま入れる= hq 2026-08-22。
#   越えた書き込み T=18:33 / 台帳 last_used_at L=18:21:17 / 判定時刻 now=19:21:13。
#   L <= T = **relayはまだ便を閉じていない**=撃つ機会が無かった=「便待ち」。鳴らさない。
#   実測: 19:21:13 に「未発火」と鳴った3分後(19:24:12)、便が入った瞬間に relay が撃って
#   223,483 → 84,156 まで落ちた。**直ったのではなく、便が来たから撃てた**=警報が誤り。
T_OVER = NOW - 2893.0            # 18:33:00(19:21:13 の 48分13秒前)
L_WAIT = NOW - 3596.0            # 18:21:17 = T より **前**(便が閉じていない)
L_CLOSED = NOW - 2473.0          # 18:40:00 = T より **後**(便が閉じたのに越えたまま)


def over_row(sid, dept, closed_at):
    """『最後の圧縮より後に線を越えた書き込みが1本ある』行を作る(T は共通)。"""
    r = tl(sid, dept, [(-7000, 30000), (T_OVER - NOW, 223483)], [-7200])
    r["closed_at"] = closed_at
    return r


waiting = over_row("ed37ac2f", "hq", L_WAIT)
真の未発火 = over_row("dead0003", "future-room", L_CLOSED)
boundary = over_row("edge0004", "platform-se", T_OVER)        # L == T ちょうど
just_closed = over_row("edge0005", "copy-director", NOW - 300.0)  # 閉じた直後(猶予の中)
nolegder = over_row("edge0006", "qa-reviewer", 0.0)           # 台帳が読めない行

rows3 = [waiting, 真の未発火, boundary, just_closed, nolegder]
for r in rows3:
    r["managed"] = "relay:現行"
o3 = {r["sid"]: r for r in cw.judge(rows3, COMPACT, ROTATE, now=NOW)}

check("★実データ(T=18:33 / L=18:21:17 / now=19:21:13)は便待ち",
      o3["ed37ac2f"]["over_kind"] == "便待ち", o3["ed37ac2f"]["over_kind"])
check("便待ちは鳴らさない", o3["ed37ac2f"]["alert"] is False)
check("★本物の未発火(便が閉じたのに越えたまま)は未発火のまま",
      o3["dead0003"]["over_kind"] == "未発火", o3["dead0003"]["over_kind"])
check("★本物の未発火は鳴る(鳴らす側を殺していない)", o3["dead0003"]["alert"] is True)
check("境界 L==T は黙る側へ倒す", o3["edge0004"]["over_kind"] == "便待ち",
      o3["edge0004"]["over_kind"])
check("便を閉じた直後は猶予の中=処理中", o3["edge0005"]["over_kind"] == "処理中",
      o3["edge0005"]["over_kind"])
check("台帳が読めない行は従来どおり経過時間へ倒す(黙らない)",
      o3["edge0006"]["over_kind"] == "未発火", o3["edge0006"]["over_kind"])
check("★便待ちは OVER_KINDS に説明がある(表に出せる)", "便待ち" in cw.OVER_KINDS)

# ★変異検査= 旧仕様(経過時間だけ)へ戻したら、実データが「未発火」に戻ること。
def _old_fired_since(r, compact_at, now):
    """旧仕様= `COMPACT_LAG_SEC` 単独で未発火を決めていた版。"""
    ctxs, stamps = r.get("ctxs") or [], r.get("stamps") or []
    bounds = r.get("bounds")
    if bounds is None or not stamps or len(stamps) != len(ctxs):
        return "未発火"
    last_b = max(bounds) if bounds else 0.0
    overs = [t for c, t in zip(ctxs, stamps) if t > last_b and c >= compact_at]
    if not overs:
        return "圧縮済"
    if now - max(overs) < cw.COMPACT_LAG_SEC:
        return "処理中"
    return "未発火"


check("★変異: 旧仕様なら実データが未発火に戻る(=この検査は穴を守っている)",
      _old_fired_since(waiting, COMPACT, NOW) == "未発火",
      _old_fired_since(waiting, COMPACT, NOW))
check("★変異: 旧仕様でも本物の未発火は未発火(2件の違いは L だけ)",
      _old_fired_since(真の未発火, COMPACT, NOW) == "未発火")
check("★変異: 猶予を L から測っていること(L 直後を now にすると処理中)",
      cw._fired_since(真の未発火, COMPACT, L_CLOSED + 60) == "処理中",
      cw._fired_since(真の未発火, COMPACT, L_CLOSED + 60))

# ★書く側(relay)と読む側(見張り)で名前が食い違っていないか= **実行して**確かめる。
#   台帳を偽物へ差し替え、close_marks() が何を拾うかを見る(本番の台帳には触らない)。
_real_local = cw.LOCAL
try:
    _tmp = tempfile.mkdtemp(prefix="cwtest_")
    os.makedirs(os.path.join(_tmp, "llm"))
    with open(os.path.join(_tmp, "llm", "room_sessions.json"), "w", encoding="utf-8") as _f:
        _f.write(json.dumps({
            # 正= relayが便の終わりに書く epoch
            "roomA": {"turn_closed_at": NOW - 100.0, "last_used_at": "2026-08-22T18:23:25"},
            # 退避= まだ turn_closed_at を持たない部屋(JSTの素の文字列)
            "roomB": {"last_used_at": "2026-08-22T18:23:25"},
            # どちらも無い部屋は入らない
            "roomC": {"active_session_id": "x"},
        }, ensure_ascii=False))
    cw.LOCAL = _tmp
    _cm = cw.close_marks()
finally:
    cw.LOCAL = _real_local
check("★close_marks: turn_closed_at を正として拾う", _cm.get("roomA") == NOW - 100.0, str(_cm))
check("★close_marks: 無い部屋は last_used_at(JST)へ退避する",
      abs((_cm.get("roomB") or 0) - datetime(2026, 8, 22, 18, 23, 25,
                                             tzinfo=cw.JST).timestamp()) < 1, str(_cm))
check("★close_marks: どちらも無い部屋は入れない(0=経過時間へ倒す)", "roomC" not in _cm, str(_cm))
check("★relay側: `turn_closed_at` を実際に書いている",
      "turn_closed_at" in open(os.path.join(os.path.dirname(cw.__file__), "session_relay.py"),
                               encoding="utf-8", errors="replace").read())

print("== 「管理外」を生きている窓と止まった窓へ分ける(研究室HQ msg 1540683236756164702) ==")
# HQの実測をそのまま型にする(2026-08-22 20:21 の6便):
#   eb3904a8 研究室メイン= 最終書き込み 08/22 16:29:26(=約4時間前で停止)なのに5便連続で鳴った
#   0ebedfa2 研究室メイン= 最終書き込み 20:12:39(=10分前)・context_guard が8回警告・本物
STOP_AT = NOW - 4 * 3600.0        # 止まった窓(打つ手が無い)
LIVE_AT = NOW - 600.0             # 生きている窓(Chamiが畳める)


def manual(sid, last_epoch, mtime=None):
    r = row(sid, "研究室メイン", 168562, last_epoch)
    r["mtime"] = last_epoch if mtime is None else mtime
    return cw.mark_managed([r], {})[0]


止まった窓 = manual("eb3904a8", STOP_AT)
生きた窓 = manual("0ebedfa2", LIVE_AT)
_j = {r["sid"]: r for r in cw.judge([止まった窓, 生きた窓], COMPACT, ROTATE, now=NOW)}
check("★1: 止まった管理外(4時間無音)は鳴らさない",
      _j["eb3904a8"]["over_kind"] == "停止窓" and not _j["eb3904a8"]["alert"], str(_j["eb3904a8"]))
check("★2: 生きている管理外(10分前)は「管理外」のまま鳴らす",
      _j["0ebedfa2"]["over_kind"] == "管理外" and _j["0ebedfa2"]["alert"], str(_j["0ebedfa2"]))
check("★2: 鳴らす枝を殺していない(alertに1件は残る)",
      len([r for r in _j.values() if r["alert"]]) == 1)
check("★どちらも読めない行は鳴らす側へ倒す",
      cw._manual_kind({"last_epoch": 0.0, "mtime": 0.0}, NOW) == "管理外")

print("== 生死の根拠は器(mtime)ではなく中身(研究室HQ msg 1540926977874337802) ==")
# ★★ここは 2026-08-23 まで**逆を検査していた**= 「usage行より mtime が新しければ生きている扱い」。
#   その1行が `alive = max(last_epoch, mtime)` を固定し、**合格しているテストが穴を守っていた**。
#   実データ(89b029da 研究室メイン):
#     中身の最終行 08/23 00:31 / mtime 08/23 12:02(差 691分) → 12:21 に「管理外」で発火。
#   中身は一文字も増えていない=打つ手の無い警報。mtime は last_epoch が読めない時の代役へ落とす。
DEAD_BODY = NOW - 691 * 60.0        # 中身の最終行= 11時間31分前
FRESH_JAR = NOW - 19 * 60.0         # 器だけ新しい= 19分前(STALE_SEC の内側)
実データ = manual("89b029da", DEAD_BODY, mtime=FRESH_JAR)
check("★実データ: 中身が止まっていれば mtime が新しくても停止窓",
      cw._manual_kind(実データ, NOW) == "停止窓", cw._manual_kind(実データ, NOW))
_d = {r["sid"]: r for r in cw.judge([manual("89b029da", DEAD_BODY, mtime=FRESH_JAR)],
                                    COMPACT, ROTATE, now=NOW)}
check("★実データ: 判定まで通しても鳴らない", _d["89b029da"]["alert"] is False, str(_d["89b029da"]))
check("★変異: 旧仕様(max(last_epoch, mtime))なら同じ行が鳴る=この検査は穴を守っている",
      (NOW - max(DEAD_BODY, FRESH_JAR)) < cw.STALE_SEC,
      "旧仕様でも黙る=検体が穴を再現できていない")
# ★退避の枝を殺していない= last_epoch が読めない行では mtime を使う(fail-open の向きは維持)
check("★last_epoch が無い行は mtime を代役に使う(新しければ鳴る)",
      cw._manual_kind({"last_epoch": 0.0, "mtime": FRESH_JAR}, NOW) == "管理外")
check("★last_epoch が無い行は mtime を代役に使う(古ければ黙る)",
      cw._manual_kind({"last_epoch": 0.0, "mtime": DEAD_BODY}, NOW) == "停止窓")
# ★★「停止窓」を管理下(現行)へ広げてはいけない= 2026-08-23 に足しかけて実測で取り下げた枝。
#   実データ 3800efa5(プラットフォームSE・relay現行)= 121便すべてが圧縮の区切りの後・
#   最新 219,630(交代線超)・最終書き込み 09:05(=3時間37分前)。
#   「止まっているから黙る」を管理下へ付けると、**盤上で一番危ない行が消えた**。
#   管理外の停止窓は「打てる手がその窓の前のChamiにしか無い」から正しいのであって、
#   管理下の未発火は relay 側の不具合=窓が止まっていても今すぐ調べられる。
_止まった管理下 = tl("mgd00011", "platform-se",
                 [(-40000, 130000), (-13000, 219630)], [], last_epoch=NOW - 13000.0)
_止まった管理下["managed"], _止まった管理下["closed_at"] = "relay:現行", NOW - 12000.0
_m = {r["sid"]: r for r in cw.judge([_止まった管理下], COMPACT, ROTATE, now=NOW)}
check("★止まっていても管理下の本物の未発火は鳴らし続ける(停止窓で黙らせない)",
      _m["mgd00011"]["over_kind"] == "未発火" and _m["mgd00011"]["alert"] is True,
      str(_m["mgd00011"]["over_kind"]))
check("★その行は実際に『止まっている』(=止まりを理由に黙らせていないことの証明)",
      cw._stalled(_止まった管理下, NOW) is True)

# ★変異(HQ仕様3)= 閾値を極端へ振ると、1と2は**両方同時には満たせない**。
#   = 判定が本当に「最後の書き込みの新しさ」で分かれている証明。
_real_stale = cw.STALE_SEC
try:
    cw.STALE_SEC = 0.0
    _z = {r["sid"]: r for r in cw.judge([manual("eb3904a8", STOP_AT), manual("0ebedfa2", LIVE_AT)],
                                        COMPACT, ROTATE, now=NOW)}
    check("★変異: 閾値0だと生きている窓まで黙る(=2が落ちる)",
          _z["0ebedfa2"]["over_kind"] == "停止窓", str(_z["0ebedfa2"]))
    cw.STALE_SEC = 10 ** 9
    _i = {r["sid"]: r for r in cw.judge([manual("eb3904a8", STOP_AT), manual("0ebedfa2", LIVE_AT)],
                                        COMPACT, ROTATE, now=NOW)}
    check("★変異: 閾値∞だと止まった窓まで鳴る(=1が落ちる)",
          _i["eb3904a8"]["over_kind"] == "管理外" and _i["eb3904a8"]["alert"], str(_i["eb3904a8"]))
finally:
    cw.STALE_SEC = _real_stale
check("★変異の後始末: 閾値が元へ戻っている", cw.STALE_SEC == _real_stale)
check("★停止窓は alert() の見出しに載せない",
      "停止窓" not in ("未発火", "見失い", "管理外"))

print("== 窓が滑るだけで中央値が上がらない(研究室HQ msg 1540926977874337802 穴②) ==")
# ★★実物の transcript を1本作って、**本物の scan() を時刻だけ変えて3回**通す。
#   HQの実測(89b029da・書き込みは一切増えていない):
#     09:21 便=78 中央値= 83,757 / 11:21 便=55 中央値= 86,183 / 12:21 便=9 中央値=122,320
#   = 止まった窓では小さい初期の便から先に窓の外へ落ち、**一文字も書かずに線を越える。**
#   直した後は窓を「そのセッションの最後の書き込み」から遡って切るので、時刻をずらしても動かない。
import statistics                                        # noqa: E402

_N便, _間隔 = 78, 580.0                                   # 12.4時間ぶんの並び(12時間の窓より長い)
_終わり = time.time() - 11.5 * 3600                       # 最後の書き込み= 11時間半前(=止まっている)
_並び = [(_終わり - (_N便 - 1 - i) * _間隔, 20000 + int(i * (135000 - 20000) / (_N便 - 1)))
         for i in range(_N便)]


def _write_transcript(dirpath, name, samples):
    """scan() が実際に読む形の transcript を作る(判定と分岐は本物のまま回す)。"""
    p = os.path.join(dirpath, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "起動"},
                            "timestamp": datetime.utcfromtimestamp(
                                samples[0][0]).strftime("%Y-%m-%dT%H:%M:%S.000Z")}) + "\n")
        for ts, ctx in samples:
            f.write(json.dumps({
                "type": "assistant",
                "timestamp": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "message": {"model": "claude-opus-5",
                            "usage": {"input_tokens": ctx, "cache_read_input_tokens": 0,
                                      "cache_creation_input_tokens": 0}}}) + "\n")
    return p


def _old_window_median(samples, now, hours=12.0):
    """旧仕様= 窓を `now` から遡って切っていた版(この行が穴の本体だった)。"""
    sel = [c for t, c in samples if t >= now - hours * 3600]
    return int(statistics.median(sel)) if sel else 0


class _FakeClock(object):
    """scan() の中の `time.time()` だけを差し替える(外へ出る手ではなく**時計**を偽物にする)。"""

    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now


_proj = tempfile.mkdtemp(prefix="cwscan_")
os.makedirs(os.path.join(_proj, "D--dummy"))
_write_transcript(os.path.join(_proj, "D--dummy"), "aa11bb22-0000-0000-0000-000000000000.jsonl",
                  _並び)

# ★同じファイルを、時計だけ変えて3回数える(HQの 09:21 / 11:21 / 12:21 と同じ実験)
_時計 = [_終わり, _終わり + 10 * 3600, _終わり + 11.7 * 3600]
_real_projects, _real_time = cw.PROJECTS, cw.time
_ずらし = []
try:
    cw.PROJECTS = _proj
    for _t in _時計:
        cw.time = _FakeClock(_t)
        _row = cw.scan(12.0)[0]
        _ずらし.append(_row["median"])
finally:
    cw.PROJECTS, cw.time = _real_projects, _real_time

_旧 = [_old_window_median(_並び, _t) for _t in _時計]
check("★変異: 旧仕様なら同じ検体が時刻だけで違う中央値を出す(穴の再現)",
      len(set(_旧)) == 3, str(_旧))
check("★変異: 旧仕様なら書き込み0のまま線を越える",
      max(_旧) >= COMPACT and min(_旧) < COMPACT, str(_旧))
check("★直った側: 本物の scan() は時刻をずらしても中央値が動かない",
      len(set(_ずらし)) == 1, str(_ずらし))
check("★直った側: その中央値は線の下(=鳴らない)", _ずらし[0] < COMPACT, str(_ずらし[0]))
check("★窓は12時間ぶんだけ残す(全便をそのまま数えていない)",
      0 < _row["n"] < _N便, "%d / %d" % (_row["n"], _N便))
check("★止まった窓なので判定まで通しても鳴らない",
      all(not r.get("alert") for r in cw.judge(cw.mark_managed([_row], {}), COMPACT, ROTATE)),
      str(_row.get("over_kind")))

print("== 変異検査(旧仕様へ戻したら落ちること) ==")
real_judge = cw.judge


def _old_judge(rows, compact_at, rotate_at, now=None):
    """初版の判定= `not managed` 付き(管理外しか数えない)。"""
    out = []
    for r in rows:
        if not r.get("managed") and r["median"] >= compact_at:
            r["over_kind"], r["level"], r["alert"] = "管理外", "圧縮線超", True
            out.append(r)
    return out


cw.judge = _old_judge
mrows = cw.mark_managed(sample(), managed_map())
mover = {r["sid"]: r for r in cw.judge(mrows, COMPACT, ROTATE, now=NOW)}
cw.judge = real_judge
check("★変異: 旧仕様では管理下の線超(2f7b8457)が消える", "2f7b8457" not in mover,
      "旧仕様でも拾えている=この検査は何も守っていない")
check("★変異: 旧仕様の件数は2件だけ", len(mover) == 2, str(len(mover)))

print("")
print("PASS=%d FAIL=%d" % (ok, ng))
sys.exit(1 if ng else 0)
