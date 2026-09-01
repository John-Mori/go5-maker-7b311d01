# FANZA/DMM アフィ売上レポート 自動生成ツール

DMMアフィリエイト管理画面からエクスポートした報酬明細CSV(Shift-JIS/cp932)を
読み込み、日次の売上レポートを整形して指定の送信口へ出力する。Python標準ライブラリのみ。

## 特徴
- 資格情報・URL・af_id・APIキーは一切同梱していない。すべて利用者が `config.ini` に入れる(自分のPCの中だけ)。
- 列は「名前」で引く(位置で引かない)。DMM側で列が増減しても必須列が在れば動く。
  必須列が欠けたら黙らず `ReportFormatError` を投げる。
- 送信口は抽象化(stdout / Discord Webhook)。将来メール等を足しても中核は変えない。
- 失敗は握り潰さない。例外はローカルログへ残し、可能なら送信口へ「生成に失敗」を通知して非0で終了。

## セットアップ
1. Python 3.9 以上(パース/集計/整形/送信は標準ライブラリのみ。追加インストール不要)。
   `[download] mode = playwright` を使う場合のみ `pip install playwright` と
   `playwright install chromium` が必要(下記「CSVの取得」参照)。
2. `config.example.ini` を `config.ini` にコピーし、自分の値を入れる。
   - `[input] csv_dir` … CSVを置く/保存するフォルダ
   - `[output] sender` … `stdout`(画面表示) か `discord`(Webhook投稿)
   - `[output] webhook_url` … discord のとき自分のWebhook URL
   - `[download] mode` … `local`(手動配置・検証用) か `playwright`(ブラウザ自動DL・本番)
   - `config.ini` は zip に同梱しない/共有しない(自分のPCの中だけ)。

## CSVの取得
- `mode = local` … `csv_dir` に置いた最新CSVをそのまま使う(検証・移行期用)。
- `mode = playwright` … DMMアフィ管理画面へブラウザで自動ログインしCSVを自動DLする(本番方式)。
  ログインURL・フォームのセレクタ・CSVエクスポート導線は実物の管理画面を見ないと分からないため
  ソースには埋め込んでいない。`config.ini [download]` の各項目
  (`login_url` / `username_selector` / `password_selector` / `login_submit_selector` /
  `report_url` / `csv_export_selector` / `username` / `password`)に、実物を見て値を入れること。
  未設定のまま実行すると当て推量で動かず `DownloadError` で明確に止まる。

## 取得失敗と売上ゼロの区別
自動DLが失敗した日は「無言の欠測」にしない。送信本文の件名が `[取得失敗] ...` になり、
本文1行目に「※これは売上ゼロではありません。取得エラーのため金額は不明です。」と出る
(通常の売上レポートには「報酬合計」の行があるが、取得失敗の通知には出ない)。

## 使い方
```
python run_report.py --dry-run                 # 送らず画面に整形結果(まず動作確認)
python run_report.py                           # config の送信口へ送信
python run_report.py --csv path/to/report.csv  # CSVを直接指定(省略時は csv_dir の最新)
python run_report.py --date 2026-09-01          # レポート日付(既定=今日)
python run_report.py --clicks 1711              # クリック数を別途渡すと総成約率を出す
```

## CSVの形式(実物で確認)
`サービス, 品番, 商品タイトル, 販売金額, 報酬体系, 報酬件数, 報酬額` の7列(cp932)。
クリック数はこのCSVに含まれないため、総成約率が要るときは `--clicks` で渡す。

## 前日比
CSVに日付列が無いため、実行ごとに日次サマリを `state/daily_summary.json` に保存し、
今回より前の最新の保存日と比較して前日比を出す。初回は「前回データが無い」と表示。

## 定期実行(任意)
Windowsのタスクスケジューラで `python <ツールの場所>\run_report.py` を毎日1回起動する。
作業フォルダ(開始ディレクトリ)をツール直下にすると `config.ini` を相対で拾える。

## テスト / 納品前チェック
```
python -m unittest discover -s tests   # 単体テスト(合成データ・実データは使わない)
python scripts/check_no_secrets.py     # 同梱物に機密が無いか機械チェック(zip前に必ず)
python scripts/build_zip.py            # 機密チェックを通してから dist/ にzipを固める
```
