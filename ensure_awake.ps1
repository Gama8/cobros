[CmdletBinding()]
param([string]$ProjectRoot = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$manifest = Get-Content -LiteralPath (Join-Path $ProjectRoot 'logs\task_schedule.json') -Raw | ConvertFrom-Json
$name = $manifest.awake.name
if ($name -notmatch '^CobranzaV5Temp_Awake_\d{8}_\d{8}$') { throw 'No hay una tarea de energia valida en el calendario.' }
function As-Offset($value) {
    if ($value -is [datetime]) { return [DateTimeOffset]$value }
    return [DateTimeOffset]::Parse([string]$value)
}
$until = As-Offset $manifest.awake.until
$untilText = $until.ToOffset([TimeSpan]::FromHours(-5)).ToString("yyyy-MM-dd'T'HH:mm:sszzz")
if ([DateTimeOffset]::Now -ge $until) { throw 'El periodo de prueba ya termino.' }
$task = Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop
$powershellExe = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Until "{1}" -TaskName "{2}"' -f (Join-Path $ProjectRoot 'keep_awake.ps1'), $untilText, $name
if ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $powershellExe -or $task.Actions[0].Arguments -ne $arguments -or $task.Actions[0].WorkingDirectory -ne $ProjectRoot) { throw 'La accion de energia no coincide con esta copia temporal.' }
$statusPath = Join-Path $ProjectRoot 'logs\keep_awake.json'
function Read-HealthyAwake {
    if (-not (Test-Path -LiteralPath $statusPath)) { return $null }
    try {
        $state = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
        if ($state.status -ne 'active' -or $state.task_name -ne $name -or -not $state.heartbeat) { return $null }
        $age = ([DateTimeOffset]::Now - (As-Offset $state.heartbeat)).TotalSeconds
        if ($age -lt -10 -or $age -gt 90 -or (As-Offset $state.until) -ne $until) { return $null }
        $process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
        if ($null -eq $process -or $process.ProcessName -notin @('powershell','pwsh')) { return $null }
        return $state
    } catch { return $null }
}
$healthy = Read-HealthyAwake
if ($task.State -ne 'Running' -or $null -eq $healthy) {
    if ($task.State -eq 'Running' -and $null -eq $healthy) { Stop-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop }
    Start-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop
}
$deadline = [DateTimeOffset]::Now.AddSeconds(15)
do {
    $healthy = Read-HealthyAwake
    if ($null -ne $healthy) { return $healthy }
    Start-Sleep -Milliseconds 200
} while ([DateTimeOffset]::Now -lt $deadline)
throw 'Las tareas estan registradas, pero el auxiliar de energia no tiene un proceso vivo confirmado.'
