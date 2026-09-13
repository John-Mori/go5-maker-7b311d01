<#
.SYNOPSIS
  コンソール窓を1枚も出さずに console-subsystem の exe を実行し、標準出力と終了コードを呼び出し元へ返す。

.DESCRIPTION
  黒窓の正体= PE の subsystem が 3(CUI)の exe を、コンソールを持たない親から起動すると、
  Windows が新しいコンソールを割り当てる。既定のターミナルが Windows Terminal(既定=
  HKCU:\Console\%%Startup の Delegation* が all-zero GUID)なので、それが WT の窓として前に出る。

  実測(2026-09-13 23:3x・イージス研究室 `local/_work/winprobe.py`)=
    A `blender.exe` を素で起動        -> 可視窓 1枚(WindowsTerminal.exe・title= exeのフルパス)
    B `blender.exe` を CREATE_NO_WINDOW -> 可視窓 0枚
    C `blender-launcher.exe`(subsystem 2=GUI) -> 可視窓 0枚。ただし **標準出力を返さない**ので
      `--background` のスクリプト実行には使えない(`--version` が空で返る実測あり)。

  つまり「窓を消す」と「出力を受け取る」を両立できるのは B だけだ。
  ★このスクリプトは **新しいプロセスを作らない**(呼び出し元の pwsh/powershell の中で走る)。
    ラッパを `python foo.py` のような別プロセスで挟むと、そのラッパ自身が CUI なので窓が出る。

.EXAMPLE
  & "D:\SougouStartFolder\5SecMovieMaker\scripts\_daemons\Invoke-NoWindow.ps1" `
      -FilePath "C:\...\blender.exe" `
      -ArgumentList @("--background","--python","D:\...\review.py","--","--out","D:\...\out")
  $LASTEXITCODE  # 子の終了コード

.NOTES
  所有= イージス研究室。黒窓ポリシーの正本は `scripts/_daemons/console_window_policy.json`、
  常駐からの隠し起動は `scripts/_daemons/run_hidden.vbs`(こちらは出力を返さない用途向け)。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $FilePath,

    [Parameter(Position = 1)]
    [string[]] $ArgumentList = @(),

    [string] $WorkingDirectory,

    # 出力を画面へ流さず、まとめて返り値として受け取りたい時に立てる
    [switch] $PassThruOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $FilePath)) {
    throw "Invoke-NoWindow: 実行体が無い: $FilePath"
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName               = (Resolve-Path -LiteralPath $FilePath).ProviderPath
$psi.UseShellExecute        = $false   # ★これが $true だと CreateNoWindow が効かない
$psi.CreateNoWindow         = $true    # ★窓を作らせない本体
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError  = $true
$psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
$psi.StandardErrorEncoding  = [System.Text.Encoding]::UTF8
if ($WorkingDirectory) { $psi.WorkingDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).ProviderPath }

# ★ArgumentList は .NET Core 2.1 以降にしか無い= pwsh7 では使えるが Windows PowerShell 5.1
#   (.NET Framework)には無い。両方で動くように、無い時は自前で引用符を組む。
if ($psi.PSObject.Properties.Name -contains 'ArgumentList') {
    foreach ($a in $ArgumentList) { $psi.ArgumentList.Add($a) }
} else {
    $quoted = foreach ($a in $ArgumentList) {
        if ($a -match '[\s"]') { '"' + ($a -replace '(\\*)"', '$1$1\"') + '"' } else { $a }
    }
    $psi.Arguments = ($quoted -join ' ')
}

$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi

try {
    [void]$proc.Start()
    # ★両方を非同期で読んでから待つ。片方だけ ReadToEnd すると
    #   もう片方のパイプが詰まって子が止まる(長い --background 実行で刺さる)。
    $tOut = $proc.StandardOutput.ReadToEndAsync()
    $tErr = $proc.StandardError.ReadToEndAsync()
    $proc.WaitForExit()
    $text = $tOut.Result + $tErr.Result
    $code = $proc.ExitCode
}
finally {
    $proc.Dispose()
}

if ($PassThruOutput) {
    $text
} elseif ($text) {
    Write-Host -Object $text.TrimEnd()
}

exit $code
