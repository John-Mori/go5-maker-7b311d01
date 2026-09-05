# 旧5秒動画資産の安全退避記録

- 退避日: 2026-09-05
- 状態: 使用停止・復元可能
- 目的: 旧5秒動画メーカー専用で、現行のDiscord部門運営、YMM4動画制作、オタクグッズアフィリエイトから参照されていない資産を作業領域から外す

## 退避したファイル

| 元の場所 | 現在の場所 | SHA-256 |
|---|---|---|
| `icon.svg` | `icon.svg` | `84C8E95436C9CE43083148BB8B748D7A4D70248F5347AEBAB847F03062B16E5D` |
| `icon-maskable.svg` | `icon-maskable.svg` | `94FA1B8A723149479B742E88520DB22E0ACBC6F4C4127A15D2D007ADA2CB6660` |
| `scripts/make_icons.py` | `scripts/make_icons.py` | `4E3C4F330B5AA0603E4C294E6AF479FDFB016305D8CEBA2EAE34D5BF18C13FFB` |
| `docs/設計・調査/設計書_アカウント切替（2アカウント）.md` | `docs/設計書_アカウント切替（2アカウント）.md` | `B4A2E11E9C7FDEFF80EA2E9050E7FF8965EF34CC9C59782BFDCA6E216664A855` |
| `docs/設計・調査/設計書_短縮URL表示とYouTube説明欄.md` | `docs/設計書_短縮URL表示とYouTube説明欄.md` | `7BDC081ED407CBC85D63760FC33875B74A44CC445C783A8C4E559F67CDB92FB3` |

## 判断根拠

リポジトリ内の稼働コード、設定、タスク、フックから上記5点への参照がないことを確認した。旧Webアプリ本体、同期処理、GAS、Workers、`local`、`.claude`、Discord・部門運営コードは現在も相互依存があるため、この退避には含めていない。

## 復元

Git管理下の移動として記録している。必要になった場合は、この表の「元の場所」へ各ファイルを戻す。ファイル内容が変わっていないことはSHA-256で確認できる。
