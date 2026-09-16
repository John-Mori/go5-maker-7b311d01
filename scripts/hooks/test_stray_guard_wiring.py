#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""転送ツール混入ガードの**配線**の回帰ガード(判定そのものの試験ではない)。

なぜ要るか(2026-09-16 aegis-gl・ケヴィン・デブライネ):
  起動側フック `scripts/hooks/stray_transfer_guard.decide_stray()` は
  `check_no_stray_transfer_tools.check_root()` を import して引く。そして
  **例外は握って `(None, [])` を返す= fail-open**(ガードでセッションを殺さない)。
  この設計は正しい。だが実際にこうなった:
    ab3280f 改修αが本体を再帰化した際 `check_root()` が消えた
      → decide_stray は ImportError を握って**黙った**= ガードが無効化されたのに誰も気付かない
    0ec296c 改修αが後方互換APIとして復活させて直った(気付いてもらえたのは運)
  fail-open は「落ちない」ための設計であって「壊れたことに気付く」設計ではない。
  そこを埋めるのがこのテストだ= **本体のAPI契約と、炎上の実物と同じ配置で鳴ることを固定入力で見る。**

実行= python scripts/hooks/test_stray_guard_wiring.py   (rc=0 で緑 / rc=1 で赤)
"""
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
for _p in (os.path.join(ROOT, "scripts"), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PASS = 0
FAIL = 0


def _check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


# 炎上の実物と同じファイル名・同じ配置(Chami msg 1549490188701409385 の相手=
# 咲季の便 msg 1549488334873825351 に載っていた2本)。★ここを緩めるな。
INCIDENT = {
    "local/file_transfer/1_ファイアウォール許可_管理者.bat":
        '@echo off\r\nrem スマホ受信サーバー用のファイアウォール許可\r\n'
        'netsh advfirewall firewall add rule name="upload_server" dir=in action=allow '
        'protocol=TCP localport=8765\r\npause\r\n',
    "local/file_transfer/2_受信サーバー起動.bat":
        '@echo off\r\ncd /d E:\\転送ツール\r\npython upload_server.py\r\npause\r\n',
}
# 転送と無関係な正規の起動bat。★これを鳴らしたら誤検知=「常に誤発火する安全網は無視される」(§3)。
INNOCENT = {
    "起動_5秒動画メーカー.bat": '@echo off\r\nstart "" http://localhost:8080/index.html\r\n',
    "scripts/run_status.bat": '@echo off\r\npowershell -File scripts\\status.ps1\r\n',
}


def _build(base, files):
    for rel, body in files.items():
        p = os.path.join(base, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(body)


def main():
    print("== 転送ツール混入ガード 配線の回帰ガード ==")

    # ① 本体のAPI契約。★ab3280f でここが落ちて、起動側フックが黙って無効化された。
    try:
        import check_no_stray_transfer_tools as chk
        has_root = callable(getattr(chk, "check_root", None))
        has_tree = callable(getattr(chk, "check_tree", None))
    except Exception as e:                       # noqa: BLE001
        chk, has_root, has_tree = None, False, False
        print(f"  (import 失敗: {e})")
    _check("① 本体に check_root() が在る(起動側フックが引く唯一のAPI)", has_root)
    _check("① 本体に check_tree() が在る(pre-commit 経路の main が引く)", has_tree)

    import stray_transfer_guard as g
    _check("① 起動側フックに decide_stray() が在る", callable(getattr(g, "decide_stray", None)))

    tmp = tempfile.mkdtemp(prefix="strayguard_")
    try:
        # ② 炎上の実物と同じ配置で、本体が2本とも名指しで落とす(ルート直下ではなく1階層下)
        _build(tmp, INCIDENT)
        hits = chk.check_root(tmp) if has_root else None
        names = sorted(n for n, _w in (hits or []))
        _check("② 炎上の実物と同じ配置(local/file_transfer/)で2件とも捕まる",
               len(names) == 2)
        _check("② 1_ファイアウォール許可_管理者.bat が名指しされる(名前は転送系に当たらない)",
               any(n.endswith("1_ファイアウォール許可_管理者.bat") for n in names))
        _check("② 2_受信サーバー起動.bat が名指しされる",
               any(n.endswith("2_受信サーバー起動.bat") for n in names))

        # ③ 起動側フックが、同じ配置で**文面を返す**(ここが配線。黙ったら赤)
        _orig_root = g.ROOT
        try:
            g.ROOT = tmp
            msg, gh = g.decide_stray({"hook_event_name": "SessionStart"})
        finally:
            g.ROOT = _orig_root
        _check("③ decide_stray が黙らない(fail-open に落ちていない)", bool(msg))
        _check("③ 文面に実物のパスが2本とも載る",
               bool(msg) and "1_ファイアウォール許可_管理者.bat" in msg
               and "2_受信サーバー起動.bat" in msg)
        _check("③ 退避先 E:\\転送ツール\\ を案内している", bool(msg) and "E:\\転送ツール" in msg)
        # 本体が再帰化した後も文面が「ルート直下」と言っていたら、退避先を誤らせる嘘になる
        _check("③ 文面が「ルート直下」と言っていない(本体は再帰する)",
               bool(msg) and "ルート直下" not in msg)

        # ④ 誤検知ガード。転送と無関係な正規の起動batしか無い木では**黙る**
        tmp2 = tempfile.mkdtemp(prefix="strayguard_ok_")
        try:
            _build(tmp2, INNOCENT)
            hits2 = chk.check_root(tmp2) if has_root else None
            _check("④ 転送と無関係な正規の起動batは1件も落とさない", hits2 == [])
            try:
                g.ROOT = tmp2
                msg2, _ = g.decide_stray({})
            finally:
                g.ROOT = _orig_root
            _check("④ 混入が無い時は起動側フックが黙る(毎便鳴る安全網は無視される)", msg2 is None)
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ⑤ commit 経路の配線。正本 scripts/hooks/pre-commit がガードを**表記チェックの早期exitより前**で叩く
    pc = os.path.join(ROOT, "scripts", "hooks", "pre-commit")
    src = ""
    try:
        with open(pc, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError:
        pass
    i_guard = src.find("check_no_stray_transfer_tools")
    i_exit = src.find("[ -z \"$files\" ] && exit 0")
    _check("⑤ pre-commit がガードを叩く", i_guard >= 0)
    _check("⑤ ガードは .md 無しコミットの早期exitより前に在る(順序に意味がある)",
           i_guard >= 0 and i_exit >= 0 and i_guard < i_exit)

    print(f"\n{PASS} PASS / {FAIL} FAIL")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
