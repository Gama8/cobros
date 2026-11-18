[CmdletBinding(SupportsShouldProcess=$true)]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([IO.Path]::GetFileName($ProjectRoot) -ne 'cobranza_bot_v5_temp') { throw 'Usa exclusivamente la copia temporal.' }
$envPath = Join-Path $ProjectRoot '.env'
if ($PSCmdlet.ShouldProcess($envPath, 'Desactivar envios automaticos con TEST_ENABLED=false')) {
    $text = [IO.File]::ReadAllText($envPath)
    if ($text -match '(?m)^[ \t]*TEST_ENABLED[ \t]*=') {
        $text = [regex]::Replace($text, '(?m)^[ \t]*TEST_ENABLED[ \t]*=[^\r\n]*', 'TEST_ENABLED=false')
    } else { $text = $text.TrimEnd() + "`r`nTEST_ENABLED=false`r`n" }
    [IO.File]::WriteAllText($envPath, $text, [Text.UTF8Encoding]::new($false))
    Write-Output 'TEST_ENABLED=false guardado. Los siguientes procesos automaticos quedan bloqueados.'
}
$tasks = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop)
foreach ($task in $tasks) {
    $todayKey = [DateTimeOffset]::Now.ToOffset([TimeSpan]::FromHours(-5)).ToString('yyyyMMdd')
    if ($task.TaskName -match '^CobranzaV5Temp_(\d{8})_' -and $Matches[1] -lt $todayKey) { continue }
    if ($task.TaskName -match '^CobranzaV5Temp_Awake_\d{8}_(\d{8})$' -and $Matches[1] -lt $todayKey) { continue }
    if ($task.TaskName -match '^CobranzaV5Temp_(?:(?:Daily|\d{8})_(?:0900|1200|1500)|Awake_(?:Daily|\d{8}_\d{8}))$' -and
        $task.Actions.Count -eq 1 -and $task.Actions[0].WorkingDirectory -eq $ProjectRoot -and
        $PSCmdlet.ShouldProcess($task.TaskName, 'Detener y eliminar esta tarea temporal')) {
        if ($task.State -eq 'Running') { Stop-ScheduledTask -TaskPath '\' -TaskName $task.TaskName -ErrorAction Stop }
        Unregister-ScheduledTask -TaskPath '\' -TaskName $task.TaskName -Confirm:$false -ErrorAction Stop
        Write-Output "Eliminada: $($task.TaskName)"
    }
}
if (-not $WhatIfPreference) {
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'logs') -Force | Out-Null
    @{ status='cancelled'; cancelled_at=[DateTimeOffset]::Now.ToString('o') } | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $ProjectRoot 'logs\setup_ready.json') -Encoding UTF8
    Write-Output 'PROGRAMACION CANCELADA. Se conservan credenciales, datos y logs. Los contactos ya enviados no se pueden retirar.'
}
