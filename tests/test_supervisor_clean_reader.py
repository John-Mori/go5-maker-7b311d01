# -*- coding: utf-8 -*-
"""GOLDEN: LAN配信サーバ(clean_reader --serve)が常駐の名簿に載っている  2026-09-03

依頼= 分析部門アーモンドアイ(研究室HQ経由 DISPATCH-aegis-gl-1788368962368)。
症状= Chamiがスマホで http://192.168.10.103:8000/ を開くと「サーバが見つかりません」。
真因= --serve が**対話セッションのバックグラウンドタスク**として起動されていて、
      セッションを畳むたびに道連れで死んでいた(1セッション中に3回=C-038 再発)。

この検査が守る不変条件:
  ①常駐の名簿(supervise_daemons.ps1 の $daemons)に居る= 落ちても10分以内に戻る
  ②python.exe で起動する(pythonw.exe は stdout/stderr が None になり serve() の
    最初の print() で落ちる=**無音で死ぬ**形になる)
  ③引数(--serve --port 8000)が起動行に実際に載る配線がある
  ④一発起動(手動の変換実行)と取り違えない= Match が --serve を含む
  ⑤このファイルはASCII限定(PS5.1 は BOM無しをANSIで読む=非ASCIIで構文が壊れる)

★これは**静的な検査**だ。実際に落として戻ることは 2026-09-03 02:24 に実物で確認した
  (pid 16084 を落とす→接続拒否→supervise 1周→pid 26788 で復帰→127.0.0.1 と
   192.168.10.103 の両方が 200)。ここはその配線が**消えないこと**だけを見張る。

実行: PYTHONIOENCODING=utf-8 python tests/test_supervisor_clean_reader.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS1 = os.path.join(ROOT, "scripts", "_daemons", "supervise_daemons.ps1")

_fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        _fails.append(name)


raw = io.open(PS1, "rb").read()
src = raw.decode("utf-8", "replace")

check("①名簿に clean_reader_serve が載っている", "clean_reader_serve" in src)
check("①起動するのは scripts\\analysis\\clean_reader.py",
      "scripts\\analysis\\clean_reader.py" in src)
# ★コメント行は数えない= なぜ pythonw が駄目かを**コメントで書き残す**のが規律なのに、
#   「文字列としての pythonw の不在」を測ると、その記録ごと禁じてしまう。
_code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
check("②python.exe で起動する(pythonw は使わない)",
      not any("pythonw" in ln for ln in _code))
check("②起動行は python を直接叩く",
      any(("&& python \"' + $d.Rel" in ln) for ln in _code))
check("③引数を起動行へ載せる配線がある($argStr)",
      "$argStr" in src and re.search(r"\$argStr\s*=\s*' '\s*\+\s*\$d\.Args", src) is not None)
check("③名簿の Args が --serve --port 8000", "'--serve --port 8000'" in src)
check("④Match は --serve を含む(手動の一発起動と取り違えない)",
      "clean_reader.py*--serve" in src)
check("④Match が在ればそれで探す(File 決め打ちにしない)",
      "Get-DaemonMatch" in src and "Find-DaemonProcesses $match" in src)
check("⑤ASCII限定(PS5.1のコードページ事故を避ける)",
      all(b < 128 for b in raw))

# ログの受け皿= 標準出力/標準エラーを両方1本のファイルへ落とす(無音で死なせない)
check("ログ: >> と 2>&1 の両方が起動行に在る",
      ">>" in src and "2>&1" in src)
check("ログ: 置き場は local\\_work\\clean_reader_serve.out.log",
      "local\\_work\\clean_reader_serve.out.log" in src)
check("ログ: 置き場が無ければ作る(初回起動で消えない)",
      "New-Item -ItemType Directory -Path $logDir" in src)

# 既存の常駐を1つも落としていないこと(名簿は**足すだけ**)
for name in ("absence_watchdog", "local_responder", "gemini_responder",
             "office_daily", "claude_responder", "daemon_keeper", "discord_gateway"):
    check("回帰: %s が名簿に残っている" % name, ("Name='%s'" % name) in src)

print()
print("FAILS:", len(_fails))
for n in _fails:
    print(" -", n)
sys.exit(1 if _fails else 0)
