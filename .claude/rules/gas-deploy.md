---
paths:
  - "gas/**"
  - "scripts/deploy_gas.mjs"
---

> ★この章は `CLAUDE.md` から移した。**内容は変えていない**(2026-08-29・研究室HQ)。
> 毎便の固定費(床)を下げるため、上の `paths` に当たるファイルを触る時だけ読み込まれる。

### GAS(コード.gs)の反映(自動化済み・手動コピペ禁止)

- `gas/コード.gs` を編集したら**必ず `GAS_VERSION` をバンプ**する(日付＋英字サフィックス。例 `2026-07-02H`)。
- 反映は **`GASを反映.bat`(＝`node scripts/deploy_gas.mjs`)** を実行するだけ。
  clasp で push→**既存デプロイIDに新バージョンを当てる**ため **exec URL は不変**。
  `?ping=1` でバージョン一致を機械検証し、`?action=admin_setup` で**トリガー再設定＋ヘッダ移行**まで自動実行する。
  → GAS エディタへの手動コピペ・手動再デプロイは案内しない(初回だけ `GAS初期設定.bat`)。
- 反映前チェックだけしたい時は `node scripts/deploy_gas.mjs --check`。
- **`clasp pull` を `gas/` に対して実行しない**(ローカルが正。クラウド版で上書きされる)。
  設計・落とし穴の詳細は `docs/設計・調査/GAS自動反映_設計書.md`。
- 秘密(`.clasp.json` / `scripts/gas_deploy_config.json` / `~/.clasprc.json`)はコミット禁止。
