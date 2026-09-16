#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""claim_room — 対話セッションが「私はこの部屋の担当だ」と名乗る(2026-07-27)。

なぜ要るか(Chami原文「絵文字スタンプつかない問題の恒久解決策ないの?」への恒久対処):
  進捗印(既読/着手/即答)を押す `scripts/hooks/progress_mark.py` は、部屋を2段で解決する。
    ① cwd から引く(session_rooms.dept_of_payload)
    ② 引けなければ transcript の**自己申告**から引く(room_from_transcript)
  ①は `D:\\SougouStartFolder` = hq しか引けない。research-room / keiei-kikaku / aegis-gl の
  セッションは `D:\\SougouStartFolder\\5SecMovieMaker` で動き、そこは**22セッションが共有**
  しているので cwd では誰の部屋か決められない(足すと他人の部屋へ印を押す)。
  そこで②が要るのだが、②が探していた信号は `inbox_waiter.py --name <部屋>` の実行で、
  **鳩(inbox_waiter)は2026-07-19に退役している**(プロセス0本)。
  = **誰も信号を出していない**。実測(直近14時間)でも hq 以外の3部屋は印がゼロだった。
  → 退役した鳩の代わりに、この小さなコマンドが信号になる。

使い方(セッション起動時に1回だけ):
  python scripts/discord/claim_room.py research-room

★混線しない理由(絶対条件):
  部屋の判定に使うのは**このコマンドを実行した記録が transcript に残ること**であって、
  下で書くファイルではない。transcript は**セッションごとに別ファイル**なので、
  自分が打ったコマンドしか入らない=22セッションが同じフォルダで動いていても混ざらない。
  ここで書くファイルは**人が後から追うための台帳**で、部屋の解決には一切使わない
  (部屋名をキーにしたファイルを解決に使うと、最後に打った1セッションが全員の部屋を
   決めてしまい、まさに「他人の部屋に印を押す」事故になる)。

★サブエージェント(Task)は名乗るな(2026-07-27 実測):
  サブエージェントの tool_use は **親セッションの transcript に書き込まれる**
  (実測= hq のtranscriptに、hqが自分で打った `inbox_waiter.py --name hq` が2件)。
  つまりサブが別の部屋を名乗ると、**親の部屋が上書きされる**(最後の名乗りが勝つため)。
  名乗るのは**部屋を持つ本人のセッションだけ**。

★fail-open: 台帳が書けなくても名乗り自体は成立する(exit 0)。
"""
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
# 追記だけの台帳。progress_mark はこれを読まない(上の「混線しない理由」参照)。
CLAIM_LOG = os.path.join(LOCAL, "llm", "room_claims.jsonl")

# 本人セッションが応対する部屋。progress_mark.SESSION_ROOMS と同じ白名簿
# (system-engineer 等のデーモンの部屋を名乗らせない。増減時は対で直すこと)。
SESSION_ROOMS = ("hq", "aegis-gl", "research-room", "keiei-kikaku")


def main():
    args = [a for a in sys.argv[1:] if a != "--name"]   # `--name <部屋>` 形も受ける
    room = (args[0] if args else "").strip()
    if not room:
        print("使い方: claim_room.py <部屋>   例) claim_room.py research-room")
        print("部屋: " + " / ".join(SESSION_ROOMS))
        return 2
    if room not in SESSION_ROOMS:
        # ★白名簿外は**名乗らせない**。デーモンの部屋を人が名乗ると、デーモンが在席と誤認して
        #   譲り続け、その部屋が無音になる。
        print(f"白名簿にない部屋です: {room}(受け付ける部屋= {', '.join(SESSION_ROOMS)})")
        return 2
    try:
        os.makedirs(os.path.dirname(CLAIM_LOG), exist_ok=True)
        with open(CLAIM_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "room": room,
                "pid": os.getpid(),
                "cwd": os.getcwd(),
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass        # 台帳が書けなくても名乗りは transcript 側に残る(fail-open)
    print(f"部屋を名乗りました: {room}(進捗印と在席はこのセッションが持つ)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"claim_room: skip ({e})")
        sys.exit(0)         # 何があってもセッションを止めない
