# play.ps1 - Download a song on Windows via the local go-music-api backend.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/play.ps1 "牧马城市 毛不易" "C:\Users\lenovo\Desktop\output.mp3"
# If the output path is omitted, the file lands under %USERPROFILE%\.openclaw\media\.
#
# Fixes baked in (2026-08-04): delegates real work to play_windows.py, which
#   * detects the true audio container (kuwo may serve M4A/AAC despite ".mp3")
#     and transcodes to standard MP3 with ffmpeg before embedding metadata;
#   * uses port 8080 (the backend EXE hardcodes it).

$ErrorActionPreference = 'Stop'

$Query   = $args[0]
$OutPath = if ($args.Count -gt 1) { $args[1] } else { "" }

if (-not $Query) {
    Write-Host "usage: play.ps1 <query> [output-path]" -ForegroundColor Yellow
    exit 1
}

# ---- find python ----
$Py = $null
foreach ($cand in @("py", "py -3", "python", "python3")) {
    try {
        $p = $cand.Split(" ")[0]
        if (Get-Command $p -ErrorAction SilentlyContinue) { $Py = $cand; break }
    } catch { }
}
if (-not $Py) {
    Write-Host "[music] Python not found. Install Python 3 or run: winget install --id Python.Python.3.12" -ForegroundColor Red
    exit 1
}

# ---- find ffmpeg (optional; used to normalize M4A->MP3) ----
$Ff = ""
if ($env:FFMPEG -and (Test-Path $env:FFMPEG)) {
    $Ff = $env:FFMPEG
} else {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd) { $Ff = $cmd.Source }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyScript  = Join-Path $ScriptDir "play_windows.py"

$PyArgs = @()
$PyArgs += $Py.Split(" ") | Where-Object { $_ }
$PyArgs += @($PyScript, $Query)
if ($OutPath) { $PyArgs += $OutPath }
if ($Ff)      { $PyArgs += $Ff }

Write-Host "[music] running: $Py $PyScript `"$Query`""
& $Py.Split(" ")[0] ($PyArgs | Select-Object -Skip 1)
