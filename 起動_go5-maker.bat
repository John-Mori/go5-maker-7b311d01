@echo off
rem ============================================================
rem  go5-maker 司令塔/部門セッション ワンクリック起動 (go5-maker固定)
rem  2026-07-15 作成: 外フォルダから開いてcd跨ぎ=毎コマンド分類器判定
rem  →分類器(claude-opus-4-8)障害時にBash/Edit(書き込み)全滅する罠を塞ぐため。
rem  必ずこのbatから開く=cwdが常に go5-maker 直下に固定される。
rem ============================================================
cd /d D:\SougouStartFolder\go5-maker
title go5-maker (Claude Code)
echo [cwd] %CD%
where claude >nul 2>&1
if %errorlevel%==0 (
  claude
) else (
  echo.
  echo claude コマンドが見つかりません。Claude Code CLI をインストールするか、
  echo Claude Code アプリのフォルダ選択で D:\SougouStartFolder\go5-maker を開いてください。
  echo (このウィンドウのcwdは go5-maker 直下に固定済み)
  echo.
  pause
)
