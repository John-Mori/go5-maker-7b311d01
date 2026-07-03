@echo off
rem go5-maker: 販売数の常駐ポーリング（タスクスケジューラから15分ごとに呼ばれる）
rem 普段は「要求なし・期限内・キュー空」なら即終了しDMMに一切触れない。
rem リモート「▶今すぐ取得」要求か、18時間経過した追跡サークルがある時だけ実際に取得する。
chcp 65001 >nul
cd /d "%~dp0.."
node scripts\fetch_sales.mjs --poll >> "%TEMP%\go5-sales-poll.log" 2>&1
