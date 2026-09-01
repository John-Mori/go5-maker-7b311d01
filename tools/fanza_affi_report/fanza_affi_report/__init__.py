"""FANZA/DMM アフィリエイト売上レポート自動化ツール (独立・zip納品).

移植性の高い中核(OS/送信口に依存しない):
  parser   : Shift-JIS(cp932) CSV → 明細行
  aggregate: 明細 → 日次サマリ(報酬体系別/サービス別/上位作品)
  state    : 日次サマリの保存と前日比
  senders  : 送信口の抽象(stdout / Discord Webhook / 差し替え可能)
  report   : サマリ → 送信本文(機密を含めない)

★このパッケージは資格情報・APIキー・af_id を一切同梱しない。
  設定は config.ini に利用者(🐧さん)自身が入れる。
"""

__version__ = "0.1.0"
