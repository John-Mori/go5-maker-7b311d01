# fivesec_autodraft — 朝の無人ドラフト自動作成(β-5c)

2026-10-29 導入(5S部門の依頼。Chami「ドラフトにまで自動で投稿とか済ませておいてほしい」)。

| 物 | 役割 |
|---|---|
| `fivesec_autodraft.py` | 本体。`LocalData/fivesec/daily_pick_YYYYMMDD.json` の作品ごとに、専用プロファイルの Chrome で本番を開き `FivesecAutoDraft.run(spec)` を呼ぶ |
| `fivesec_autodraft.ps1` | 定時便の入口(`--allow-no-sync --notify`) |
| `register_fivesec_autodraft_task.ps1` | タスク `fivesec_autodraft_0630` を登録。06:30〜09:00 に30分おき・StartWhenAvailable・IgnoreNew・20分上限。`hidden_task.ps1` 経由=窓を出さない |

- 入力は 5S部門が `daily_pick_手順.md` の9.で書く JSON。md だけでは動かない(無ければ `no_input` を数え、3回目で5S部門へ1回知らせる)。
- 台帳 `LocalData/fivesec/autodraft_ledger_YYYYMMDD.json`: 作品ごとに試行回数・stockId・cloud。済んだ作品は飛ばし、1作品3回まで。
- 記録 `LocalData/fivesec/autodraft.log`(1行JSON)。画像は `LocalData/fivesec/autodraft_img/` に落としてから渡す。
- 同期(⚙の2欄)が未設定のうちは端末内だけのドラフトになる(スマホから見えない・5S部門 了承済み)。入った後は cloud:false を失敗に数える。
- 知らせは 5S部門(fivesecmm)へ 1日に成功1回・失敗1回まで。本番に `FivesecAutoDraft.version` が無い/同期未設定(`--allow-no-sync` 無し)は即1回。
- 手で流す: `py -3.12 scripts/_daemons/fivesec_autodraft.py --date 20261029 [--json <path>] [--allow-no-sync] [--limit 1] [--notify --dry-run]`
- 専用プロファイル(`LocalData/fivesec_autodraft_profile`)を Chrome で開いている間は起動できない(`launch` で数え、次の30分で再試行)。
