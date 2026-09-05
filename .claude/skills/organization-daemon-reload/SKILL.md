---
name: organization-daemon-reload
description: AI組織の部門daemonやkeeperが読むコード・設定を変更した後に、再読込の要否判定、停止しない載せ替え、実便確認を行う時だけ使う。単発スクリプト、旧Webアプリ、YMM4、グッズアフィリエイトの作業には使わない。
---

# AI組織daemonの載せ替え

このスキルは、ファイル変更を稼働中の別プロセスへ安全に反映するためのもの。組織基盤の境界は [README](../../../README.md) と [CLAUDE](../../../CLAUDE.md)、パスの正本は [layout.json](../../../config/layout.json) で確認する。

## 判断

1. `AI-Organization` を作業ディレクトリにし、`python scripts/audit_layout.py` と `python scripts/run_legacy_hook.py --check` を通す。
2. `layout.json` の `legacy_runtime_root` を `scripts/path_config.py` で解決する。旧runtimeの絶対パスを新しいコードや手順へ複製しない。
3. 変更ファイルを読む常駐プロセスと読込時点を、現在のimport、keeperの監視対象、起動処理から確認する。
   - 便ごとに読む設定・台帳だけなら再起動しない。
   - import時または起動時にだけ読むコードなら載せ替える。
   - keeper自身を変えた場合は、自己監視されると仮定しない。
4. 監視対象の固定一覧をこのスキルへ写さない。必ず現行runtimeのkeeperと検査を正とする。

## 載せ替え

- 実行前に対象PID、稼働部門数、inflight/queueの集計を保存する。メッセージ本文や秘密値は表示しない。
- ユーザーの依頼範囲に載せ替えが含まれる時だけ、現行runtimeが提供するreload入口を、解決したruntimeをcwdとして使う。
- reload待ちは必ずdetachされた入口を使う。依頼を処理中のセッションから前景で待機すると、自分自身のinflight解除を待つ循環になる。
- 強制終了やqueue削除を代替にしない。既存のlease/再配達設計を保つ。
- 無限待機しない。現行reload入口のタイムアウト、デバウンス、最小間隔を尊重し、越えたら状態を残して停止する。

## 確認

次の全てを別々に確認する。

1. 必要だったプロセスのPIDまたは起動時刻が変わった。
2. daemon/keeperの公式検査が通った。
3. カナリア便が1本だけ処理され、重複配送、欠落、再送ループがない。
4. 元の症状と同じ経路で新しい挙動を確認した。

PID変更だけなら「載せ替え済み」、検査とカナリアまでなら「反映確認済み」。同じ実利用場面を見ていない状態を「直った」と報告しない。
