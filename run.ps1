<#
.SYNOPSIS
  Start Samvaad on Windows (and its translator, if it is not already running) and open it in the browser.

.DESCRIPTION
  Snapdragon PC: starts GenieX (Qwen3 on the NPU). Other laptops: starts Ollama.

.EXAMPLE
  .\run.ps1              # this PC only
  .\run.ps1 -Lan         # also reachable on Wi-Fi, for the Beacon
  .\run.ps1 -Mock        # try the interface without models
  .\run.ps1 -Asr faster  # force an engine: auto, qnn, faster, transformers, mock
#>
param(
    [switch]$Lan,
    [ValidateSet("", "auto", "qnn", "faster", "transformers", "mock")][string]$Asr = "",
    [switch]$Mock,
    [switch]$NoGeniex
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Write-Host "Samvaad is not set up yet. Run .\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}

function Test-Url([string]$url) {
    try { Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

$snapdragon = ("$([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture)" -eq "Arm64")
$geniex = Get-Command geniex -ErrorAction SilentlyContinue
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    $local = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $local) { $ollama = Get-Item $local }
}
$ollamaPath = $null
if ($ollama) { $ollamaPath = if ($ollama.Source) { $ollama.Source } else { $ollama.FullName } }

if (-not $Mock) {
    if (Test-Url "http://127.0.0.1:18181/v1/models") {
        Write-Host "GenieX is already running (Qwen3 on the NPU)." -ForegroundColor Green
    } elseif (Test-Url "http://127.0.0.1:11434/api/version") {
        Write-Host "Ollama is already running." -ForegroundColor Green
    } elseif ($snapdragon -and $geniex -and -not $NoGeniex) {
        Write-Host "Starting GenieX (Qwen3 on the NPU) in its own window..." -ForegroundColor Cyan
        Start-Process -FilePath $geniex.Source -ArgumentList "serve" -WindowStyle Minimized
    } elseif ($ollamaPath) {
        Write-Host "Starting Ollama..." -ForegroundColor Cyan
        Start-Process -FilePath $ollamaPath -ArgumentList "serve" -WindowStyle Hidden
    } else {
        Write-Host "No translator is installed, so translation is off. Run .\setup.ps1 (see README)." -ForegroundColor Yellow
    }
}

$arguments = @("-m", "samvaad")
if ($Lan) { $arguments += "--lan" }
if ($Mock) { $arguments += "--mock" }
if ($Asr) { $arguments += @("--asr", $Asr) }
& $vpy @arguments
