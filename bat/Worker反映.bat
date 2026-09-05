@echo off
rem fanza-worker(FANZAデータproxy)を Cloudflare に反映する。
rem Booksの%オフ修正(?コミット済)を本番へ。wranglerはログイン済み想定。
cd /d "%~dp0fanza-worker"
title go5 Worker反映
echo fanza-worker を Cloudflare に反映します...
echo.
call npx wrangler deploy
echo.
echo ----------------------------------------
echo 上のログを確認してください(Deployed ... と出れば成功)。
echo 問題があれば: git revert HEAD で戻し、このbatを再実行。
echo ----------------------------------------
pause
