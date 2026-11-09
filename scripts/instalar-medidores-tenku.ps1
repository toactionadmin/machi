<#
Instala o actualiza los medidores de Tenku. Se corre como administrador y se puede repetir sin problema.

  1. windows_exporter (CPU, RAM, disco, red): servicio de Windows en el puerto 9182.
  2. nvidia_gpu_exporter (uso, temperatura y memoria de la RTX 4090, vía nvidia-smi): tarea programada
     "toAction Medidor GPU" que arranca con el equipo, en el puerto 9835.
  3. Firewall: los dos puertos solo aceptan conexiones desde Tailscale (100.64.0.0/10).

Las versiones están fijadas y cada descarga se verifica con su SHA-256 antes de instalar nada:
si no coincide, el script se detiene. Para subir de versión, cambia $WindowsExporter / $GpuExporter
(versión y SHA-256 salen de la página de la versión en GitHub).

Uso, en PowerShell como administrador:
  powershell -ExecutionPolicy Bypass -File scripts\instalar-medidores-tenku.ps1
#>
[CmdletBinding()]
param(
    [string]$Base = "C:\ProgramData\toaction",
    [int]$PuertoEquipo = 9182,
    [int]$PuertoGpu = 9835
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$WindowsExporter = @{
    Version = "0.32.1"
    Url     = "https://github.com/prometheus-community/windows_exporter/releases/download/v0.32.1/windows_exporter-0.32.1-amd64.msi"
    Sha256  = "8e1ade6a2fbcdeb4774c300b598667cd7888246be8fcc4b586d11b3680433981"
}
$GpuExporter = @{
    Version = "1.16.0"
    Url     = "https://github.com/utkuozdemir/nvidia_gpu_exporter/releases/download/v1.16.0/nvidia_gpu_exporter_1.16.0_windows_x86_64.zip"
    Sha256  = "82153bbea747527e6d7ee16c4423de7a32a94154ef8090730fd3cf5401b4261d"
}

function Paso($texto) { Write-Host "`n== $texto" -ForegroundColor Cyan }

function Descargar($Origen, $Destino, $Sha256) {
    Invoke-WebRequest -Uri $Origen -OutFile $Destino -UseBasicParsing
    $real = (Get-FileHash $Destino -Algorithm SHA256).Hash.ToLower()
    if ($real -ne $Sha256.ToLower()) {
        Remove-Item $Destino -Force
        throw "El SHA-256 de lo descargado no coincide ($real). No se instaló nada de este archivo."
    }
    Write-Host "Descargado y verificado: $(Split-Path $Destino -Leaf)"
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "Corre este script en una PowerShell abierta como administrador." }

if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    throw "No encuentro nvidia-smi: el medidor de GPU lo necesita (viene con el driver de NVIDIA)."
}

$tmp = Join-Path $env:TEMP "medidores-tenku"
New-Item -ItemType Directory -Force $tmp | Out-Null

# --- 1. windows_exporter ---
Paso "windows_exporter $($WindowsExporter.Version) (puerto $PuertoEquipo)"
$servicio = Get-Service windows_exporter -ErrorAction SilentlyContinue
$instalada = $null
if ($servicio) {
    $instalada = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
        Where-Object DisplayName -like "windows_exporter*" | Select-Object -First 1).DisplayVersion
}
if ($servicio -and $instalada -and ([version]$instalada).ToString(3) -eq $WindowsExporter.Version) {
    Write-Host "Ya está instalado ($instalada)."
} else {
    $msi = Join-Path $tmp "windows_exporter.msi"
    Descargar $WindowsExporter.Url $msi $WindowsExporter.Sha256
    $argumentos = @("/i", "`"$msi`"", "/qn", "ENABLED_COLLECTORS=cpu,cs,logical_disk,memory,net,os,physical_disk,system,thermalzone",
              "LISTEN_PORT=$PuertoEquipo", "/l*v", "`"$tmp\windows_exporter.log`"")
    $p = Start-Process msiexec.exe -ArgumentList $argumentos -Wait -PassThru
    if ($p.ExitCode -notin 0, 3010) { throw "msiexec terminó con código $($p.ExitCode). Registro: $tmp\windows_exporter.log" }
    Write-Host "windows_exporter instalado."
}
Set-Service windows_exporter -StartupType Automatic
if ((Get-Service windows_exporter).Status -ne "Running") { Start-Service windows_exporter }

# --- 2. Exportador de la GPU NVIDIA ---
Paso "nvidia_gpu_exporter $($GpuExporter.Version) (puerto $PuertoGpu)"
$carpetaGpu = Join-Path $Base "medidores\nvidia_gpu_exporter"
$exe = Join-Path $carpetaGpu "nvidia_gpu_exporter.exe"
$versionMarca = Join-Path $carpetaGpu "version.txt"
$tarea = "toAction Medidor GPU"
$actual = if (Test-Path $versionMarca) { (Get-Content $versionMarca -Raw).Trim() } else { "" }
if ((Test-Path $exe) -and $actual -eq $GpuExporter.Version) {
    Write-Host "Ya está instalado ($actual)."
} else {
    $zip = Join-Path $tmp "nvidia_gpu_exporter.zip"
    Descargar $GpuExporter.Url $zip $GpuExporter.Sha256
    Stop-ScheduledTask -TaskName $tarea -ErrorAction SilentlyContinue
    Get-Process nvidia_gpu_exporter -ErrorAction SilentlyContinue | Stop-Process -Force
    New-Item -ItemType Directory -Force $carpetaGpu | Out-Null
    Expand-Archive -Path $zip -DestinationPath $carpetaGpu -Force
    if (-not (Test-Path $exe)) { throw "El zip no trae nvidia_gpu_exporter.exe." }
    Set-Content -Path $versionMarca -Value $GpuExporter.Version -Encoding ascii
    Write-Host "nvidia_gpu_exporter instalado en $carpetaGpu."
}
# Que la carpeta sea escribible solo por administradores y SYSTEM (la tarea corre como SYSTEM).
icacls $carpetaGpu /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null

$accion = New-ScheduledTaskAction -Execute $exe -Argument "--web.listen-address=:$PuertoGpu" -WorkingDirectory $carpetaGpu
$inicio = New-ScheduledTaskTrigger -AtStartup
$vigia = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Limited
Register-ScheduledTask -TaskName $tarea -Action $accion -Trigger $inicio, $vigia -Settings $ajustes -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $tarea
Write-Host "Tarea programada '$tarea' creada y en marcha."

# --- 3. Firewall ---
Paso "Firewall: puertos $PuertoEquipo y $PuertoGpu solo desde Tailscale"
foreach ($r in @(@("toAction Medidor equipo", $PuertoEquipo), @("toAction Medidor GPU", $PuertoGpu))) {
    Get-NetFirewallRule -DisplayName $r[0] -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $r[0] -Direction Inbound -Protocol TCP -LocalPort $r[1] `
        -RemoteAddress "100.64.0.0/10" -Action Allow -Profile Any | Out-Null
    Write-Host "Regla '$($r[0])' creada."
}

# --- 4. Comprobación ---
Paso "Comprobación"
Start-Sleep -Seconds 8
$ok = $true
foreach ($m in @(@("equipo", $PuertoEquipo, "windows_cpu_time_total"), @("GPU", $PuertoGpu, "nvidia_smi_utilization_gpu_ratio"))) {
    try {
        $cuerpo = (Invoke-WebRequest "http://127.0.0.1:$($m[1])/metrics" -UseBasicParsing -TimeoutSec 10).Content
        if ($cuerpo -match $m[2]) { Write-Host "Medidor de $($m[0]): responde y trae $($m[2])." -ForegroundColor Green }
        else { Write-Host "Medidor de $($m[0]): responde, pero no encuentro $($m[2])." -ForegroundColor Yellow; $ok = $false }
    } catch {
        Write-Host "Medidor de $($m[0]) (puerto $($m[1])) no responde: $($_.Exception.Message)" -ForegroundColor Red; $ok = $false
    }
}
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
if ($ok) { Write-Host "`nListo. Avísale a Claude." -ForegroundColor Green } else { Write-Host "`nRevisa lo de arriba y avísale a Claude." -ForegroundColor Yellow }
