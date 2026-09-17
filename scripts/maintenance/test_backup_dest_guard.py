# -*- coding: utf-8 -*-
r"""backup_local_to_drive.ps1 の宛先検証(安全弁)を実行で確かめる検査台。

2026-09-17 04:00 の全skip(ABORT)を受けて新設。守りたい性質は2つで、
どちらも「判定と分岐は本物のまま」回して確かめる——外へ出る手(robocopy /
Remove-Item / persona_send)は GO5_BACKUP_LIB_ONLY=1 で一切定義も実行もされない。

  1. 宛先ツリーが違う(Shared Drive が G:\ で先に来た等)なら必ず止まる。
     ここを緩めると retention の Remove-Item が別ツリーを消す(QA 2026-07-17)。
  2. ツリーは正しいのに日付スナップショットの leaf だけ無い場合は通す。
     leaf はこのスクリプトが作る物で、初回・宛先の整理後・未ハイドレート中は
     正当に存在しない。ここで止めたせいで 9/17 は2ソースとも取れなかった。

使い方: python scripts/maintenance/test_backup_dest_guard.py
"""
import base64
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS1 = ROOT / "scripts" / "maintenance" / "backup_local_to_drive.ps1"
BAK = ROOT / "scripts" / "maintenance" / "backup_local_to_drive.ps1.bak_20260917_destanchor"
DEST_CFG = ROOT / "local" / "backup_dest.txt"

# 本番と同じ日本語の相対宛先(cp932 事故の回帰も兼ねる)
REL_JA = "AFI5秒動画設計・戦略運用\\001_システムバックアップ\\local"

_ran = []
_fails = []


def ok(name):
    _ran.append(name)
    print("  PASS %s" % name)


def bad(name, got, want):
    _ran.append(name)
    _fails.append(name)
    print("  FAIL %s: got=%r want=%r" % (name, got, want))


def eq(name, got, want):
    if got == want:
        ok(name)
    else:
        bad(name, got, want)


_last_err = [""]


def _ps(script):
    # powershell.exe emits its progress stream to stderr as CLIXML; keep it out of the
    # value under test. A real failure still shows up as an empty stdout.
    head = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n"
        "$ProgressPreference='SilentlyContinue'\n"
    )
    enc = base64.b64encode((head + script).encode("utf-16-le")).decode("ascii")
    p = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
        capture_output=True,
    )
    _last_err[0] = p.stderr.decode("utf-8", "replace").strip()
    return p.stdout.decode("utf-8", "replace").strip()


def state(root, rel):
    """本番 ps1 の Get-DestState を、実ディレクトリ相手にそのまま実行する。"""
    return _ps(
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n"
        "$env:GO5_BACKUP_LIB_ONLY='1'\n"
        ". '%s'\n"
        "Get-DestState '%s' '%s'\n" % (PS1, root, rel)
    )


def legacy(root, rel):
    """変更前の判定(leaf の Test-Path だけ)を同じ場面で実行して分岐を見る。"""
    return _ps(
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n"
        "if (-not (Test-Path (Join-Path '%s' '%s'))) { 'ABORT' } else { 'PROCEED' }\n"
        % (root, rel)
    )


def main():
    print("== A: 外へ出る手が動いていないこと ==")
    # LIB_ONLY で dot-source しても、本体が走れば G:\ を触りログが増える。
    # Write-Log は定義されるが呼ばれない=ログのバイト数が1バイトも動かないこと。
    logfile = ROOT / "local" / "backup.log"
    before = logfile.stat().st_size if logfile.exists() else -1
    st = state("C:\\nonexistent-root-for-selftest", REL_JA)
    after = logfile.stat().st_size if logfile.exists() else -1
    eq("A1 LIB_ONLY で backup.log が1バイトも増えない", after, before)
    eq("A2 関数が値を返す(本体は走っていない)", st, "wrong-tree")

    print("== B: 宛先ツリーが違えば止まる(安全弁の本体) ==")
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "sharedDriveLike"
        empty.mkdir()
        eq("B1 空のドライブルート=wrong-tree", state(empty, REL_JA), "wrong-tree")
        (empty / "別の戦略フォルダ" / "001_システムバックアップ").mkdir(parents=True)
        eq(
            "B2 名前が似た別ツリーでも親が合わなければ wrong-tree",
            state(empty, REL_JA),
            "wrong-tree",
        )

    print("== C: 正しいツリーでの通し方 ==")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "MyDriveLike"
        leaf = root / REL_JA
        leaf.mkdir(parents=True)
        eq("C1 ツリー在り+leaf在り=ok", state(root, REL_JA), "ok")

        shutil.rmtree(leaf)
        got = state(root, REL_JA)
        eq("C2 ツリー在り+leaf無し=通す(9/17の実害の形)", got, "ok-leaf-missing")
        # 同じ場面で変更前はどう分岐したか。ここが今回の恒久の芯。
        eq("C3 変更前の判定は同じ場面で ABORT だった", legacy(root, REL_JA), "ABORT")

        # 00_AI-HQ 側の leaf も同じ親の下にぶら下がる。親だけ在れば通ること。
        shutil.rmtree(root / "AFI5秒動画設計・戦略運用" / "001_システムバックアップ")
        eq("C4 親まで消えたら wrong-tree へ落ちる", state(root, REL_JA), "wrong-tree")

    print("== D: keeps がドライブ直下へ落ちる設定を先に弾く ==")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "MyDriveLike2"
        (root / "local").mkdir(parents=True)
        eq("D1 rel='local'(親なし)=no-parent", state(root, "local"), "no-parent")
        eq("D2 rel='\\local' でも no-parent", state(root, "\\local"), "no-parent")

    print("== E: 本番の実物(いまの G:\\ と backup_dest.txt) ==")
    rel_live = ""
    if DEST_CFG.exists():
        for line in DEST_CFG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rel_live = line.strip()
                break
    if not rel_live:
        bad("E1 backup_dest.txt が読める", "", "1行目")
    else:
        ok("E1 backup_dest.txt が読める (%s)" % rel_live)
        live_root = _ps(
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n"
            "(Get-ChildItem 'G:\\' -Directory -ErrorAction SilentlyContinue |"
            " Select-Object -First 1).FullName\n"
        )
        if not live_root:
            print("  SKIP E2/E3: G:\\ が見えない(Drive 未マウント)")
        else:
            ok("E2 ドライブルート解決 = %s" % live_root)
            got = state(live_root, rel_live)
            if got in ("ok", "ok-leaf-missing"):
                ok("E3 いまの宛先は通る判定 (%s)" % got)
            else:
                bad("E3 いまの宛先が通らない", got, "ok / ok-leaf-missing")

    print("== F: 変更前の控え(在る環境だけ・.bak は git管理外) ==")
    if not BAK.exists():
        print("  SKIP F1: 控えが無い環境(.bak は untracked のまま置く運用)")
    else:
        src = BAK.read_text(encoding="utf-8", errors="replace")
        if "does not contain the expected destination. Backup skipped." in src:
            ok("F1 控えは leaf 直接判定のまま(C3の対比元)")
        else:
            bad("F1 控えの中身", "旧メッセージ無し", "旧メッセージ有り")

    print("")
    print("%d/%d PASS" % (len(_ran) - len(_fails), len(_ran)))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
