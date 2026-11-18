[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = $PSScriptRoot }
$env:PYTHONDONTWRITEBYTECODE = '1'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
Write-Output '1/3 Comprobando servicios sin enviar contactos...'
& $python -B (Join-Path $ProjectRoot 'check_connections.py')
if ($LASTEXITCODE -ne 0) { throw 'Los servicios no estan listos. No se registraron tareas nuevas.' }
Write-Output '2/3 Registrando tres tareas diarias sin vencimiento...'
& (Join-Path $ProjectRoot 'create_daily_tasks.ps1') -ProjectRoot $ProjectRoot -ReplaceExisting
$manifest = Get-Content -LiteralPath (Join-Path $ProjectRoot 'logs\task_schedule.json') -Raw | ConvertFrom-Json
if ($manifest.mode -ne 'continuous' -or $manifest.tasks.Count -ne 3) { throw 'Calendario diario incorrecto.' }
$owner = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$rows = @()
foreach ($item in $manifest.tasks) {
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $item.Name -ErrorAction Stop
    $taskSid = if ($task.Principal.UserId -match '^S-1-') { $task.Principal.UserId } else { ([Security.Principal.NTAccount]::new($task.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value }
    $expected = if ($item.AtColombia -is [datetime]) { [DateTimeOffset]$item.AtColombia } else { [DateTimeOffset]::Parse($item.AtColombia) }
    $actual = [DateTimeOffset]::Parse($task.Triggers[0].StartBoundary)
    if ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $python -or $task.Actions[0].Arguments -ne $item.Arguments -or
        $task.Actions[0].WorkingDirectory -ne $ProjectRoot -or $taskSid -ne $owner -or $task.Principal.LogonType -ne 'Interactive' -or
        $task.Triggers.Count -ne 1 -or $task.Triggers[0].DaysInterval -ne 1 -or $task.Triggers[0].EndBoundary -or $actual -ne $expected -or
        $task.Triggers[0].Repetition.Interval -ne 'PT1M' -or $task.Triggers[0].Repetition.Duration -ne 'PT9M30S' -or
        $task.Settings.DisallowStartIfOnBatteries -or $task.Settings.StopIfGoingOnBatteries -or -not $task.Settings.WakeToRun) { throw "Tarea diaria incorrecta: $($item.Name)." }
    if ($task.State -eq 'Disabled') { Enable-ScheduledTask -TaskPath '\' -TaskName $item.Name | Out-Null }
    $info = Get-ScheduledTaskInfo -TaskPath '\' -TaskName $item.Name
    if ($info.NextRunTime -le [datetime]::Now.AddMinutes(-1) -or $info.NextRunTime -gt [datetime]::Now.AddHours(25)) { throw "Proxima ejecucion incorrecta: $($item.Name)." }
    $rows += [PSCustomObject]@{ Tarea=$item.Name; ProximaEjecucion=$info.NextRunTime }
}
Write-Output '3/3 Iniciando y verificando el auxiliar de energia...'
$awake = & (Join-Path $ProjectRoot 'ensure_awake.ps1') -ProjectRoot $ProjectRoot
@{ status='ready'; mode='continuous'; start_date=$null; end_date=$null;
   prepared_at=[DateTimeOffset]::Now.ToString('o'); keep_awake_pid=$awake.pid;
   awake_task=$manifest.awake.name; launch_retry=$manifest.launch_retry; tasks=@($rows) } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $ProjectRoot 'logs\setup_ready.json') -Encoding UTF8
$rows | Format-Table -AutoSize
Write-Output 'LISTO: tres tareas diarias, sin fecha de inicio ni fin, hasta que ejecutes cancelar.ps1.'
Write-Output 'Cada dia: 3 llamadas, 1 WhatsApp, 1 email, 0 SMS. Horas Colombia: 09:00, 12:00 y 15:00.'
