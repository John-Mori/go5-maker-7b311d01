@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === GAS自動反映の初回セットアップ（1回だけ） ===
echo.
echo [1/2] Google へのログイン（ブラウザが開きます。john.mori8k@gmail.com で承認してください）
echo      すでにログイン済みなら、その旨表示されます。
call npx --yes @google/clasp login
echo.
echo [2/2] スクリプトIDと exec URL を登録します。
node scripts\bootstrap_gas.mjs %*
echo.
pause
