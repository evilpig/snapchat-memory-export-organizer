# Snapchat Memories Organizer

A Python script to organize, rename, tag, and composite your exported Snapchat Memories — without re-downloading anything from Snapchat's servers.

## What it does

- **Finds all your export folders automatically** — works with any number of zip exports
- **Reads `memories_history.json`** for date/time and GPS location data
- **Embeds EXIF metadata** (date + GPS coordinates) into every photo and video
- **Renames files** from Snapchat's gibberish format to clean `YYYY-MM-DD_HHMMSS.jpg`
- **Composites overlay PNGs onto photos** — Snapchat stores text/sticker overlays as separate transparent PNGs; this merges them onto the original automatically
- **Backs up originals** (pre-composite) to `memories_organized/originals/`
- **Consolidates everything** from all export folders into a single `memories_organized/` folder
- **Shows progress** with elapsed time and ETA
- **Writes a full log** of any warnings or unmatched files

---

## Requirements

- Python 3.7+
- [Pillow](https://pypi.org/project/Pillow/): `pip install Pillow`
- [exiftool](https://exiftool.org/):
  - **Windows**: Download, rename to `exiftool.exe`, place next to the script or add to PATH
  - **macOS**: `brew install exiftool`
  - **Linux**: `sudo apt install exiftool`

---

## How to use

### Step 1 — Export your Memories from Snapchat

1. Open Snapchat → Profile → ⚙️ Settings → Privacy Controls → My Data
2. Select **Memories** and submit the export request
3. Wait for Snapchat to email you download links (can take hours or days)
4. Download **all** the zip files — if you have a lot of memories there may be many

### Step 2 — Extract the zips

Extract all zip files into the same parent folder:

```
snapchat/
  mydata~1234567890/        ← extracted zip 1
  mydata~1234567890-2/      ← extracted zip 2
  mydata~1234567890-3/      ← extracted zip 3
  ...
```

### Step 3 — Run the script

Place `snapchat_memories_organizer.py` (and `exiftool.exe` on Windows) in the `snapchat/` folder, then run:

```bash
pip install Pillow
python snapchat_memories_organizer.py
```

**Example output:**
```
╔═══════════════════════════════════════════════════════════════╗
║           Snapchat Memories Organizer  v2.0                   ║
╚═══════════════════════════════════════════════════════════════╝

✓  Pillow    :  10.3.0
✓  exiftool  :  exiftool
✓  JSON      :  ...\mydata~1234567890\json\memories_history.json
✓  Entries   :  6969 memories in JSON

✓  Scanning memories folders...
    mydata~1234567890/memories/   →  4100 files
    mydata~1234567890-2/memories/ →  3895 files
   Total: 7995 files found
   Paired with overlay  : 1823
   No overlay           : 4748
   No -main/-overlay    : 1424

✓  Output    :  ...\memories_organized
✓  Originals :  ...\memories_organized\originals

  14:22:01  [ 10.0%]    697 / 6969  |  elapsed 1m 14s  |  ETA ~10m 46s
  14:22:51  [ 20.0%]   1394 / 6969  |  elapsed 2m 04s  |  ETA ~8m 16s
  ...

═════════════════════════════════════════════════════════════════
  ✅  All done!  (11m 02s)
      Matched & tagged    : 6800
      Overlays composited : 1620   (originals in /originals/)
      Composite failures  : 3      (main file copied as fallback)
      EXIF write warnings : 2      (files still copied, just no metadata)
      No JSON match       : 169    (missing from local export — see log)
      Extra files copied  : 1026
      Output folder       : ...\memories_organized
      Originals folder    : ...\memories_organized\originals
      Log file            : ...\memories_organized\organizer_log.txt
═════════════════════════════════════════════════════════════════
```

---

## Output structure

```
snapchat/
  memories_organized/
    2016-04-24_012000.jpg    ← renamed, EXIF tagged, overlay composited
    2016-04-24_011400.jpg
    2016-07-17_153600.mp4    ← renamed, date + GPS tagged
    ...
    originals/
      2016-04-24_6b6aad0c-...-main.jpg     ← original pre-composite photo
      2016-04-24_6b6aad0c-...-overlay.png  ← original overlay PNG
      ...
    organizer_log.txt
```

---

## Understanding the output

| Message | Meaning |
|---|---|
| `Overlays composited` | A `-overlay.png` was found and merged onto its `-main` photo. Both originals are in `/originals/`. |
| `Composite failures` | Compositing failed (unusual file format); the main photo was copied without the overlay as a fallback. |
| `EXIF write warnings` | exiftool couldn't write metadata to a file (usually corrupted or unusual format). File was still copied and renamed. |
| `No JSON match` | A JSON entry had no corresponding local file — usually means a zip wasn't fully extracted. Those memories can be re-downloaded from Snapchat before the export links expire. |
| `Extra files copied` | Local files with no JSON entry. Copied as-is with original filename. |

---

## Notes

- **Original source files are never modified or deleted**
- Export links from Snapchat expire after a few days — if you have `No JSON match` warnings and want to recover those files, re-download them from Snapchat before the links expire
- GPS coordinates are embedded as standard EXIF GPS tags — apps like Google Photos will place them on a map automatically
- On Windows, GPS shows in Explorer's Details pane for photos. For videos, verify with `exiftool yourfile.mp4 | grep GPS`
- If you have duplicate timestamps (two photos taken the same second), files are named `YYYY-MM-DD_HHMMSS_2.jpg`, `_3.jpg`, etc.

---

## License

MIT — do whatever you want with it.
