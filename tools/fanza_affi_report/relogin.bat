@echo off
REM FANZA/DMMアフィ売上レポート: セッション失効時の再ログイン(手動・年数回想定)
REM 実Chrome/Edgeが開くので、2FA/CAPTCHA込みで人が手でログインしてください。
REM 「ログイン状態を保持」にチェックしてログイン後、コンソールでEnterを押すと
REM セッションが保存されます。パスワードはこのツールのどこにも保存されません。

cd /d "%~dp0"
python -m fanza_affi_report.relogin --config config.ini
pause
