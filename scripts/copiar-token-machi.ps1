<#
Copia el MACHI_TOKEN al portapapeles, sin mostrarlo, para pegarlo en Kujira cuando
`scripts/cargar-secretos.sh` (repo nostrade) lo pida. No imprime el token ni lo guarda en otro lado.
El portapapeles se vacía solo a los 90 segundos.

Uso, en PowerShell como administrador (machi.env solo lo leen administradores):
  powershell -ExecutionPolicy Bypass -File scripts\copiar-token-machi.ps1
#>
[CmdletBinding()]
param([string]$EnvFile = "C:\ProgramData\toaction\machi.env", [int]$Segundos = 90)
$ErrorActionPreference = "Stop"

$linea = Get-Content $EnvFile | Where-Object { $_ -match '^\s*MACHI_TOKEN\s*=\s*\S+' } | Select-Object -First 1
if (-not $linea) { throw "No encuentro MACHI_TOKEN en $EnvFile. Corre primero scripts\instalar-tenku.ps1." }
$token = ($linea -split '=', 2)[1].Trim()
Set-Clipboard -Value $token
Write-Host "Token de Machi copiado al portapapeles ($($token.Length) caracteres, no se muestra)." -ForegroundColor Green
Write-Host "Pégalo en Kujira cuando cargar-secretos.sh lo pida. Se borrará del portapapeles en $Segundos s."
Start-Sleep -Seconds $Segundos
if ((Get-Clipboard -Raw).Trim() -eq $token) { Set-Clipboard -Value " "; Write-Host "Portapapeles vaciado." }
