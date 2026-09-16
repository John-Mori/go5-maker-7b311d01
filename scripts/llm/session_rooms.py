#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一部屋=一セッションの対応表と、対話セッションの在席(presence)判定。

なぜこのモジュールが要るか(2026-07-20 実測・Vol.3):
  hq waiter を立てていたのに、アメス(dept_daemon)が同じ便へ応答した。原因は2つとも構造的:
    1. inbox_waiter は新着1件を配達すると **自了する**。つまり Chami が喋った瞬間に
       readiness 信号(waiterプロセス)が消える。私が返信を書いている数分がまるごと無防備。
    2. dept_daemon.interactive_alive() は 30秒キャッシュのプロセス列挙。waiterの生死の
       前後に必ず判定の窓ができる。
  → readiness(waiter)だけでは埋まらない。**liveness(そのセッションが今ツールを動かしている)**
    を足して合成する。これは pulse_touch.py が研究室本体(claude_responder)向けに既に採った
    設計で、同じ思想を部門部屋へ広げただけ(新しい概念を持ち込まない)。

対応の正本はここ1箇所:
  mirror_to_discord.py(ミラー先の決定)と pulse_touch.py(在席の記録)が別々に対応表を
  持つと、片方だけ増やした時に「ミラーは飛ぶのに在席は立たない」= 二重応答が静かに復活する。

在席ファイルの寿命(PRESENCE_TTL)について:
  ターン処理中は PostToolUse が絶え間なく発火するので在席は立ち続ける(=waiterが死んでいる窓を覆う)。
  ターンとターンの間(私がChamiの発言を待っている間)は道具を使わないので在席は枯れるが、
  **その時間帯は waiter が武装されている**ので readiness 側が受け持つ。二つは相補的で、
  どちらも死んでいる時だけデーモンが受ける = 可用性は落とさない(fail-open)。
"""
import os
import re
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))

# cwdの正規化パス -> (dept, そのセッションでの私の名義)
# ★部屋の無いセッションは載せない(Chami指示「1部屋=1セッションで対になっているところだけ」)
PAIRS = {
    "d:\\sougoustartfolder": ("hq", "シャビ・アロンソ"),
    # gl-暫定でアロンソ(組織層=イージスAegisConcielカテゴリのGL室・2026-07-20 Chami新設)。
    # ★cwdを 00_AI-HQ にするのは必須(飾りではない):
    #   部屋の判定は transcript_path の親フォルダ名(=セッション開始時のcwdから作られる)で行う。
    #   このGLセッションを D:\SougouStartFolder で開くと**HQ Vol.3と同じ D--SougouStartFolder**に
    #   なり、2つのセッションが同じhq室へミラーし、在席も混線する(どちらが応対中か区別できない)。
    #   00_AI-HQ で開けば D--SougouStartFolder-00-AI-HQ となり完全に分離できる。
    "d:\\sougoustartfolder\\00_ai-hq": ("aegis-gl", "シャビ・アロンソ"),
}

PRESENCE_TTL = 150      # 秒。この時間内に道具が動いていれば「対話セッションが応対中」とみなす


def _presence_dir():
    return os.path.join(os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local"), "llm")


def presence_path(dept):
    return os.path.join(_presence_dir(), f"interactive_presence_{dept}.txt")


def _norm(path):
    """区切り文字・大小・末尾スラッシュを吸収する。

    ★スラッシュ表記("D:/SougouStartFolder")を取りこぼす穴が実測で見つかった(2026-07-20)。
      引けないと在席が立たず=デーモンが攫う、という**静かに壊れる**種類の失敗なので正規化する。
    """
    return os.path.normcase(os.path.normpath(str(path))).rstrip("\\/")


def dept_of_cwd(cwd):
    """cwd から対になる (dept, 名義) を引く。対が無ければ (None, None)。

    ★cwdは信用しきれない(2026-07-20 実測で判明した真因):
      hookのpayloadに載る cwd は**セッションのcwdではなくツールの作業ディレクトリ**で、
      Bashで `cd 5SecMovieMaker` した瞬間から `D:\\SougouStartFolder\\5SecMovieMaker` に化ける。
      その結果 PAIRS が引けず、ミラーが**無言で停止**した(状態ファイルも更新されないので
      気づく手がかりが無い)。だから第一の手がかりは transcript_path 側に置く=dept_of_payload。
    """
    if not cwd:
        return (None, None)
    target = _norm(cwd)
    for key, pair in PAIRS.items():
        if _norm(key) == target:
            return pair
    return (None, None)


def _slug(path):
    """Claude Codeが ~/.claude/projects/ 配下のフォルダ名を作る時と同じ潰し方。

    "D:\\SougouStartFolder" -> "D--SougouStartFolder"
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def dept_of_payload(payload):
    """hookのpayloadから (dept, 名義) を引く。cwdの漂流に影響されない。

    第一手がかり = transcript_path の親フォルダ名。
      ~/.claude/projects/D--SougouStartFolder/<session_id>.jsonl
      この親フォルダ名は**セッション開始時のcwdから作られ、以後も変わらない**ので、
      作業中にどこへcdしようと揺れない。しかも 5SecMovieMaker で開いた別セッションは
      "D--SougouStartFolder-5SecMovieMaker" になるので取り違えない
      (=「1部屋=1セッションで対になっているところだけ」というChami指示を壊さない)。
    第二手がかり = cwd の完全一致(transcript_pathが無いhookイベント向けの保険)。
    """
    payload = payload or {}
    tp = payload.get("transcript_path")
    if tp:
        proj = os.path.basename(os.path.dirname(str(tp)))
        if proj:
            for key, pair in PAIRS.items():
                if proj.lower() == _slug(key).lower():
                    return pair
            return (None, None)     # 別プロジェクトのセッション=対の部屋は無い
    return dept_of_cwd(payload.get("cwd"))


def proc_table():
    """{pid: (親pid, 実行ファイル名(小文字))}。取れなければ空dict。

    ★プロセスの実体を見る**唯一の実装**(ORG-11。窓の在席判定=session_presence もこれを使う)。
      PowerShell(Get-CimInstance)を起こすと1回あたり数百msかかるので使わない。
      ctypesのToolhelp32スナップショットは実測**402プロセスで8ms**。
    ★どんな失敗でも {} を返す(呼び出し側は「分からない」として扱う)。
    """
    try:
        if os.name != "nt":
            return {}
        import ctypes
        from ctypes import wintypes

        class _PE32(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]

        k = ctypes.windll.kernel32
        snap = k.CreateToolhelp32Snapshot(2, 0)      # TH32CS_SNAPPROCESS
        if snap in (0, -1):
            return {}
        procs = {}
        try:
            e = _PE32()
            e.dwSize = ctypes.sizeof(_PE32)
            ok = k.Process32First(snap, ctypes.byref(e))
            while ok:
                procs[int(e.th32ProcessID)] = (int(e.th32ParentProcessID),
                                               e.szExeFile.decode("ascii", "replace").lower())
                ok = k.Process32Next(snap, ctypes.byref(e))
        finally:
            k.CloseHandle(snap)
        return procs
    except Exception:
        return {}


def owner_session_pid():
    """このhookを起こした**対話セッション本体(claude.exe)のPID**を返す。取れなければ 0。

    ★なぜPIDが要るか(2026-07-27 実測・Chami原文「トーク履歴が汚れる」の真因):
      在席の判定は今まで**mtimeの新しさ(PRESENCE_TTL=150秒)だけ**だった。
      hookが刻むのは「道具を使い終えた時」なので、**セッションが長考している間・
      サブエージェントを1本回している間は1回も刻まれない**(実測: Taskツール1本が
      10分を超えると10分間まったく無音)。150秒でそれを「窓が死んだ」と判定し、
      デーモンが同じ便へ答えに行った=**同じ部屋にClaudeが2人**(10:05の事故)。
      → **時間ではなく実体を見る**。窓のプロセスが生きているなら、
        何分黙っていようとその窓は存在する。

    ★取り方: 自分(hookのpython)から**親を辿って最初の claude.exe** を採る。
      実測(2026-07-27)= python.exe → bash.exe×3 → **claude.exe** → Claude.exe(デスクトップ) → explorer.exe。
      Toolhelp32のスナップショット1回=**402プロセスで8ms**。hook1回あたりの追加コストとして許容できる
      (hook自体のpython起動が約100ms)。psutilは入っているが**使わない**=依存を増やさない。
    ★どんな失敗でも 0 を返す(hookは絶対に止めない)。0=「PIDでは分からない」であって
      「窓が居ない」ではない。読む側(session_presence)が時間の側へフォールバックする。
    """
    procs = proc_table()
    if not procs:
        return 0
    pid = os.getpid()
    for _ in range(12):                              # 深さ上限=輪になっても抜ける
        row = procs.get(pid)
        if not row:
            return 0
        if row[1] == "claude.exe":
            return pid
        pid = row[0]
    return 0


def touch_presence(dept):
    """対話セッションが生きて働いていることを刻む。失敗しても黙って諦める(hookを止めない)。

    ★2026-07-27 追加: mtimeだけでなく**窓のPID**も1行だけ書く(上の owner_session_pid 参照)。
      読む側は今までどおり mtime を見てよい(**中身を読まない読み手は1ミリも変わらない**)。
      PIDは「150秒の時間切れ」を実体で上書きするための材料として session_presence が使う。
    """
    if not dept:
        return
    p = presence_path(dept)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # 追記ではなく上書き(1行だけ持つ=ファイルが太らない)。書けなければ従来どおりtouchだけ。
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write('{"pid": %d, "ts": %d}\n' % (owner_session_pid(), int(time.time())))
        except OSError:
            with open(p, "a", encoding="utf-8"):
                pass
        os.utime(p, None)
    except OSError:
        pass


def presence_fresh(dept):
    """在席ファイルが PRESENCE_TTL 以内に更新されているか。判定不能はFalse(=デーモンが受ける)。"""
    try:
        return (time.time() - os.path.getmtime(presence_path(dept))) < PRESENCE_TTL
    except OSError:
        return False
