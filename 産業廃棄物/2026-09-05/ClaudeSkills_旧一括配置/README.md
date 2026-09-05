# 旧Claude skills退避

2026-09-05に、旧5秒動画専用skillと二重管理catalogを有効配置から外しました。削除ではなく復元可能な退避です。

- `active-old`: 旧 `.claude/skills` の8ディレクトリ
- `catalog-old`: 旧 `docs/departments/00_common/skills` のREADMEと6ディレクトリ

現在の機能別正本:

- AI組織運営: `D:\\SougouStartFolder\\AI-Organization\\.claude\\skills`
- YMM4 Shorts: `D:\\SougouStartFolder\\5chShortMovie\\.claude\\skills`
- グッズアフィリエイト: `D:\\SougouStartFolder\\AnimeGameGoodsAFI\\.claude\\skills`

復元する場合は、このフォルダを丸ごと戻さず、必要な1技能だけを現行の配置定義へ追加し、trigger descriptionを対象機能へ狭めてから同期します。

