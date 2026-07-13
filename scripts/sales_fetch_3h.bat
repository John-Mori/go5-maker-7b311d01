@echo off
rem go5-maker: 3時間ごとのフル販売数取得（タスクスケジューラから0/3/6/9/12/15/18/21時に呼ばれる）
rem --force = 18時間スキップを無視して、追跡サークルの全作品の販売数を今すぐ取得する。
chcp 65001 >nul
cd /d "%~dp0.."
node scripts\fetch_sales.mjs --force >> "%TEMP%\go5-sales-3h.log" 2>&1
