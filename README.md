# Snapchat Memories Organizer

A pair of Python scripts to organize, rename, and fix the metadata on your exported Snapchat Memories — without re-downloading anything from Snapchat's servers.

## What it does

**`snapchat_memories_organizer.py`**
- Scans all your extracted Snapchat export folders automatically (handles any number of zips)
- Reads `memories_history.json` for date/time and GPS location data
- Embeds EXIF metadata (date + GPS coordinates) into every photo and video
- Renames files from Snapchat's gibberish format to clean `YYYY-MM-DD_HHMMSS.jpg` filenames
- Consolidates everything from all export folders into a single `memories_organized/` folder
- Shows progress with elapsed time and ETA
- Writes a log file with details of any files that couldn't be matched

**`snapchat_overlay_compositor.py`** *(run after the organizer)*
- Snapchat stores text/sticker overlays as separate transparent PNG files alongside the original JPG
- This script composites each overlay PNG on top of its matching JPG into a single merged image
- Originals (unmerged JPG + PNG) are preserved in `memories_organized/originals/`

---

## Requirements

- Python 3.7+
- [exiftool](https://exiftool.org/)
  - **Windows**: Download, rename to `exiftool.exe`, place next to the script or add to PATH
  - **macOS**: `brew install exiftool`
  - **Linux**: `sudo apt install exiftool`
- [Pillow](https://pypi.org/project/Pillow/) *(for the compositor script only)*
  - `pip install Pillow`

---

## How to use

### Step 1 — Export your Memories from Snapchat

1. Open Snapchat → Profile → ⚙️ Settings → Privacy Controls → My Data
2. Select **Memories** and submit the request
3. Wait for Snapchat to email you download links (can take hours or days)
4. Download **all** the zip files they send — if you have a lot of memories there may be many

### Step 2 — Extract the zips

Extract all zip files into the same parent folder:

```
snapchat/
  mydata~1234567890/        ← extracted zip 1
  mydata~1234567890-2/      ← extracted zip 2
  mydata~1234567890-3/      ← extracted zip 3
  ...
```

### Step 3 — Run the organizer

Place `snapchat_memories_organizer.py` (and `exiftool.exe` on Windows) in the `snapchat/` folder, then run:

```bash
python snapchat_memories_organizer.py
```

Output will appear in `snapchat/memories_organized/`. A log file is saved there too.

**Example output:**
```
╔═══════════════════════════════════════════════════════════════╗
║           Snapchat Memories Organizer  v1.1                   ║
╚═══════════════════════════════════════════════════════════════╝

✓  exiftool  :  exiftool
✓  JSON      :  ...\mydata~1234567890\json\memories_history.json
✓  Entries   :  6969 memories in JSON

✓  Scanning memories folders...
    mydata~1234567890/memories/   →  4100 files
    mydata~1234567890-2/memories/ →  1200 files
    ...
   Total: 7995 files found

  14:22:01  [ 10.0%]    697 / 6969  |  elapsed 1m 12s  |  ETA ~10m 48s
  14:22:48  [ 20.0%]   1394 / 6969  |  elapsed 1m 59s  |  ETA ~7m 56s
  ...

═════════════════════════════════════════════════════════════════
  ✅  All done!  (9m 43s)
      Matched & tagged    : 6800
      EXIF write warnings : 2   (files still copied, just no metadata)
      No JSON match       : 169 (missing from local export — see log)
      Extra files copied  : 1026
      Output folder       : ...\memories_organized
      Log file            : ...\memories_organized\organizer_log.txt
═════════════════════════════════════════════════════════════════
```

### Step 4 — (Optional) Composite overlays

```bash
pip install Pillow
python snapchat_overlay_compositor.py
```

This merges Snapchat text/sticker overlays onto their photos. Originals are saved to `memories_organized/originals/`.

---

## Understanding the output

| Message | Meaning |
|---|---|
| `EXIF write warnings` | File was copied and renamed fine, exiftool just couldn't write metadata to it (usually a corrupted or unusual file) |
| `No JSON match` | A JSON entry had no corresponding local file. Usually means some zips weren't fully extracted. Those memories are absent locally but can be re-downloaded from Snapchat before the export links expire. |
| `Extra files copied` | Local files with no JSON entry (e.g. overlay PNGs, or files from an incomplete export). Copied as-is with original filename. |

---

## Notes

- **Original files are never modified or deleted** — the scripts only copy
- The export links Snapchat emails you expire after a few days, so run the organizer while they're still valid if you intend to recover any missing files
- GPS coordinates are embedded as standard EXIF GPS tags — apps like Google Photos will place them on a map automatically
- On Windows, file date metadata shows correctly in Explorer's Details pane for photos; for videos use `exiftool yourfile.mp4` to verify

---

## License

MIT — do whatever you want with it.
