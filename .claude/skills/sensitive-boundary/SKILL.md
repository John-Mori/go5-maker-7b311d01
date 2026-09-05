---
name: sensitive-boundary
description: secret、token、credential、cookie、passphrase、認証ファイルの棚卸し、移動、参照更新、ACL確認を依頼された時だけ使う。通常ファイル整理や設定編集には使わず、明示許可がない限り本文を一切読まない。
---

# 機密ファイル境界

非公開領域は [README](../../../README.md) と [CLAUDE](../../../CLAUDE.md) の境界に従い、保存先は [layout.json](../../../config/layout.json) の `private_root` から解決する。判断できない時はfail closedで停止する。

## 明示許可なしで扱える情報

- パス、ファイル名、拡張子、byte数、作成・更新時刻
- ownerとACL規則
- gitのtracked/untracked/ignored状態
- 非機密のコードや設定に書かれた、対象ファイル名またはパスへの参照

候補ファイルには`Get-Content`、`type`、内容検索、preview、parse、import、source、実行、hash計算を行わない。環境変数、コマンド履歴、ログへ値を出さない。ファイル名自体が値を含む場合は表示を伏せる。

## 移動前

1. `private_root` が解決でき、意図した組織専用の非公開領域であることを確認する。
2. 対象をglobではなく`-LiteralPath`で特定し、移動元と移動先の絶対パスが許可範囲内か確認する。
3. git管理対象か、ignoreが実際に効くか、過去履歴に残るかを区別する。現在の移動は過去履歴から秘密を消さない。
4. daemon、Scheduled Task、hook、外部ツールがどのidentityで読むかを、値を見ずに参照元とACLから確認する。
5. 移動後に必要な参照変更とrollback先を、内容を含まないmanifestへ記録する。記録項目は旧新パス、size、mtime、ACL状態、参照元で十分とし、本文やhashを入れない。

## 移動と確認

- ユーザーが移動・権限変更を依頼した場合だけ実行する。棚卸し依頼だけなら変更しない。
- 先にprivate側のdirectoryとignore/ACLを確認し、次に単一対象を移し、参照をパス設定へ切り替える。一括移動から始めない。
- 旧場所に値を含むcompat copyやsymlinkを残さない。互換が必要なら、秘密値ではなくprivate pathを解決する薄い設定入口を使う。
- 移動後は本文を開かず、存在、size、ACL、git非追跡、必要プロセスの読込成功だけを確認する。
- destination不明、ACL継承不明、参照元identity不明、同名候補が複数、本文読取が必要だが未許可、のいずれかなら移動しない。

秘密本文をcommit、台帳、チャット、検証出力へ載せない。明示的に本文読取を許可された場合も、その目的に必要な最小範囲だけを扱い、値を回答へ再掲しない。
