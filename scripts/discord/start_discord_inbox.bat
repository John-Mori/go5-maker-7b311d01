@echo off
rem Discord受信ポーラー常駐起動 (Phase DB)
rem 自動起動したい場合: このファイルのショートカットを shell:startup フォルダへ置く
cd /d D:\SougouStartFolder\go5-maker
title go5 Discord受信ポーラー
python scripts\discord\inbox_poller.py
pause
