# Snapchat Memories Organizer

A Python script to organize, rename, tag, and composite your exported Snapchat Memories — without re-downloading anything from Snapchat's servers.

## What it does

- **Finds all your export folders automatically** — works with any number of zip exports
- **Reads `memories_history.json`** for date/time and GPS location data
- **Embeds EXIF metadata** (date + GPS coordinates) into every photo and video
- **Renames files** from Snapchat's gibberish format to clean `YYYY-MM-DD_HHMMSS` filenames
- **Composites overlay PNGs onto photos** using Pillow
- **Burns overlay PNGs onto videos** using ffmpeg (text/stickers baked into every frame)
- **Consolidates everything** from all export folders into a single `memories_organized/` folder
- **Interactive setup wizard** — asks your preferences before doing anything
- **Shows progress** with elapsed time and ETA
- **Writes a full log** of any warnings or unmatched files

---

## Requirements

### Python 3.7+

### Pillow
```
pip install Pillow
```
Used for: compositing overlay PNGs onto photos.

### exiftool
Used for: embedding date and GPS metadata into files.
- **Windows**: Download from https://exiftool.org/, rename to `exiftool.exe`, place next to the script or add to PATH
- **macOS**: `brew install exiftool`
- **Linux**: `sudo apt install exiftool`

### ffmpeg
Used for: burning overlay PNGs onto videos. Only needed if you choose to process video overlays.
- **Windows**: Download from https://ffmpeg.org/download.html and place `ffmpeg.exe` next to the script, or run `winget install ffmpeg`
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

---

## Disk space

By default the script **moves** files from your extracted folders into `memories_organized/`, so you only need a small amount of extra space. Your original **zip files are your backup** — don't delete them until you're happy with the output.

If you'd rather keep the extracted files untouched, choose **Copy** when the wizard asks — but be aware this requires roughly **2× the size of your export** in free space (e.g. a 22 GB export needs ~44 GB free).

---

## How to use

### Step 1 — Export your Memories from Snapchat

1. Open Snapchat → Profile → ⚙️ Settings → Privacy Controls → My Data
2. Select **Memories** and submit the export request
3. Wait for Snapchat to email you download links (can take hours or days)
4. Download **all** the zip files they send

### Step 2 — Extract the zips

Extract all zip files into the same parent folder:

```
snapchat/
  mydata~1234567890/        ← extracted zip 1
  mydata~1234567890-2/      ← extracted zip 2
  mydata~1234567890-3/      ← extracted zip 3
  ...
```

### Step 3 — Install dependencies

```bash
pip install Pillow
```

Install exiftool and ffmpeg per the Requirements section above.

### Step 4 — Run the script

Place `snapchat_memories_organizer.py` in the `snapchat/` folder, then run:

```bash
python snapchat_memories_organizer.py
```

The script will check your dependencies, scan your files, then ask a few questions:

```
  Setup — answer a few questions

  File handling:
    1) Move files  (saves disk space — keep your zip files as backup)  (default)
    2) Copy files  (safe, but needs ~2× free disk space)

  Composite overlay PNGs onto photos? [Y/n]:

  Burn overlay PNGs onto videos? (slower — re-encodes video) [Y/n]:

  Video re-encode quality:
    1) Fast / larger file  (CRF 23, good for archiving)
    2) Balanced            (CRF 28, recommended)           (default)
    3) Small / lower quality (CRF 33, saves space)

  Save pre-composite originals to memories_organized/originals/? [Y/n]:

  Composited photo JPEG quality:
    1) High   (95 — recommended)  (default)
    2) Medium (85)
    3) Low    (75 — smaller files)

  Looks good — start processing? [Y/n]:
```

### Step 5 — Wait

Video overlay compositing is slow (re-encoding). A rough estimate:
- **Photos only**: ~1–2 hours for 7000 files
- **With video overlays**: add ~30–60 seconds per video overlay

Progress is shown every 50 files with elapsed time and ETA.

---

## Output structure

```
snapchat/
  memories_organized/
    2016-04-24_012000.jpg      ← renamed, EXIF tagged, overlay composited
    2016-07-17_153600.mp4      ← renamed, date + GPS tagged, overlay burned in
    ...
    originals/                 ← pre-composite originals (if you chose to keep them)
      2016-04-24_...-main.jpg
      2016-04-24_...-overlay.png
      ...
    organizer_log.txt
```

---

## Understanding the output

| Message | Meaning |
|---|---|
| `Photos composited` | Overlay PNG was merged onto the photo using Pillow. |
| `Videos composited` | Overlay PNG was burned into the video using ffmpeg. |
| `Composite failures` | Compositing failed; the original file was copied as-is as a fallback. |
| `EXIF write warnings` | exiftool couldn't write metadata (unusual file format). File still copied. |
| `No JSON match` | A JSON entry had no corresponding local file — usually an incomplete zip extraction. Those files can be re-downloaded from Snapchat before the export links expire. |
| `Extra files` | Local files with no JSON entry — copied as-is. |

---

## Uploading to Immich

If you self-host [Immich](https://immich.app/), use the companion script `snapchat_immich_upload.py` to import everything into per-year albums (`Snapchat 2016`, `Snapchat 2017`, etc.).

```bash
pip install requests
python snapchat_immich_upload.py
```

Fill in your `IMMICH_URL` and `IMMICH_API_KEY` at the top of that script first.

---

## License

MIT — do whatever you want with it.
