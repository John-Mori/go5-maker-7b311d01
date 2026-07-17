@echo off
rem go5 daily maintenance - backfill measurement links once per day
cd /d D:\SougouStartFolder\go5-maker
title go5-daily-maintenance
:loop
python scripts\maintenance\backfill_short_links.py --go >> local\maintenance.log 2>&1
rem Cloudflare usage report (B-4). No-op until Chami puts local\cf_api_token.txt + cf_account_id.txt.
python scripts\maintenance\cf_usage_report.py >> local\maintenance.log 2>&1
powershell -NoProfile -Command "Start-Sleep -Seconds 86400"
goto loop
