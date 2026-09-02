# FANZA/DMM アフィ売上レポート 自動生成ツール

DMMアフィリエイト管理画面からエクスポートした報酬明細CSV(Shift-JIS/cp932)を
読み込み、日次の売上レポートを整形して指定の送信口へ出力する。Python標準ライブラリのみ
(送信口=mailを使う場合も標準ライブラリのsmtplibのみ)。

## 特徴
- 資格情報・URL・af_id・Webhook URL/SMTP資格情報は一切同梱していない。すべて利用者が
  `config.ini` に入れる(自分のPCの中だけ。`config.ini` はgit管理外)。
- 列は「名前」で引く(位置で引かない)。DMM側で列が増減しても必須列が在れば動く。
  必須列が欠けたら黙らず `ReportFormatError` を投げる。0バイト/HTML混入(ログイン画面が
  200で返るケース)/ヘッダのみ(=正常な売上ゼロ)も区別して扱う。
- 送信口は抽象化(stdout / Discord Webhook / mail)。CSV原本を添付して送る。
- 失敗は握り潰さない。例外を分類(`FailureKind`: セッション失効/構造変化疑い/CSV異常/
  ネットワーク障害/配送失敗/不明)し、対処ヒント付きで送信口へ通知してから非0で終了。
- 同日の二重送信を防ぐ(タスクスケジューラの二重起動/手動再実行対策)。`--force` で解除可。

## ★採用方式(腕A/腕Bについて)
設計メモで検討した2方式のうち、**採用は腕A(mode=session。保存済みセッションでの
完全自動取得)のみ**。腕B(毎朝手作業でCSVをダウンロードして所定フォルダに置く運用)は
不採用・未実装。`mode = local` は検証・移行期・手動フォールバック用として残しているが、
本番の既定は `mode = session`。

## セットアップ
1. Python 3.9 以上(パース/集計/整形/送信は標準ライブラリのみ。追加インストール不要)。
   `[download] mode = session` を使う場合のみ `pip install playwright` が必要
   (下記「CSVの取得」参照)。**`playwright install chromium` は不要**
   ( `browser_channel` で指定した、PCに元から入っている実Chrome/実Edgeをそのまま使うため)。
2. `config.example.ini` を `config.ini` にコピーし、自分の値を入れる。
   - `[input] csv_dir` … CSVを保存するフォルダ
   - `[output] sender` … `stdout`(画面表示) / `discord`(Webhook投稿。CSV添付あり) /
     `mail`(★未検証プレースホルダ。下記「未検証の範囲」参照)
   - `[output] webhook_url` … sender=discord のとき自分のWebhook URL
   - `[output] smtp_host / smtp_port / smtp_user / smtp_password / mail_from / mail_to` …
     sender=mail のとき使う
   - `[download] mode` … `local`(手動配置・検証用) か `session`(ブラウザ自動DL・本番)
   - `[download] browser_channel` … `chrome` か `msedge`(使っているブラウザに合わせる)
   - `[schedule] period` … `yesterday`(既定・本番はこれ) か `today`(動作確認用)
   - `config.ini` は zip に同梱しない/共有しない(自分のPCの中だけ)。

## CSVの取得
- `mode = local` … `csv_dir` に置いた最新CSVをそのまま使う(検証・移行期・手動フォールバック用)。
- `mode = session` … 保存済みセッション(`session_dir` の永続ブラウザプロファイル)で
  DMMアフィ管理画面からCSVを自動取得する(★本番方式・腕A確定)。**資格情報はどこにも
  保存しない**二層方式:
  - 日常運転: `session_dir` の永続プロファイルでセッションを再利用するだけ(ログイン操作をしない)。
    第1層(`export_url_template` が設定されていれば直URL叩き。速い)→ 失敗したら
    第2層(`report_page_url` を開いて `csv_export_selector` のボタンをクリックしてDL)
    の順にフォールバックする。セッション失効(401/403/ログイン画面へのリダイレクト)を
    検知した場合は `SessionExpired` を即座に投げ、フォールバックはしない
    (再ログインが要るだけなので、クリック経路を試しても無駄なため)。
  - 失効時のみ: `relogin.bat` をダブルクリック(または
    `python -m fanza_affi_report.relogin --config config.ini` を手で実行)し、
    実Chrome/実Edgeが開いたログイン画面で人が手でログインする(2FA/CAPTCHA込み)。
    「ログイン状態を保持」にチェックしてログイン後、コンソールでEnterを押すと
    セッションが `session_dir` へ保存される。**パスワードはこのツールのどこにも
    保存されない**(ブラウザ自身のセッションCookieが保存されるだけ)。
  - `export_url_template` / `report_page_url` / `csv_export_selector` / `login_url` は
    実物の管理画面を見ないと分からないため、コードには埋め込まず全て `config.ini` から渡す。
    未設定のまま実行すると当て推量で動かず `DownloadError`/`ConfigError` で明確に止まる。

## 未検証の範囲(★重要)
以下は🐧さんの実資格情報/実環境がないと検証できないため、コードは書いたが
「未検証」のまま提供している。**実際に動作確認できたと主張していない**:
- 実ログイン・実DMMアフィ管理画面からの自動CSV取得(`mode = session` の実配線)
- 実Discord Webhookへの添付ファイル付き送信
- 実SMTPサーバーを使った `mail` 送信口(プレースホルダ実装。starttls前提・smtplib標準機能のみ)

オフラインの単体テスト(合成データ)では、上記の呼び出し口の分岐ロジック(直叩き/クリック
フォールバックの選択、セッション失効の分類、添付ファイルの受け渡し、メール送信口の設定
バリデーション)はフェイクオブジェクトで検証済み。実ネットワーク・実ブラウザは一切使っていない。

## 取得失敗と売上ゼロの区別
自動DLが失敗した日は「無言の欠測」にしない。送信本文の件名が `[取得失敗] ...` になり、
本文1行目に「※これは売上ゼロではありません。取得エラーのため金額は不明です。」と出る
(通常の売上レポートには「報酬合計」の行があるが、取得失敗の通知には出ない)。
失敗本文には分類(例: セッション失効)と対処ヒント(例: relogin実行の案内)を付ける。

## 同日冪等性
`state/daily_summary.json` に送信済み日付を記録し、同じ日付を2回送らない
(タスクスケジューラの二重起動・手動再実行対策)。`--dry-run` は常にスキップ判定を無視し、
状態も記録しない(検証実行のため)。`--force` を付けると冪等性チェックを無視して強制再送する
(手動で再送したいときの解除弁)。

## 使い方
```
python run_report.py --dry-run                 # 送らず画面に整形結果(まず動作確認)
python run_report.py                           # config の送信口へ送信(既定=前日分)
python run_report.py --csv path/to/report.csv  # CSVを直接指定(省略時は自動取得/csv_dirの最新)
python run_report.py --date 2026-09-01          # レポート日付を明示指定(既定=[schedule] period)
python run_report.py --clicks 1711              # クリック数を別途渡すと総成約率を出す
python run_report.py --force                    # 同日冪外を無視して強制再送
```

## CSVの形式(実物で確認)
`サービス, 品番, 商品タイトル, 販売金額, 報酬体系, 報酬件数, 報酬額` の7列(cp932)。
クリック数はこのCSVに含まれないため、総成約率が要るときは `--clicks` で渡す。

## 前日比
CSVに日付列が無いため、実行ごとに日次サマリを `state/daily_summary.json` に保存し、
今回より前の最新の保存日と比較して前日比を出す。初回は「前回データが無い」と表示。
前回送信日から2日以上空いている場合は、本文に欠測の可能性を示す注記を出す。

## 定期実行(任意)
Windowsのタスクスケジューラで `python <ツールの場所>\run_report.py` を毎日1回起動する。
作業フォルダ(開始ディレクトリ)をツール直下にすると `config.ini` を相対で拾える。
既定の対象期間(`[schedule] period = yesterday`)により、深夜〜早朝の実行で「前日分」を送る想定。

## テスト / 納品前チェック
```
python -m unittest discover -s tests   # 単体テスト(合成データ・実データは使わない)
python scripts/check_no_secrets.py     # 同梱物に機密が無いか機械チェック(zip前に必ず)
python scripts/build_zip.py            # 機密チェックを通してから dist/ にzipを固める
```
