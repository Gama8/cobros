param([DateTimeOffset]$Until, [string]$TaskName = '', [switch]$Continuous)
if (-not $Continuous -and -not $PSBoundParameters.ContainsKey('Until')) { throw 'Indica Until o Continuous.' }
$untilValue = if ($Continuous) { $null } else { $Until.ToString('o') }
$ErrorActionPreference = 'Stop'
$logDir = Join-Path $PSScriptRoot 'logs'
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$statusPath = Join-Path $logDir 'keep_awake.json'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CobranzaTestPower {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern uint SetThreadExecutionState(uint state);
}
'@
try {
    if (-not $Continuous -and [DateTimeOffset]::Now -ge $Until) { return }
    if ([CobranzaTestPower]::SetThreadExecutionState([uint32]2147483649) -eq 0) { throw 'Windows no aceptó mantener el sistema activo.' }
    while ($Continuous -or [DateTimeOffset]::Now -lt $Until) {
        $configText = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '.env'))
        if ($configText -match '(?im)^[ \t]*TEST_ENABLED[ \t]*=[ \t]*false[ \t]*(?:#.*)?$') { break }
        @{ status='active'; pid=$PID; until=$untilValue; task_name=$TaskName; heartbeat=[DateTimeOffset]::Now.ToString('o') } |
            ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
        Start-Sleep -Seconds 30
    }
} finally {
    [void][CobranzaTestPower]::SetThreadExecutionState([uint32]2147483648)
    # Un auxiliar anterior no sobrescribe el estado de una preparación más reciente.
    $current = $null
    if (Test-Path -LiteralPath $statusPath) {
        try { $current = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json } catch { $current = $null }
    }
    if ($null -eq $current -or $current.pid -eq $PID) {
        @{ status='finished'; pid=$PID; until=$untilValue; task_name=$TaskName; heartbeat=[DateTimeOffset]::Now.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
    }
}
