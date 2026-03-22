"""
╔═══════════════════════════════════════════════════════════════╗
║           Snapchat Memories Organizer  v3.1                   ║
╚═══════════════════════════════════════════════════════════════╝

What this script does:
  ✓ Finds all your extracted Snapchat export folders automatically
  ✓ Reads memories_history.json for date/time and GPS metadata
  ✓ Embeds EXIF date and GPS coordinates into every file
  ✓ Renames files to clean YYYY-MM-DD_HHMMSS format
  ✓ Composites overlay PNGs onto photos (Pillow)
  ✓ Burns overlay PNGs onto videos (ffmpeg) — handles rotation correctly
  ✓ Consolidates everything into a single output folder
  ✓ Interactive setup wizard with optional video test before full run
  ✓ Moves files by default to save disk space (zips are your backup)

REQUIREMENTS:
  - Python 3.7+

  - Pillow       pip install Pillow
    Used for: compositing overlay PNGs onto photos

  - exiftool     https://exiftool.org/
    Windows:  download, rename to exiftool.exe, place next to this script
              OR add to PATH
    macOS:    brew install exiftool
    Linux:    sudo apt install exiftool

  - ffmpeg + ffprobe    https://ffmpeg.org/download.html
    Windows:  download, place ffmpeg.exe + ffprobe.exe next to this script
              OR add to PATH  OR: winget install ffmpeg
    macOS:    brew install ffmpeg
    Linux:    sudo apt install ffmpeg
    Used for: burning overlay PNGs onto videos (optional)

HOW TO USE:
  1. Export your Memories from Snapchat:
       Snapchat → Profile → Settings → Privacy Controls → My Data
       Select "Memories" and request the data export.
  2. Download and extract ALL zip files Snapchat sends you.
     Put all the extracted folders into the same parent folder.
  3. Place this script in that folder:

       snapchat/
         mydata~1234567890/               ← extracted zip 1
         mydata~1234567890-2/             ← extracted zip 2 (if any)
         snapchat_memories_organizer.py   ← this script
         exiftool.exe                     ← Windows, if not on PATH
         ffmpeg.exe                       ← Windows, if not on PATH
         ffprobe.exe                      ← Windows, if not on PATH

  4. Run:  python snapchat_memories_organizer.py
     Answer the setup questions — optionally run a video test first.

  5. Results:
       memories_organized/           ← renamed, tagged, composited files
       memories_organized/originals/ ← pre-composite originals (if kept)
       memories_organized/organizer_log.txt

NOTES:
  - Original source files are never modified; by default they are moved
    (not copied) into memories_organized/. Your zip files are your backup.
  - The script always reads the full JSON regardless of how many zips are
    extracted — "No JSON match" entries are normal when testing one zip.
  - Videos that can't be probed for dimensions will be copied as-is.
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
    PILLOW_VERSION   = Image.__version__
except ImportError:
    PILLOW_AVAILABLE = False
    PILLOW_VERSION   = "not installed"


# ─── CONSTANTS ────────────────────────────────────────────────────────────────

BASE_DIR             = Path(__file__).parent
OUTPUT_FOLDER_NAME   = "memories_organized"
ORIGINALS_FOLDER_NAME = "originals"
VIDEO_EXTENSIONS     = {".mp4", ".mov"}
IMAGE_EXTENSIONS     = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS

VIDEO_QUALITY_PRESETS = {
    "1": ("Fast / larger file  (CRF 23, good for archiving)", 23),
    "2": ("Balanced            (CRF 28, recommended)",        28),
    "3": ("Small / lower quality (CRF 33, saves space)",      33),
}


# ─── HELPERS ──────────────────────────────────────────────────────────────────

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
    # exiftool uses -ver; ffmpeg/ffprobe use -version
    flag = "-ver" if name == "exiftool" else "-version"
    candidates = [name, str(BASE_DIR / f"{name}.exe"), str(BASE_DIR / name)]
    for c in candidates:
        try:
            r = subprocess.run([c, flag], capture_output=True, text=True)
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


def _find_all(base_dir):
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
    main_files    = {}
    overlay_files = {}
    unpaired      = []
    for f in all_files:
        stem = f.stem
        if stem.endswith("-main"):
            main_files[stem[:-5]] = f
        elif stem.endswith("-overlay"):
            overlay_files[stem[:-8]] = f
        else:
            unpaired.append(f)
    all_keys = set(main_files) | set(overlay_files)
    pairs = {key: {"main": main_files.get(key), "overlay": overlay_files.get(key)}
             for key in all_keys}
    return pairs, unpaired


def build_date_index(pairs, unpaired):
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


# ─── VIDEO INFO ───────────────────────────────────────────────────────────────

def get_video_info(ffprobe_path, video_path):
    """
    Returns (stored_w, stored_h, display_w, display_h, rotation).
    Uses two separate ffprobe queries to reliably detect rotation from
    both stream tags and stream_side_data (displaymatrix).
    Handles negative rotation values (-90 etc).
    """
    cmd_stream = [ffprobe_path, "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height:stream_tags=rotate",
                  "-of", "json", str(video_path)]
    cmd_side   = [ffprobe_path, "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream_side_data=rotation",
                  "-of", "json", str(video_path)]

    r1 = subprocess.run(cmd_stream, capture_output=True, text=True)
    r2 = subprocess.run(cmd_side,   capture_output=True, text=True)

    if r1.returncode != 0:
        return None, None, None, None, 0
    try:
        d1     = json.loads(r1.stdout)
        stream = d1.get("streams", [{}])[0]
        sw     = stream.get("width")
        sh     = stream.get("height")
        rotate = int(stream.get("tags", {}).get("rotate", 0))

        if rotate == 0 and r2.returncode == 0:
            d2 = json.loads(r2.stdout)
            for sd in d2.get("streams", [{}])[0].get("side_data_list", []):
                rot = sd.get("rotation")
                if rot is not None:
                    rotate = abs(int(float(rot)))
                    break

        dw, dh = (sh, sw) if rotate in (90, 270) else (sw, sh)
        return sw, sh, dw, dh, rotate
    except Exception:
        return None, None, None, None, 0


# ─── COMPOSITING ──────────────────────────────────────────────────────────────

def composite_photo(main_path, overlay_path, out_path, jpeg_quality):
    base    = Image.open(main_path).convert("RGBA")
    overlay = Image.open(overlay_path).convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, Image.LANCZOS)
    Image.alpha_composite(base, overlay).convert("RGB").save(
        out_path, "JPEG", quality=jpeg_quality)


def composite_video(ffmpeg_path, main_path, overlay_path, out_path, crf):
    """
    Burns overlay PNG onto every frame of a video.
    ffmpeg auto-applies displaymatrix rotation during encode so the output
    is always in display orientation. We scale the overlay to display
    dimensions (dw x dh) so it aligns correctly.
    """
    ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")
    sw, sh, dw, dh, rotate = get_video_info(ffprobe_path, main_path)
    if sw is None:
        return False, "Could not determine video dimensions"

    filter_str = f"[1:v]scale={dw}:{dh}[ov];[0:v][ov]overlay=0:0"

    cmd = [
        ffmpeg_path, "-y",
        "-i", str(main_path),
        "-i", str(overlay_path),
        "-filter_complex", filter_str,
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", "fast",
        "-c:a", "copy",
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


# ─── VIDEO TEST ───────────────────────────────────────────────────────────────

def run_video_test(ffmpeg_path):
    """
    Find the first video+overlay pair and do a test composite.
    Shows the output path so the user can verify it looks correct.
    Returns True if test passed (or user skips), False to abort.
    """
    ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")

    # Find first video+overlay pair
    test_main = test_overlay = None
    for folder in sorted(BASE_DIR.glob("mydata~*")):
        mem = folder / "memories"
        if not mem.is_dir():
            continue
        for f in sorted(mem.iterdir()):
            if f.stem.endswith("-main") and f.suffix.lower() in VIDEO_EXTENSIONS:
                ov = f.with_name(f.stem[:-5] + "-overlay.png")
                if ov.exists():
                    test_main, test_overlay = f, ov
                    break
        if test_main:
            break

    if not test_main:
        print("  ⚠  No video+overlay pair found to test — skipping video test.")
        return True

    print(f"\n  Testing with: {test_main.name}")

    sw, sh, dw, dh, rotate = get_video_info(ffprobe_path, test_main)
    if sw is None:
        print("  ❌  Could not probe video dimensions. Check ffprobe is installed.")
        return False

    print(f"  Video: stored {sw}x{sh}, display {dw}x{dh}, rotation {rotate}°")

    out_path = BASE_DIR / "video_overlay_test_output.mp4"
    ok, err  = composite_video(ffmpeg_path, test_main, test_overlay, out_path, crf=28)

    if ok and out_path.exists() and out_path.stat().st_size > 50_000:
        print(f"  ✅  Test output saved to: {out_path.name}")
        print(f"      Open it and verify the overlay text is correctly positioned.")
        return ask_yn("  Does the test video look correct?", default="y")
    else:
        print(f"  ❌  Video test failed.")
        if err:
            for line in err.splitlines()[-5:]:
                if any(x in line.lower() for x in ["error", "invalid"]):
                    print(f"      ffmpeg: {line.strip()}")
        return False


# ─── WIZARD ───────────────────────────────────────────────────────────────────

def run_wizard(exiftool_found, ffmpeg_path, pillow_ok):
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
    if ffmpeg_path:
        config["composite_videos"] = ask_yn(
            "Burn overlay PNGs onto videos? (slower — re-encodes video)", default="y")
        if config["composite_videos"]:
            choice = ask(
                "Video re-encode quality:",
                {k: v[0] for k, v in VIDEO_QUALITY_PRESETS.items()},
                default="2"
            )
            config["video_crf"] = VIDEO_QUALITY_PRESETS[choice][1]

            # Optional video test
            if ask_yn("  Run a quick video overlay test before the full run?", default="y"):
                print()
                passed = run_video_test(ffmpeg_path)
                if not passed:
                    print("\n  ❌  Video test failed or output looked wrong.")
                    print("      Fix the issue and re-run, or choose not to process video overlays.")
                    sys.exit(1)
    else:
        print("\n  ⚠  ffmpeg not found — video overlay compositing disabled.")
        config["composite_videos"] = False
        config["video_crf"] = 28

    # Keep originals
    if config["composite_photos"] or config["composite_videos"]:
        config["keep_originals"] = ask_yn(
            "Save pre-composite originals to memories_organized/originals/?",
            default="y")
    else:
        config["keep_originals"] = False

    # JPEG quality
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
    print("║           Snapchat Memories Organizer  v3.1                   ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print()

    # Dependency checks
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

    # Find JSON
    json_path = find_json()
    if not json_path:
        print("\n  ❌  Could not find memories_history.json in any mydata~* folder.")
        sys.exit(1)
    print(f"  ✓  JSON       {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("Saved Media", [])
    print(f"  ✓  Entries    {len(entries)} memories in JSON")

    # Collect files
    print()
    print(f"  Scanning memories folders in {BASE_DIR} ...")
    all_files = _find_all(BASE_DIR)
    pairs, unpaired = build_file_map(all_files)
    date_index = build_date_index(pairs, unpaired)

    photo_pairs = sum(1 for p in pairs.values()
                      if p["overlay"] and p["main"]
                      and p["main"].suffix.lower() in IMAGE_EXTENSIONS)
    video_pairs = sum(1 for p in pairs.values()
                      if p["overlay"] and p["main"]
                      and p["main"].suffix.lower() in VIDEO_EXTENSIONS)
    no_overlay  = sum(1 for p in pairs.values() if not p["overlay"])

    print(f"  Total files found    : {len(all_files)}")
    print(f"  Photo + overlay pairs: {photo_pairs}")
    print(f"  Video + overlay pairs: {video_pairs}")
    print(f"  No overlay           : {no_overlay}")
    print(f"  Unpaired files       : {len(unpaired)}")

    if not all_files:
        print("\n  ❌  No files found in any mydata~*/memories/ folder.")
        sys.exit(1)

    # Wizard
    cfg = run_wizard(exiftool_path, ffmpeg_path, PILLOW_AVAILABLE)

    # Set up output dirs
    output_dir    = BASE_DIR / OUTPUT_FOLDER_NAME
    originals_dir = output_dir / ORIGINALS_FOLDER_NAME
    output_dir.mkdir(exist_ok=True)
    if cfg["keep_originals"]:
        originals_dir.mkdir(exist_ok=True)

    print()
    print(f"  Output    : {output_dir}")
    if cfg["keep_originals"]:
        print(f"  Originals : {originals_dir}")
    print()

    # Process
    date_cursors     = {k: 0 for k in date_index}
    used_names       = set()
    matched          = 0
    photo_composited = 0
    video_composited = 0
    composite_failed = 0
    unmatched        = 0
    unmatched_list   = []
    skipped          = 0
    exif_failed      = 0
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
                ext      = overlay_file.suffix
                new_name = unique_filename(dt, ext, used_names)
                dest     = output_dir / new_name
                transfer(overlay_file, dest, cfg["move"])

            elif overlay_file and cfg["composite_photos"] \
                    and main_file.suffix.lower() in IMAGE_EXTENSIONS:
                new_name = unique_filename(dt, ".jpg", used_names)
                dest     = output_dir / new_name
                try:
                    composite_photo(main_file, overlay_file, dest, cfg["jpeg_quality"])
                    photo_composited += 1
                    if cfg["keep_originals"]:
                        shutil.copy2(main_file,    originals_dir / main_file.name)
                        shutil.copy2(overlay_file, originals_dir / overlay_file.name)
                    if cfg["move"]:
                        main_file.unlink()
                        overlay_file.unlink()
                except Exception:
                    composite_failed += 1
                    transfer(main_file, dest, cfg["move"])

            elif overlay_file and cfg["composite_videos"] \
                    and main_file.suffix.lower() in VIDEO_EXTENSIONS:
                ext      = main_file.suffix
                new_name = unique_filename(dt, ext, used_names)
                dest     = output_dir / new_name
                ok, err  = composite_video(ffmpeg_path, main_file,
                                           overlay_file, dest, cfg["video_crf"])
                if ok:
                    video_composited += 1
                    if cfg["keep_originals"]:
                        shutil.copy2(main_file,    originals_dir / main_file.name)
                        shutil.copy2(overlay_file, originals_dir / overlay_file.name)
                    if cfg["move"]:
                        main_file.unlink()
                        overlay_file.unlink()
                else:
                    composite_failed += 1
                    if err:
                        relevant = [l for l in err.splitlines()
                                    if any(x in l.lower() for x in
                                           ["error", "invalid", "failed"])]
                        if relevant:
                            print(f"\n  [VIDEO FAIL] {main_file.name}")
                            for line in relevant[-3:]:
                                print(f"    {line.strip()}")
                    transfer(main_file, dest, cfg["move"])

            else:
                ext      = main_file.suffix
                new_name = unique_filename(dt, ext, used_names)
                dest     = output_dir / new_name
                transfer(main_file, dest, cfg["move"])

        else:
            _, _, src_file = item
            new_name = unique_filename(dt, src_file.suffix, used_names)
            dest     = output_dir / new_name
            transfer(src_file, dest, cfg["move"])

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

    # Extra files
    extra = 0
    for date_key, items in date_index.items():
        cursor = date_cursors.get(date_key, 0)
        for item in items[cursor:]:
            srcs = []
            if item[0] == "pair":
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

    # Log
    elapsed_total = time.time() - start_time
    log_path = output_dir / "organizer_log.txt"
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("Snapchat Memories Organizer v3.1 — run log\n")
        log.write(f"Completed  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.write(f"Duration   : {fmt_duration(elapsed_total)}\n\n")
        log.write(f"Settings:\n")
        log.write(f"  File mode        : {'MOVE' if cfg['move'] else 'COPY'}\n")
        log.write(f"  Photo overlays   : {'Yes' if cfg['composite_photos'] else 'No'}\n")
        log.write(f"  Video overlays   : {'Yes' if cfg['composite_videos'] else 'No'}\n\n")
        log.write(f"Results:\n")
        log.write(f"  Matched & tagged     : {matched}\n")
        log.write(f"  Photos composited    : {photo_composited}\n")
        log.write(f"  Videos composited    : {video_composited}\n")
        log.write(f"  Composite failures   : {composite_failed}\n")
        log.write(f"  EXIF write warnings  : {exif_failed}\n")
        log.write(f"  No JSON match        : {unmatched}\n")
        log.write(f"  Extra files          : {extra}\n")
        log.write(f"  Skipped (bad data)   : {skipped}\n")
        if unmatched_list:
            log.write("\n── No local file found for these JSON entries ──\n")
            for d in unmatched_list:
                log.write(f"  {d}\n")
        if exif_failed_list:
            log.write("\n── EXIF write failures ──\n")
            for n in exif_failed_list:
                log.write(f"  {n}\n")

    # Summary
    print()
    print("═" * 65)
    print(f"  ✅  All done!  ({fmt_duration(elapsed_total)})")
    print(f"      Matched & tagged     : {matched}")
    print(f"      Photos composited    : {photo_composited}")
    print(f"      Videos composited    : {video_composited}")
    print(f"      Composite failures   : {composite_failed}  (original copied as fallback)")
    print(f"      EXIF write warnings  : {exif_failed}")
    print(f"      No JSON match        : {unmatched}  (missing from local export)")
    print(f"      Extra files          : {extra}")
    print(f"      Skipped (bad data)   : {skipped}")
    print(f"      Output folder        : {output_dir}")
    if cfg["keep_originals"]:
        print(f"      Originals folder     : {originals_dir}")
    print(f"      Log file             : {log_path}")
    print("═" * 65)
    print()


if __name__ == "__main__":
    main()
