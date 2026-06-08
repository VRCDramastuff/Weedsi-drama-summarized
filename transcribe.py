#!/usr/bin/env python3
# Transcribe all audio/video in the drama folder via OpenAI Whisper.
# Why ffmpeg first: Whisper caps uploads at 25MB; we downmix to 16k mono 32kbps mp3
# and segment into <=20min chunks so every chunk is well under the cap regardless of source size.
import os, sys, subprocess, glob, json, time, re, hashlib
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
WORK = os.path.join(ROOT, "_transcribe_work")
OUTDIR = os.path.join(ROOT, "transcripts")
os.makedirs(WORK, exist_ok=True)
os.makedirs(OUTDIR, exist_ok=True)

# --- API key from .env (var name: OPENAI_API) ---
key = None
with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
    for line in f:
        if line.strip().startswith("OPENAI_API"):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
if not key:
    print("NO_KEY"); sys.exit(2)
HEADERS = {"Authorization": f"Bearer {key}"}

# --- which files, in priority order ---
AUDIO_EXT = (".ogg", ".m4a", ".mp3")
VIDEO_EXT = (".mp4", ".mov")
HIGH_VALUE = [  # substrings that float to the top of the audio queue
    "apparent court claims", "talking about glitch's proof", "glitch claims",
    "confronting starcunt", "scum, glitch, buds", "blockbuster claims",
    "glitch makes a promise", "threats of doxxing", "I talk about the screenshots",
    "my reply to owner", "jealousy", "claims i was using for cuddles",
    "Claims i doxxed",
]

def priority(path):
    base = os.path.basename(path)
    for i, h in enumerate(HIGH_VALUE):
        if h.lower() in path.lower():
            return (0, i, base)
    return (1, 0, path.lower())

mode = sys.argv[1] if len(sys.argv) > 1 else "audio"
exts = AUDIO_EXT if mode == "audio" else VIDEO_EXT

all_media = []
for dirpath, _, files in os.walk(ROOT):
    if "_transcribe_work" in dirpath or "transcripts" in dirpath:
        continue
    for fn in files:
        if fn.lower().endswith(exts):
            all_media.append(os.path.join(dirpath, fn))
# de-dupe by (relative-to-_unpacked basename) is risky; keep all but skip already-done
all_media.sort(key=priority)

def safe(path):
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    s = re.sub(r"[^A-Za-z0-9._-]", "_", rel)
    # Windows MAX_PATH guard: long folder/file names blow past ~260 chars.
    if len(s) > 150:
        s = s[:100] + "_" + hashlib.md5(rel.encode("utf-8")).hexdigest()[:8]
    return s

def transcribe_chunk(chunk_path):
    with open(chunk_path, "rb") as fh:
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers=HEADERS,
            files={"file": (os.path.basename(chunk_path), fh, "audio/mpeg")},
            data={"model": "whisper-1", "response_format": "text"},
            timeout=600,
        )
    if r.status_code == 200:
        return ("ok", r.text.strip())
    body = r.text.lower()
    if r.status_code in (401, 429) and ("insufficient_quota" in body or "exceeded" in body or "billing" in body or r.status_code == 401):
        return ("credits", r.text)
    return ("error", f"HTTP {r.status_code}: {r.text[:300]}")

done = 0
total = len(all_media)
manifest = {}  # original relpath -> transcript filename
print(f"MODE={mode} files={total}", flush=True)
for path in all_media:
    sid = safe(path)
    out_txt = os.path.join(OUTDIR, sid + ".txt")
    manifest[os.path.relpath(path, ROOT)] = os.path.basename(out_txt)
    if os.path.exists(out_txt) and os.path.getsize(out_txt) > 0:
        done += 1
        continue
    # transcode + segment
    for old in glob.glob(os.path.join(WORK, "seg_*.mp3")):
        os.remove(old)
    seg_tpl = os.path.join(WORK, "seg_%03d.mp3")
    subprocess.run(
        [FFMPEG, "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
         "-f", "segment", "-segment_time", "1200", seg_tpl],
        capture_output=True,
    )
    chunks = sorted(glob.glob(os.path.join(WORK, "seg_*.mp3")))
    if not chunks:
        with open(out_txt, "w", encoding="utf-8") as w:
            w.write("[NO AUDIO / ffmpeg produced nothing]")
        done += 1
        continue
    parts = []
    failed = False
    for ci, ch in enumerate(chunks):
        status, text = transcribe_chunk(ch)
        if status == "credits":
            print("CREDITS_EXHAUSTED", flush=True)
            print(text[:300], flush=True)
            sys.exit(42)
        if status == "error":
            parts.append(f"[chunk {ci} error: {text}]")
            failed = True
        else:
            parts.append(text)
        time.sleep(0.3)
    with open(out_txt, "w", encoding="utf-8") as w:
        w.write("\n".join(parts))
    done += 1
    print(f"[{done}/{total}] {'(partial) ' if failed else ''}{os.path.relpath(path, ROOT)}", flush=True)

# merge manifest across runs (audio + video) so nothing is lost
mpath = os.path.join(OUTDIR, "_manifest.tsv")
existing = {}
if os.path.exists(mpath):
    for line in open(mpath, encoding="utf-8"):
        if "\t" in line:
            k, v = line.rstrip("\n").split("\t", 1)
            existing[k] = v
existing.update(manifest)
with open(mpath, "w", encoding="utf-8") as mf:
    for k in sorted(existing):
        mf.write(f"{k}\t{existing[k]}\n")

print(f"DONE mode={mode} transcribed_or_cached={done}/{total}", flush=True)
