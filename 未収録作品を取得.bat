@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === API未収録作品のフル情報を取得します（PCスクレイプ） ===
node scripts\fetch_missing_works.mjs
echo.
pause
