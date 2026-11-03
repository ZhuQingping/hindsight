param(
    [ValidateSet('all', 'api', 'ui')][string]$Component = 'all',
    [int]$Port,
    [int]$UiPort,
    [switch]$RandomPort
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$PythonExe = Join-Path $SourceRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw 'Run .\scripts\dev\setup.ps1 first.'
}
$PreviousPythonPath = $env:PYTHONPATH
$PreviousUtf8 = $env:PYTHONUTF8
Push-Location $SourceRoot
try {
    $env:PYTHONUTF8 = '1'
    $Paths = @((Join-Path $SourceRoot 'hindsight-extensions/contextdb-service'), (Join-Path $SourceRoot 'hindsight-api-slim'))
    if ($PreviousPythonPath) { $Paths += $PreviousPythonPath }
    $env:PYTHONPATH = $Paths -join [IO.Path]::PathSeparator
    $LaunchArguments = @('-m', 'hindsight_ext_contextdb.local', '--component', $Component)
    if ($PSBoundParameters.ContainsKey('Port')) { $LaunchArguments += @('--port', "$Port") }
    if ($PSBoundParameters.ContainsKey('UiPort')) { $LaunchArguments += @('--ui-port', "$UiPort") }
    if ($RandomPort) { $LaunchArguments += '--random-port' }
    & $PythonExe @LaunchArguments
    if ($LASTEXITCODE -ne 0) { throw "ContextBase exited with code $LASTEXITCODE." }
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
    $env:PYTHONUTF8 = $PreviousUtf8
    Pop-Location
}
