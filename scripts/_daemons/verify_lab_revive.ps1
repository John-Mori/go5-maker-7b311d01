# verify_lab_revive.ps1 - one-shot PRODUCTION verification of the Lab auto-revival (P0-3).
#
# WHY this exists: "registered" is not "works". The revive task was registered on 2026-07-16
#   and looked fine, but it held the wrong id-system value and would NOT have revived anyone
#   (found only when it was inspected, never by firing). Chami's rule after that:
#   a safety net is verified only by making it actually fire in production conditions.
#
# WHAT it does (all of it unattended, because this script KILLS the sessions that would
#   otherwise be driving the test - including the one that wrote it):
#   1. record the state before
#   2. kill every claude process (this is the production condition: "nobody is alive")
#   3. run the scheduled revive path exactly as Windows would (via the hidden VBS launcher)
#   4. wait and check: did a claude process come back? was the prompt passed?
#   5. write the result to local/_lab_revive_verify.log AND notify Discord
#
# NOTE: ASCII-only (PS 5.1 reads a BOM-less .ps1 as ANSI; non-ASCII corrupts parsing).
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$log  = Join-Path $root 'local\_lab_revive_verify.log'

function Say($m) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  Add-Content -LiteralPath $log -Value "$ts $m" -Encoding UTF8
  Write-Output "$ts $m"
}

Say "=== verify start ==="
$before = @(Get-Process -Name 'claude' -ErrorAction SilentlyContinue)
Say ("before: {0} claude process(es)" -f $before.Count)

# 2. production condition: no session alive
foreach ($p in $before) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 5
$mid = @(Get-Process -Name 'claude' -ErrorAction SilentlyContinue)
Say ("after kill: {0} claude process(es) (expect 0)" -f $mid.Count)

# 3. run the revive path exactly as the scheduled task does
Start-Process wscript.exe -ArgumentList ('"' + (Join-Path $root 'scripts\_daemons\lab_revive_hidden.vbs') + '"') -WindowStyle Hidden
Say "revive triggered (via lab_revive_hidden.vbs = same path as the scheduled task)"

# 4. wait for the window to come up (the design allows up to 10 minutes; we poll 3)
$ok = $false
for ($i = 0; $i -lt 36; $i++) {
  Start-Sleep -Seconds 5
  $now = @(Get-Process -Name 'claude' -ErrorAction SilentlyContinue)
  if ($now.Count -gt 0) { $ok = $true; Say ("revived after ~{0}s ({1} process(es))" -f (($i + 1) * 5), $now.Count); break }
}
if (-not $ok) { Say "FAIL: no claude process came back within 180s" }

# was the prompt actually built and passed?
$promptFile = Join-Path $root 'local\_lab_revive_prompt.txt'
$hasPrompt = (Test-Path -LiteralPath $promptFile) -and ((Get-Item $promptFile).Length -gt 0)
Say ("prompt file present: {0}" -f $hasPrompt)
$tail = Get-Content -LiteralPath (Join-Path $root 'local\_lab_revive.log') -Tail 2 -ErrorAction SilentlyContinue
foreach ($t in $tail) { Say ("revive.log: {0}" -f $t) }

$verdict = if ($ok -and $hasPrompt) { 'PASS' } elseif ($ok) { 'PARTIAL (revived, prompt missing)' } else { 'FAIL' }
Say ("=== verdict: {0} ===" -f $verdict)

# 5. report to Discord (Mk.II = machine announcements). Body via file: keeps this ps1 ASCII.
$body = @"
(auto) P0-3 verification of the Lab auto-revival, run in production conditions.

- before: $($before.Count) claude process(es)
- after kill: $($mid.Count) (expected 0 = "nobody is alive")
- revived: $ok
- revival prompt passed: $hasPrompt
- verdict: $verdict

Full log: local\_lab_revive_verify.log
"@
$tmp = Join-Path $env:TEMP ("go5_verify_{0}.txt" -f (Get-Date -Format 'yyyyMMddHHmmss'))
Set-Content -LiteralPath $tmp -Value $body -Encoding utf8
$persona = [regex]::Unescape('\u30E1\u30BF\u30EB\u30AE\u30A2Mk.II')
& python (Join-Path $root 'scripts\discord\persona_send.py') --channel 'incident' --persona $persona --body-file $tmp | Out-Null
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
Say "reported to incident channel"
