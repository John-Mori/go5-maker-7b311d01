@echo off
rem go5-maker: 毎朝の採算速報自動配信(product-scout・裁定4・Chami依頼2026-07-18「ちゃんと毎朝欲しい/実装go」)
rem D1 market_snapshot(Worker cronが毎朝06:00 JSTに保存済み)を読み、採算予選の上位をDiscordへ自動投稿する。
chcp 65001 >nul
cd /d "%~dp0..\.."
python scripts\product_scout\morning_scan.py >> "%TEMP%\go5-product-scout-morning.log" 2>&1
