#!/usr/bin/env python3
# play_windows.py - Search, rank, download and normalize a track on Windows.
#
# Fixes baked in (2026-08-04):
#   * Format mismatch: the stream API may return M4A/AAC (kuwo source) even
#     though callers ask for ".mp3". We detect the real container by magic
#     bytes and, if ffmpeg is available, transcode to a standard MP3. The
#     embedded-metadata step (embed_metadata.py uses mutagen ID3) only works
#     on real MP3, so conversion must happen BEFORE embedding.
#   * Port: reads ~/.openclaw/music/port, defaults to 8080 (the EXE hardcodes it).
#
# Usage: python play_windows.py "<query>" ["<out-path>"] ["<ffmpeg-path>"]

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

query = sys.argv[1] if len(sys.argv) > 1 else ""
out_path = sys.argv[2] if len(sys.argv) > 2 else ""
ffmpeg = sys.argv[3] if len(sys.argv) > 3 else ""

if not query:
    print(json.dumps({"error": "missing query"}, ensure_ascii=False))
    sys.exit(1)

# ---- resolve port (backend hardcodes 8080) ----
port = 8080
port_file = os.path.join(os.path.expanduser("~"), ".openclaw", "music", "port")
if os.path.exists(port_file):
    try:
        port = int(open(port_file, encoding="utf-8").read().strip())
    except Exception:
        port = 8080

media_dir = os.path.join(os.path.expanduser("~"), ".openclaw", "media")
cache_index = os.path.join(os.path.expanduser("~"), ".openclaw", "music", "cache-index.json")
os.makedirs(media_dir, exist_ok=True)

if not out_path:
    safe = re.sub(r'[^\w\-一-龥]+', '_', query) or "music"
    out_path = os.path.join(media_dir, safe + ".mp3")


def http_get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def slug(text):
    text = re.sub(r'[^\w\-一-龥]+', '_', text, flags=re.UNICODE)
    text = re.sub(r'_+', '_', text).strip('_')
    return text or "music"


def load_cache():
    if os.path.exists(cache_index):
        try:
            return json.load(open(cache_index, "r", encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(idx):
    try:
        json.dump(idx, open(cache_index, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---- cache hit by query ----
idx = load_cache()
hit = idx.get(query)
if isinstance(hit, dict):
    p = hit.get("path")
    if p and os.path.exists(p) and os.path.getsize(p) > 1024:
        if os.path.abspath(p) != os.path.abspath(out_path):
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            shutil.copy2(p, out_path)
        print(json.dumps({"cache_hit": True, "path": out_path, "size": os.path.getsize(out_path),
                          "chosen": hit.get("chosen")}, ensure_ascii=False))
        sys.exit(0)

# ---- search ----
raw = http_get_json("http://localhost:%d/api/v1/music/search?%s" % (port, urllib.parse.urlencode({"q": query})))
items = []
if isinstance(raw, dict):
    d = raw.get("data")
    if isinstance(d, list):
        items = d
    elif isinstance(d, dict):
        for k in ("data", "list", "songs"):
            if isinstance(d.get(k), list):
                items = d[k]
                break
    elif isinstance(raw.get("list"), list):
        items = raw["list"]
if not items:
    print(json.dumps({"error": "no items parsed from search response"}, ensure_ascii=False))
    sys.exit(1)

query_l = query.lower()
prefer_artist = None
for name in ("周杰伦", "jay chou", "jay", "林俊杰", "陈奕迅", "毛不易"):
    if name in query_l:
        prefer_artist = name
        break


def score(item):
    name = str(item.get("name", ""))
    artist = str(item.get("artist", ""))
    source = str(item.get("source", ""))
    s = 0
    for token in query.replace("/", " ").split():
        if token and token in name:
            s += 80
        if token and token in artist:
            s += 50
    if prefer_artist and prefer_artist.replace(" ", "").lower() in artist.replace(" ", "").lower():
        s += 120
    if source in ("migu", "qq", "netease", "kuwo", "kugou"):
        s += 20
    bad = ("伴奏", "小提琴", "翻唱", "cover", "live", "dj", "remix", "纯音乐")
    if any(w.lower() in (name + " " + artist).lower() for w in bad):
        s -= 100
    return s


ranked = sorted(items, key=score, reverse=True)
top = ranked[0]
default_name = "%s-%s.mp3" % (slug(top.get("artist", "unknown")), slug(top.get("name", "music")))
default_path = os.path.join(media_dir, default_name)

# skip download if the chosen track is already cached locally
if os.path.exists(default_path) and os.path.getsize(default_path) > 1024:
    if os.path.abspath(default_path) != os.path.abspath(out_path):
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        shutil.copy2(default_path, out_path)
    idx[query] = {"path": out_path, "chosen": top}
    save_cache(idx)
    print(json.dumps({"cache_hit": True, "path": out_path, "size": os.path.getsize(out_path),
                      "chosen": top}, ensure_ascii=False))
    sys.exit(0)

os.makedirs(os.path.dirname(out_path), exist_ok=True)

# ---- download stream (with multi-candidate / multi-source fallback) ----
# Some sources return a dead stream (HTTP 404) for a given track. Try the top
# scored candidates in order and use the first one that actually downloads.
chosen = None
tmp = out_path + ".part"
for cand in ranked[:6]:
    params = urllib.parse.urlencode({"id": cand["id"], "source": cand["source"]})
    url = "http://localhost:%d/api/v1/music/stream?%s" % (port, params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        if os.path.getsize(tmp) < 1024:
            raise Exception("downloaded file too small")
        chosen = cand
        if cand is not top:
            print(json.dumps({"source_fallback": True, "preferred_source": top.get("source"),
                              "used_source": cand.get("source"),
                              "name": cand.get("name"), "artist": cand.get("artist")}, ensure_ascii=False))
        break
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(json.dumps({"stream_failed": {"source": cand.get("source"),
                                            "name": cand.get("name"), "artist": cand.get("artist")},
                          "reason": str(e)}, ensure_ascii=False))
        continue

if chosen is None:
    print(json.dumps({"error": "all candidate streams failed (sources may be unavailable)"}, ensure_ascii=False))
    sys.exit(1)


# ---- detect real format by magic bytes ----
def detect(path):
    with open(path, "rb") as f:
        head = f.read(16)
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return "mp3"
    if head[4:8] == b"ftyp" and any(t in head for t in (b"mp4", b"M4A", b"isom", b"M4V")):
        return "m4a"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"RIFF":
        return "wav"
    return "unknown"


fmt = detect(tmp)
converted = False
conv_reason = ""

if fmt == "mp3":
    shutil.move(tmp, out_path)
else:
    ff = ffmpeg or shutil.which("ffmpeg") or ""
    if ff and os.path.exists(ff):
        if not out_path.lower().endswith(".mp3"):
            out_path = os.path.splitext(out_path)[0] + ".mp3"
        try:
            subprocess.run([ff, "-y", "-i", tmp, "-codec:a", "libmp3lame", "-b:a", "192k", out_path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            os.remove(tmp)
            converted = True
        except Exception as e:
            conv_reason = str(e)
    else:
        conv_reason = "ffmpeg not found"
    if not converted:
        ext_map = {"m4a": ".m4a", "ogg": ".ogg", "flac": ".flac", "wav": ".wav"}
        alt = os.path.splitext(out_path)[0] + ext_map.get(fmt, ".dat")
        shutil.move(tmp, alt)
        out_path = alt

# ---- embed metadata (only meaningful for real MP3) ----
embedded = False
if out_path.lower().endswith(".mp3"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    emb = os.path.join(script_dir, "embed_metadata.py")
    if os.path.exists(emb):
        cover = str(chosen.get("cover", "") or "")
        lyric_url = ""
        cid = chosen.get("id")
        csrc = chosen.get("source")
        if cid and csrc:
            lyric_url = "http://localhost:%d/api/v1/music/lyric?%s" % (
                port, urllib.parse.urlencode({"id": cid, "source": csrc}))
        try:
            subprocess.run([sys.executable, emb, out_path, str(port),
                            json.dumps(chosen, ensure_ascii=False), cover, lyric_url],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            embedded = True
        except Exception:
            embedded = False

# ---- cache + report ----
idx[query] = {"path": out_path, "chosen": chosen}
save_cache(idx)

print(json.dumps({
    "cache_hit": False,
    "chosen": chosen,
    "path": out_path,
    "size": os.path.getsize(out_path),
    "detected_format": fmt,
    "converted_to_mp3": converted,
    "convert_note": conv_reason,
    "metadata_embedded": embedded,
}, ensure_ascii=False))
