@echo off
rem go5-maker: 常駐ポーリング（タスクスケジューラから15分ごとに呼ばれる）
rem 普段は「依頼キュー空・要求なし・期限内」なら即終了しDMMに一切触れない。
rem  1) 未収録作品/ブックスのフル情報（依頼キューにあれば取得）
rem  2) 販売数（リモート要求 or 18時間経過した追跡サークルがあれば取得）
chcp 65001 >nul
cd /d "%~dp0.."
node scripts\fetch_missing_works.mjs --poll >> "%TEMP%\go5-sales-poll.log" 2>&1
node scripts\fetch_sales.mjs --poll >> "%TEMP%\go5-sales-poll.log" 2>&1
