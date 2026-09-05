@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === GAS（コード.gs）をクラウドへ自動反映します ===
node scripts\deploy_gas.mjs %*
if errorlevel 1 pause
