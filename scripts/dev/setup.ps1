param(
    [switch]$LocalModels,
    [string]$Python = '3.11'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $SourceRoot
try {
    Get-Command uv -ErrorAction Stop | Out-Null
    Get-Command node -ErrorAction Stop | Out-Null
    Get-Command npm.cmd -ErrorAction Stop | Out-Null
    $NodeVersion = [version](& node -p 'process.versions.node')
    if ($NodeVersion.Major -ne 24 -and -not ($NodeVersion.Major -eq 22 -and $NodeVersion.Minor -ge 12)) {
        throw 'Use Node.js 24 or Node.js 22.12+.'
    }
    $SyncArguments = @('sync', '--frozen', '--package', 'hindsight-api-slim', '--extra', 'embedded-db', '--python', $Python)
    if ($LocalModels) { $SyncArguments += @('--extra', 'local-ml') }
    & uv @SyncArguments
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    # The root prepare hook is Bash-only. Optional platform binaries are still
    # installed; SDK compilation resolves esbuild's Windows package directly.
    & npm.cmd ci --ignore-scripts --include=dev --include=optional --no-audit --no-fund --workspace=contextbase-control-plane --workspace=hindsight-clients/typescript
    if ($LASTEXITCODE -ne 0) { throw 'Node dependency installation failed.' }
    & npm.cmd run build -w contextbase-client
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript SDK build failed.' }
    Write-Host 'Dependencies ready. Configure .env, then run .\scripts\dev\start.ps1.'
    Write-Host 'Remote model providers need no -LocalModels; local embedding/reranking providers require it.'
} finally { Pop-Location }
