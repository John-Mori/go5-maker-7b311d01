# update_token.ps1 - claude setup-token で出たトークンを安全に local/cli_auth_token.txt へ保存する。
# UTF-8 BOM付きで保存すること(PS5.1はBOM無しをCP932として読み日本語文字列が壊れる=INC-109b)。
param([string]$Dest = "D:\SougouStartFolder\5SecMovieMaker\local\cli_auth_token.txt")
$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "=== 合鍵(トークン)を保存します ===" -ForegroundColor Cyan
$tok = Read-Host "トークンを貼り付けて Enter"
$tok = ($tok -replace '\s', '').Trim()

if ([string]::IsNullOrWhiteSpace($tok)) { Write-Host "空です。中止しました。" -ForegroundColor Red; exit 1 }
if ($tok.Length -lt 20) { Write-Host ("短すぎます({0}文字)。貼り付けミスの可能性。中止しました。" -f $tok.Length) -ForegroundColor Red; exit 1 }
if (-not ($tok.StartsWith('sk-ant'))) {
  Write-Host ("注意: 通常 sk-ant で始まります。今の先頭: {0}..." -f $tok.Substring(0, [Math]::Min(6, $tok.Length))) -ForegroundColor Yellow
  $ans = Read-Host "このまま保存しますか? (y/n)"
  if ($ans -ne 'y') { Write-Host "中止しました。" -ForegroundColor Red; exit 1 }
}

if (Test-Path $Dest) { Copy-Item $Dest "$Dest.bak" -Force }
[System.IO.File]::WriteAllText($Dest, $tok, [System.Text.Encoding]::ASCII)

$saved = [System.IO.File]::ReadAllText($Dest)
Write-Host ""
Write-Host ("OK 保存しました: {0}" -f $Dest) -ForegroundColor Green
Write-Host ("   長さ: {0}文字 / 先頭: {1}..." -f $saved.Length, $saved.Substring(0, [Math]::Min(8, $saved.Length)))
Write-Host "次: 研究室に「保存した」と伝えてください。"
