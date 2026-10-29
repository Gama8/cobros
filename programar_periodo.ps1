[CmdletBinding()]
param([string]$ProjectRoot = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Primero ejecuta instalar.ps1.' }
$envFile = Join-Path $ProjectRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) { throw 'Falta configurar .env.' }
$envHash = (Get-FileHash -LiteralPath $envFile -Algorithm SHA256).Hash
try { Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Out-Null }
catch { throw 'Windows bloqueo el Programador. Ejecuta este script en PowerShell como administrador con la misma cuenta que dejara la sesion iniciada.' }
Write-Output '1/4 Validando configuracion y calendario...'
& $python -B (Join-Path $ProjectRoot 'preflight.py') --check-live
if ($LASTEXITCODE -ne 0) { throw 'Revisa el .env. No se han creado tareas.' }
$json = & $python -B (Join-Path $ProjectRoot 'schedule.py')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo leer el calendario.' }
$plan = ($json -join "`n") | ConvertFrom-Json
Write-Output "Periodo inclusivo: $($plan.start_date) a $($plan.end_date). Horas Colombia: 09:00, 12:00 y 15:00."
Write-Output 'Solo se registraran franjas futuras. Se conserva el .env.'
Write-Output '2/4 Comprobando Twilio, WhatsApp y Gmail sin enviar contactos...'
& $python -B (Join-Path $ProjectRoot 'check_connections.py')
if ($LASTEXITCODE -ne 0) { throw 'Los servicios no estan listos. No se han creado tareas nuevas.' }
Write-Output '3/4 Registrando y verificando tareas...'
& (Join-Path $ProjectRoot 'create_tasks.ps1') -ProjectRoot $ProjectRoot -PythonPath $python -ReplaceExisting
$manifest = Get-Content -LiteralPath (Join-Path $ProjectRoot 'logs\task_schedule.json') -Raw | ConvertFrom-Json
if ($manifest.start_date -ne $plan.start_date -or $manifest.end_date -ne $plan.end_date -or $manifest.tasks.Count -eq 0) { throw 'Calendario registrado incorrecto.' }
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$rows = @()
foreach ($item in $manifest.tasks) {
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $item.Name -ErrorAction Stop
    $expectedArguments = '-u "{0}" --test-date {1}' -f $item.Script, $item.TestDate
    $at = if ($item.AtColombia -is [datetime]) { $item.AtColombia.ToLocalTime() } else { [DateTimeOffset]::Parse($item.AtColombia).LocalDateTime }
    $taskSid = if ($task.Principal.UserId -match '^S-1-') { $task.Principal.UserId } else {
        ([Security.Principal.NTAccount]::new($task.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value
    }
    if ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $python -or
        $task.Actions[0].Arguments -ne $expectedArguments -or $task.Actions[0].WorkingDirectory -ne $ProjectRoot -or
        $task.Triggers.Count -ne 1 -or [Math]::Abs(([datetime]::Parse($task.Triggers[0].StartBoundary) - $at).TotalSeconds) -gt 1 -or
        $task.Triggers[0].Repetition.Interval -ne 'PT1M' -or $task.Triggers[0].Repetition.Duration -ne 'PT9M30S' -or
        $task.Settings.DisallowStartIfOnBatteries -or $task.Settings.StopIfGoingOnBatteries -or -not $task.Settings.WakeToRun -or
        $task.Principal.LogonType -ne 'Interactive' -or $taskSid -ne $ownerSid) { throw "Configuracion incorrecta: $($item.Name)." }
    if ($task.State -eq 'Disabled') { Enable-ScheduledTask -TaskPath '\' -TaskName $item.Name | Out-Null }
    $info = Get-ScheduledTaskInfo -TaskPath '\' -TaskName $item.Name -ErrorAction Stop
    if ([Math]::Abs(($info.NextRunTime - $at).TotalSeconds) -gt 1) { throw "Proxima ejecucion incorrecta: $($item.Name)." }
    $rows += [PSCustomObject]@{ Tarea=$item.Name; HoraColombia=$item.AtColombia; ProximaEjecucion=$info.NextRunTime }
}
Write-Output '4/4 Iniciando y verificando el auxiliar de energia...'
$awake = & (Join-Path $ProjectRoot 'ensure_awake.ps1') -ProjectRoot $ProjectRoot
if ((Get-FileHash -LiteralPath $envFile -Algorithm SHA256).Hash -ne $envHash) { throw 'El .env cambio durante la preparacion.' }
@{ status='ready'; start_date=$manifest.start_date; end_date=$manifest.end_date;
   prepared_at=[DateTimeOffset]::Now.ToString('o'); keep_awake_pid=$awake.pid;
   awake_task=$manifest.awake.name; launch_retry=$manifest.launch_retry; tasks=@($rows) } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $ProjectRoot 'logs\setup_ready.json') -Encoding UTF8
$rows | Format-Table -AutoSize
Write-Output "LISTO: $($rows.Count) franjas futuras verificadas del $($manifest.start_date) al $($manifest.end_date)."
Write-Output 'No se enviaron contactos ahora. Deja el PC encendido, con Internet y tu sesion iniciada; puedes bloquearla y cerrar esta consola.'

