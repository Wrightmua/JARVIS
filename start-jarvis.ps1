# Starts Ollama (if needed) and the JARVIS server, then opens the HUD in Edge.
# Optional overrides (uncomment):
# $env:JARVIS_MODEL = "qwen2.5:7b"        # smarter, slower
# $env:JARVIS_CITY = "Sydney"             # default weather location
# $env:JARVIS_NEWS_REGION = "AU:en"       # Google News country:language
# $env:JARVIS_USER_TITLE = "sir"          # how JARVIS addresses you
# $env:JARVIS_VOICE = "en-GB-RyanNeural"  # any edge-tts voice

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$model = if ($env:JARVIS_MODEL) { $env:JARVIS_MODEL } else { "qwen2.5:3b" }
$port = if ($env:JARVIS_PORT) { $env:JARVIS_PORT } else { 8765 }

$ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollama) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
if (-not (Test-Path $ollama)) { throw "Ollama not found. Install it from https://ollama.com/download" }

try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null }
catch {
    Write-Host "Starting Ollama..."
    Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

$have = (& $ollama list) -join "`n"
if ($have -notmatch [regex]::Escape($model)) {
    Write-Host "Downloading $model (one-time)..."
    & $ollama pull $model
}

# Stop any JARVIS server still running from a previous start, so the new code is what answers.
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Start-Job { Start-Sleep 4; Start-Process "msedge" "--app=http://127.0.0.1:$using:port" } | Out-Null
Write-Host "JARVIS online at http://127.0.0.1:$port  (Ctrl+C to shut down)"
& "$PSScriptRoot\.venv\Scripts\python.exe" -m jarvis.server
