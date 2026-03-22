"""
╔═══════════════════════════════════════════════════════════════╗
║           Snapchat Memories Organizer  v2.1                   ║
╚═══════════════════════════════════════════════════════════════╝

What this script does:
  ✓ Finds all your extracted Snapchat export folders automatically
  ✓ Reads memories_history.json for date/time and GPS metadata
  ✓ Embeds EXIF date and GPS coordinates into every file
  ✓ Renames files to clean YYYY-MM-DD_HHMMSS format
  ✓ Consolidates everything into a single output folder
  ✓ Composites overlay PNGs onto their matching photos automatically
  ✓ Backs up originals (pre-composite) to memories_organized/originals/
  ✓ Moves files by default to save disk space (your zip files are the backup)
  ✓ Set MOVE_FILES = False to copy instead (requires ~2x free disk space)

REQUIREMENTS:
  - Python 3.7+
  - Pillow:   pip install Pillow
  - exiftool:
      Windows : Download from https://exiftool.org/
                Rename the .exe to exiftool.exe
                Place it next to this script OR add it to your PATH
      macOS   : brew install exiftool
      Linux   : sudo apt install exiftool

HOW TO USE:
  1. Export your Memories from Snapchat:
       Snapchat → Profile → Settings → Privacy Controls → My Data
       Select "Memories" and request the data export.
  2. Download and extract ALL zip files Snapchat sends you.
     Put all the extracted folders into the same parent folder.
  3. Place this script (and exiftool.exe on Windows) in that folder:

       snapchat/
         mydata~1234567890/               ← extracted zip 1
         mydata~1234567890-2/             ← extracted zip 2 (if any)
         mydata~1234567890-3/             ← extracted zip 3 (if any)
         snapchat_memories_organizer.py   ← this script
         exiftool.exe                     ← Windows only, if not on PATH

  4. Open a terminal in that folder and run:
         python snapchat_memories_organizer.py

  5. Results:
       memories_organized/          ← all renamed, tagged, composited files
       memories_organized/originals/ ← original pre-composite JPGs and PNGs

NOTES:
  - Original source files are never modified or deleted.
  - Overlay PNGs are matched to their photo by the shared filename prefix
    (Snapchat names them identically except -main vs -overlay).
  - Files without an overlay are renamed and tagged as normal.
  - A full log is saved to memories_organized/organizer_log.txt.
  - [NO FILE] warnings mean a JSON entry had no matching local file —
    usually caused by an incomplete zip extraction.
"""

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False


# ─── CONFIGURATION ────────────────────────────────────────────────────────────

# Folder containing all mydata~* folders (default: same folder as this script)
BASE_DIR = Path(__file__).parent

# Output folder name
OUTPUT_FOLDER_NAME = "memories_organized"

# Subfolder inside output for pre-composite originals
ORIGINALS_FOLDER_NAME = "originals"

# exiftool executable ("exiftool" if on PATH, or place exiftool.exe next to script)
EXIFTOOL = "exiftool"

# Progress update every N files
PROGRESS_EVERY = 100

# JPEG quality for composited images (1-95)
COMPOSITE_QUALITY = 95

# Move files instead of copying (saves disk space — your zip files are the backup)
# Set to False to copy instead, which requires ~2x the disk space of your export
MOVE_FILES = True

# ──────────────────────────────────────────────────────────────────────────────


def transfer(src, dest):
    """Move or copy a file depending on MOVE_FILES setting."""
    if MOVE_FILES:
        shutil.move(str(src), dest)
    else:
        shutil.copy2(src, dest)


def fmt_duration(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def eta_str(done, total, elapsed):
    if done == 0:
        return "calculating..."
    return fmt_duration((total - done) / (done / elapsed))


def find_exiftool():
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
    for folder in sorted(base_dir.glob("mydata~*")):
        for candidate in [
            folder / "json" / "memories_history.json",
            folder / "memories_history.json",
        ]:
            if candidate.exists():
                return candidate
    return None


def find_memory_files(base_dir):
    """
    Scan all mydata~* subfolders for memories/ directories.
    Returns a dict keyed by bare stem (everything before -main/-overlay),
    mapping to {"main": Path, "overlay": Path or None}.
    Also returns a list of files with no -main/-overlay suffix.
    """
    all_files = []
    for folder in sorted(base_dir.glob("mydata~*")):
        memories_dir = folder / "memories"
        if memories_dir.is_dir():
            files = [f for f in memories_dir.iterdir()
                     if f.is_file() and not f.name.startswith(".")]
            all_files.extend(files)
            print(f"    {folder.name}/memories/  →  {len(files)} files")
    return all_files


def build_file_map(all_files):
    """
    Group files into pairs by their shared stem prefix.
    e.g. "2021-10-23_ae838916-...-main.mp4" and
         "2021-10-23_ae838916-...-overlay.png"
    share the key "2021-10-23_ae838916-...".

    Returns:
      pairs:   dict  bare_key → {"main": Path, "overlay": Path|None}
      unpaired: list of Path  (files with no -main/-overlay suffix)
    """
    main_files = {}
    overlay_files = {}
    unpaired = []

    for f in all_files:
        stem = f.stem  # filename without extension
        if stem.endswith("-main"):
            key = stem[:-5]  # strip "-main"
            main_files[key] = f
        elif stem.endswith("-overlay"):
            key = stem[:-8]  # strip "-overlay"
            overlay_files[key] = f
        else:
            unpaired.append(f)

    # Combine into pairs
    all_keys = set(main_files) | set(overlay_files)
    pairs = {}
    for key in all_keys:
        pairs[key] = {
            "main": main_files.get(key),
            "overlay": overlay_files.get(key),
        }

    return pairs, unpaired


def build_date_index(pairs, unpaired):
    """
    Index pairs and unpaired files by their YYYY-MM-DD date prefix.
    Returns dict: "YYYY-MM-DD" → list of (key_or_path, is_pair)
    """
    index = {}
    for key, pair in pairs.items():
        m = re.match(r"(\d{4}-\d{2}-\d{2})", key)
        if m:
            date_key = m.group(1)
            index.setdefault(date_key, []).append(("pair", key, pair))
    for f in unpaired:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", f.name)
        if m:
            date_key = m.group(1)
            index.setdefault(date_key, []).append(("file", f.name, f))
    return index


def parse_location(location_str):
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
    for fmt in ["%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def unique_filename(dt, ext, used_names):
    base = dt.strftime("%Y-%m-%d_%H%M%S")
    candidate = base + ext.lower()
    counter = 2
    while candidate in used_names:
        candidate = f"{base}_{counter}{ext.lower()}"
        counter += 1
    used_names.add(candidate)
    return candidate


def composite_images(main_path, overlay_path, out_path):
    """Composite overlay PNG on top of main image, save as JPEG."""
    base = Image.open(main_path).convert("RGBA")
    overlay = Image.open(overlay_path).convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, Image.LANCZOS)
    merged = Image.alpha_composite(base, overlay)
    merged.convert("RGB").save(out_path, "JPEG", quality=COMPOSITE_QUALITY)


def apply_exif(exiftool_path, file_path, dt, lat, lon):
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
    print("║           Snapchat Memories Organizer  v2.0                   ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print()

    # 1. Check dependencies
    if not PILLOW_AVAILABLE:
        print("❌  Pillow is not installed. Run:  pip install Pillow")
        sys.exit(1)

    exiftool_path = find_exiftool()
    if not exiftool_path:
        print("❌  exiftool not found!")
        print()
        print("    Windows : Download https://exiftool.org/")
        print("              Rename to exiftool.exe, place next to this script.")
        print("    macOS   : brew install exiftool")
        print("    Linux   : sudo apt install exiftool")
        sys.exit(1)

    print(f"✓  Pillow    :  {Image.__version__}")
    print(f"✓  exiftool  :  {exiftool_path}")
    print(f"✓  Mode      :  {'MOVE (originals will be removed after processing)' if MOVE_FILES else 'COPY (originals kept, ~2x disk space required)'}")

    # 2. Load JSON
    json_path = find_json(BASE_DIR)
    if not json_path:
        print()
        print("❌  Could not find memories_history.json in any mydata~* folder.")
        print(f"    Expected location: {BASE_DIR}")
        sys.exit(1)
    print(f"✓  JSON      :  {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("Saved Media", [])
    print(f"✓  Entries   :  {len(entries)} memories in JSON")

    # 3. Collect and index files
    print()
    print(f"✓  Scanning memories folders in  {BASE_DIR} ...")
    all_files = find_memory_files(BASE_DIR)
    print(f"   Total: {len(all_files)} files found")

    if not all_files:
        print()
        print("❌  No files found in any mydata~*/memories/ folder.")
        sys.exit(1)

    pairs, unpaired = build_file_map(all_files)
    date_index = build_date_index(pairs, unpaired)

    overlay_count = sum(1 for p in pairs.values() if p["overlay"] is not None)
    print(f"   Paired with overlay  : {overlay_count}")
    print(f"   No overlay           : {len(pairs) - overlay_count}")
    print(f"   No -main/-overlay    : {len(unpaired)}")

    # 4. Set up output folders
    output_dir = BASE_DIR / OUTPUT_FOLDER_NAME
    originals_dir = output_dir / ORIGINALS_FOLDER_NAME
    output_dir.mkdir(exist_ok=True)
    originals_dir.mkdir(exist_ok=True)
    print()
    print(f"✓  Output    :  {output_dir}")
    print(f"✓  Originals :  {originals_dir}")
    print()

    # 5. Process JSON entries
    date_cursors = {k: 0 for k in date_index}
    used_names = set()

    matched = 0
    composited = 0
    unmatched = 0
    unmatched_list = []
    skipped = 0
    exif_failed = 0
    exif_failed_list = []
    composite_failed = 0

    total = len(entries)
    print(f"Processing {total} entries...\n")

    for entry in entries:
        date_str = entry.get("Date", "")
        location_str = entry.get("Location", "")

        dt = parse_date(date_str)
        if dt is None:
            skipped += 1
            continue

        date_key = dt.strftime("%Y-%m-%d")
        lat, lon = parse_location(location_str)

        items_for_date = date_index.get(date_key, [])
        cursor = date_cursors.get(date_key, 0)

        if cursor >= len(items_for_date):
            unmatched += 1
            unmatched_list.append(date_str)
            continue

        item = items_for_date[cursor]
        date_cursors[date_key] = cursor + 1

        kind = item[0]

        if kind == "pair":
            _, key, pair = item
            main_file = pair["main"]
            overlay_file = pair["overlay"]

            if main_file is None:
                # Overlay with no main — transfer overlay as-is
                ext = overlay_file.suffix
                new_name = unique_filename(dt, ext, used_names)
                dest = output_dir / new_name
                shutil.copy2(overlay_file, originals_dir / overlay_file.name)
                transfer(overlay_file, dest)
            elif overlay_file is not None and PILLOW_AVAILABLE:
                # Composite overlay onto main
                ext = ".jpg"
                new_name = unique_filename(dt, ext, used_names)
                dest = output_dir / new_name
                try:
                    composite_images(main_file, overlay_file, dest)
                    composited += 1
                    # Back up both originals then remove if moving
                    shutil.copy2(main_file, originals_dir / main_file.name)
                    shutil.copy2(overlay_file, originals_dir / overlay_file.name)
                    if MOVE_FILES:
                        main_file.unlink()
                        overlay_file.unlink()
                except Exception as e:
                    composite_failed += 1
                    # Fall back to transferring main without overlay
                    transfer(main_file, dest)
            else:
                # Main with no overlay — transfer as normal
                ext = main_file.suffix
                new_name = unique_filename(dt, ext, used_names)
                dest = output_dir / new_name
                transfer(main_file, dest)

        else:
            # Unpaired file — transfer as-is
            _, _, src_file = item
            ext = src_file.suffix
            new_name = unique_filename(dt, ext, used_names)
            dest = output_dir / new_name
            transfer(src_file, dest)

        # Apply EXIF to the output file
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

    # 6. Copy any leftover files not matched to a JSON entry
    extra = 0
    for date_key, items in date_index.items():
        cursor = date_cursors.get(date_key, 0)
        for item in items[cursor:]:
            kind = item[0]
            if kind == "pair":
                _, key, pair = item
                for f in [pair["main"], pair["overlay"]]:
                    if f is not None:
                        dest = output_dir / f.name
                        counter = 2
                        while dest.exists():
                            dest = output_dir / f"{f.stem}_{counter}{f.suffix}"
                            counter += 1
                        transfer(f, dest)
                        extra += 1
            else:
                _, _, src_file = item
                dest = output_dir / src_file.name
                counter = 2
                while dest.exists():
                    dest = output_dir / f"{src_file.stem}_{counter}{src_file.suffix}"
                    counter += 1
                transfer(src_file, dest)
                extra += 1

    # 7. Write log
    elapsed_total = time.time() - start_time
    log_path = output_dir / "organizer_log.txt"
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("Snapchat Memories Organizer v2.0 — run log\n")
        log.write(f"Completed  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.write(f"Duration   : {fmt_duration(elapsed_total)}\n\n")
        log.write(f"Matched & tagged    : {matched}\n")
        log.write(f"Overlays composited : {composited}\n")
        log.write(f"Composite failures  : {composite_failed}\n")
        log.write(f"EXIF write warnings : {exif_failed}\n")
        log.write(f"No JSON match       : {unmatched}\n")
        log.write(f"Extra files copied  : {extra}\n")
        log.write(f"Skipped (bad data)  : {skipped}\n")
        if unmatched_list:
            log.write("\n── Entries in JSON with no local file found ──\n")
            log.write("   Usually caused by missing or incomplete zip extractions.\n\n")
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
    print(f"      Overlays composited : {composited}  (originals in /originals/)")
    print(f"      Composite failures  : {composite_failed}  (main file copied as fallback)")
    print(f"      EXIF write warnings : {exif_failed}  (files still copied, just no metadata)")
    print(f"      No JSON match       : {unmatched}  (missing from local export — see log)")
    print(f"      Extra files copied  : {extra}  (local files with no JSON entry)")
    print(f"      Skipped (bad data)  : {skipped}")
    print(f"      Output folder       : {output_dir}")
    print(f"      Originals folder    : {originals_dir}")
    print(f"      Log file            : {log_path}")
    print("═" * 65)
    print()


if __name__ == "__main__":
    main()
