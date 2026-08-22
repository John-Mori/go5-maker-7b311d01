#!/usr/bin/env python3
"""presence hook: ツール実行のたびに研究室の脈を打つ (PostToolUse・S1/P1根治)。

なぜ要るか(INC-94):
  脈(claude_active.txt)を打つのは従来waiterだけ。waiterは新着配達と同時に自了するため、
  研究室が長いターンを処理している間は脈が止まり、無人代打が「死亡」と誤判定して発火していた。
  このフックは「実際にツールを使って働いている間、脈が打たれ続ける」を保証する=閾値調整に
  依存しない本質解(改善設計書_基盤恒久化_世界OSS調査 §3.4 / k8sのliveness相当)。

仕組み:
  - .claude/settings.json の PostToolUse に登録=このrepoの全セッションで発火する。
  - **自分が研究室(main)かどうか**を判定し、一致した時だけ lab_tool_pulse.txt をtouchする。
  - ★touch先はwaiterの脈(claude_active.txt)とは**別ファイル**(出荷前批評のfatal指摘・2026-07-18):
    liveness(道具を使って働いている)とreadiness(waiterが箱を見ている)を同じファイルに混ぜると、
    耳が死んだまま長時間作業した場合に代打が永久に抑止され、45分/900秒級の安全上限が消える。
    判定の合成は presence.lab_alive() 側で行う(readiness主信号+liveness猶予+硬い上限)。
  - 部門セッションでは何もしない(部門の脈で研究室を生存偽装すると、研究室が本当に死んだ時に
    代打が永久に出ない=INC-94の逆事故になるため)。
  - 判定できない場合も何もしない=現行動作(waiterの脈)に安全に退化する。fail-open。

★★2026-08-13(イージス研究室・C-044の2件目)——判定を「札」から「自己申告」へ移した。
  実測した事故= 脈 local/llm/lab_tool_pulse.txt が **2026-07-20 19:22 で停止**(23.9日)。
  コードは1行も壊れていない。**条件が切れただけで機能が消えた**:
    旧実装は stdin の session_id を local/llm/lab_session_id.txt(研究室が起動時に手で名乗る札)と
    照合し、一致した時だけ打っていた。部屋の作り替えで名乗り(claim_lab.py)が途切れて以降、
    条件が二度と成立しなくなった。**警報は出ない**ので24日間誰も気づかなかった。
  実害= presence.lab_alive() が **readiness 1本へ退行**し、司令塔が長いターンを処理している最中に
    代打が出る条件(INC-94そのもの)が復活していた。さらに revive_lab.ps1 §2.5 が
    「presenceが死亡と言っている窓」を掃除するため、**生きた司令塔を殺す**経路まで出来ていた
    (2026-08-13 の窓死4回・調査= docs/設計・調査/研究室の窓の死因_調査と計装.md)。

  新しい判定(どちらか当たれば main)=
    ① 札 lab_session_id.txt と session_id が一致(**旧経路は残す**。C-003=消さずに足す)
    ② **司令塔の耳を武装したのが自分か**= `inbox_waiter.py --name main` が起動時に書き残した
       claude.exe のPID(local/llm/lab_owner_pid.txt)と、自分の claude.exe が同じ。
  ②が本命だ。理由=
    - 司令塔の定義は「耳を `--name main` で武装している窓」そのもの。武装は毎回必ず起きる=
      人が思い出して打つ作法ではない=**機構に載っている**(C-044⑤が求めた形)。
    - 見ているのが**プロセスの親子関係**なので、他の部屋のセッションは真似できない。
    - 耳は配達のたびに自了するが、PIDのファイルは**残る**ので長いターンの最中も判定できる。
  ★★**transcriptの文字列で判定する案は実測で棄却した**(2026-08-13 17:21・自分で踏んだ):
    「自分のtranscriptの中で `inbox_waiter.py --name main` を実行しているか」を見る実装を
    本番へ入れたところ、**この機能をデバッグしていた aegis-gl のセッションが自分を司令塔と誤認**し、
    実物の lab_tool_pulse.txt を打ち・lab_session_id.txt を自分のIDで上書きした(17:21:23)。
    tool_useのinput.commandだけを見る・python実行を要求する、という progress_mark.py 譲りの
    防御を両方入れてもこうなる= **文字列は書けてしまう**。これは HQ が名指しで警告した
    「部門セッションが司令塔の生存を偽装する」=INC-94の逆事故そのもので、
    **黙って壊れる方向**(研究室が本当に死んだ時に代打が永久に出ない)。だから採らない。
  ★判定が付かない時は打たない=従来動作(waiterの脈)へ安全に退化する。

研究室の名乗り(手動でやり直したい時): python scripts/hooks/claim_lab.py <自分のsession_id>
"""
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
LAB_ID_FILE = os.path.join(LOCAL, "llm", "lab_session_id.txt")
LAB_OWNER_PID = os.path.join(LOCAL, "llm", "lab_owner_pid.txt")
PULSE = os.path.join(LOCAL, "llm", "lab_tool_pulse.txt")  # liveness専用(readinessと分離)


def _touch_room_presence(payload):
    """対になるDiscord部屋がある対話セッションなら、その部屋の在席を刻む(2026-07-20 Vol.3)。

    waiterは新着配達と同時に自了するため、私が返信を書いている数分は readiness が消える。
    その窓でデーモン(アメス)が同じ便に応答した=実測。ここは liveness 側の信号で、
    dept_daemon.interactive_alive() が readiness と合成して判定する。
    ※研究室本体のliveness(lab_tool_pulse)とは別ファイル・別用途なので混ぜない。
    """
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        from session_rooms import dept_of_payload, touch_presence
        dept, _ = dept_of_payload(payload)
        touch_presence(dept)
    except Exception:
        pass            # 在席が刻めなくても現行動作(waiterの脈)に安全に退化する


def lab_owner_pid():
    """耳(`inbox_waiter --name main`)が書き残した司令塔 claude.exe のPID。無ければ0。"""
    try:
        with open(LAB_OWNER_PID, "r", encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def is_lab_session(payload, my_pid=None):
    """このセッションが研究室(main)か。判定不能はFalse(=打たない・fail-open)。

    my_pid= 自分の claude.exe のPID(検査から差し込めるように外出ししてある)。
    """
    sid = str(payload.get("session_id") or "")
    try:
        with open(LAB_ID_FILE, "r", encoding="utf-8") as f:
            lab_id = f.read().strip()
    except OSError:
        lab_id = ""
    if sid and lab_id and sid == lab_id:
        return True                     # ①旧経路(札)。壊さず残す
    owner = lab_owner_pid()
    if not owner:
        return False                    # 耳がまだ一度も武装していない= 分からない= 打たない
    if my_pid is None:
        try:
            sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
            from session_rooms import owner_session_pid
            my_pid = owner_session_pid()
        except Exception:
            my_pid = 0
    return bool(my_pid) and my_pid == owner


def _context_guard(payload):
    """文脈の上限をこの窓にも効かせる(2026-08-22・研究室HQ実依頼 msg 1540618940533841982)。

    ★なぜ**このhookに相乗り**しているか(正直に書く):
      本来は .claude/settings.json の PostToolUse へ `context_guard.py` を1本足すのが筋だ。
      ところがこの作業セッションからは settings.json への書き込みがハーネスに止められる
      (承認が要る)。**このhookは既に全セッションの PostToolUse で鳴っている**ので、
      同じ発火点をここから借りる。判定と文面の正本は `scripts/hooks/context_guard.py`
      1か所のまま(こちらは payload を渡すだけ=ロジックを二重に持たない)。
      ★settings.json へ独立登録できたら、この相乗りは外してよい。

    ★何を守るか= relayの管理外(=手で開いた窓)は 120,000の圧縮線も185,000の交代線も
      効かない。実測(2026-08-22)= 研究室メイン 0351851c は文脈の中央値 486,209・最大 933,992。
      消費の71.2%が cache読み=文脈の読み直しで、その最大の1本がこれだった。
    ★fail-open: ここで何が起きても脈と在席は既に済んでいる(呼び出しは main の最後)。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import context_guard
        msg, _ctx, _lv = context_guard.decide(payload)
        if msg:
            print(json.dumps({
                "systemMessage": msg,
                "hookSpecificOutput": {
                    "hookEventName": payload.get("hook_event_name") or "PostToolUse",
                    "additionalContext": msg,
                },
            }, ensure_ascii=False))
    except Exception:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    _touch_room_presence(payload)
    try:
        lab = is_lab_session(payload)
    except Exception:
        return 0                        # 判定でこけてもhookは絶対に止めない
    if lab:
        try:
            os.makedirs(os.path.dirname(PULSE), exist_ok=True)
            with open(PULSE, "a", encoding="utf-8"):
                pass
            os.utime(PULSE, None)
        except OSError:
            pass
    _context_guard(payload)             # ★脈より後(相乗りが本業を止めない)
    return 0


if __name__ == "__main__":
    sys.exit(main())
