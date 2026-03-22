"""
╔═══════════════════════════════════════════════════════════════╗
║           Snapchat Memories Organizer  v3.0                   ║
╚═══════════════════════════════════════════════════════════════╝

What this script does:
  ✓ Finds all your extracted Snapchat export folders automatically
  ✓ Reads memories_history.json for date/time and GPS metadata
  ✓ Embeds EXIF date and GPS coordinates into every file
  ✓ Renames files to clean YYYY-MM-DD_HHMMSS format
  ✓ Composites overlay PNGs onto photos (Pillow)
  ✓ Burns overlay PNGs onto videos (ffmpeg)
  ✓ Consolidates everything into a single output folder
  ✓ Interactive setup wizard — no config file editing needed

REQUIREMENTS:
  - Python 3.7+

  - Pillow       pip install Pillow
    Used for: compositing overlay PNGs onto photos

  - exiftool     https://exiftool.org/
    Windows:  download, rename to exiftool.exe, place next to this script
              OR add to PATH
    macOS:    brew install exiftool
    Linux:    sudo apt install exiftool

  - ffmpeg       https://ffmpeg.org/download.html
    Windows:  download, place ffmpeg.exe next to this script OR add to PATH
              OR: winget install ffmpeg
    macOS:    brew install ffmpeg
    Linux:    sudo apt install ffmpeg
    Used for: burning overlay PNGs onto videos (only needed if you choose
              to process video overlays)

HOW TO USE:
  1. Export your Memories from Snapchat:
       Snapchat → Profile → Settings → Privacy Controls → My Data
       Select "Memories" and request the data export.
  2. Download and extract ALL zip files Snapchat sends you.
     Put all the extracted folders into the same parent folder.
  3. Place this script in that same parent folder:

       snapchat/
         mydata~1234567890/               ← extracted zip 1
         mydata~1234567890-2/             ← extracted zip 2 (if any)
         snapchat_memories_organizer.py   ← this script
         exiftool.exe                     ← Windows, if not on PATH
         ffmpeg.exe                       ← Windows, if not on PATH

  4. Run:  python snapchat_memories_organizer.py
     The script will ask you a few questions, then do all the work.

  5. Results:
       memories_organized/           ← renamed, tagged, composited files
       memories_organized/originals/ ← pre-composite originals (if kept)
       memories_organized/organizer_log.txt
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
    PILLOW_VERSION = Image.__version__
except ImportError:
    PILLOW_AVAILABLE = False
    PILLOW_VERSION = "not installed"


# ─── CONSTANTS ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
OUTPUT_FOLDER_NAME = "memories_organized"
ORIGINALS_FOLDER_NAME = "originals"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".mp4", ".mov", ".gif", ".heic", ".webp"}

VIDEO_EXTENSIONS = {".mp4", ".mov"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}

# ffmpeg CRF values: lower = better quality, larger file
VIDEO_QUALITY_PRESETS = {
    "1": ("Fast / larger file  (CRF 23, good for archiving)", 23),
    "2": ("Balanced            (CRF 28, recommended)",        28),
    "3": ("Small / lower quality (CRF 33, saves space)",      33),
}

# ──────────────────────────────────────────────────────────────────────────────


def fmt_duration(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s" if m else f"{s}s"


def eta_str(done, total, elapsed):
    if done == 0:
        return "calculating..."
    return fmt_duration((total - done) / (done / elapsed))


def ask(prompt, options, default=None):
    """
    Print a numbered menu and return the user's choice key.
    options: dict of key → description string
    """
    print(f"\n  {prompt}")
    for key, desc in options.items():
        marker = " (default)" if key == default else ""
        print(f"    {key}) {desc}{marker}")
    while True:
        choice = input("  Enter choice: ").strip()
        if choice == "" and default:
            return default
        if choice in options:
            return choice
        print(f"  Please enter one of: {', '.join(options.keys())}")


def ask_yn(prompt, default="y"):
    marker = " [Y/n]" if default == "y" else " [y/N]"
    while True:
        val = input(f"  {prompt}{marker}: ").strip().lower()
        if val == "":
            return default == "y"
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("  Please enter y or n.")


# ─── DEPENDENCY CHECKS ────────────────────────────────────────────────────────

def find_tool(name):
    """Find a tool on PATH or next to the script. Returns path string or None."""
    candidates = [name, str(BASE_DIR / f"{name}.exe"), str(BASE_DIR / name)]
    for c in candidates:
        try:
            r = subprocess.run([c, "-version" if name == "ffmpeg" else "-ver"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                return c
        except FileNotFoundError:
            continue
    return None


# ─── FILE DISCOVERY ───────────────────────────────────────────────────────────

def find_json():
    for folder in sorted(BASE_DIR.glob("mydata~*")):
        for candidate in [
            folder / "json" / "memories_history.json",
            folder / "memories_history.json",
        ]:
            if candidate.exists():
                return candidate
    return None


def find_memory_files():
    """Scan all mydata~* subfolders for memories/ directories."""
    all_files = []
    for folder in sorted(BASE_DIR.glob("mydata~*")):
        memories_dir = folder / "memories"
        if memories_dir.is_dir():
            files = [f for f in memories_dir.iterdir()
                     if f.is_file() and not f.name.startswith(".")
                     and f.suffix.lower() in SUPPORTED_EXTENSIONS | {".png"}]
            all_files.extend(files)
            print(f"    {folder.name}/memories/  →  {len(files)} files")
    return all_files


def build_file_map(all_files):
    """
    Group files into pairs by shared UUID stem prefix.
    e.g. "2023-05-18_475f61fd-3ba8-...-main.mp4" and
         "2023-05-18_475f61fd-3ba8-...-overlay.png"
    share key "2023-05-18_475f61fd-3ba8-..."

    Returns:
      pairs:    dict  bare_key → {"main": Path|None, "overlay": Path|None}
      unpaired: list of Path (no -main/-overlay suffix)
    """
    main_files = {}
    overlay_files = {}
    unpaired = []

    for f in all_files:
        stem = f.stem
        if stem.endswith("-main"):
            key = stem[:-5]
            main_files[key] = f
        elif stem.endswith("-overlay"):
            key = stem[:-8]
            overlay_files[key] = f
        else:
            unpaired.append(f)

    all_keys = set(main_files) | set(overlay_files)
    pairs = {key: {"main": main_files.get(key), "overlay": overlay_files.get(key)}
             for key in all_keys}

    return pairs, unpaired


def build_date_index(pairs, unpaired):
    """Index everything by YYYY-MM-DD prefix."""
    index = {}
    for key, pair in pairs.items():
        m = re.match(r"(\d{4}-\d{2}-\d{2})", key)
        if m:
            index.setdefault(m.group(1), []).append(("pair", key, pair))
    for f in unpaired:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", f.name)
        if m:
            index.setdefault(m.group(1), []).append(("file", f.name, f))
    return index


# ─── METADATA ─────────────────────────────────────────────────────────────────

def parse_location(s):
    if not s:
        return None, None
    m = re.search(r"([-\d.]+),\s*([-\d.]+)\s*$", s.strip())
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass
    return None, None


def parse_date(s):
    for fmt in ["%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone.utc)
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


def apply_exif(exiftool_path, file_path, dt, lat, lon):
    exif_date = dt.strftime("%Y:%m:%d %H:%M:%S")
    args = [exiftool_path, "-overwrite_original", "-q",
            f"-AllDates={exif_date}",
            f"-FileModifyDate={exif_date}",
            f"-FileCreateDate={exif_date}"]
    if lat is not None and lon is not None:
        args += [f"-GPSLatitude={abs(lat)}",
                 f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
                 f"-GPSLongitude={abs(lon)}",
                 f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}"]
    args.append(str(file_path))
    return subprocess.run(args, capture_output=True, text=True).returncode == 0


# ─── COMPOSITING ──────────────────────────────────────────────────────────────

def composite_photo(main_path, overlay_path, out_path, jpeg_quality):
    """Composite overlay PNG onto photo using Pillow."""
    base = Image.open(main_path).convert("RGBA")
    overlay = Image.open(overlay_path).convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, Image.LANCZOS)
    merged = Image.alpha_composite(base, overlay)
    merged.convert("RGB").save(out_path, "JPEG", quality=jpeg_quality)


def composite_video(ffmpeg_path, main_path, overlay_path, out_path, crf):
    """
    Burn overlay PNG onto every frame of a video using ffmpeg.
    Uses overlay filter: scales PNG to match video dimensions.
    """
    cmd = [
        ffmpeg_path,
        "-y",                          # overwrite output
        "-i", str(main_path),          # input video
        "-i", str(overlay_path),       # input overlay PNG
        "-filter_complex",
        "[1:v]scale=iw:ih[ov];[0:v][ov]overlay=0:0",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", "fast",
        "-c:a", "copy",                # keep original audio
        "-movflags", "+faststart",
        str(out_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr


def transfer(src, dest, move):
    if move:
        shutil.move(str(src), dest)
    else:
        shutil.copy2(src, dest)


# ─── WIZARD ───────────────────────────────────────────────────────────────────

def run_wizard(exiftool_found, ffmpeg_found, pillow_ok):
    """Ask the user setup questions and return a config dict."""
    print()
    print("  ┌─────────────────────────────────────────────────────┐")
    print("  │              Setup — answer a few questions          │")
    print("  └─────────────────────────────────────────────────────┘")

    config = {}

    # Move or copy
    config["move"] = ask(
        "File handling:",
        {"1": "Move files  (saves disk space — keep your zip files as backup)",
         "2": "Copy files  (safe, but needs ~2× free disk space)"},
        default="1"
    ) == "1"

    # Photo overlays
    if pillow_ok:
        config["composite_photos"] = ask_yn(
            "Composite overlay PNGs onto photos?", default="y")
    else:
        print("\n  ⚠  Pillow not installed — photo overlay compositing disabled.")
        print("     Run:  pip install Pillow   then re-run this script.")
        config["composite_photos"] = False

    # Video overlays
    if ffmpeg_found:
        config["composite_videos"] = ask_yn(
            "Burn overlay PNGs onto videos? (slower — re-encodes video)", default="y")
        if config["composite_videos"]:
            choice = ask(
                "Video re-encode quality:",
                {k: v[0] for k, v in VIDEO_QUALITY_PRESETS.items()},
                default="2"
            )
            config["video_crf"] = VIDEO_QUALITY_PRESETS[choice][1]
    else:
        print("\n  ⚠  ffmpeg not found — video overlay compositing disabled.")
        print("     Install ffmpeg and place ffmpeg.exe next to this script to enable.")
        config["composite_videos"] = False
        config["video_crf"] = 28

    # Keep originals backup
    if config["composite_photos"] or config["composite_videos"]:
        config["keep_originals"] = ask_yn(
            "Save pre-composite originals to memories_organized/originals/?",
            default="y")
    else:
        config["keep_originals"] = False

    # JPEG quality for photo compositing
    if config["composite_photos"]:
        choice = ask(
            "Composited photo JPEG quality:",
            {"1": "High   (95 — recommended)",
             "2": "Medium (85)",
             "3": "Low    (75 — smaller files)"},
            default="1"
        )
        config["jpeg_quality"] = {"1": 95, "2": 85, "3": 75}[choice]
    else:
        config["jpeg_quality"] = 95

    # Progress interval
    config["progress_every"] = 50

    print()
    print("  ┌─────────────────────────────────────────────────────┐")
    print("  │  Settings summary                                    │")
    print("  ├─────────────────────────────────────────────────────┤")
    print(f"  │  File mode        : {'MOVE' if config['move'] else 'COPY':<37}│")
    print(f"  │  Photo overlays   : {'Yes (quality ' + str(config['jpeg_quality']) + ')' if config['composite_photos'] else 'No':<37}│")
    vov = f"Yes (CRF {config['video_crf']})" if config["composite_videos"] else "No"
    print(f"  │  Video overlays   : {vov:<37}│")
    print(f"  │  Keep originals   : {'Yes' if config['keep_originals'] else 'No':<37}│")
    print("  └─────────────────────────────────────────────────────┘")

    if not ask_yn("\n  Looks good — start processing?", default="y"):
        print("\n  Cancelled.")
        sys.exit(0)

    return config


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    start_time = time.time()

    print()
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║           Snapchat Memories Organizer  v3.0                   ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print()

    # ── Dependency checks ──
    if not PILLOW_AVAILABLE:
        print("  ⚠  Pillow not installed  (pip install Pillow)")
    else:
        print(f"  ✓  Pillow     {PILLOW_VERSION}")

    exiftool_path = find_tool("exiftool")
    if not exiftool_path:
        print("  ❌  exiftool not found!")
        print("      Windows : https://exiftool.org/ — rename to exiftool.exe")
        print("      macOS   : brew install exiftool")
        print("      Linux   : sudo apt install exiftool")
        sys.exit(1)
    print(f"  ✓  exiftool   {exiftool_path}")

    ffmpeg_path = find_tool("ffmpeg")
    if ffmpeg_path:
        print(f"  ✓  ffmpeg     {ffmpeg_path}")
    else:
        print("  ⚠  ffmpeg not found  (video overlay compositing unavailable)")
        print("      Windows : https://ffmpeg.org/download.html or: winget install ffmpeg")
        print("      macOS   : brew install ffmpeg")
        print("      Linux   : sudo apt install ffmpeg")

    # ── Find JSON ──
    json_path = find_json()
    if not json_path:
        print("\n  ❌  Could not find memories_history.json in any mydata~* folder.")
        sys.exit(1)
    print(f"  ✓  JSON       {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("Saved Media", [])
    print(f"  ✓  Entries    {len(entries)} memories in JSON")

    # ── Collect files ──
    print()
    print(f"  Scanning memories folders in {BASE_DIR} ...")
    all_files = find_memory_files(BASE_DIR) if False else _find_all(BASE_DIR)
    pairs, unpaired = build_file_map(all_files)
    date_index = build_date_index(pairs, unpaired)

    photo_pairs  = sum(1 for p in pairs.values()
                       if p["overlay"] and p["main"]
                       and p["main"].suffix.lower() in IMAGE_EXTENSIONS)
    video_pairs  = sum(1 for p in pairs.values()
                       if p["overlay"] and p["main"]
                       and p["main"].suffix.lower() in VIDEO_EXTENSIONS)
    no_overlay   = sum(1 for p in pairs.values() if not p["overlay"])

    print(f"  Total files found    : {len(all_files)}")
    print(f"  Photo + overlay pairs: {photo_pairs}")
    print(f"  Video + overlay pairs: {video_pairs}")
    print(f"  No overlay           : {no_overlay}")
    print(f"  Unpaired files       : {len(unpaired)}")

    # ── Wizard ──
    cfg = run_wizard(exiftool_path, ffmpeg_path, PILLOW_AVAILABLE)

    # ── Set up output ──
    output_dir   = BASE_DIR / OUTPUT_FOLDER_NAME
    originals_dir = output_dir / ORIGINALS_FOLDER_NAME
    output_dir.mkdir(exist_ok=True)
    if cfg["keep_originals"]:
        originals_dir.mkdir(exist_ok=True)

    print()
    print(f"  Output    : {output_dir}")
    if cfg["keep_originals"]:
        print(f"  Originals : {originals_dir}")
    print()

    # ── Process ──
    date_cursors   = {k: 0 for k in date_index}
    used_names     = set()
    matched        = 0
    photo_composited = 0
    video_composited = 0
    composite_failed = 0
    unmatched      = 0
    unmatched_list = []
    skipped        = 0
    exif_failed    = 0
    exif_failed_list = []

    total = len(entries)
    print(f"  Processing {total} entries...\n")

    for entry in entries:
        date_str     = entry.get("Date", "")
        location_str = entry.get("Location", "")

        dt = parse_date(date_str)
        if dt is None:
            skipped += 1
            continue

        date_key = dt.strftime("%Y-%m-%d")
        lat, lon = parse_location(location_str)

        items  = date_index.get(date_key, [])
        cursor = date_cursors.get(date_key, 0)

        if cursor >= len(items):
            unmatched += 1
            unmatched_list.append(date_str)
            continue

        item = items[cursor]
        date_cursors[date_key] = cursor + 1
        kind = item[0]

        dest = None

        if kind == "pair":
            _, key, pair = item
            main_file    = pair["main"]
            overlay_file = pair["overlay"]

            if main_file is None:
                # Overlay only — treat as standalone
                ext      = overlay_file.suffix
                new_name = unique_filename(dt, ext, used_names)
                dest     = output_dir / new_name
                transfer(overlay_file, dest, cfg["move"])

            elif overlay_file and cfg["composite_photos"] \
                    and main_file.suffix.lower() in IMAGE_EXTENSIONS:
                # Photo composite
                new_name = unique_filename(dt, ".jpg", used_names)
                dest     = output_dir / new_name
                try:
                    composite_photo(main_file, overlay_file, dest,
                                    cfg["jpeg_quality"])
                    photo_composited += 1
                    if cfg["keep_originals"]:
                        shutil.copy2(main_file, originals_dir / main_file.name)
                        shutil.copy2(overlay_file, originals_dir / overlay_file.name)
                    if cfg["move"]:
                        main_file.unlink()
                        overlay_file.unlink()
                except Exception as e:
                    composite_failed += 1
                    transfer(main_file, dest, cfg["move"])

            elif overlay_file and cfg["composite_videos"] \
                    and main_file.suffix.lower() in VIDEO_EXTENSIONS:
                # Video composite
                ext      = main_file.suffix
                new_name = unique_filename(dt, ext, used_names)
                dest     = output_dir / new_name
                ok, _    = composite_video(ffmpeg_path, main_file,
                                           overlay_file, dest, cfg["video_crf"])
                if ok:
                    video_composited += 1
                    if cfg["keep_originals"]:
                        shutil.copy2(main_file, originals_dir / main_file.name)
                        shutil.copy2(overlay_file, originals_dir / overlay_file.name)
                    if cfg["move"]:
                        main_file.unlink()
                        overlay_file.unlink()
                else:
                    composite_failed += 1
                    transfer(main_file, dest, cfg["move"])

            else:
                # No overlay compositing — just transfer main
                ext      = main_file.suffix
                new_name = unique_filename(dt, ext, used_names)
                dest     = output_dir / new_name
                transfer(main_file, dest, cfg["move"])

        else:
            # Unpaired file
            _, _, src_file = item
            new_name = unique_filename(dt, src_file.suffix, used_names)
            dest     = output_dir / new_name
            transfer(src_file, dest, cfg["move"])

        # Apply EXIF to output
        if dest and dest.exists():
            if not apply_exif(exiftool_path, dest, dt, lat, lon):
                exif_failed += 1
                exif_failed_list.append(dest.name)

        matched += 1
        if matched % cfg["progress_every"] == 0:
            elapsed = time.time() - start_time
            pct     = matched / total * 100
            ts      = datetime.now().strftime("%H:%M:%S")
            print(f"  {ts}  [{pct:5.1f}%]  {matched:>5} / {total}"
                  f"  |  elapsed {fmt_duration(elapsed)}"
                  f"  |  ETA ~{eta_str(matched, total, elapsed)}")

    # ── Extra files ──
    extra = 0
    for date_key, items in date_index.items():
        cursor = date_cursors.get(date_key, 0)
        for item in items[cursor:]:
            kind = item[0]
            srcs = []
            if kind == "pair":
                _, _, pair = item
                srcs = [f for f in [pair["main"], pair["overlay"]] if f]
            else:
                srcs = [item[2]]
            for src in srcs:
                dest = output_dir / src.name
                c = 2
                while dest.exists():
                    dest = output_dir / f"{src.stem}_{c}{src.suffix}"
                    c += 1
                transfer(src, dest, cfg["move"])
                extra += 1

    # ── Log ──
    elapsed_total = time.time() - start_time
    log_path = output_dir / "organizer_log.txt"
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("Snapchat Memories Organizer v3.0 — run log\n")
        log.write(f"Completed  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.write(f"Duration   : {fmt_duration(elapsed_total)}\n\n")
        log.write(f"Settings:\n")
        log.write(f"  File mode        : {'MOVE' if cfg['move'] else 'COPY'}\n")
        log.write(f"  Photo overlays   : {'Yes' if cfg['composite_photos'] else 'No'}\n")
        log.write(f"  Video overlays   : {'Yes' if cfg['composite_videos'] else 'No'}\n\n")
        log.write(f"Results:\n")
        log.write(f"  Matched & tagged     : {matched}\n")
        log.write(f"  Photo composited     : {photo_composited}\n")
        log.write(f"  Video composited     : {video_composited}\n")
        log.write(f"  Composite failures   : {composite_failed}\n")
        log.write(f"  EXIF write warnings  : {exif_failed}\n")
        log.write(f"  No JSON match        : {unmatched}\n")
        log.write(f"  Extra files copied   : {extra}\n")
        log.write(f"  Skipped (bad data)   : {skipped}\n")
        if unmatched_list:
            log.write("\n── No local file found for these JSON entries ──\n")
            for d in unmatched_list:
                log.write(f"  {d}\n")
        if exif_failed_list:
            log.write("\n── EXIF write failures ──\n")
            for n in exif_failed_list:
                log.write(f"  {n}\n")

    # ── Summary ──
    print()
    print("═" * 65)
    print(f"  ✅  All done!  ({fmt_duration(elapsed_total)})")
    print(f"      Matched & tagged     : {matched}")
    print(f"      Photos composited    : {photo_composited}")
    print(f"      Videos composited    : {video_composited}")
    print(f"      Composite failures   : {composite_failed}  (original copied as fallback)")
    print(f"      EXIF write warnings  : {exif_failed}  (files still copied, no metadata)")
    print(f"      No JSON match        : {unmatched}  (missing from local export)")
    print(f"      Extra files          : {extra}")
    print(f"      Skipped (bad data)   : {skipped}")
    print(f"      Output folder        : {output_dir}")
    if cfg["keep_originals"]:
        print(f"      Originals folder     : {originals_dir}")
    print(f"      Log file             : {log_path}")
    print("═" * 65)
    print()


def _find_all(base_dir):
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


if __name__ == "__main__":
    main()
