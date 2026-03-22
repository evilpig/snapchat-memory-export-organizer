"""
╔═══════════════════════════════════════════════════════════════╗
║           Snapchat Memories Organizer  v1.1                   ║
║           github.com/  (feel free to share!)                  ║
╚═══════════════════════════════════════════════════════════════╝

What this script does:
  ✓ Finds all your extracted Snapchat export folders automatically
  ✓ Reads memories_history.json for date/time and GPS metadata
  ✓ Embeds EXIF date and GPS coordinates into every file
  ✓ Renames files to clean YYYY-MM-DD_HHMMSS format
  ✓ Consolidates everything into a single output folder
  ✓ Writes a log file listing any files that couldn't be matched

REQUIREMENTS:
  - Python 3.7+
  - exiftool:
      Windows : Download from https://exiftool.org/
                Rename the .exe to exiftool.exe
                Either place it next to this script OR add it to your PATH
      macOS   : brew install exiftool
      Linux   : sudo apt install exiftool

HOW TO USE:
  1. Export your Memories from Snapchat:
       Snapchat → Profile → Settings → Privacy Controls → My Data
       Select "Memories" and request your data export.
  2. Download and extract ALL of the zip files Snapchat sends you.
     (There may be just one, or many if you have a lot of memories.)
     Put all the extracted folders in the same parent folder.
  3. Place this script in that same parent folder, e.g.:

       snapchat/
         mydata~1234567890/               ← extracted zip 1
         mydata~1234567890-2/             ← extracted zip 2 (if any)
         mydata~1234567890-3/             ← extracted zip 3 (if any)
         snapchat_memories_organizer.py   ← this script
         exiftool.exe                     ← (Windows only, if not on PATH)

  4. Open a terminal in that folder and run:
         python snapchat_memories_organizer.py

  5. Your organized memories will appear in:
         snapchat/memories_organized/

NOTES:
  - Your original files are never modified or deleted.
  - Files that can't have EXIF written (rare) are still copied and renamed.
  - If you have duplicate timestamps, _2, _3 etc. are appended automatically.
  - Videos get their file timestamps set; EXIF date is set where supported.
  - [NO FILE] warnings mean a JSON entry had no matching local file — usually
    caused by missing or incomplete zip extractions. Those memories are absent
    from your local export and would need to be re-downloaded from Snapchat.
  - A full log is saved to memories_organized/organizer_log.txt when done.
"""

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ─── CONFIGURATION (you can change these if needed) ───────────────────────────

# Folder containing all mydata~* folders (default: same folder as this script)
BASE_DIR = Path(__file__).parent

# Output folder name
OUTPUT_FOLDER_NAME = "memories_organized"

# exiftool executable ("exiftool" if on PATH, or place exiftool.exe next to script)
EXIFTOOL = "exiftool"

# Progress update every N files
PROGRESS_EVERY = 100

# ──────────────────────────────────────────────────────────────────────────────


def fmt_duration(seconds):
    """Format elapsed seconds as Xm Ys."""
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def eta_str(done, total, elapsed):
    """Estimate remaining time."""
    if done == 0:
        return "calculating..."
    rate = done / elapsed
    return fmt_duration((total - done) / rate)


def find_exiftool():
    """Find exiftool on PATH or in the script directory."""
    candidates = [EXIFTOOL, str(BASE_DIR / "exiftool.exe"), str(BASE_DIR / "exiftool")]
    for candidate in candidates:
        try:
            result = subprocess.run([candidate, "-ver"], capture_output=True, text=True)
            if result.returncode == 0:
                return candidate
        except FileNotFoundError:
            continue
    return None


def find_json(base_dir):
    """Search all mydata~* folders for memories_history.json."""
    for folder in sorted(base_dir.glob("mydata~*")):
        for candidate in [
            folder / "json" / "memories_history.json",
            folder / "memories_history.json",
        ]:
            if candidate.exists():
                return candidate
    return None


def find_memory_files(base_dir):
    """Scan all mydata~* subfolders for memories/ directories."""
    all_files = []
    for folder in sorted(base_dir.glob("mydata~*")):
        memories_dir = folder / "memories"
        if memories_dir.is_dir():
            files = [f for f in memories_dir.iterdir()
                     if f.is_file() and not f.name.startswith(".")]
            all_files.extend(files)
            print(f"    {folder.name}/memories/  →  {len(files)} files")
    return all_files


def parse_location(location_str):
    """Parse 'Latitude, Longitude: 52.14105, -106.59962' → (lat, lon) or (None, None)."""
    if not location_str:
        return None, None
    match = re.search(r"([-\d.]+),\s*([-\d.]+)\s*$", location_str.strip())
    if match:
        try:
            return float(match.group(1)), float(match.group(2))
        except ValueError:
            pass
    return None, None


def parse_date(date_str):
    """Parse Snapchat date string 'YYYY-MM-DD HH:MM:SS UTC' → datetime."""
    for fmt in ["%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def build_date_index(all_files):
    """Index files by YYYY-MM-DD prefix from filename."""
    index = {}
    for f in all_files:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", f.name)
        if m:
            index.setdefault(m.group(1), []).append(f)
    return index


def unique_filename(dt, original_name, used_names):
    """Generate YYYY-MM-DD_HHMMSS.ext, appending _2/_3 etc. if duplicate."""
    ext = Path(original_name).suffix.lower()
    base = dt.strftime("%Y-%m-%d_%H%M%S")
    candidate = base + ext
    counter = 2
    while candidate in used_names:
        candidate = f"{base}_{counter}{ext}"
        counter += 1
    used_names.add(candidate)
    return candidate


def apply_exif(exiftool_path, file_path, dt, lat, lon):
    """Stamp date and optional GPS into a file using exiftool."""
    exif_date = dt.strftime("%Y:%m:%d %H:%M:%S")
    args = [
        exiftool_path,
        "-overwrite_original",
        "-q",
        f"-AllDates={exif_date}",
        f"-FileModifyDate={exif_date}",
        f"-FileCreateDate={exif_date}",
    ]
    if lat is not None and lon is not None:
        args += [
            f"-GPSLatitude={abs(lat)}",
            f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
            f"-GPSLongitude={abs(lon)}",
            f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
        ]
    args.append(str(file_path))
    result = subprocess.run(args, capture_output=True, text=True)
    return result.returncode == 0


def main():
    start_time = time.time()

    print()
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║           Snapchat Memories Organizer  v1.1                   ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print()

    # 1. Check exiftool
    exiftool_path = find_exiftool()
    if not exiftool_path:
        print("❌  exiftool not found!")
        print()
        print("    Windows : Download https://exiftool.org/")
        print("              Rename to exiftool.exe and place next to this script.")
        print("    macOS   : brew install exiftool")
        print("    Linux   : sudo apt install exiftool")
        sys.exit(1)
    print(f"✓  exiftool  :  {exiftool_path}")

    # 2. Find and load JSON
    json_path = find_json(BASE_DIR)
    if not json_path:
        print()
        print("❌  Could not find memories_history.json in any mydata~* folder.")
        print("    Make sure at least one extracted zip folder is here:")
        print(f"    {BASE_DIR}")
        sys.exit(1)
    print(f"✓  JSON      :  {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("Saved Media", [])
    print(f"✓  Entries   :  {len(entries)} memories in JSON")

    # 3. Collect files
    print()
    print(f"✓  Scanning memories folders in  {BASE_DIR} ...")
    all_files = find_memory_files(BASE_DIR)
    print(f"   Total: {len(all_files)} files found")

    if not all_files:
        print()
        print("❌  No files found! Make sure your extracted mydata~* folders")
        print("    contain a 'memories' subfolder with your media files.")
        sys.exit(1)

    # 4. Set up output
    output_dir = BASE_DIR / OUTPUT_FOLDER_NAME
    output_dir.mkdir(exist_ok=True)
    print()
    print(f"✓  Output    :  {output_dir}")
    print()

    # 5. Build index and process
    date_index = build_date_index(all_files)
    date_cursors = {k: 0 for k in date_index}
    used_names = set()

    matched = 0
    unmatched = 0
    unmatched_list = []
    skipped = 0
    exif_failed = 0
    exif_failed_list = []

    total = len(entries)
    print(f"Processing {total} entries...\n")

    for i, entry in enumerate(entries):
        date_str = entry.get("Date", "")
        location_str = entry.get("Location", "")

        dt = parse_date(date_str)
        if dt is None:
            skipped += 1
            continue

        date_key = dt.strftime("%Y-%m-%d")
        lat, lon = parse_location(location_str)

        files_for_date = date_index.get(date_key, [])
        cursor = date_cursors.get(date_key, 0)

        if cursor >= len(files_for_date):
            unmatched += 1
            unmatched_list.append(date_str)
            continue

        src = files_for_date[cursor]
        date_cursors[date_key] = cursor + 1

        new_name = unique_filename(dt, src.name, used_names)
        dest = output_dir / new_name

        shutil.copy2(src, dest)

        if not apply_exif(exiftool_path, dest, dt, lat, lon):
            exif_failed += 1
            exif_failed_list.append(new_name)

        matched += 1
        if matched % PROGRESS_EVERY == 0:
            elapsed = time.time() - start_time
            pct = matched / total * 100
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  {ts}  [{pct:5.1f}%]  {matched:>5} / {total}"
                  f"  |  elapsed {fmt_duration(elapsed)}"
                  f"  |  ETA ~{eta_str(matched, total, elapsed)}")

    # 6. Copy leftover files with no JSON match
    extra = 0
    for date_key, files in date_index.items():
        cursor = date_cursors.get(date_key, 0)
        for f in files[cursor:]:
            dest = output_dir / f.name
            counter = 2
            while dest.exists():
                dest = output_dir / f"{f.stem}_{counter}{f.suffix}"
                counter += 1
            shutil.copy2(f, dest)
            extra += 1

    # 7. Write log file
    elapsed_total = time.time() - start_time
    log_path = output_dir / "organizer_log.txt"
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("Snapchat Memories Organizer — run log\n")
        log.write(f"Completed : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.write(f"Duration  : {fmt_duration(elapsed_total)}\n\n")
        log.write(f"Matched & tagged    : {matched}\n")
        log.write(f"EXIF write warnings : {exif_failed}\n")
        log.write(f"No JSON match       : {unmatched}\n")
        log.write(f"Extra files copied  : {extra}\n")
        log.write(f"Skipped (bad data)  : {skipped}\n")
        if unmatched_list:
            log.write("\n── Entries in JSON with no local file found ──\n")
            log.write("   These memories were missing from your local export.\n")
            log.write("   They may need to be re-downloaded from Snapchat.\n\n")
            for d in unmatched_list:
                log.write(f"  {d}\n")
        if exif_failed_list:
            log.write("\n── Files where EXIF write failed ──\n")
            log.write("   Files were still copied and renamed correctly.\n\n")
            for name in exif_failed_list:
                log.write(f"  {name}\n")

    # 8. Summary
    print()
    print("═" * 65)
    print(f"  ✅  All done!  ({fmt_duration(elapsed_total)})")
    print(f"      Matched & tagged    : {matched}")
    print(f"      EXIF write warnings : {exif_failed}  (files still copied, just no metadata)")
    print(f"      No JSON match       : {unmatched}  (missing from local export — see log)")
    print(f"      Extra files copied  : {extra}  (local files with no JSON entry)")
    print(f"      Skipped (bad data)  : {skipped}")
    print(f"      Output folder       : {output_dir}")
    print(f"      Log file            : {log_path}")
    print("═" * 65)
    print()


if __name__ == "__main__":
    main()
