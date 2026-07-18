# 品質・監査 (QA) はHQ直下へ移転しました (2026-07-18)

Chami指示「ここも人事部門みたいに研究室HQ直下にしたい。直下になって！Go!」により、
QA部門の正本 (BOOT.md / 検証標準.md / STATUS.md) は
**`D:\SougouStartFolder\00_AI-HQ\departments\qa\`** へ移転 (人事の前例に倣う・全PJ管轄化+公開repo機密防衛)。

このフォルダに残るのは **G5 (go5-maker) 固有の資産のみ**:
- `checks/` — G5の回帰チェック群 (repo構造に依存するコードのため残置。HQのBOOTから参照)
- `改善書_*.md` / `改善設計書_*.md` / `受け入れ条件表_*.md` — G5の設計・履歴 (commitに紐づく記録)

新しい正本を読むこと。ここにBOOT/STATUS/検証標準を再作成しない。
