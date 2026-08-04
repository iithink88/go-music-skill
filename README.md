# go-music-skill (offline-enhanced)

A music download/play skill for WorkBuddy / OpenClaw-compatible agents, wrapping the
[`go-music-api`](https://github.com/guohuiyuan/go-music-api) backend.

> This is a patched fork. Original skill by **scavin** (ClawHub: `scavin/go-music-skill`).

## Fixes baked in (this fork)
- **Port 8080**: the backend binary hardcodes port 8080; the scripts now use it explicitly
  (the original random-port logic silently failed health checks on Windows).
- **Format fix**: streams are often M4A/AAC; the scripts detect the real format via magic bytes
  and transcode to a standard MP3 (with ID3 tags) using `ffmpeg`.
- **Multi-source fallback**: if one music source returns 404/dead, it auto-tries the next candidate.
- **Robust backend download**: HTTP Range resume + retries + ZIP/PE validation.
- **Windows support**: added `install.ps1` / `play.ps1` / `play_windows.py` (the original shipped
  only `.sh` scripts, so `docs/windows.md` pointed at files that did not exist).

## Install (requires internet for the backend)
1. Copy this folder into your skills directory, e.g.
   `C:\Users\<you>\.workbuddy\skills\go-music-skill\`.
2. Start the backend:
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts\install.ps1`
   - macOS/Linux: `bash scripts/install.sh`
   The first run downloads the matching `go-music-api` binary from GitHub Releases.
3. Download a song:
   `powershell -ExecutionPolicy Bypass -File scripts\play.ps1 "歌名 歌手"`

## Offline use
An offline bundle that already includes the Windows backend (`backend/go-music-api.exe`) is
distributed separately so it can be installed with **no internet**. Ask the maintainer for the
`go-music-skill-offline.zip` package.

## Security note
The backend is downloaded from GitHub Releases without checksum signing (upstream behavior).
Provide platform cookies only via a throwaway account if you use cookie-gated sources, and clean
up `%USERPROFILE%\.openclaw` afterward.
