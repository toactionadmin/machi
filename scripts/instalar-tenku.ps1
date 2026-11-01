<#
Instala o actualiza machi en Tenku. Se corre como administrador y se puede repetir sin problema.

  1. Carpeta protegida C:\ProgramData\toaction (solo Administradores, SYSTEM y el usuario del servicio).
  2. Copias de skill-hunter y machi en esa carpeta, con su entorno de Python.
  3. Secretos en C:\ProgramData\toaction\machi.env: pide solo los que falten, sin mostrarlos.
  4. Firewall: el puerto 8706 solo acepta conexiones desde Tailscale (100.64.0.0/10).
  5. Tarea programada "toAction Machi": arranca con el equipo, aunque nadie inicie sesión,
     y se reinicia sola si falla.

Uso, en PowerShell como administrador:
  powershell -ExecutionPolicy Bypass -File scripts\instalar-tenku.ps1
#>
[CmdletBinding()]
param(
    [string]$Base = "C:\ProgramData\toaction",
    [int]$Puerto = 8706
)
$ErrorActionPreference = "Stop"

function Paso($texto) { Write-Host "`n== $texto" -ForegroundColor Cyan }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "Corre este script en una PowerShell abierta como administrador." }
$usuario = "$env:USERDOMAIN\$env:USERNAME"

# --- 1. Carpeta protegida ---
Paso "Carpeta $Base"
New-Item -ItemType Directory -Force $Base, "$Base\machi" | Out-Null
icacls $Base /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "${usuario}:(OI)(CI)F" | Out-Null
Write-Host "Acceso solo para Administradores, SYSTEM y $usuario."

# --- 2. Código ---
Paso "Código (skill-hunter y machi)"
foreach ($repo in @(@("skill-hunter", "$Base\skill-hunter"), @("machi", "$Base\machi-app"))) {
    $url = "https://github.com/toactionadmin/$($repo[0]).git"; $destino = $repo[1]
    git config --global --add safe.directory ($destino -replace '\\', '/') 2>$null
    if (Test-Path "$destino\.git") { git -C $destino pull --ff-only -q } else { git clone -q $url $destino }
    if ($LASTEXITCODE) { throw "git falló con $($repo[0])" }
    Write-Host "$($repo[0]): $(git -C $destino log --oneline -1)"
}
$app = "$Base\machi-app"
if (-not (Test-Path "$app\.venv")) { python -m venv "$app\.venv" }
& "$app\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$app\.venv\Scripts\python.exe" -m pip install -q -e $app
if ($LASTEXITCODE) { throw "No se pudo instalar machi en su entorno de Python" }
Write-Host "machi instalado en $app\.venv"

# --- 3. Secretos ---
Paso "Secretos ($Base\machi.env)"
$envFile = "$Base\machi.env"
$valores = [ordered]@{}
if (Test-Path $envFile) {
    foreach ($l in Get-Content $envFile) {
        if ($l -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $valores[$Matches[1]] = $Matches[2] }
    }
}
function Secreto($nombre, $pregunta) {
    if ($valores[$nombre]) { Write-Host "$nombre ya está guardado (no se muestra)."; return }
    $s = Read-Host $pregunta -AsSecureString
    $valores[$nombre] = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}
if (-not $valores["MACHI_TOKEN"]) {
    $bytes = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $valores["MACHI_TOKEN"] = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    Write-Host "MACHI_TOKEN generado (lo usarán Binzu, Senritsu y Gyo)."
}
Secreto "ANTHROPIC_API_KEY" "Pega la clave de la API de Claude llamada machi (no se verá)"
Secreto "NOTION_TOKEN" "Pega el token de la integración Machi de Notion (no se verá)"
if (-not $valores.Contains("NOTION_DB_ID")) { $valores["NOTION_DB_ID"] = "" }  # lo completa Claude al crear la base

$clave = "$Base\machi-drive.json"
if (-not (Test-Path $clave)) {
    $origen = Read-Host "Ruta del archivo .json de la cuenta machi-drive (ej. C:\Users\...\Downloads\toaction-servidores-xxxx.json)"
    $origen = $origen.Trim('"', ' ')
    if (-not (Test-Path $origen)) { throw "No encuentro $origen" }
    Move-Item $origen $clave
    Write-Host "Clave movida a $clave (ya no queda en la carpeta original)."
}
$ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
$valores["GOOGLE_SA_FILE"] = $clave
$valores["SKILL_HUNTER_DIR"] = "$Base\skill-hunter"
$valores["MACHI_DATOS"] = "$Base\machi"
$valores["MACHI_PUERTO"] = "$Puerto"
if ($ffmpeg) { $valores["FFMPEG"] = $ffmpeg } else { Write-Warning "No encuentro ffmpeg: instálalo con 'winget install Gyan.FFmpeg'." }

$lineas = @("# Secretos de machi. Lo escribe scripts\instalar-tenku.ps1. Nunca al repositorio ni al chat.")
foreach ($k in $valores.Keys) { $lineas += "$k=$($valores[$k])" }
[IO.File]::WriteAllLines($envFile, $lineas, (New-Object Text.UTF8Encoding $false))
Write-Host "Guardado."

# --- 4. Firewall ---
Paso "Firewall: puerto $Puerto solo desde Tailscale"
Get-NetFirewallRule -DisplayName "toAction Machi" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "toAction Machi" -Direction Inbound -Protocol TCP -LocalPort $Puerto `
    -RemoteAddress "100.64.0.0/10" -Action Allow -Profile Any | Out-Null
Write-Host "Regla 'toAction Machi' creada."
if (-not (Test-Path "C:\Program Files\Tailscale\tailscale.exe")) {
    Write-Warning "Tailscale no está instalado: sin él, Binzu no llega a machi. Instálalo desde tailscale.com con la cuenta de Kujira."
}

# --- 5. Tarea programada ---
Paso "Tarea programada 'toAction Machi'"
Write-Host "Windows pedirá la contraseña de ${usuario}: la tarea corre con ese usuario aunque nadie inicie sesión."
$cred = Get-Credential -UserName $usuario -Message "Contraseña de $usuario para la tarea de machi"
$accion = New-ScheduledTaskAction -Execute "$app\.venv\Scripts\machi.exe" -Argument "--env `"$envFile`"" -WorkingDirectory "$Base\machi"
$inicio = New-ScheduledTaskTrigger -AtStartup
# Respaldo: cada 5 minutos revisa; si machi no está corriendo (se cayó o le faltaba un secreto), lo arranca.
$vigia = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "toAction Machi" -Action $accion -Trigger $inicio, $vigia -Settings $ajustes `
    -User $usuario -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null
Stop-ScheduledTask -TaskName "toAction Machi" -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "toAction Machi"
Start-Sleep -Seconds 8
try {
    $s = Invoke-RestMethod "http://127.0.0.1:$Puerto/salud" -TimeoutSec 5
    Write-Host "machi responde: $($s.servicio) $($s.version)" -ForegroundColor Green
} catch {
    Write-Host "machi todavía no responde. Si falta NOTION_DB_ID es normal: Claude crea la base y machi arranca solo en menos de 5 minutos." -ForegroundColor Yellow
    Write-Host "Registro: $Base\machi\machi.log"
}
Write-Host "`nListo. Avísale a Claude." -ForegroundColor Green
