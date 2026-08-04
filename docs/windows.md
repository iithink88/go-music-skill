# Windows Workflow

Load this document only when the user is on Windows or explicitly asks for Windows instructions.

## Requirements

- PowerShell 5.1 or later
- Windows amd64
- Access to GitHub Releases (for the first-time backend download)
- Python 3 for search ranking, format normalization, caching, and metadata embedding
- `ffmpeg` (optional but recommended) to transcode M4A/AAC streams to standard MP3

`go-music-api` upstream only provides the Windows amd64 release asset.

## Install and start the backend

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

What the script does:
- installs `go-music-api.exe` into `%USERPROFILE%\.openclaw\music`
- starts the backend on **port 8080** (the EXE hardcodes this; the script no longer pretends to pick a free port)
- verifies health with a local API request
- on first download, resumes interrupted GitHub Releases transfers and validates the archive (PK) + binary (MZ)

If installation fails:
- verify PowerShell version
- verify GitHub Releases reachability (slow links auto-retry with resume, up to 6 attempts)
- inspect `%USERPROFILE%\.openclaw\music\log.txt`
- confirm the downloaded file is `go-music-api_windows_amd64.zip` and is a valid ZIP

## Download a song

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/play.ps1 "牧马城市 毛不易" "$env:USERPROFILE\.openclaw\media\mumachengshi.mp3"
```

The Windows playback flow (delegates to `scripts/play_windows.py`):
- finds Python in this order: `py`, `py -3`, `python`, `python3`
- searches with the local backend on port 8080
- selects the best candidate (title/artist/source scoring, avoids karaoke/cover/remix)
- downloads the stream
- **detects the real audio container by magic bytes**; if the source returns M4A/AAC (common with kuwo) it transcodes to standard MP3 with ffmpeg (192 kbps) so players and ID3 metadata work
- reuses cached files when possible
- runs `scripts/embed_metadata.py` to embed title/artist/album/cover/lyrics (MP3 only)

If ffmpeg is not on `PATH`, set it via the `FFMPEG` environment variable:

```powershell
$env:FFMPEG = "C:\path\to\ffmpeg.exe"
powershell -ExecutionPolicy Bypass -File scripts/play.ps1 "牧马城市 毛不易"
```

## Known issues fixed (2026-08-04)

These pitfalls were hit in practice and are now patched in the bundled scripts:

1. **Backend port**. The `go-music-api.exe` binary always binds **8080** and ignores any other port. Older logic that "picked a free port" wrote a wrong port to the `port` file and then failed the health check. `install.ps1` / `install.sh` now use 8080 explicitly.
2. **Wrong file format**. The stream API returns **M4A/AAC** for some sources (e.g. kuwo) even when you request `.mp3`. Saving it as `.mp3` produces a file players may reject and that `embed_metadata.py` (mutagen ID3) cannot tag. `play.ps1` / `play.sh` now detect the true format and transcode to MP3 with ffmpeg.
3. **Slow / interrupted download**. GitHub Releases can be very slow on some networks (tens of KB/s), causing foreground timeouts. `install.ps1` downloads with HTTP Range resume + retries, and validates the final size before extracting.

## Cookie support on Windows

If the user mentions cookies, VIP-only tracks, grey tracks, or login-required tracks, load `docs/cookies.md`.
