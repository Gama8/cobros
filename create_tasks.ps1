[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [string]$ProjectRoot = $PSScriptRoot,
    [string]$PythonPath = '',
    [switch]$ReplaceExisting
)
$ErrorActionPreference = 'Stop'
if (-not [IO.Path]::IsPathRooted($ProjectRoot)) { throw 'ProjectRoot debe ser una ruta absoluta.' }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($PythonPath)) { $PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe' }
if (-not [IO.Path]::IsPathRooted($PythonPath)) { throw 'PythonPath debe ser una ruta absoluta.' }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$expectedPython = [IO.Path]::GetFullPath((Join-Path $ProjectRoot '.venv\Scripts\python.exe'))
if (-not $PythonPath.Equals($expectedPython, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Usa el Python de la .venv de esta copia temporal.'
}
if ($ProjectRoot.Contains('"') -or $PythonPath.Contains('"')) { throw 'Ruta inválida.' }
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.env'))) { throw 'Primero configura el .env temporal.' }
& $PythonPath (Join-Path $ProjectRoot 'preflight.py') --check-live
if ($LASTEXITCODE -ne 0) { throw 'Completa la configuración local antes de crear tareas.' }

# DateTimeOffset fija Colombia UTC-05; convierte los disparadores a la zona de Windows.
# Repetir el arranque dentro de la ventana; SQLite impide repetir un contacto reservado.
$slots = @('0900','1200','1500')
$scheduleJson = & $PythonPath (Join-Path $ProjectRoot 'schedule.py')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo leer el calendario de inicio y fin.' }
$schedule = ($scheduleJson -join "`n") | ConvertFrom-Json
$awakeUntil = if ($schedule.awake.until -is [datetime]) { [DateTimeOffset]$schedule.awake.until } else { [DateTimeOffset]::Parse($schedule.awake.until) }
$schedule.awake.until = $awakeUntil.ToOffset([TimeSpan]::FromHours(-5)).ToString("yyyy-MM-dd'T'HH:mm:sszzz")
$awakeName = $schedule.awake.name
$previousAwakeName = $null
$manifestPath = Join-Path $ProjectRoot 'logs\task_schedule.json'
if (Test-Path -LiteralPath $manifestPath) {
    try { $previousAwakeName = (Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).awake.name } catch { $previousAwakeName = $null }
}
$plans = @()
foreach ($item in $schedule.tasks) {
    # PowerShell 7 puede convertir fechas JSON automáticamente; 5.1 conserva texto.
    $startColombia = if ($item.at -is [datetime]) {
        [DateTimeOffset]$item.at
    } else {
        [DateTimeOffset]::ParseExact([string]$item.at, "yyyy-MM-dd'T'HH:mm:sszzz", [Globalization.CultureInfo]::InvariantCulture)
    }
    if ($startColombia -le [DateTimeOffset]::Now) { continue }
    $slot = $item.slot
    $name = $item.name
    $existingTask = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
    if ($null -ne $existingTask -and -not $ReplaceExisting) {
        throw "Ya existe $name. No se reemplaza; revisa o elimina sólo las tareas temporales."
    }
    $scriptPath = Join-Path $ProjectRoot $item.script
    if (-not (Test-Path -LiteralPath $scriptPath)) { throw "No existe $scriptPath" }
    $plans += [PSCustomObject]@{ Name=$name; Script=$scriptPath; At=$startColombia.LocalDateTime; AtColombia=$startColombia.ToOffset([TimeSpan]::FromHours(-5)).ToString("yyyy-MM-dd'T'HH:mm:sszzz"); TestDate=$item.test_date; Existed=($null -ne $existingTask) }
}
if ($plans.Count -eq 0) { throw 'No quedan franjas futuras en el período. Cambia las fechas de inicio y fin.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun
$created = @()
$registered = @()
try {
    foreach ($plan in $plans) {
        if ($PSCmdlet.ShouldProcess($plan.Name, "Crear tarea única para $($plan.At) hora de Windows")) {
            $action = New-ScheduledTaskAction -Execute $PythonPath -Argument ('-u "{0}" --test-date {1}' -f $plan.Script, $plan.TestDate) -WorkingDirectory $ProjectRoot
            $trigger = New-ScheduledTaskTrigger -Once -At $plan.At -RepetitionInterval (New-TimeSpan -Seconds $schedule.launch_retry.interval_seconds) -RepetitionDuration (New-TimeSpan -Seconds $schedule.launch_retry.duration_seconds)
            $trigger.EndBoundary = $plan.At.AddSeconds($schedule.launch_retry.duration_seconds).ToString('s')
            Register-ScheduledTask -TaskPath '\' -TaskName $plan.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Prueba controlada a medios propios. $($plan.TestDate) Colombia. Sin SMS." -Force:$ReplaceExisting | Out-Null
            if (-not $plan.Existed) { $created += $plan.Name }
            $registered += $plan
        }
    }
    if ($PSCmdlet.ShouldProcess($awakeName, 'Registrar auxiliar de energia al iniciar sesion')) {
        $awakeExisting = Get-ScheduledTask -TaskName $awakeName -TaskPath '\' -ErrorAction SilentlyContinue
        if ($null -ne $awakeExisting -and -not $ReplaceExisting) { throw "Ya existe $awakeName. Usa ReplaceExisting para actualizar." }
        $powershellExe = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $awakeArguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Until "{1}" -TaskName "{2}"' -f (Join-Path $ProjectRoot 'keep_awake.ps1'), $schedule.awake.until, $awakeName
        $awakeAction = New-ScheduledTaskAction -Execute $powershellExe -Argument $awakeArguments -WorkingDirectory $ProjectRoot
        $awakeTrigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
        $awakeTrigger.EndBoundary = $awakeUntil.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
        $awakeSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskPath '\' -TaskName $awakeName -Action $awakeAction -Trigger $awakeTrigger -Settings $awakeSettings -Principal $principal -Description 'Mantiene activo el PC de prueba hasta el fin del periodo; no envia contactos.' -Force:$ReplaceExisting | Out-Null
        if ($null -eq $awakeExisting) { $created += $awakeName }
    }
} catch {
    foreach ($name in $created) { Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false }
    throw
}
if ($registered.Count -gt 0) {
    $logDir = Join-Path $ProjectRoot 'logs'
    if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
    @{ start_date=$schedule.start_date; end_date=$schedule.end_date; awake=$schedule.awake; launch_retry=$schedule.launch_retry; tasks=@($registered) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $logDir 'task_schedule.json') -Encoding UTF8
    if ($previousAwakeName -and $previousAwakeName -ne $awakeName -and $previousAwakeName -match '^CobranzaV5Temp_Awake_\d{8}_\d{8}$') {
        $oldAwake = Get-ScheduledTask -TaskPath '\' -TaskName $previousAwakeName -ErrorAction SilentlyContinue
        if ($null -ne $oldAwake -and $oldAwake.Actions[0].WorkingDirectory -eq $ProjectRoot) {
            Stop-ScheduledTask -TaskPath '\' -TaskName $previousAwakeName -ErrorAction Stop
            Unregister-ScheduledTask -TaskPath '\' -TaskName $previousAwakeName -Confirm:$false
        }
    }
}
Write-Output "Período $($schedule.start_date) a $($schedule.end_date): $($plans.Count) tareas futuras. Los horarios pasados se omiten."
Write-Output 'La sesión del usuario debe permanecer iniciada; puede estar bloqueada.'
Write-Output 'Recuperacion: un arranque por minuto durante 9 minutos y 30 segundos. Los contactos reservados nunca se reenvian.'
$plans | Format-Table Name,At
