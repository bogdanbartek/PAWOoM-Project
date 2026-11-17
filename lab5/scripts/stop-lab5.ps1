# Zatrzymuje wszystko, co uruchomil start-lab5.ps1.
# Uzycie:  .\lab5\scripts\stop-lab5.ps1            (zatrzymuje uslugi, bramke, Eureke i RabbitMQ; Redis zostaje)
#          .\lab5\scripts\stop-lab5.ps1 -ResetData (dodatkowo kasuje baze SQLite usludi floty)
#          .\lab5\scripts\stop-lab5.ps1 -StopRedis (dodatkowo zatrzymuje kontener Redis o nazwie lab5)
param(
    [switch]$ResetData,
    [switch]$StopRedis
)

$lab5 = Split-Path -Parent $PSScriptRoot

# Procesy slucajace na portach LAB5 (uslugi + bramka). Najpierw bramka, potem uslugi.
foreach ($port in 8080, 8102, 8103, 8104, 8101) {
    $owners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($owner in $owners) {
        try {
            Stop-Process -Id $owner -Force -ErrorAction Stop
            Write-Host "Zatrzymano proces $owner (port $port)"
        } catch { Write-Host "Nie mozna zatrzymac procesu $owner (port $port): $($_.Exception.Message)" }
    }
}

Push-Location $lab5
try { cmd /c "docker compose down 2>&1" | Out-Host } finally { Pop-Location }

if ($StopRedis) { cmd /c "docker stop lab5 >nul 2>&1"; Write-Host 'Zatrzymano kontener Redis (lab5)' }

if ($ResetData) {
    $db = Join-Path $lab5 'scooter-service\app.db'
    if (Test-Path $db) { Remove-Item $db -Force; Write-Host "Usunieto $db" }
}

Write-Host 'Zatrzymane.'
