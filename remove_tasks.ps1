[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [string]$StartDate = '',
    [string]$EndDate = '',
    [string]$TestDate = '',
    [string]$ProjectRoot = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
if (-not [string]::IsNullOrWhiteSpace($TestDate)) {
    if ($StartDate -or $EndDate) { throw 'Usa TestDate para un día o StartDate y EndDate para un período.' }
    $StartDate = $TestDate
    $EndDate = $TestDate
} elseif ([string]::IsNullOrWhiteSpace($StartDate) -ne [string]::IsNullOrWhiteSpace($EndDate)) {
    throw 'Indica ambas fechas: StartDate y EndDate.'
} elseif ([string]::IsNullOrWhiteSpace($StartDate)) {
    $text = [IO.File]::ReadAllText((Join-Path $ProjectRoot '.env'))
    $StartDate = '2026-10-09'
    if ($text -match '(?m)^\s*TEST_DATE\s*=\s*([^\r\n#]+)') { $StartDate = $Matches[1].Trim().Trim([char]34).Trim([char]39) }
    if ($text -match '(?m)^\s*TEST_START_DATE\s*=\s*([^\r\n#]+)') { $StartDate = $Matches[1].Trim().Trim([char]34).Trim([char]39) }
    $EndDate = $StartDate
    if ($text -match '(?m)^\s*TEST_END_DATE\s*=\s*([^\r\n#]+)') { $EndDate = $Matches[1].Trim().Trim([char]34).Trim([char]39) }
}
$start = [datetime]::ParseExact($StartDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
$end = [datetime]::ParseExact($EndDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
if ($end -lt $start) { throw 'La fecha fin no puede ser anterior a inicio.' }
for ($day = $start; $day -le $end; $day = $day.AddDays(1)) {
    $dateKey = $day.ToString('yyyyMMdd')
    foreach ($slot in @('0900','1200','1500')) {
        $name = "CobranzaV5Temp_${dateKey}_$slot"
        $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
        if ($null -ne $task -and $PSCmdlet.ShouldProcess($name, 'Eliminar sólo esta tarea temporal')) {
            Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false
            Write-Output "Eliminada: $name"
        }
    }
}
$awakeName = 'CobranzaV5Temp_Awake_{0}_{1}' -f $start.ToString('yyyyMMdd'), $end.ToString('yyyyMMdd')
$awakeTask = Get-ScheduledTask -TaskPath '\' -TaskName $awakeName -ErrorAction SilentlyContinue
if ($null -ne $awakeTask -and $PSCmdlet.ShouldProcess($awakeName, 'Detener y eliminar el auxiliar de energia de este periodo')) {
    Stop-ScheduledTask -TaskPath '\' -TaskName $awakeName -ErrorAction Stop
    Unregister-ScheduledTask -TaskPath '\' -TaskName $awakeName -Confirm:$false
}
