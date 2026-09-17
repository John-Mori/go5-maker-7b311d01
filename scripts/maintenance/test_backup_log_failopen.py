# -*- coding: utf-8 -*-
"""backup_local_to_drive.ps1 の Write-Log が **ログのロックで死なない** ことを見る。

0歩目=壊れていた実物(2026-09-17 イージス研究室で再現):
  04:00 の go5_backup_local_daily が 1行書いた直後に
    Add-Content : 別のプロセスで使用されているため、プロセスはファイル
    'local\\backup.log' にアクセスできません。 ... [Add-Content], IOException
  で止まり、`$ErrorActionPreference='Stop'` により **スクリプトごと落ちた**。
  結果、2本目の `00_AI-HQ` は1バイトも取られなかった= **ログが忙しいだけで
  バックアップが死んだ**。11:50 に手で回して同じ落ち方を再現済み。

ロックの正体(推測ではなく実測):
  backup.log を自分で開く実験= share=Read OK / share=ReadWrite OK /
  share=None FAIL / share=Write FAIL。
  → 掴んでいる側は **読み取りで開いている**。Add-Content はその読み手を
    締め出す共有モードを選ぶので落ちる。ここを FileShare.ReadWrite で開けば通る。

この検査がすること:
  実物の ps1 から **Write-Log の本体をそのまま取り出して実行**する
  ($LogFile だけ一時ファイルへ差し替え= 偽物にするのは書き込み先1つだけ)。
  同じロックの下で:
    - ★must-fail= 旧実装(Add-Content 1行)は **例外を投げる**
    - 本物(今の Write-Log)は **投げずに1行書き足す**
  両方を1回の実行で見るので、どちらかが崩れたら必ず赤くなる。

走らせ方= python scripts/maintenance/test_backup_log_failopen.py
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PS1 = os.path.join(HERE, "backup_local_to_drive.ps1")

FAIL = []


def _ok(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        FAIL.append(msg)


def extract_function(src, name):
    """ps1 のソースから `function <name>(...) { ... }` を波括弧の対応で切り出す。

    ★丸ごと dot-source すると本番のバックアップが走ってしまうので、関数だけ borrow する。
      切り出した中身は **一字も書き換えずに実行する**(文字列一致で済ませない)。
    """
    m = re.search(r"^function\s+" + re.escape(name) + r"\s*\(", src, re.M)
    if not m:
        return ""
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    return ""


def run_ps(script):
    """PowerShell を1回回して (rc, stdout+stderr) を返す。"""
    p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", script],
                       capture_output=True, timeout=120)
    out = (p.stdout + p.stderr).decode("cp932", "replace")
    return p.returncode, out


def main():
    print("== backup の Write-Log がロックで死なないか ==")
    src = open(PS1, encoding="utf-8").read()

    body = extract_function(src, "Write-Log")
    _ok(bool(body), "ps1 から Write-Log 本体を取り出せる(名前が変わったらここで気づく)")
    if not body:
        print("\n1 FAIL")
        return 1
    _ok("FileShare]::ReadWrite" in body,
        "Write-Log は FileShare.ReadWrite で開く(読み手に締め出されない)")
    _ok("$ErrorActionPreference" not in body and "throw" not in body,
        "Write-Log は例外を投げ直さない(ログの失敗を本番へ伝播させない)")

    tmp = tempfile.mkdtemp(prefix="bklog_")
    log = os.path.join(tmp, "backup.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write("2026-09-17 04:00:00 seed\n")

    # ★0歩目の再現= 掴んでいる側と同じ開き方(読み取り・共有はReadWrite)でロックする。
    holder = open(log, "r", encoding="utf-8")
    try:
        # --- must-fail: 旧実装(Add-Content 1行)は同じロックの下で落ちる ---
        rc, out = run_ps(
            "$ErrorActionPreference='Stop'; $LogFile='%s'; "
            "try { Add-Content -Path $LogFile -Value 'OLD' -Encoding utf8; "
            "Write-Output 'OLD-WROTE' } catch { Write-Output ('OLD-THREW:' + "
            "$_.Exception.GetType().Name) }" % log.replace("\\", "\\\\"))
        _ok("OLD-THREW" in out,
            "must-fail: 旧実装(Add-Content)は同じロックで例外= あの日の落ち方を再現 → "
            + out.strip().splitlines()[-1][:70])

        # --- 本物: 取り出した Write-Log をそのまま実行する ---
        before = open(log, encoding="utf-8").read()
        rc, out = run_ps(
            "$ErrorActionPreference='Stop'; $LogFile='%s'; %s ; "
            "Write-Log 'NEW'; Write-Output 'SURVIVED'"
            % (log.replace("\\", "\\\\"), body))
        after = open(log, encoding="utf-8").read()
        _ok("SURVIVED" in out and rc == 0,
            "本物の Write-Log はロック下でも例外で止まらない(次の行まで進む)")
        _ok(after != before and after.rstrip().endswith("NEW"),
            "本物の Write-Log はロック下でも backup.log へ1行書けている")
        _ok(before in after,
            "追記であって上書きではない(先にあった行が消えない)")

        # --- 書けない時は黙らず、脇のファイルへ残す ---
        side = [f for f in os.listdir(tmp) if f.startswith("backup.log.blocked-")]
        _ok(side == [],
            "本体へ書けた時は脇のファイルを作らない(記録先を2つに増やさない)")
    finally:
        holder.close()

    print("\n" + ("ALL PASS" if not FAIL else "%d FAIL" % len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
