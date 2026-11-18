[CmdletBinding(SupportsShouldProcess=$true)]
param([string]$ProjectRoot = '', [switch]$ReplaceExisting)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = $PSScriptRoot }
$env:PYTHONDONTWRITEBYTECODE = '1'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([IO.Path]::GetFileName($ProjectRoot) -ne 'cobranza_bot_v5_temp') { throw 'Usa exclusivamente la carpeta cobranza_bot_v5_temp.' }
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
& $python -B (Join-Path $ProjectRoot 'preflight.py') --check-live
if ($LASTEXITCODE -ne 0) { throw 'Revisa .env antes de programar.' }
$json = & $python -B (Join-Path $ProjectRoot 'schedule.py')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo leer el calendario.' }
$plan = ($json -join "`n") | ConvertFrom-Json
if ($plan.mode -ne 'continuous' -or -not $plan.enabled -or $plan.tasks.Count -ne 3) { throw 'Requiere TEST_SCHEDULE_MODE=continuous y TEST_ENABLED=true.' }
$allTasks = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun
$registered = @()
$created = @()
try {
    foreach ($item in $plan.tasks) {
        $existing = $allTasks | Where-Object TaskName -EQ $item.name
        if ($existing -and ($existing.Actions.Count -ne 1 -or $existing.Actions[0].WorkingDirectory -ne $ProjectRoot)) { throw "La tarea $($item.name) pertenece a otra ubicacion. Cancelala desde esa copia antes de trasladar la programacion." }
        if ($existing -and -not $ReplaceExisting) { throw "Ya existe $($item.name); usa ReplaceExisting." }
        $at = if ($item.at -is [datetime]) { [DateTimeOffset]$item.at } else { [DateTimeOffset]::Parse($item.at) }
        if ($PSCmdlet.ShouldProcess($item.name, 'Registrar tarea diaria sin fecha de fin')) {
            $script = Join-Path $ProjectRoot $item.script
            $action = New-ScheduledTaskAction -Execute $python -Argument ('-u "{0}"' -f $script) -WorkingDirectory $ProjectRoot
            $trigger = New-ScheduledTaskTrigger -Daily -DaysInterval 1 -At $at.LocalDateTime
            $retry = New-ScheduledTaskTrigger -Once -At $at.LocalDateTime -RepetitionInterval (New-TimeSpan -Seconds 60) -RepetitionDuration (New-TimeSpan -Seconds 570)
            $trigger.Repetition = $retry.Repetition
            # UTC mantiene los horarios de Colombia incluso si Windows usa otra zona.
            $trigger.StartBoundary = $at.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
            $trigger.EndBoundary = ''
            Register-ScheduledTask -TaskPath '\' -TaskName $item.name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Prueba diaria a medios propios, hasta cancelar. Sin SMS.' -Force:$ReplaceExisting | Out-Null
            if (-not $existing) { $created += $item.name }
            $registered += [PSCustomObject]@{ Name=$item.name; Script=$script; AtColombia=$at.ToOffset([TimeSpan]::FromHours(-5)).ToString('o'); Arguments=$action.Arguments; Daily=$true }
        }
    }
    $awakeName = $plan.awake.name
    $existing = $allTasks | Where-Object TaskName -EQ $awakeName
    if ($existing -and ($existing.Actions.Count -ne 1 -or $existing.Actions[0].WorkingDirectory -ne $ProjectRoot)) { throw 'El auxiliar diario pertenece a otra ubicacion.' }
    if ($existing -and -not $ReplaceExisting) { throw 'Ya existe el auxiliar diario; usa ReplaceExisting.' }
    if ($PSCmdlet.ShouldProcess($awakeName, 'Registrar auxiliar de energia continuo al iniciar sesion')) {
        $exe = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Continuous -TaskName "{1}"' -f (Join-Path $ProjectRoot 'keep_awake.ps1'), $awakeName
        $action = New-ScheduledTaskAction -Execute $exe -Argument $arguments -WorkingDirectory $ProjectRoot
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
        $awakeSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskPath '\' -TaskName $awakeName -Action $action -Trigger $trigger -Settings $awakeSettings -Principal $principal -Description 'Auxiliar de energia de prueba, hasta cancelar; no envia contactos.' -Force:$ReplaceExisting | Out-Null
        if (-not $existing) { $created += $awakeName }
    }
} catch {
    foreach ($name in $created) { Unregister-ScheduledTask -TaskPath '\' -TaskName $name -Confirm:$false }
    throw
}
if ($registered.Count -eq 3) {
    $logDir = Join-Path $ProjectRoot 'logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    @{ mode='continuous'; start_date=$null; end_date=$null; awake=$plan.awake; launch_retry=$plan.launch_retry; tasks=@($registered) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $logDir 'task_schedule.json') -Encoding UTF8
    # Sustituir solo las tareas temporales anteriores que usan esta misma copia.
    foreach ($old in $allTasks) {
        $todayKey = [DateTimeOffset]::Now.ToOffset([TimeSpan]::FromHours(-5)).ToString('yyyyMMdd')
        if ($old.TaskName -match '^CobranzaV5Temp_(\d{8})_' -and $Matches[1] -lt $todayKey) { continue }
        if ($old.TaskName -match '^CobranzaV5Temp_Awake_\d{8}_(\d{8})$' -and $Matches[1] -lt $todayKey) { continue }
        if ($old.TaskName -match '^CobranzaV5Temp_(?:\d{8}_(?:0900|1200|1500)|Awake_\d{8}_\d{8})$' -and
            $old.Actions.Count -eq 1 -and $old.Actions[0].WorkingDirectory -eq $ProjectRoot -and
            $PSCmdlet.ShouldProcess($old.TaskName, 'Sustituir la tarea temporal por la programacion diaria')) {
            if ($old.State -eq 'Running') { Stop-ScheduledTask -TaskPath '\' -TaskName $old.TaskName }
            Unregister-ScheduledTask -TaskPath '\' -TaskName $old.TaskName -Confirm:$false -ErrorAction Stop
        }
    }
}
$registered | Format-Table Name,AtColombia
