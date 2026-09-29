<#
.SYNOPSIS
  Start CityPulse (FastAPI + built React dashboard) and publish it on a public URL.

.DESCRIPTION
  One process serves the API/WebSocket *and* frontend/dist, so a single origin is
  published with a Cloudflare quick tunnel. Cloudflare quick-tunnel hostnames are
  randomly generated per run and are never reused, so a previously shared
  *.trycloudflare.com link always dies when the tunnel process or the machine stops.
  Re-run this script to get a fresh working URL.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\serve-public.ps1
  powershell -ExecutionPolicy Bypass -File scripts\serve-public.ps1 -NoTunnel   # local only
#>
[CmdletBinding()]
param(
  [int]$Port = 8000,
  [string]$CloudflaredPath = "$env:USERPROFILE\citypulse-tools\cloudflared.exe",
  # 0.0.0.0 also accepts devices on the same Wi-Fi/LAN (helps when an ISP blocks
  # *.trycloudflare.com). Use -LocalOnly to restrict to this machine again.
  [string]$BindHost = "0.0.0.0",
  [switch]$LocalOnly,
  [switch]$NoTunnel,
  [switch]$SkipBuild,
  [switch]$SkipSimStart
)

$ErrorActionPreference = "Stop"

if ($LocalOnly) { $BindHost = "127.0.0.1" }

$ProjectRoot = Split-Path -Parent $PSScriptRoot      # ...\CityPulse
$BackendDir  = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$DistDir     = Join-Path $FrontendDir "dist"
$PythonExe   = Join-Path $BackendDir ".venv\Scripts\python.exe"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# ---------------------------------------------------------------- pre-flight ---
if (-not (Test-Path $PythonExe)) {
  throw "Backend venv not found at $PythonExe. Create it first:`n  cd backend; python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt"
}

# --------------------------------------------------------------------- build ---
$NeedsBuild = $true
if (Test-Path (Join-Path $DistDir "index.html")) {
  if ($SkipBuild) {
    $NeedsBuild = $false
  } else {
    $distTime = (Get-Item (Join-Path $DistDir "index.html")).LastWriteTime
    $srcTime  = (Get-ChildItem (Join-Path $FrontendDir "src") -Recurse -File |
                 Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    if ($distTime -gt $srcTime) { $NeedsBuild = $false }
  }
}

if ($NeedsBuild) {
  Write-Step "Building frontend (npm run build)"
  Push-Location $FrontendDir
  try { & npm run build; if ($LASTEXITCODE -ne 0) { throw "npm run build failed ($LASTEXITCODE)" } }
  finally { Pop-Location }
} else {
  Write-Step "frontend/dist is up to date - skipping build"
}

# ------------------------------------------------------------------- backend ---
# No frontend/.env is needed: with VITE_API_URL unset, lib/api.js uses relative
# calls and derives wss://<tunnel-host>/ws/citypulse from the page URL.
$BackendOut = Join-Path $BackendDir "uvicorn-out.log"
$BackendErr = Join-Path $BackendDir "uvicorn-err.log"

# Reuse an already-running CityPulse backend so re-running this script is safe
# (a second uvicorn would otherwise fail to bind, and the health probe below
# would wrongly pass against the old process).
$backend = $null
$reuseBackend = $false
$existing = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
  $probe = $null
  try { $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5 } catch { }
  if ($probe -and $probe.service -eq "CityPulse") {
    Write-Step "Reusing the running CityPulse backend on port $Port (pid $($existing.OwningProcess))"
    $h = $probe
    $reuseBackend = $true
  } else {
    throw "Port $Port is already in use by pid $($existing.OwningProcess), which is not CityPulse. Stop it or pass -Port <other>."
  }
}

if (-not $reuseBackend) {
  Write-Step "Starting backend on http://${BindHost}:$Port (serving dist/ + API + WS)"
  $backend = Start-Process -FilePath $PythonExe `
    -ArgumentList "-m", "uvicorn", "main:app", "--host", $BindHost, "--port", $Port `
    -WorkingDirectory $BackendDir `
    -RedirectStandardOutput $BackendOut -RedirectStandardError $BackendErr `
    -WindowStyle Hidden -PassThru

  $healthy = $false
  foreach ($i in 1..30) {
    Start-Sleep -Milliseconds 700
    try {
      $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
      if ($h.status -eq "ok") { $healthy = $true; break }
    } catch { }
  }
  if (-not $healthy) {
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    throw "Backend did not become healthy on port $Port. See $BackendErr"
  }
  Write-Host "    backend pid=$($backend.Id) version=$($h.version)" -ForegroundColor DarkGray
}

# ------------------------------------------------ start the live simulation ---
if (-not $SkipSimStart) {
  try {
    Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/simulation/start" -Method Post `
      -Body "{}" -ContentType "application/json" -TimeoutSec 10 | Out-Null
    Write-Host "    simulation running" -ForegroundColor DarkGray
  } catch { Write-Host "    could not auto-start simulation: $($_.Exception.Message)" -ForegroundColor Yellow }
}

# -------------------------------------------------------------------- tunnel ---
# Best-effort LAN address so phones/other devices on the same Wi-Fi can connect
# without any tunnel at all (useful when an ISP blocks *.trycloudflare.com).
# Prefer the adapter that owns the default route - that is the real Wi-Fi/Ethernet
# one, not a VMware/Hyper-V/VPN virtual adapter.
$defaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
                Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
$lanIp = $null
if ($defaultRoute) {
  $lanIp = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $defaultRoute.InterfaceIndex -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
            Select-Object -First 1).IPAddress
}
if (-not $lanIp) {
  $lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and
                           $_.InterfaceAlias -notlike "*VMware*" -and $_.InterfaceAlias -notlike "*vEthernet*" } |
            Select-Object -First 1).IPAddress
}

if ($NoTunnel) {
  Write-Host ""
  Write-Host "LOCAL URL : http://127.0.0.1:$Port" -ForegroundColor Green
  if ($lanIp -and $BindHost -eq "0.0.0.0") {
    Write-Host "LAN URL   : http://${lanIp}:$Port  (same Wi-Fi; needs a firewall allow rule)" -ForegroundColor Green
  }
  Write-Host "(no tunnel requested)"
  return
}

$cloudflared = if ($CloudflaredPath -and (Test-Path $CloudflaredPath)) { $CloudflaredPath }
               else { (Get-Command cloudflared -ErrorAction SilentlyContinue).Source }
if (-not $cloudflared) {
  throw "cloudflared not found. Download the single .exe (no install needed) and pass -CloudflaredPath, or put it on PATH. See the README's 'Instant public URL' section."
}

$TunnelOut = Join-Path $ProjectRoot "cloudflared.out.log"
$TunnelErr = Join-Path $ProjectRoot "cloudflared.err.log"

# Reuse an existing tunnel: a second quick tunnel would hand out a *different*
# hostname and orphan the link you are already sharing.
$tunnel = Get-Process -Name cloudflared -ErrorAction SilentlyContinue | Select-Object -First 1
$publicUrl = $null
if ($tunnel -and (Test-Path $TunnelErr)) {
  $publicUrl = Select-String -Path $TunnelErr -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches |
               ForEach-Object { $_.Matches.Value } | Select-Object -Unique -Last 1
  if ($publicUrl) { Write-Step "Reusing the running cloudflared tunnel (pid $($tunnel.Id))" }
}

if (-not $publicUrl) {
  Remove-Item $TunnelOut, $TunnelErr -ErrorAction SilentlyContinue
  Write-Step "Opening Cloudflare quick tunnel to http://127.0.0.1:$Port"
  $tunnel = Start-Process -FilePath $cloudflared `
    -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate" `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $TunnelOut -RedirectStandardError $TunnelErr `
    -WindowStyle Hidden -PassThru

  foreach ($i in 1..40) {
    Start-Sleep -Milliseconds 900
    if (Test-Path $TunnelErr) {
      $match = Select-String -Path $TunnelErr -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches |
               ForEach-Object { $_.Matches.Value } | Select-Object -Unique -First 1
      if ($match) { $publicUrl = $match; break }
    }
  }
  if (-not $publicUrl) {
    Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
    throw "No public URL appeared within ~36s. See $TunnelErr"
  }
}

# ------------------------------------------------------------ verify public ---
Write-Step "Verifying the public URL"
$verified = $false
foreach ($i in 1..10) {
  try {
    $ph = Invoke-RestMethod -Uri "$publicUrl/api/health" -TimeoutSec 20
    if ($ph.status -eq "ok") { $verified = $true; break }
  } catch { Start-Sleep -Seconds 2 }
}

Write-Host ""
if ($verified) {
  Write-Host "PUBLIC URL : $publicUrl" -ForegroundColor Green
  Write-Host "LOGIN      : $publicUrl/login" -ForegroundColor Green
} else {
  Write-Host "PUBLIC URL : $publicUrl  (health check NOT confirmed - the tunnel may be blocked on your network)" -ForegroundColor Yellow
}
Write-Host ""
if ($lanIp -and $BindHost -eq "0.0.0.0") {
  Write-Host "LAN URL    : http://${lanIp}:$Port  (works on the same Wi-Fi, no tunnel needed)" -ForegroundColor Green
}
Write-Host "LOCAL URL  : http://127.0.0.1:$Port" -ForegroundColor DarkGray
Write-Host ""
Write-Host "pids -> backend=$(if ($backend) { $backend.Id } else { 'reused' })  cloudflared=$($tunnel.Id)" -ForegroundColor DarkGray
Write-Host "Logs -> $BackendErr , $TunnelErr" -ForegroundColor DarkGray
Write-Host "Note -> the tunnel hostname is random per run and dies with the tunnel process." -ForegroundColor DarkGray
Write-Host "        If the PUBLIC URL is unreachable on your network (some ISPs block" -ForegroundColor DarkGray
Write-Host "        *.trycloudflare.com), use the LAN URL or deploy to Render + Vercel." -ForegroundColor DarkGray