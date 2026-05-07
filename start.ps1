# start.ps1 — Bootstrap-Skript für den AAS-Studio-Stack
#
# 1. Detect best LAN IPv4 (filters loopback, link-local, vEthernet, WSL adapters)
# 2. Per service: probe default port; if busy, walk +100 until a free port is found
# 3. Write .env  +  GUI/connection.json  with the resolved values
# 4. docker compose up -d  (with optional --build, depending on the action arg)
# 5. Print the resulting URLs

param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'clean', 'status')]
    [string]$Action = 'start'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $repoRoot

Write-Host ''
Write-Host '════════════════════════════════════════════════════════════════════' -ForegroundColor Cyan
Write-Host '  AAS-Studio · Bootstrap                                            ' -ForegroundColor Cyan
Write-Host '════════════════════════════════════════════════════════════════════' -ForegroundColor Cyan
Write-Host ''

# ─────────────────────────────────────────────────────────────────────
# 1. Detect best LAN IP
# ─────────────────────────────────────────────────────────────────────

function Get-BestLanIP {
    # Prefer adapters that are actually carrying real LAN traffic:
    #   - IPv4
    #   - state Preferred
    #   - not loopback (127.x), not link-local (169.254.x)
    #   - not from common virtual adapters (vEthernet, WSL, Docker, Hyper-V)
    $virtualAliases = '@(vEthernet|WSL|Docker|Hyper-V|VirtualBox|VMware)'

    $candidates = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.AddressState -eq 'Preferred' -and
            $_.IPAddress -notmatch '^127\.' -and
            $_.IPAddress -notmatch '^169\.254\.' -and
            $_.InterfaceAlias -notmatch $virtualAliases
        } |
        Sort-Object @{Expression = { $_.PrefixOrigin -eq 'Dhcp' }; Descending = $true},
                    InterfaceMetric

    if ($candidates) { return $candidates[0].IPAddress }

    # Fallback — accept virtual adapters
    $any = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.AddressState -eq 'Preferred' -and
            $_.IPAddress -notmatch '^127\.' -and
            $_.IPAddress -notmatch '^169\.254\.'
        } | Select-Object -First 1
    if ($any) { return $any.IPAddress }

    Write-Warning 'Konnte keine LAN-IP ermitteln, falle auf "localhost" zurück.'
    return 'localhost'
}

$hostIp = Get-BestLanIP
Write-Host "Host-IP erkannt:  $hostIp" -ForegroundColor Green

# Show all detected IPs in case the user wants to override
$allIps = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.AddressState -eq 'Preferred' -and
        $_.IPAddress -notmatch '^127\.'
    } |
    Select-Object -Property IPAddress, InterfaceAlias
if ($allIps.Count -gt 1) {
    Write-Host '  (verfügbare Adapter:)' -ForegroundColor DarkGray
    foreach ($a in $allIps) {
        $marker = if ($a.IPAddress -eq $hostIp) { '*' } else { ' ' }
        Write-Host ("   {0} {1,-15}  {2}" -f $marker, $a.IPAddress, $a.InterfaceAlias) -ForegroundColor DarkGray
    }
}
Write-Host ''

# ─────────────────────────────────────────────────────────────────────
# 2. Port scanning — find a free port near each default
# ─────────────────────────────────────────────────────────────────────

function Test-PortFree {
    param([int]$Port)
    try {
        $listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Any, $Port)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

function Find-FreePort {
    param(
        [int]$Default,
        [int]$Step = 100,
        [int]$MaxAttempts = 20
    )
    $port = $Default
    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        if (Test-PortFree -Port $port) { return $port }
        $port = $port + $Step
        if ($port -gt 65000) { $port = 49152 }   # use ephemeral range
    }
    throw "Kein freier Port nahe $Default gefunden (probiert $MaxAttempts × +$Step)."
}

# Service → Default-Host-Port (Container-interne Ports bleiben wie in compose)
$portDefaults = [ordered]@{
    GUI_PORT             = 5000
    AAS_ENV_PORT         = 8081
    AAS_REGISTRY_PORT    = 8082
    SM_REGISTRY_PORT     = 8083
    DISCOVERY_PORT       = 8084
    ORCHESTRATOR_PORT    = 8085
    INFLUXDB_PORT        = 8086
    CONTAINER_API_PORT   = 8090
    MQTT_PORT            = 1883
    UI_PORT              = 3000
    GRAFANA_PORT         = 3001
    OPCUA_PORT           = 4840
    MODBUS_PORT          = 5020
    SIMULATOR_HTTP_PORT  = 8099
    KAFKA_PORT           = 9092
    OCPP_CS_PORT         = 9000
    DLMS_PORT            = 4059
    BACNET_PORT          = 47808
}

Write-Host 'Port-Scan:' -ForegroundColor Cyan

$ports = [ordered]@{}
$conflicts = 0
foreach ($key in $portDefaults.Keys) {
    $default = $portDefaults[$key]
    $resolved = Find-FreePort -Default $default
    $ports[$key] = $resolved
    if ($resolved -ne $default) {
        $conflicts++
        Write-Host ("  {0,-22} {1,5}  →  {2,5}  (Default belegt)" -f $key, $default, $resolved) -ForegroundColor Yellow
    } else {
        Write-Host ("  {0,-22} {1,5}  ✓" -f $key, $default) -ForegroundColor DarkGreen
    }
}
Write-Host ''
if ($conflicts -gt 0) {
    Write-Host "  $conflicts Port(s) wurden umgemappt." -ForegroundColor Yellow
}

# ─────────────────────────────────────────────────────────────────────
# 3. Write .env file (docker-compose reads it automatically)
# ─────────────────────────────────────────────────────────────────────

$envPath = Join-Path $repoRoot '.env'
if (Test-Path $envPath) {
    $backupPath = "$envPath.bak"
    Copy-Item $envPath $backupPath -Force
    Write-Host "Backup der bisherigen .env nach .env.bak"
}

$envLines = @(
    '# Auto-generated by start.ps1 — do not edit manually.',
    "# Run start.bat to regenerate.",
    "HOST_IP=$hostIp"
)
foreach ($key in $ports.Keys) {
    $envLines += "$key=$($ports[$key])"
}
$envLines | Out-File -FilePath $envPath -Encoding utf8 -Force
Write-Host "[OK]  .env geschrieben" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────
# 4. Write GUI/connection.json (consumed by Studio-GUI at startup)
# ─────────────────────────────────────────────────────────────────────

$conn = [ordered]@{
    host  = $hostIp
    ports = [ordered]@{
        aas          = [int]$ports.AAS_ENV_PORT
        aas_registry = [int]$ports.AAS_REGISTRY_PORT
        sm_registry  = [int]$ports.SM_REGISTRY_PORT
        discovery    = [int]$ports.DISCOVERY_PORT
        orchestrator = [int]$ports.ORCHESTRATOR_PORT
        influxdb     = [int]$ports.INFLUXDB_PORT
        mqtt         = [int]$ports.MQTT_PORT
        grafana      = [int]$ports.GRAFANA_PORT
        ui           = [int]$ports.UI_PORT
    }
}
$connPath = Join-Path $repoRoot 'GUI\connection.json'
$conn | ConvertTo-Json -Depth 4 | Out-File -FilePath $connPath -Encoding utf8 -Force
Write-Host "[OK]  GUI/connection.json geschrieben" -ForegroundColor Green
Write-Host ''

# ─────────────────────────────────────────────────────────────────────
# 5. Docker action
# ─────────────────────────────────────────────────────────────────────

function Test-DockerAvailable {
    try {
        docker version --format '{{.Server.Version}}' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

if (-not (Test-DockerAvailable)) {
    Write-Host '[WARN] Docker Engine antwortet nicht — versuche WSL-Reset...' -ForegroundColor Yellow
    wsl --shutdown 2>$null
    Write-Host '       Warte 12 Sekunden auf Engine-Neustart...' -ForegroundColor DarkGray
    Start-Sleep -Seconds 12
    if (-not (Test-DockerAvailable)) {
        Write-Host '[ERROR] Docker Engine nach Reset immer noch nicht erreichbar.' -ForegroundColor Red
        Write-Host '        Bitte Docker Desktop manuell neu starten und erneut versuchen.' -ForegroundColor Red
        exit 2
    }
    Write-Host '[OK]  Docker Engine nach WSL-Reset wieder erreichbar.' -ForegroundColor Green
}

switch ($Action) {
    'status' {
        Write-Host 'Status (kein Restart):' -ForegroundColor Cyan
        docker compose ps
    }
    'clean' {
        Write-Host 'Tearing down stack...' -ForegroundColor Cyan
        docker compose down --volumes --remove-orphans
        Write-Host 'Rebuilding + starting...' -ForegroundColor Cyan
        docker compose up -d --build
    }
    default {
        Write-Host 'Starting docker-compose stack...' -ForegroundColor Cyan
        docker compose up -d --build
    }
}

if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '[ERROR] docker compose ist fehlgeschlagen.' -ForegroundColor Red
    exit $LASTEXITCODE
}

# ─────────────────────────────────────────────────────────────────────
# 6. Summary
# ─────────────────────────────────────────────────────────────────────

Write-Host ''
Write-Host '════════════════════════════════════════════════════════════════════' -ForegroundColor Green
Write-Host '  Stack ist hochgefahren                                            ' -ForegroundColor Green
Write-Host '════════════════════════════════════════════════════════════════════' -ForegroundColor Green
$urls = @(
    @{ name = 'Studio-GUI    ';  port = $ports.GUI_PORT },
    @{ name = 'BaSyx Web UI  ';  port = $ports.UI_PORT },
    @{ name = 'Grafana       ';  port = $ports.GRAFANA_PORT },
    @{ name = 'InfluxDB      ';  port = $ports.INFLUXDB_PORT },
    @{ name = 'AAS REST-API  ';  port = $ports.AAS_ENV_PORT },
    @{ name = 'AAS Registry  ';  port = $ports.AAS_REGISTRY_PORT },
    @{ name = 'SM Registry   ';  port = $ports.SM_REGISTRY_PORT },
    @{ name = 'Orchestrator  ';  port = $ports.ORCHESTRATOR_PORT },
    @{ name = 'Container-API ';  port = $ports.CONTAINER_API_PORT }
)
foreach ($u in $urls) {
    Write-Host ("  {0}  http://{1}:{2}" -f $u.name, $hostIp, $u.port) -ForegroundColor White
}
Write-Host ("  MQTT-Broker     tcp://{0}:{1}" -f $hostIp, $ports.MQTT_PORT) -ForegroundColor White
Write-Host ''
Write-Host 'Studio-GUI öffnen:' -ForegroundColor Cyan
Write-Host ("  http://{0}:{1}" -f $hostIp, $ports.GUI_PORT) -ForegroundColor White -BackgroundColor DarkBlue
Write-Host ''
