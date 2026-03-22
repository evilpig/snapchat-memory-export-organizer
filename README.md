# Snapchat Memories Organizer

A Python script to organize, rename, tag, and composite your exported Snapchat Memories — without re-downloading anything from Snapchat's servers.

## What it does

- **Finds all your export folders automatically** — works with any number of zip exports
- **Reads `memories_history.json`** for date/time and GPS location data
- **Embeds EXIF metadata** (date + GPS coordinates) into every photo and video
- **Renames files** from Snapchat's gibberish format to clean `YYYY-MM-DD_HHMMSS` filenames
- **Composites overlay PNGs onto photos** using Pillow
- **Burns overlay PNGs onto videos** using ffmpeg — correctly handles rotation metadata for portrait videos stored with a displaymatrix
- **Consolidates everything** into a single `memories_organized/` folder
- **Interactive setup wizard** — asks your preferences before doing anything, with an optional video test to verify compositing works before the full run
- **Moves files by default** to save disk space — your zip files are the backup
- **Shows progress** with elapsed time and ETA
- **Writes a full log** of any warnings or unmatched files

---

## Requirements

### Python 3.7+

### Pillow
```
pip install Pillow
```
Used for compositing overlay PNGs onto photos.

### exiftool
Used for embedding date and GPS metadata.
- **Windows**: Download from https://exiftool.org/, rename to `exiftool.exe`, place next to the script or add to PATH
- **macOS**: `brew install exiftool`
- **Linux**: `sudo apt install exiftool`

### ffmpeg + ffprobe
Used for burning overlay PNGs onto videos. ffprobe is included with ffmpeg.
- **Windows**: Download from https://ffmpeg.org/download.html, place `ffmpeg.exe` and `ffprobe.exe` next to the script, or run `winget install ffmpeg`
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

---

## Disk space

By default the script **moves** files from your extracted folders into `memories_organized/`, so you only need a small amount of extra space. Your original **zip files are your backup** — don't delete them until you're happy with the output.

If you'd rather keep the extracted files untouched, choose **Copy** in the wizard — but this requires roughly **2× the size of your export** in free space.

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

### Step 4 — (Optional) Test on one zip first

To verify everything works before a multi-hour full run:

1. Create a test folder with just one extracted zip
2. Copy the `json/` folder from zip 1 into your test folder
3. Run the script from that folder

The script always processes the full JSON regardless of how many zips are present — a high `No JSON match` count is normal when testing one zip.

### Step 5 — Run the script

Place `snapchat_memories_organizer.py` (and tools) in the `snapchat/` folder and run:

```bash
python snapchat_memories_organizer.py
```

The wizard will ask:

```
  File handling:
    1) Move files  (saves disk space — keep your zip files as backup)  (default)
    2) Copy files  (safe, but needs ~2× free disk space)

  Composite overlay PNGs onto photos? [Y/n]:

  Burn overlay PNGs onto videos? (slower — re-encodes video) [Y/n]:

  Video re-encode quality:
    1) Fast / larger file  (CRF 23)
    2) Balanced            (CRF 28, recommended)  (default)
    3) Small / lower quality (CRF 33)

  Run a quick video overlay test before the full run? [Y/n]:
    → Finds first video+overlay pair, composites it, asks you to verify

  Save pre-composite originals to memories_organized/originals/? [Y/n]:

  Composited photo JPEG quality:
    1) High   (95 — recommended)  (default)
    2) Medium (85)
    3) Low    (75 — smaller files)

  Looks good — start processing? [Y/n]:
```

### Step 6 — Wait

Video overlay compositing re-encodes each video which takes time. Rough estimates:
- **Photos only**: ~1–2 hours for 7000 files
- **With video overlays**: add ~5–15 seconds per video overlay depending on length and CPU

---

## Output structure

```
snapchat/
  memories_organized/
    2016-04-24_012000.jpg      ← renamed, EXIF tagged, overlay composited
    2016-07-17_153600.mp4      ← renamed, GPS tagged, overlay burned in
    ...
    originals/                 ← pre-composite originals (if kept)
      2016-04-24_...-main.jpg
      2016-04-24_...-overlay.png
      ...
    organizer_log.txt
  video_overlay_test_output.mp4  ← test video (safe to delete after)
```

---

## Understanding the output

| Message | Meaning |
|---|---|
| `Photos composited` | Overlay PNG merged onto photo using Pillow. |
| `Videos composited` | Overlay PNG burned into video using ffmpeg. |
| `Composite failures` | Compositing failed; original copied as-is. |
| `EXIF write warnings` | exiftool couldn't write metadata (unusual file). File still copied and renamed. |
| `No JSON match` | JSON entry had no local file. Normal when testing one zip. For a full run, usually means an incomplete extraction — re-download from Snapchat before export links expire. |
| `Extra files` | Local files with no JSON entry — copied as-is. |

---

## Video rotation handling

Snapchat videos are almost always portrait. Some older videos are stored as landscape with a displaymatrix rotation tag (-90°) telling players to rotate for display. The script detects this via `ffprobe` and scales the overlay to the **display dimensions** (after rotation), which is what ffmpeg outputs. This ensures overlays line up correctly on all video types.

---

## Uploading to Immich

If you self-host [Immich](https://immich.app/), use `snapchat_immich_upload.py` to import into per-year albums (`Snapchat 2016`, `Snapchat 2017`, etc.):

```bash
pip install requests
python snapchat_immich_upload.py
```

Set `IMMICH_URL` and `IMMICH_API_KEY` at the top of that script first.

---

## License

MIT — do whatever you want with it.
