#!/usr/bin/env python3
# Build TRANSCRIPTS.md from transcripts/_manifest.tsv, grouped by top-level folder.
import os
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "transcripts")
manifest = os.path.join(OUT, "_manifest.tsv")

rows = []
for line in open(manifest, encoding="utf-8"):
    if "\t" not in line:
        continue
    rel, txt = line.rstrip("\n").split("\t", 1)
    # skip the _unpacked duplicates of audio that also exist in the original tree
    rows.append((rel, txt))

def topgroup(rel):
    rel = rel.replace("\\", "/")
    if rel.startswith("_unpacked/"):
        return "_unpacked (extracted archives)"
    return rel.split("/")[0] if "/" in rel else rel

# de-dupe: prefer original-tree path over _unpacked copy when transcript text identical
seen_text = {}
groups = {}
for rel, txt in sorted(rows):
    tf = os.path.join(OUT, txt)
    if not os.path.exists(tf):
        continue
    content = open(tf, encoding="utf-8").read().strip()
    key = content[:200]
    is_unpacked = rel.replace("\\", "/").startswith("_unpacked/")
    if key in seen_text and is_unpacked:
        continue  # drop the archive-mirror duplicate
    seen_text[key] = rel
    groups.setdefault(topgroup(rel), []).append((rel, content))

lines = ["# Transcripts (audio + video)\n",
         "*Machine transcription (OpenAI Whisper) of every voice note and video in this archive. "
         "Grouped by folder. Headings link to the source media. Whisper can mishear names/slang; "
         "treat wording as close, not exact. These are the Owner (Weedsi) speaking unless the file/context says otherwise.*\n",
         "\n---\n"]
for g in sorted(groups):
    lines.append(f"\n## {g}\n")
    for rel, content in groups[g]:
        relq = rel.replace("\\", "/")
        lines.append(f"\n### [{os.path.basename(rel)}](<{relq}>)\n")
        lines.append(f"`{relq}`\n")
        lines.append("\n" + (content if content else "*(empty / no speech detected)*") + "\n")
with open(os.path.join(ROOT, "TRANSCRIPTS.md"), "w", encoding="utf-8") as w:
    w.write("\n".join(lines))
print("TRANSCRIPTS.md written:", sum(len(v) for v in groups.values()), "entries in", len(groups), "groups")
