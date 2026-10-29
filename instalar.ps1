[CmdletBinding()]
param([string]$ProjectRoot = $PSScriptRoot, [string]$BasePython = '')
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    if ($BasePython) {
        & $BasePython -m venv (Join-Path $ProjectRoot '.venv')
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv (Join-Path $ProjectRoot '.venv')
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv (Join-Path $ProjectRoot '.venv')
    } else {
        throw 'Instala Python 3.10 o posterior o indica -BasePython con su ruta absoluta.'
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) { throw 'No se pudo crear .venv.' }
}
& $python -m pip install --disable-pip-version-check --no-input -r (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
$envFile = Join-Path $ProjectRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot '.env.example') -Destination $envFile
}
Write-Output 'Instalacion lista. Configura el .env local con tus contactos, credenciales y fechas.'
Write-Output 'No se crearon tareas ni se enviaron contactos. Un .env existente se conserva.'

