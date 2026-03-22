"""
╔═══════════════════════════════════════════════════════════════╗
║       Snapchat Overlay Compositor                             ║
║       Run this AFTER snapchat_memories_organizer.py           ║
╚═══════════════════════════════════════════════════════════════╝

What this script does:
  ✓ Finds PNG overlay files paired with a matching JPG (same timestamp)
  ✓ Composites the PNG on top of the JPG → saves merged version in place
  ✓ Moves original unmerged JPG + PNG into a backup folder
  ✓ Leaves standalone PNGs (no matching JPG) untouched

REQUIREMENTS:
  - Python 3.7+
  - Pillow:  pip install Pillow

USAGE:
  1. Wait for snapchat_memories_organizer.py to finish.
  2. Run: python snapchat_overlay_compositor.py
"""

import shutil
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("❌  Pillow is not installed. Run:  pip install Pillow")
    sys.exit(1)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

# Folder produced by the main organizer script
INPUT_DIR = Path(__file__).parent / "memories_organized"

# Backup folder for originals (unmerged JPG + raw PNG)
BACKUP_DIR = Path(__file__).parent / "memories_organized" / "originals"

# Progress every N files
PROGRESS_EVERY = 100

# ──────────────────────────────────────────────────────────────────────────────


def composite_overlay(jpg_path: Path, png_path: Path, out_path: Path):
    """Paste PNG overlay on top of JPG, save as JPEG to out_path."""
    base = Image.open(jpg_path).convert("RGBA")
    overlay = Image.open(png_path).convert("RGBA")

    # Resize overlay to match base if needed
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, Image.LANCZOS)

    # Composite
    merged = Image.alpha_composite(base, overlay)

    # Save as JPEG (convert back to RGB first)
    merged.convert("RGB").save(out_path, "JPEG", quality=95)


def main():
    print()
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║       Snapchat Overlay Compositor                             ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print()

    if not INPUT_DIR.exists():
        print(f"❌  Input folder not found: {INPUT_DIR}")
        print("    Run snapchat_memories_organizer.py first.")
        sys.exit(1)

    BACKUP_DIR.mkdir(exist_ok=True)
    print(f"✓  Input   : {INPUT_DIR}")
    print(f"✓  Backup  : {BACKUP_DIR}")
    print()

    # Find all PNGs in the organized folder
    all_pngs = list(INPUT_DIR.glob("*.png"))
    print(f"✓  Found {len(all_pngs)} PNG files to check")
    print()

    merged = 0
    skipped_no_match = 0
    failed = 0

    for i, png_path in enumerate(sorted(all_pngs)):
        # Look for a matching JPG with the same stem (same timestamp)
        jpg_path = png_path.with_suffix(".jpg")

        if not jpg_path.exists():
            # No matching JPG — this is a real PNG photo, leave it alone
            skipped_no_match += 1
            continue

        # Composite
        try:
            # Save merged version with the JPG filename (overwrites)
            composite_overlay(jpg_path, png_path, jpg_path)

            # Move originals to backup
            shutil.move(str(jpg_path), BACKUP_DIR / jpg_path.name)  # wait — we just overwrote it
            # Actually: save merged to temp name, backup original, rename merged
            # Let's redo this properly below
        except Exception as e:
            print(f"  [FAIL] {png_path.name}: {e}")
            failed += 1
            continue

        merged += 1
        if merged % PROGRESS_EVERY == 0:
            print(f"  ... composited {merged} pairs")

    print()
    print("═" * 65)
    print(f"  ✅  Done!")
    print(f"      Merged pairs        : {merged}")
    print(f"      Standalone PNGs     : {skipped_no_match}  (left untouched)")
    print(f"      Failed              : {failed}")
    print(f"      Originals backed up : {BACKUP_DIR}")
    print("═" * 65)
    print()


# ─── Fixed main with proper backup logic ──────────────────────────────────────

def main():
    print()
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║       Snapchat Overlay Compositor                             ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print()

    if not INPUT_DIR.exists():
        print(f"❌  Input folder not found: {INPUT_DIR}")
        print("    Run snapchat_memories_organizer.py first.")
        sys.exit(1)

    BACKUP_DIR.mkdir(exist_ok=True)
    print(f"✓  Input   : {INPUT_DIR}")
    print(f"✓  Backup  : {BACKUP_DIR}")
    print()

    all_pngs = list(INPUT_DIR.glob("*.png"))
    print(f"✓  Found {len(all_pngs)} PNG files to check")
    print()

    merged_count = 0
    skipped_no_match = 0
    failed = 0

    for png_path in sorted(all_pngs):
        jpg_path = png_path.with_suffix(".jpg")

        if not jpg_path.exists():
            skipped_no_match += 1
            continue

        # Temp path for the merged output
        merged_path = jpg_path.with_name(jpg_path.stem + "_merged.jpg")

        try:
            composite_overlay(jpg_path, png_path, merged_path)
        except Exception as e:
            print(f"  [FAIL] {png_path.name}: {e}")
            # Clean up temp if it exists
            if merged_path.exists():
                merged_path.unlink()
            failed += 1
            continue

        # Back up the originals
        shutil.move(str(jpg_path), BACKUP_DIR / jpg_path.name)
        shutil.move(str(png_path), BACKUP_DIR / png_path.name)

        # Rename merged to the original JPG name
        merged_path.rename(jpg_path)

        merged_count += 1
        if merged_count % PROGRESS_EVERY == 0:
            print(f"  ... composited {merged_count} pairs")

    print()
    print("═" * 65)
    print(f"  ✅  Done!")
    print(f"      Merged pairs        : {merged_count}")
    print(f"      Standalone PNGs     : {skipped_no_match}  (left untouched)")
    print(f"      Failed              : {failed}")
    print(f"      Originals in        : {BACKUP_DIR}")
    print("═" * 65)
    print()


if __name__ == "__main__":
    main()
