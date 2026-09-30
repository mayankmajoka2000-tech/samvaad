<#
.SYNOPSIS
  Start Samvaad (and GenieX, if it is not already running) and open it in the browser.

.EXAMPLE
  .\run.ps1              # this PC only
  .\run.ps1 -Lan         # also reachable on Wi-Fi, for the Beacon
  .\run.ps1 -Asr mock    # try the interface without models
#>
param(
    [switch]$Lan,
    [ValidateSet("", "qnn", "transformers", "mock")][string]$Asr = "",
    [switch]$NoGeniex
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Write-Host "Samvaad is not set up yet. Run .\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}

if (-not $NoGeniex) {
    $running = $false
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:18181/v1/models" -TimeoutSec 2 | Out-Null
        $running = $true
    } catch { }
    $geniex = Get-Command geniex -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host "GenieX is already running." -ForegroundColor Green
    } elseif ($geniex) {
        Write-Host "Starting GenieX (Qwen3 on the NPU) in its own window..." -ForegroundColor Cyan
        Start-Process -FilePath $geniex.Source -ArgumentList "serve" -WindowStyle Minimized
    } else {
        Write-Host "GenieX is not installed, so translation is off. See README, step 4." -ForegroundColor Yellow
    }
}

$arguments = @("-m", "samvaad")
if ($Lan) { $arguments += "--lan" }
if ($Asr) { $arguments += @("--asr", $Asr) }
& $vpy @arguments
