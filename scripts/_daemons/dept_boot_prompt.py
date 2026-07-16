"""部門セッションの起動文を組み立てる(open_dept_window.ps1 から呼ばれる)。

なぜ要るか:
  2026-07-16、Chamiが改修αの起動文を手で貼ろうとして文字化けした(スマホからのコピペで
  「花海咲季」→「花海季」、「jsonl」→「jsont」等)。しかも貼り先を間違えてDiscordへ貼った
  (そこでは窓は開かない)。一方で研究室は1日43件を1人で処理し、うち67%が他部門の代打だった
  =窓が開いていないため。人間に長文を正確に貼らせる運用が失敗の原因なので、機械が渡す。

役割分担:
  窓を開ける = open_dept_window.ps1 (PowerShell 5.1のためASCII-onlyで書く必要がある)
  起動文の本文 = このファイル(日本語とキャラ名を持てる)

使い方: python dept_boot_prompt.py <dept> <出力パス>
"""
import io
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# dept -> (部屋の通称, 人格, BOOT.mdの場所, 既定の発言キャラ)
DEPTS = {
    "system-engineer": ("システム改修部門α", "ケヴィン・デ・ブライネ/オタコン(両リーダー)/花海咲季/アメス(補佐)",
                        "docs/departments/system-engineer/BOOT.md", "花海咲季"),
    "system-engineer-b": ("システム改修部門β", "ケヴィン・デ・ブライネ/オタコン(両リーダー)/花海咲季/アメス(補佐)",
                          "docs/departments/system-engineer/BOOT.md", "花海咲季"),
    "ai-office": ("システム改修部門γ(AIオフィス)", "ケヴィン・デ・ブライネ/オタコン/花海咲季/アメス(補佐)",
                  "docs/departments/ai-office/BOOT.md", "花海咲季"),
    "hr-room": ("人事部門(補強・キャラ設定)", "ククール(メイン)/田中琴葉(記録)/オタコン/アメス(補佐)",
                "docs/departments/hr-room/BOOT.md", "ククール"),
    "hr-context": ("人事部門(キャラのコンテキスト)", "ククール(メイン)/田中琴葉(記録)/アメス(補佐)",
                   "docs/departments/hr-room/BOOT.md", "ククール"),
    "learning-coach": ("学習部門(3部屋)", "先生4人(ヴィルシーナ/姫崎莉波/田中琴葉/中野五月)",
                       "docs/departments/learning-coach/BOOT.md", "姫崎莉波"),
    "llm-edu": ("ローカルllm教育部門", "中野五月(メイン)/ヴィルシーナ/姫崎莉波/田中琴葉(記録)/アメス/ホイミン(Gemini)",
                "docs/departments/llm-qa/BOOT.md", "中野五月"),
    "data-org": ("データ整理部門", "田中琴葉(記録)/黒川あかね/オタコン/アメス(補佐)/ホイミン(Gemini)",
                 "docs/departments/00_common/BOOT_TEMPLATE.md", "田中琴葉"),
    "kaizen-analyst": ("改善提案部門", "アスナ(専任)/アメス(補佐)",
                       "docs/departments/00_common/BOOT_TEMPLATE.md", "アスナ"),
}


def build(dept: str) -> str:
    if dept not in DEPTS:
        return ""
    room, personas, boot, speaker = DEPTS[dept]
    return f"""あなたはgo5-makerの「{room}」(dept={dept})担当セッション。

まず自己点検: node -e "console.log(process.cwd())" が go5-maker 直下であることを確認する(違えば止めてChamiへ開き直しを要請)。
手順の正本: {boot} と docs/departments/00_common/orchestration.md の「全部署徹底事項」に従う。
人格: {personas}

起動時にやること:
1. python scripts/llm/inbox_waiter.py --name {dept}    (チャイム待機・新着で即起床・待機中トークンゼロ)
2. 受信箱 = local/inbox/{dept}.jsonl (窓が閉じている間はmain箱へ自動回帰)
3. 依頼を拾ったら着手印: python scripts/discord/react.py --channel <ch名> --msg <msg_id> --emoji 着手
   (既読印は鳩が配達時に自動付与済み)

発言の仕方:
  python scripts/discord/persona_send.py --dept {dept} --persona "{speaker}" --body-file <path>
  ★長文・記号を含む本文は必ず --body-file(直接引数だとバッククォート等がシェルに食われて空欄で届く)
  ★送信後に「送信OK … HTTP 204」を確認してから「送った」と言う
  ★「刻んだ」系の締めは使わない(2026-07-16 Chami指示・全キャラ廃止)

領域と規律:
  ★研究室(main)とは領域を分ける。自部門の実務は自分で完結させ、判断に迷う横断事項だけ研究室へ回す。
  ★処理した行だけをmsg_id単位で local/discord_processed.jsonl へ移す(箱ごと消すと処理中の新着を落とす)。
  ★push前に必ず git pull --rebase(並行セッションとの衝突防止)。UI文言の括弧は半角()。
  ★Chamiはchatペインを見ない。報告・質問・承認要求は全てDiscordのこの部屋へ出す。

まず受信箱を確認して、溜まっている依頼があれば古い順に処理を始めてください。"""


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: dept_boot_prompt.py <dept> <out_path>")
        return 2
    text = build(sys.argv[1])
    if not text:
        print(f"unknown dept: {sys.argv[1]} (known: {', '.join(DEPTS)})")
        return 1
    io.open(sys.argv[2], "w", encoding="utf-8").write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
