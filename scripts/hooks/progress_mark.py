#!/usr/bin/env python
"""progress_mark — 進捗印(既読/着手/即答)を**正しいタイミングで**押すhook。

★2026-07-21 Chami「私が既読と着手をどのタイミングでつけて欲しいという記憶はありますか?」
  → 記録されていた。正本= `docs/departments/00_common/rules/運用細則_セッションと起床.md` §37
     (4段・2026-07-19 Chami発案「即答」新設・QA合意):

     📮送信(sendms) = 鳩が配達時に**自動**            → 届いた証明(Claudeが見たとは限らない)
     ✅既読(kidoku) = **起床して読んだ直後**に自分で押す → 読んだ・返答/作業はこれから
     💬即答(sokutou)= **その場の返事で完結した時**に押す → 「読んだだけ」との曖昧さ解消
     👀着手(chakusyu)= **本格的な作業を始める時**に押す

  狙い= Chamiの画面から **未達/届いたが無人/読んだ/即答済み/着手済み** が判別できること。

★研究室HQ Vol.4の初版(react_mark)はこれを守れていなかった:
  ターン終了時に**既読と着手をまとめて押していた**。4つの印は時系列を表す信号なのに、
  同時に押せば時系列が消える。さらに雑談だけのターンでも着手が付き=**嘘の印**になる。
  「機構化した」ことだけ正しく、**中身が仕様と違った**。本ファイルがその訂正。

phase:
  read   … UserPromptSubmit(受け取った瞬間)      → 既読
  work   … PostToolUse で作業系ツールを使った時   → 着手(1ターン1回)
  end    … Stop(ターン終了時)                    → 着手が無ければ 即答

★fail-open: 何が失敗してもセッションは止めない(exit 0)。
"""
import json
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
REACT_MARK = os.path.join(ROOT, "scripts", "discord", "react_mark.py")
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

# 「本格的な作業」とみなすツール。読むだけ(Read/Grep/Glob)は着手ではない=読んでいる最中に
# 着手を押すと、調べただけで終わった時に嘘になる。
WORK_TOOLS = {"Edit", "Write", "NotebookEdit", "Bash", "PowerShell"}


def turn_flag(dept):
    return os.path.join(LOCAL, "llm", f"progress_turn_{dept}.flag")


# 本人セッションが応対する部屋。ここに載っている名前だけを自己申告として受け付ける
# (system-engineer等の**デーモンの部屋を巻き込まない**ための白名簿)。
SESSION_ROOMS = ("hq", "aegis-gl", "research-room", "keiei-kikaku")
WAITER_RE = re.compile(r"inbox_waiter\.py\s+--name\s+([A-Za-z][\w-]*)")


def room_from_transcript(tp):
    """このセッションが自分で武装したwaiterの名前から部屋を決める(2026-07-21・ORG-17)。

    ★なぜcwdで決められないか: `D:\\SougouStartFolder\\5SecMovieMaker` は**22セッションが共有**
      している(実測)。ここをPAIRSでad研究室に割り当てると、バックエンドやQAのセッションまで
      ad研究室へ印を押し、ミラーと在席も混線する(引き継ぎ書§5が禁じている構成そのもの)。
      hq(専用cwd)と違い、ad研究室は**cwdで識別できない**。

    ★代わりに使う信号= セッションが起動時に必ず打つ `inbox_waiter.py --name <部屋>`。
      transcriptはセッション毎に別ファイルなので、**自分が打ったコマンドだけ**が入っている
      =他セッションと混ざらない。新しい手順を増やさずに済む(既にBOOTでやっていること)。

    ★白名簿(SESSION_ROOMS)で絞るので、`--name system-engineer` 等のデーモン部屋は
      一致せず**印を押さない**(あちらはデーモンが押す)。

    ★**素のテキスト検索では駄目**(実測で誤検出): 引き継ぎ書やBOOT.mdには
      `inbox_waiter.py --name hq` という**文字列そのものが載っている**ため、それを読んだだけの
      無関係なセッションまでhqと判定された(5SecMovieMakerの1セッションが実際に誤判定された)。
      → **実際に実行したコマンド(tool_use)だけ**を見る。読んだ/書いた文字列は数えない。
    """
    hits = []
    try:
        with open(tp, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "inbox_waiter" not in line:
                    continue            # 安いフィルタ(大きいtranscriptでも軽い)
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                content = (rec.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    cmd = str((b.get("input") or {}).get("command") or "")
                    hits += [m for m in WAITER_RE.findall(cmd) if m in SESSION_ROOMS]
    except OSError:
        return None
    return hits[-1] if hits else None     # 最後の申告=今その部屋を担当している


def _room_cached(payload, phase):
    """room_from_transcript の結果をセッション単位でキャッシュする(ORG-43)。

    ★なぜ: room_from_transcript は transcript 全行を読む。PostToolUse は全ツールで鳴るため、
      毎回フル走査すると長いセッションほど hook が重くなる。
      部屋は途中で変わらない(変わるのは再武装した時だけ)ので、
      **read(=ユーザー発言ごと・低頻度)でフル解決してキャッシュを更新**し、
      work/end はキャッシュを読むだけにする。
    """
    sid = payload.get("session_id") or "S"
    cache = os.path.join(LOCAL, "llm", f"_room_cache_{sid}.txt")
    if phase != "read":
        try:
            v = open(cache, encoding="utf-8").read().strip()
            if v:
                return None if v == "-" else v
        except OSError:
            pass
    room = room_from_transcript(payload.get("transcript_path") or "")
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            f.write(room or "-")
    except OSError:
        pass
    return room


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    phase = sys.argv[1] if len(sys.argv) > 1 else "read"
    try:
        from session_rooms import dept_of_payload
        dept, _ = dept_of_payload(payload)
    except Exception:
        dept = None
    if not dept:
        # cwdで決まらない部屋(ad研究室=5SecMovieMakerを22セッションで共有)は自己申告で解決する。
        # ★進捗印だけに使う。ミラーには広げない——あちらは本人が手で投稿している部屋があり、
        #   二重投稿になる(ORG-03と同型の事故を自分で作らない)。
        dept = _room_cached(payload, phase)
    if not dept:
        return

    # ★在席(presence)を刻む(2026-07-22 ORG-43・AD-GLの不備報告2件目への恒久解)。
    #   モドリッチの実測= research-room の presence は**一度も立たない**。
    #   `PAIRS` は cwd→部屋 の表で research-room の行が無く、足すと**22セッション全部が
    #   research-room の在席を刻む**(彼が自ら指摘した罠)。
    #   → このhookは既に**セッション単位**で部屋を解決している(waiter信号・ORG-17)ので、
    #     ここで刻むのが正しい置き場。PostToolUse は全ツールで鳴る=ターン中ずっと新鮮に保てる。
    #   ★モドリッチは回避策として「刻み続ける常駐ループ」を立てていたが、あれは
    #     **セッションを閉じても在席が残り、留守番が永遠に譲って部屋が無音になる**。
    #     hookなら本人が実際に動いている間だけ刻まれる=閉じれば自然に枯れて留守番へ渡る。
    try:
        from session_rooms import touch_presence
        touch_presence(dept)
    except Exception:
        pass

    if phase == "work":
        if payload.get("tool_name") not in WORK_TOOLS:
            return
        if os.path.exists(turn_flag(dept)):
            return                      # このターンでは既に着手を押した
        kinds = "着手"
    elif phase == "end":
        if os.path.exists(turn_flag(dept)):
            try:
                os.remove(turn_flag(dept))   # ターン終了=次のターンのために倒す
            except OSError:
                pass
            return                      # 着手済み=即答は押さない(排他)
        kinds = "即答"
    else:
        kinds = "既読"

    try:
        subprocess.run([sys.executable, REACT_MARK, "--dept", dept, "--kinds", kinds],
                       capture_output=True, timeout=45)
    except Exception:
        return
    if phase == "work":
        try:
            os.makedirs(os.path.dirname(turn_flag(dept)), exist_ok=True)
            open(turn_flag(dept), "w").close()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
