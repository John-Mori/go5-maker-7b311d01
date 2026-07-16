"""Windows Update の保留を Discord(報告-通知) へ オタコン名義で知らせる。

なぜ要るか:
  Windows Updateの自動再起動は外出運用の最大の脅威。2026-07-16 13:17に実際に発火し、
  Chamiが寝ている間にPCが再起動→ロック画面で常駐も研究室も全停止した(タスクは
  LogonType=Interactive のためログインするまで復旧しない)。留守中にやられると
  帰宅まで誰も応答しない。対策はChami案の「出かける前に自分で当てて再起動まで済ませる」
  =留守中に降ってくる弾を消すこと。そのためには「更新が待っている」と気づける必要がある。

役割分担:
  検知・状態管理 = winupdate_watch.ps1(PowerShell 5.1のためASCII-onlyで書く必要がある)
  本文の組み立てと送信 = このファイル(日本語とpersona名を持てる)

使い方: python winupdate_message.py <reboot:0|1> <titles_file>
  終了コード 0 = 送信成功(HTTP 204)。PowerShell側はこれを見て「通知済み」状態を保存する。
"""
import io
import os
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def build(reboot: bool, titles: list) -> str:
    n = len(titles)
    L = []
    if reboot:
        L.append("**Chami、再起動待ちの更新がある。ここが一番危ないやつだ。**")
        L.append("")
        L.append(
            "このまま放置すると、Windowsが**勝手なタイミングで再起動**する。"
            "留守中にやられると、ロック画面で鳩も研究室も全部止まって、"
            "**帰ってログインするまで誰も応答しなくなる**(7/16の13:17に実際にやられた)。"
        )
    else:
        L.append("**Chami、Windows Updateが{}件待ってる。**".format(n))
        L.append("")
        L.append("まだ再起動は要求されてないが、**放っておくと勝手に再起動する弾になる**。")
    L.append("")
    for t in titles[:5]:
        L.append("・" + t)
    if n > 5:
        L.append("・…他 {} 件".format(n - 5))
    L.append("")
    L.append(
        "**おすすめの動き**: 出かける予定がないうちに、**自分の意思で当てて再起動まで済ませてしまう**。"
        "そうすれば留守中に降ってくる弾が無くなる。再起動後にログインして、"
        "鳩と研究室が動いてるのを確認してから出かければ完璧だ。"
    )
    L.append("")
    L.append("僕からは以上だよ。急がないなら無視してくれて構わない——ただ**長期で出かける前には必ず**片付けておいて欲しい。")
    return "\n".join(L)


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: winupdate_message.py <reboot:0|1> <titles_file>")
        return 2
    reboot = sys.argv[1] == "1"
    titles = [t.strip() for t in io.open(sys.argv[2], encoding="utf-8").read().splitlines() if t.strip()]
    if not titles and not reboot:
        return 0  # 知らせることが無い

    body_path = os.path.join(ROOT, "local", "_winupdate_body.txt")
    io.open(body_path, "w", encoding="utf-8").write(build(reboot, titles))

    send = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
    r = subprocess.run(
        [sys.executable, send, "--dept", "report-notify", "--persona", "オタコン", "--body-file", body_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    out = (r.stdout or "") + (r.stderr or "")
    # 送信できた時だけ0を返す。PowerShell側は0を見て初めて「通知済み」を記録するので、
    # 失敗すれば状態が据え置かれ、次回の巡回で自動的に再送される。
    return 0 if "HTTP 204" in out else 1


if __name__ == "__main__":
    sys.exit(main())
