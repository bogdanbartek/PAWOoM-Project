# Uruchamia caly LAB5 w tle z jednej konsoli:
#   Redis, Eureka, RabbitMQ (Docker) + Scooter, Insurance, Payment, Maintenance (Uvicorn) + Gateway (Java).
# Uzycie (z dowolnego katalogu):  .\lab5\scripts\start-lab5.ps1
# Logi: $env:TEMP\lab5-logs\*.out / *.err    Zatrzymanie: .\lab5\scripts\stop-lab5.ps1
param(
    [string]$JavaHome = $(if ($env:JAVA_HOME) { $env:JAVA_HOME } else { 'C:\Users\oscar\tools\jdk-21.0.13+9' }),
    [string]$MavenHome = 'C:\Users\oscar\tools\apache-maven-3.9.11',
    [int]$RouteWaitSeconds = 150
)

# Continue (nie Stop): Windows PowerShell 5.1 zamienia stderr programow natywnych (docker) w bledy.
# Wszystkie bledy krytyczne sa zglaszane jawnie przez throw.
$ErrorActionPreference = 'Continue'
$lab5 = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $env:TEMP 'lab5-logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
Remove-Item "$logDir\*" -Force -ErrorAction SilentlyContinue

function Wait-Http($url, $seconds, $what) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($r.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 2
    }
    throw "Timeout: $what ($url) did not respond within $seconds s. Logs: $logDir"
}

function Port-Busy($port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

Write-Host '== 1/5 Docker: Redis, Eureka, RabbitMQ' -ForegroundColor Cyan
cmd /c "docker info >nul 2>&1"
if ($LASTEXITCODE -ne 0) { throw 'Docker nie dziala. Uruchom Docker Desktop i sprobuj ponownie.' }

foreach ($p in 8101, 8102, 8103, 8104, 8080) {
    if (Port-Busy $p) { throw "Port $p jest zajety. Uruchom najpierw .\lab5\scripts\stop-lab5.ps1" }
}

if (-not (Port-Busy 6379)) {
    cmd /c "docker start lab5 >nul 2>&1"
    if ($LASTEXITCODE -ne 0) {
        cmd /c "docker run -d --name lab5 -p 127.0.0.1:6379:6379 redis:7-alpine >nul 2>&1"
        if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie uruchomic Redisa (kontener lab5).' }
    }
}
$env:COMPOSE_PROGRESS = 'quiet'   # bez wielostronicowego logu budowania obrazu
Push-Location $lab5
try { cmd /c "docker compose up -d --build 2>&1" | Out-Host } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'docker compose up nie powiodl sie' }

Write-Host 'Czekam na Eureke (:8761) i panel RabbitMQ (:15672)...'
Wait-Http 'http://127.0.0.1:8761/' 120 'Eureka'
Wait-Http 'http://127.0.0.1:15672/' 120 'RabbitMQ management'

Write-Host '== 2/5 Sprawdzam srodowiska Pythona' -ForegroundColor Cyan
$services = @(
    @{ Dir = 'scooter-service';     Name = 'SCOOTER-SERVICE';     Port = 8101 },
    @{ Dir = 'insurance-service';   Name = 'INSURANCE-SERVICE';   Port = 8103 },
    @{ Dir = 'payment-service';     Name = 'PAYMENT-SERVICE';     Port = 8102 },
    @{ Dir = 'maintenance-service'; Name = 'MAINTENANCE-SERVICE'; Port = 8104 }
)
foreach ($s in $services) {
    $py = Join-Path $lab5 "$($s.Dir)\.venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        throw "Brak $py. Utworz srodowisko: cd lab5\$($s.Dir); py -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    }
}

# Wspolna konfiguracja (dziedziczona przez uruchamiane procesy).
$env:EUREKA_SERVER_URL = 'http://127.0.0.1:8761'
$env:INSTANCE_IP = '127.0.0.1'
$env:INSTANCE_HOST = 'localhost'
$env:RABBITMQ_URL = 'amqp://guest:guest@127.0.0.1:5672/%2F'
$env:DATABASE_URL = 'sqlite:///./app.db'
$env:REDIS_URL = 'redis://localhost:6379/0'
$env:CACHE_PREFIX = 'lab5:131409:scooter-service'

Write-Host '== 3/5 Uslugi Pythona (kolejnosc: Scooter i Insurance PRZED Payment - tworza swoje kolejki)' -ForegroundColor Cyan
$pids = @()
foreach ($s in $services) {
    $env:SERVICE_NAME = $s.Name
    $env:SERVICE_PORT = [string]$s.Port
    $dir = Join-Path $lab5 $s.Dir
    $proc = Start-Process -FilePath (Join-Path $dir '.venv\Scripts\python.exe') `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', $s.Port `
        -WorkingDirectory $dir -WindowStyle Hidden -PassThru -ErrorAction Stop `
        -RedirectStandardOutput "$logDir\$($s.Dir).out" -RedirectStandardError "$logDir\$($s.Dir).err"
    $pids += $proc.Id
    Wait-Http "http://127.0.0.1:$($s.Port)/health" 60 $s.Name
    Write-Host ("  {0,-20} port {1}  pid {2}  OK" -f $s.Name, $s.Port, $proc.Id)
}

Write-Host '== 4/5 Bramka (Java)' -ForegroundColor Cyan
$gwDir = Join-Path $lab5 'gateway'
$jar = Join-Path $gwDir 'target\api-gateway.jar'
$env:JAVA_HOME = $JavaHome
if (-not (Test-Path (Join-Path $JavaHome 'bin\java.exe'))) { throw "Nie znaleziono Javy w $JavaHome (parametr -JavaHome)" }
if (-not (Test-Path $jar)) {
    Write-Host '  Brak jara - buduje bramke (mvn package)...'
    $env:Path = "$JavaHome\bin;$MavenHome\bin;$env:Path"
    Push-Location $gwDir
    try { mvn -B -q -DskipTests package } finally { Pop-Location }
}
$gw = Start-Process -FilePath (Join-Path $JavaHome 'bin\java.exe') -ArgumentList '-jar', 'target\api-gateway.jar' `
    -WorkingDirectory $gwDir -WindowStyle Hidden -PassThru -ErrorAction Stop `
    -RedirectStandardOutput "$logDir\gateway.out" -RedirectStandardError "$logDir\gateway.err"
$pids += $gw.Id
Wait-Http 'http://127.0.0.1:8080/health' 90 'Gateway'
Write-Host ("  GATEWAY              port 8080  pid {0}  OK" -f $gw.Id)
$pids | Set-Content (Join-Path $logDir 'pids.txt')

Write-Host '== 5/5 Czekam az brama zobaczy wszystkie uslugi w Eurece (zwykle 30-70 s)' -ForegroundColor Cyan
$routes = '/api/scooters', '/api/payments', '/api/insurances', '/api/jobs'
$deadline = (Get-Date).AddSeconds($RouteWaitSeconds)
$ready = $false
while ((Get-Date) -lt $deadline) {
    $codes = foreach ($r in $routes) {
        try { (Invoke-WebRequest -Uri "http://127.0.0.1:8080$r" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop).StatusCode }
        catch { if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 } }
    }
    Write-Host ("  " + (($routes | ForEach-Object -Begin { $i = 0 } -Process { "$_=$($codes[$i])"; $i++ }) -join '  '))
    if (($codes | Where-Object { $_ -ne 200 }).Count -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 5
}

Write-Host ''
if ($ready) {
    Write-Host 'GOTOWE: wszystkie 4 trasy odpowiadaja 200.' -ForegroundColor Green
} else {
    Write-Host 'UWAGA: nie wszystkie trasy odpowiadaja 200 - odczekaj jeszcze chwile (rejestr Eureki sie odswieza) i sprawdz logi.' -ForegroundColor Yellow
}
Write-Host "Logi:             $logDir"
Write-Host 'Panel Eureki:     http://localhost:8761/'
Write-Host 'Panel RabbitMQ:   http://localhost:15672/   (guest / guest)'
Write-Host 'Bramka:           http://localhost:8080/api/scooters'
Write-Host 'Zatrzymanie:      .\lab5\scripts\stop-lab5.ps1'
