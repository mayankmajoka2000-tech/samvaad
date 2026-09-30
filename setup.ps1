<#
.SYNOPSIS
  One-time setup for Samvaad on a Snapdragon Windows PC.

.DESCRIPTION
  1. Checks this is Windows on Arm.
  2. Finds or installs native ARM64 Python 3.12.
  3. Creates .venv and installs the packages.
  4. Downloads the Whisper NPU models from Qualcomm AI Hub.
  5. Caches the Whisper tokenizer so Samvaad works offline.
  6. Downloads a sample clip and creates config.toml.
  7. Checks for GenieX (Qwen3 on the NPU).
  8. Runs a short NPU speech test.

.EXAMPLE
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  Get-ChildItem -Recurse | Unblock-File
  .\setup.ps1
#>
param(
    [string]$Chipset = "",
    [string]$WhisperModel = "whisper_base"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step([int]$n, [string]$text) { Write-Host "`n[$n/8] $text" -ForegroundColor Cyan }
function Ok([string]$text) { Write-Host "      $text" -ForegroundColor Green }
function Warn([string]$text) { Write-Host "      $text" -ForegroundColor Yellow }

# ------------------------------------------------------------------ 1
Step 1 "Checking this PC"
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$os = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
Write-Host "      Processor: $cpu ($os)"
if ("$os" -ne "Arm64") {
    Warn "This is not Windows on Arm, so there is no Snapdragon NPU."
    Warn "For development on this PC use:  pip install -r requirements-dev.txt  then  python -m samvaad --asr transformers"
    exit 1
}
if (-not $Chipset) {
    if ($cpu -match "X2") { $Chipset = "qualcomm-snapdragon-x2-elite" } else { $Chipset = "qualcomm-snapdragon-x-elite" }
}
Ok "Model target: $Chipset"

# ------------------------------------------------------------------ 2
Step 2 "Finding native ARM64 Python 3.12"
function Find-ArmPython {
    $candidates = @()
    foreach ($spec in @("-V:3.12-arm64", "-3.12")) {
        try {
            $p = & py $spec -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $candidates += "$p".Trim() }
        } catch { }
    }
    $local = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312-arm64\python.exe"
    if (Test-Path $local) { $candidates += $local }
    foreach ($c in $candidates) {
        try {
            $machine = & $c -c "import platform; print(platform.machine())"
            if ("$machine".Trim() -eq "ARM64") { return $c }
        } catch { }
    }
    return $null
}
$py = Find-ArmPython
if (-not $py) {
    Write-Host "      Installing Python 3.12 (ARM64) with winget..."
    winget install --id Python.Python.3.12 --architecture arm64 --scope user --silent --accept-package-agreements --accept-source-agreements
    $py = Find-ArmPython
}
if (-not $py) {
    throw "ARM64 Python 3.12 was not found. Install 'Windows installer (ARM64)' from python.org, then run .\setup.ps1 again."
}
Ok "Python: $py"

# ------------------------------------------------------------------ 3
Step 3 "Installing packages into .venv"
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { & $py -m venv .venv }
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Installing packages failed. Check the internet connection and run .\setup.ps1 again." }
Ok "Packages installed"

# ------------------------------------------------------------------ 4
Step 4 "Downloading Whisper for the NPU from Qualcomm AI Hub"
$modelDir = Join-Path $PSScriptRoot "models\whisper"
if ((Test-Path "$modelDir\encoder.onnx") -and (Test-Path "$modelDir\decoder.onnx")) {
    Ok "Whisper models already in models\whisper"
} else {
    $fetch = Join-Path $PSScriptRoot ".venv\Scripts\qai-hub-apps.exe"
    $tmp = Join-Path $env:TEMP ("samvaad-fetch-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    & $fetch fetch whisper_windows_py --model $WhisperModel --chipset $Chipset --output-dir $tmp
    if ($LASTEXITCODE -ne 0 -and $Chipset -ne "qualcomm-snapdragon-x-elite") {
        Warn "No build for $Chipset; trying the Snapdragon X Elite build."
        & $fetch fetch whisper_windows_py --model $WhisperModel --chipset qualcomm-snapdragon-x-elite --output-dir $tmp
    }
    $encoder = Get-ChildItem -Path $tmp -Recurse -Filter "encoder.onnx" | Select-Object -First 1
    if (-not $encoder) { throw "The Whisper download did not contain encoder.onnx. See README > Troubleshooting." }
    New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
    Copy-Item -Path (Join-Path $encoder.DirectoryName "*") -Destination $modelDir -Recurse -Force
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Ok "Saved to models\whisper"
}

# ------------------------------------------------------------------ 5
Step 5 "Caching the Whisper tokenizer for offline use"
$size = $WhisperModel -replace "^whisper_", "" -replace "_", "-"
& $vpy -c "from transformers import WhisperConfig, WhisperTokenizer, WhisperFeatureExtractor; m='openai/whisper-$size'; WhisperConfig.from_pretrained(m); WhisperTokenizer.from_pretrained(m); WhisperFeatureExtractor.from_pretrained(m); print('      cached', m)"
if ($LASTEXITCODE -ne 0) { throw "Could not download the Whisper tokenizer from Hugging Face." }

# ------------------------------------------------------------------ 6
Step 6 "Sample clip and settings"
New-Item -ItemType Directory -Force -Path "samples" | Out-Null
if (-not (Test-Path "samples\fox.wav")) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/hf_whisper_asr_shared/v1/audio/fox.wav" -OutFile "samples\fox.wav"
        Ok "Downloaded samples\fox.wav"
    } catch { Warn "Could not download the sample clip; the benchmark will ask for your own WAV file." }
}
if (-not (Test-Path "config.toml")) {
    $cfg = Get-Content "config.example.toml" -Raw -Encoding UTF8
    $cfg = $cfg -replace 'model_size = "base"', "model_size = `"$size`""
    Set-Content -Path "config.toml" -Value $cfg -Encoding UTF8
    Ok "Created config.toml"
} else { Ok "config.toml already exists (left unchanged)" }

# ------------------------------------------------------------------ 7
Step 7 "Checking GenieX (Qwen3 translation on the NPU)"
$geniex = Get-Command geniex -ErrorAction SilentlyContinue
if ($geniex) {
    Ok "GenieX found: $($geniex.Source)"
    Write-Host "      First time only, download the translation model by running:" -ForegroundColor Gray
    Write-Host "        geniex infer ai-hub-models/Qwen3-4B-Instruct-2507" -ForegroundColor White
    Write-Host "      Type a test sentence, check the reply, then close it." -ForegroundColor Gray
} else {
    Warn "GenieX is not installed yet. Download and run the Windows ARM64 installer:"
    Write-Host "        https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-geniex/geniex-cli.exe" -ForegroundColor White
    Warn "Then open a new PowerShell window and run:  geniex infer ai-hub-models/Qwen3-4B-Instruct-2507"
}

# ------------------------------------------------------------------ 8
Step 8 "Testing speech recognition on the NPU"
if (Test-Path "samples\fox.wav") {
    & $vpy tools\benchmark.py --runs 3 --skip-llm
    if ($LASTEXITCODE -eq 0) { Ok "The NPU speech engine works." } else { Warn "The speech test failed; see README > Troubleshooting." }
} else { Warn "Skipped (no sample clip)." }

Write-Host "`nSetup complete. Start Samvaad with:  .\run.ps1" -ForegroundColor Green
Write-Host "With Beacon on the same Wi-Fi:        .\run.ps1 -Lan`n" -ForegroundColor Green
