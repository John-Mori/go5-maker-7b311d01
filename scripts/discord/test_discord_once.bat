@echo off
rem Discord受信テスト(1回だけ巡回して終了)
cd /d D:\SougouStartFolder\go5-maker
python scripts\discord\inbox_poller.py --once
pause
