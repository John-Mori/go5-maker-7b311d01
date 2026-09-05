---
name: organization-ledger
description: AI組織運営のchange_log、open_defectsなどJSONL台帳へ追記またはcloseする時だけ使う。YMM4のmanifest、商品データ、Webアプリの業務データ、一般JSON編集には使わない。
---

# AI組織JSONL台帳

組織基盤の境界は [README](../../../README.md) と [CLAUDE](../../../CLAUDE.md)、現行runtimeの場所は [layout.json](../../../config/layout.json) で確認する。

## 正本と入口

- `scripts/path_config.py` で `legacy_runtime_root` と `knowledge_root` を解決し、対象台帳の正本を1つに決める。新しい絶対パスを埋め込まない。
- 台帳を直接編集しない。現行runtimeの `jsonl_store`、close用CLI、または同等の検証済みwriterを使う。
- `echo >>`、PowerShellのリダイレクト、`Out-File`、手書きJSONで追記しない。BOM、エスケープ、途中書込みで有効な記録が黙って消えるため。
- 追記専用を保つ。既存行の修正・削除で状態を表さず、訂正やcloseも新しいイベントとして書く。

## 追記

1. 同じIDまたは同じ事象が既に起票されていないか、公式のlist/search入口で確認する。
2. 台帳の現行schemaをwriter側から確認し、必須項目だけを渡す。
3. 時刻はJSTを含むISO 8601など、既存writerが要求するタイムゾーン付き形式にする。独自の時刻parserを増やさない。
4. 部門は実作業部門、報告先は依頼元を記録する。代行と担当を混同しない。
5. 追記後にhealth/parse検査と、対象IDが公式readerから1件として見えることを確認する。

## close

- 現行runtimeのclose入口を使い、対象ID、確認者、確認場面、機械で解決できる成果物の場所を渡す。
- commit hashだけを修正証拠にしない。DiscordメッセージID、実在ファイル、URL、または同じ場面の検証結果を使う。
- writerに拒否されたcloseを成功扱いしない。理由を残し、追加証拠が無ければ未完了のままにする。
- 二つの台帳で同じ事象を管理している場合は、片方だけ閉じず、両方の公式入口と対応IDを確認する。

秘密値や会話本文を台帳へ複製しない。記録しただけなら「記録済み」、同じ症状の実物確認前は「直った」と表現しない。
