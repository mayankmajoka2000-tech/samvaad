<#
.SYNOPSIS
  One-time setup for Samvaad on any Windows laptop.

.DESCRIPTION
  Snapdragon PC (Windows on Arm): Whisper and Qwen3 run on the Hexagon NPU.
    Installs ARM64 Python 3.12, the Whisper NPU models from Qualcomm AI Hub, and checks GenieX.
  Any other Windows laptop (Intel or AMD): Whisper runs on the CPU (or an NVIDIA GPU),
    Qwen3 runs with Ollama. Installs Python 3.12, faster-whisper, Ollama and the Qwen3 model.

  Steps: 1 check the laptop, 2 Python, 3 packages, 4 speech model, 5 translator,
  6 sample clip and settings, 7 quick test.

.EXAMPLE
  Set-ExecutionPolicy -Scope Process Bypass -Force
  .\setup.ps1
  .\setup.ps1 -Whisper base         # smaller, faster speech model on Intel/AMD laptops
  .\setup.ps1 -NoTranslator         # skip Ollama and Qwen3 (about 2.5 GB)
#>
param(
    [string]$Chipset = "",
    [string]$WhisperModel = "whisper_base",
    [string]$Whisper = "small",
    [string]$OllamaModel = "qwen3:4b-instruct-2507-q4_K_M",
    [switch]$NoTranslator
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step([int]$n, [string]$text) { Write-Host "`n[$n/7] $text" -ForegroundColor Cyan }
function Ok([string]$text) { Write-Host "      $text" -ForegroundColor Green }
function Warn([string]$text) { Write-Host "      $text" -ForegroundColor Yellow }

# ------------------------------------------------------------------ 1
Step 1 "Checking this laptop"
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$cpuArch = (Get-CimInstance Win32_Processor | Select-Object -First 1).Architecture   # 12 = ARM64, 9 = x64
$os = if ($cpuArch -eq 12) { "Arm64" } else { "X64" }
Write-Host "      Processor: $cpu ($os)"
$Snapdragon = ($cpuArch -eq 12)
if ($Snapdragon) {
    if (-not $Chipset) {
        if ($cpu -match "X2") { $Chipset = "qualcomm-snapdragon-x2-elite" } else { $Chipset = "qualcomm-snapdragon-x-elite" }
    }
    Ok "Snapdragon PC: speech and translation will run on the NPU (model target: $Chipset)"
} else {
    Ok "Intel/AMD PC: speech on the CPU (or NVIDIA GPU), translation with Ollama"
}

# ------------------------------------------------------------------ 2
function Test-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Find-Python([string]$wantPlatform) {
    $candidates = @()
    $specs = @("-3.12", "-3.13", "-3.11")
    if ($wantPlatform -eq "win-arm64") { $specs = @("-V:3.12-arm64", "-3.12") }
    foreach ($spec in $specs) {
        try {
            $p = & py $spec -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $candidates += "$p".Trim() }
        } catch { }
    }
    foreach ($dir in @("Python312-arm64", "Python312", "Python313", "Python311")) {
        $local = Join-Path $env:LOCALAPPDATA "Programs\Python\$dir\python.exe"
        if (Test-Path $local) { $candidates += $local }
    }
    foreach ($c in $candidates) {
        try {
            # sysconfig reports the build itself (win-amd64 / win-arm64 / win32); platform.machine()
            # reports the CPU, so an emulated x64 Python on a Snapdragon PC would wrongly pass.
            $plat = & $c -c "import sysconfig, sys; print(sysconfig.get_platform() if sys.version_info >= (3, 11) else 'old')"
            if ("$plat".Trim() -eq $wantPlatform) { return $c }
        } catch { }
    }
    return $null
}

if ($Snapdragon) {
    Step 2 "Finding native ARM64 Python 3.12"
    $py = Find-Python "win-arm64"
    if (-not $py -and (Test-Winget)) {
        Write-Host "      Installing Python 3.12 (ARM64) with winget..."
        winget install --id Python.Python.3.12 --architecture arm64 --scope user --silent --accept-package-agreements --accept-source-agreements
        $py = Find-Python "win-arm64"
    }
    if (-not $py) { throw "ARM64 Python 3.12 was not found. Install 'Windows installer (ARM64)' from python.org, then run .\setup.ps1 again." }
} else {
    Step 2 "Finding Python 3.11 to 3.13"
    $py = Find-Python "win-amd64"
    if (-not $py -and (Test-Winget)) {
        Write-Host "      Installing Python 3.12 with winget..."
        winget install --id Python.Python.3.12 --architecture x64 --scope user --silent --accept-package-agreements --accept-source-agreements
        $py = Find-Python "win-amd64"
    }
    if (-not $py) { throw "Python 3.12 was not found. Install it from python.org (tick 'Add to PATH'), then run .\setup.ps1 again." }
}
Ok "Python: $py"

# ------------------------------------------------------------------ 3
Step 3 "Installing packages into .venv"
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { & $py -m venv .venv }
& $vpy -m pip install --upgrade pip --quiet
$req = "requirements.txt"
if ($Snapdragon) { $req = "requirements-snapdragon.txt" }
& $vpy -m pip install -r $req
if ($LASTEXITCODE -ne 0) { throw "Installing packages failed. Check the internet connection and run .\setup.ps1 again." }
Ok "Packages installed ($req)"

# ------------------------------------------------------------------ 4
$size = $WhisperModel -replace "^whisper_", "" -replace "_", "-"
if ($Snapdragon) {
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
    Write-Host "      Caching the Whisper tokenizer for offline use..."
    & $vpy -c "from transformers import WhisperConfig, WhisperTokenizer, WhisperFeatureExtractor; m='openai/whisper-$size'; WhisperConfig.from_pretrained(m); WhisperTokenizer.from_pretrained(m); WhisperFeatureExtractor.from_pretrained(m); print('      cached', m)"
    if ($LASTEXITCODE -ne 0) { throw "Could not download the Whisper tokenizer from Hugging Face." }
} else {
    Step 4 "Downloading the Whisper speech model ($Whisper)"
    & $vpy -c "from faster_whisper import WhisperModel; WhisperModel('$Whisper', device='cpu', compute_type='int8'); print('      Whisper-$Whisper is ready and cached for offline use')"
    if ($LASTEXITCODE -ne 0) { throw "Could not download the Whisper model from Hugging Face." }
}

# ------------------------------------------------------------------ 5
function Test-Url([string]$url) {
    try { Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}
function Find-Ollama {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $local = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $local) { return $local }
    return $null
}

if ($Snapdragon) {
    Step 5 "Checking GenieX (Qwen3 translation on the NPU)"
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
} elseif ($NoTranslator) {
    Step 5 "Translator: skipped (-NoTranslator)"
} else {
    Step 5 "Translator: Qwen3-4B with Ollama"
    $ollama = Find-Ollama
    if (-not $ollama -and (Test-Winget)) {
        Write-Host "      Installing Ollama with winget..."
        winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
        $ollama = Find-Ollama
    }
    if (-not $ollama) { throw "Ollama did not install. Get it from https://ollama.com/download, then run .\setup.ps1 again." }
    Ok "Ollama: $ollama"
    if (-not (Test-Url "http://127.0.0.1:11434/api/version")) {
        Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
        for ($i = 0; $i -lt 60 -and -not (Test-Url "http://127.0.0.1:11434/api/version"); $i++) { Start-Sleep -Seconds 1 }
    }
    Write-Host "      Downloading $OllamaModel (about 2.5 GB, first time only)..."
    & $ollama pull $OllamaModel
    if ($LASTEXITCODE -ne 0) { throw "Downloading the Qwen3 model failed. Check the internet connection and run .\setup.ps1 again." }
    Ok "Translator ready"
}

# ------------------------------------------------------------------ 6
Step 6 "Sample clip and settings"
New-Item -ItemType Directory -Force -Path "samples" | Out-Null
if (-not (Test-Path "samples\fox.wav")) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/hf_whisper_asr_shared/v1/audio/fox.wav" -OutFile "samples\fox.wav"
        Ok "Downloaded samples\fox.wav"
    } catch { Warn "Could not download the sample clip; skipping the speech test." }
}
if (-not (Test-Path "config.toml")) {
    $cfg = Get-Content "config.example.toml" -Raw -Encoding UTF8
    $cfg = $cfg -replace '(?m)^model_size = "base"', "model_size = `"$size`""
    $cfg = $cfg -replace '(?m)^cpu_model_size = "small"', "cpu_model_size = `"$Whisper`""
    $cfg = $cfg -replace '(?m)^model = "qwen3:4b-instruct-2507-q4_K_M"', "model = `"$OllamaModel`""
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "config.toml"), $cfg, (New-Object System.Text.UTF8Encoding $false))
    Ok "Created config.toml"
} else { Ok "config.toml already exists (left unchanged)" }

# ------------------------------------------------------------------ 7
Step 7 "Quick test on this laptop"
if (Test-Path "samples\fox.wav") {
    $benchArgs = @("tools\benchmark.py", "--runs", "3")
    if ($Snapdragon -or $NoTranslator) { $benchArgs += "--skip-llm" }
    & $vpy @benchArgs
    if ($LASTEXITCODE -eq 0) { Ok "The speech engine works." } else { Warn "The test failed; see README > Troubleshooting." }
} else { Warn "Skipped (no sample clip)." }

Write-Host "`nSetup complete. Start Samvaad with:  .\run.ps1" -ForegroundColor Green
Write-Host "With Beacon on the same Wi-Fi:        .\run.ps1 -Lan`n" -ForegroundColor Green
