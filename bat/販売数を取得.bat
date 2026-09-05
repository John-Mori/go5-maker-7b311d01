@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 候補タブの実売本数（販売数）を取得します（PC=日本IPでスクレイプ） ===
echo （候補タブでサークルを表示すると、取得待ちの作品がここに溜まります）
node scripts\fetch_sales.mjs %*
echo.
pause
