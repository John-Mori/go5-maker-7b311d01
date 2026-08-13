#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daemon_code_version の検査(純関数＋配線)。

なぜ要るか= C-042。**機構を足しても、載せ替え(配線)が無ければ在るのに効かない。**
  2026-08-13 に研究室HQが踏んだのがそれ= absence_watchdog の滞留警報は 8/12 に入っていたのに、
  古いプロセスが13時間走り続けて一度も鳴かなかった。ここでは「版を測れるか」だけでなく
  **supervise_daemons.ps1 がその測定を実際に呼んでいるか**まで機械が数える。

★このテストは**先に落ちるのを見てから**置いた(配線前は検査4/5/6が FAIL)。
走らせ方= python scripts/_daemons/test_daemon_code_version.py
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daemon_code_version as dcv  # noqa: E402

NG = 0


def check(name, ok, detail=""):
    global NG
    print(("OK   " if ok else "FAIL ") + name + (("  " + detail) if detail and not ok else ""))
    if not ok:
        NG += 1


def main():
    # 1) 写しと正本(ps1の$daemons)が両方向で一致する=どちらかに足した時に落ちる
    ps1 = dcv.supervised_from_ps1()
    check("SUPERVISED と supervise_daemons.ps1 の $daemons が一致(両方向)",
          sorted(ps1) == sorted(dcv.SUPERVISED),
          "ps1=%s / py=%s" % (sorted(ps1), sorted(dcv.SUPERVISED)))

    # 2) 監視対象の実体が在る(パスの打ち間違いは静かに「版0」になる)
    missing = [rel for _n, rel in dcv.SUPERVISED
               if not os.path.exists(os.path.join(dcv.ROOT, rel))]
    check("7本の .py が実在する", missing == [], "無い: %s" % missing)

    # 3) 閉包が推移的に辿れている(absence_watchdog は自分＋4本を起動時に固定する)
    names = {os.path.basename(p) for p in dcv.closure(dict(dcv.SUPERVISED)["absence_watchdog"])}
    want = {"absence_watchdog.py", "session_presence.py", "dept_names.py",
            "session_rooms.py", "dept_daemon.py"}
    check("absence_watchdog の閉包に import 先が入る", want <= names,
          "足りない: %s" % sorted(want - names))

    # 4) mtime= 「編集が落ち着いたか」だけに使う。import 先が新しければそちらを拾う
    with tempfile.TemporaryDirectory(prefix="qa_dcv_") as d:
        os.makedirs(os.path.join(d, "scripts", "llm"))
        dirs = [("scripts", "llm")]
        a = os.path.join(d, "scripts", "llm", "a_entry.py")
        b = os.path.join(d, "scripts", "llm", "b_dep.py")
        open(a, "w", encoding="utf-8").write("from b_dep import x\n")
        open(b, "w", encoding="utf-8").write("x = 1\n")
        old = time.time() - 3600
        os.utime(a, (old, old))
        epoch, who = dcv.version_of(a, root=d, import_dirs=dirs)
        check("import 先の方が新しければ、そちらが版になる(mtime側)",
              who == os.path.normpath(b) and epoch > old + 1, "who=%s" % who)

        # 5) ★版はmtimeでなく中身。**gitの書き戻し(中身同じ・mtimeだけ動く)で版が動かない**こと。
        #    2026-08-13 実測= 並列セッションのgit操作で7本全部が同じ秒になった。
        #    mtime判定のままなら、git操作のたびに常駐7本が全滅再起動していた。
        h0 = dcv.code_hash(a, root=d, import_dirs=dirs)
        touched = time.time()
        os.utime(a, (touched, touched))
        os.utime(b, (touched, touched))
        check("mtimeだけ動いても版(sha1)は動かない",
              dcv.code_hash(a, root=d, import_dirs=dirs) == h0)

        # 6) import 先の**中身**が変われば版は動く(起動時に固定される物なので、これが本命)
        open(b, "w", encoding="utf-8").write("x = 2\n")
        check("import 先の中身が変われば版(sha1)が動く",
              dcv.code_hash(a, root=d, import_dirs=dirs) != h0)

    # 7) 配線= ps1 が daemon_code_version を実際に呼んでいる(呼ばなければ測定は死んでいる)
    src = open(dcv.PS1, encoding="utf-8", errors="replace").read()
    check("supervise_daemons.ps1 が daemon_code_version.py を呼んでいる",
          "daemon_code_version.py" in src)

    # 8) 配線= 起動した版を記録している(記録しなければ「そのpidが何を読んだか」が消える)
    check("ps1 が起動時の版を local\\_daemon_codever へ記録している",
          "_daemon_codever" in src and "Set-Content -LiteralPath $verFile" in src)

    # 8.5) 配線= 控えが無い相手は5列目(最終コミット時刻)で判定する。ここが繋がっていないと
    #      「この機構より前から走っているプロセス」= まさに今回の14.9日組が素通りする。
    check("ps1 が控え無しの判定に $cv.Commit(5列目)を使っている",
          "$cv.Commit" in src and "$parts.Count -ge 5" in src)

    # 9) 間引き= 連続改修で再起動が便を食い潰した 7/29 の事故を繰り返さない。
    #    daemon_keeper と同じ2つの下限(落ち着き90秒 / 同じ常駐は600秒に1回)を持つこと。
    check("ps1 に debounce(90s) と最短間隔(600s) の下限が在る",
          "$codeDebounceSec = 90" in src and "$codeMinAgeSec  = 600" in src)

    # 10) ★受け渡しの形= ps1 は $parts.Count -ge 4 で捨てる。列が1本足りないだけで
    #     $codeVer が空になり、機構は**在るのに何もしない**(ログに no data と出るだけ)。
    #     人が気をつける所ではないので、実際に走らせて列の数と中身を数える。
    out = subprocess.run([sys.executable, os.path.join(HERE, "daemon_code_version.py")],
                         capture_output=True, text=True, encoding="utf-8")
    lines = [l for l in out.stdout.splitlines() if l.strip()]
    cols_ok = len(lines) == len(dcv.SUPERVISED) and all(len(l.split("\t")) >= 5 for l in lines)
    check("出力が 1常駐1行・5列(name/mtime/file/sha1/commit)", cols_ok,
          "rc=%s 行=%d 例=%r" % (out.returncode, len(lines), lines[0] if lines else ""))
    if cols_ok:
        name, _e, _f, sha, commit = lines[0].split("\t")[:5]
        check("4列目が閉包のsha1と一致する",
              sha == dcv.code_hash(dict(dcv.SUPERVISED)[name]), "出力=%s" % sha)
        # 11) 記録の無いプロセス用の物差し。0だと ps1 は「判定できない」として載せ替えない=
        #     ここが黙って0になると、15日古いプロセスを永久に見逃す(実際に5本居た)。
        check("5列目(最終コミットepoch)が取れている", float(commit) > 0, "出力=%s" % commit)

    # 12) 配線= 記録の無いプロセスを最終コミット時刻で判定する経路が ps1 に在る
    check("ps1 に「記録が無い相手」の判定(Commit)が在る",
          "$cv.Commit" in src and "Commit = [double]$parts[4]" in src)

    print(("NG %d" % NG) if NG else "OK 全PASS")
    return 1 if NG else 0


if __name__ == "__main__":
    sys.exit(main())
