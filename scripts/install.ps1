# install.ps1 - Install and start the go-music-api backend on Windows (amd64)
#
# Fixes baked in (2026-08-04):
#   1. The backend EXE hardcodes port 8080. This script therefore uses 8080
#      explicitly and writes it to the `port` file (older logic pretended to
#      pick a random free port, which the EXE ignored -> health-check mismatch).
#   2. GitHub Releases downloads can be very slow / interrupted on some networks.
#      The download uses HTTP Range resume + up to 6 retries, and verifies the
#      expected byte size before accepting the file.
#   3. The downloaded archive is validated as a real ZIP (PK header) and the
#      extracted binary as a real PE (MZ header) before use.

$ErrorActionPreference = 'Stop'

$BASE  = Join-Path $env:USERPROFILE '.openclaw\music'
$BIN   = Join-Path $BASE 'go-music-api.exe'
$ZIP   = Join-Path $BASE 'go-music-api_windows_amd64.zip'
$LOG   = Join-Path $BASE 'log.txt'
$PIDF  = Join-Path $BASE 'pid'
$PORTF = Join-Path $BASE 'port'
$PORT  = 8080   # backend binary hardcodes this port

New-Item -ItemType Directory -Force -Path $BASE | Out-Null
Write-Host "[music] base dir: $BASE"

function Test-PeHeader($Path) {
    try {
        $fs = [System.IO.File]::OpenRead($Path)
        $b = New-Object byte[] 2
        $null = $fs.Read($b, 0, 2)
        $fs.Close()
        return ($b[0] -eq 0x4D -and $b[1] -eq 0x5A)   # 'MZ'
    } catch { return $false }
}

function Test-ZipHeader($Path) {
    try {
        $fs = [System.IO.File]::OpenRead($Path)
        $b = New-Object byte[] 2
        $null = $fs.Read($b, 0, 2)
        $fs.Close()
        return ($b[0] -eq 0x50 -and $b[1] -eq 0x4B)   # 'PK'
    } catch { return $false }
}

# ---- backend acquisition: try a bundled offline copy first, then download ----
$Bundled = Join-Path (Split-Path $PSScriptRoot) 'backend\go-music-api.exe'
if ((Test-Path $BIN) -and (Test-PeHeader $BIN)) {
    Write-Host "[music] backend already present"
} elseif ((Test-Path $Bundled) -and (Test-PeHeader $Bundled)) {
    Write-Host "[music] using bundled offline backend (no internet required): $Bundled"
    Copy-Item $Bundled -Destination $BIN -Force
    Write-Host "[music] installed from bundle: $BIN"
} else {
    Write-Host "[music] fetching release info..."
    $api  = 'https://api.github.com/repos/guohuiyuan/go-music-api/releases/latest'
    $rel  = Invoke-RestMethod -Uri $api -TimeoutSec 30
    $asset = $rel.assets | Where-Object { $_.name -like '*windows_amd64*' } | Select-Object -First 1
    if (-not $asset) { Write-Error "[music] no windows_amd64 asset found"; exit 1 }
    $url      = $asset.browser_download_url
    $expected = $asset.size
    Write-Host "[music] asset: $($asset.name) ($expected bytes)"

    # resume + retry download
    $ok = $false
    $tries = 0
    while ($tries -lt 6 -and -not $ok) {
        $tries++
        $start = if (Test-Path $ZIP) { (Get-Item $ZIP).Length } else { 0 }
        if ($expected -and $start -ge $expected) { $ok = $true; break }
        try {
            Write-Host "[music] downloading (attempt $tries, from $start bytes)..."
            $req = [System.Net.HttpWebRequest]::Create($url)
            if ($start -gt 0) { $req.AddRange($start) }
            $req.Timeout = 300000
            $resp   = $req.GetResponse()
            $stream = $resp.GetResponseStream()
            $fs = [System.IO.File]::Open($ZIP, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write)
            $buf = New-Object byte[] 65536
            while ($true) {
                $n = $stream.Read($buf, 0, $buf.Length)
                if ($n -le 0) { break }
                $fs.Write($buf, 0, $n)
            }
            $fs.Close(); $stream.Close(); $resp.Close()
            if (-not $expected -or (Get-Item $ZIP).Length -ge $expected) { $ok = $true }
        } catch {
            Write-Host "[music] download error: $_"
            Start-Sleep -Seconds 3
        }
    }
    if (-not $ok) { Write-Error "[music] download failed after retries"; exit 1 }
    if (-not (Test-ZipHeader $ZIP)) { Write-Error "[music] downloaded file is not a valid zip (likely an HTML error page)"; exit 1 }

    $extract = Join-Path $BASE 'extract'
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive -Path $ZIP -DestinationPath $extract -Force
    $exe = Get-ChildItem $extract -Recurse -Filter 'go-music-api.exe' | Select-Object -First 1
    if (-not $exe -or -not (Test-PeHeader $exe.FullName)) {
        Write-Error "[music] exe missing or not a valid PE after extraction"; exit 1
    }
    Copy-Item $exe.FullName -Destination $BIN -Force
    Remove-Item $extract -Recurse -Force
    Remove-Item $ZIP -Force -ErrorAction SilentlyContinue
    Write-Host "[music] installed: $BIN"
}

# write the port file (always 8080 - the EXE ignores any other value)
$PORT | Out-File -Encoding ascii $PORTF

# start backend if not already healthy on 8080
$running = $false
try {
    Invoke-RestMethod -Uri "http://localhost:$PORT/api/v1/music/search?q=test" -TimeoutSec 5 | Out-Null
    $running = $true
} catch { $running = $false }

if (-not $running) {
    # kill any stale process occupying 8080 (best effort)
    try {
        $stale = Get-Process -Id (Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue
        if ($stale) { Write-Host "[music] note: port $PORT already held by another process" }
    } catch { }

    Write-Host "[music] starting backend on port $PORT..."
    $p = Start-Process -FilePath $BIN -WindowStyle Hidden -PassThru -RedirectStandardOutput $LOG -RedirectStandardError $LOG
    $p.Id | Out-File -Encoding ascii $PIDF
    $healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-RestMethod -Uri "http://localhost:$PORT/api/v1/music/search?q=test" -TimeoutSec 5 | Out-Null
            $healthy = $true; break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $healthy) { Write-Error "[music] backend failed to start, see $LOG"; exit 1 }
}

Write-Host "[music] ready at http://localhost:$PORT"
