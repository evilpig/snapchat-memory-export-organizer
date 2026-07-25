"""
╔═══════════════════════════════════════════════════════════════╗
║           Snapchat → Immich Uploader                          ║
║           Run AFTER snapchat_memories_organizer.py            ║
╚═══════════════════════════════════════════════════════════════╝

What this script does:
  ✓ Uploads all files from memories_organized/ to your Immich server
  ✓ Creates one album per year: "Snapchat 2016", "Snapchat 2017", etc.
  ✓ Skips files already uploaded (Immich deduplication by hash)
  ✓ Shows progress with ETA
  ✓ Writes a log of any failures

REQUIREMENTS:
  - Python 3.7+
  - requests:  pip install requests

SETUP:
  1. In Immich, go to Account Settings → API Keys → New API Key
     Give it these permissions: asset.upload, album.create, album.read,
     album.update (or just use a full-access key)
  2. Fill in IMMICH_URL and IMMICH_API_KEY below
  3. Run: python snapchat_immich_upload.py
"""

import hashlib
import json
import mimetypes
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("❌  requests is not installed. Run:  pip install requests")
    sys.exit(1)


# ─── CONFIGURATION ────────────────────────────────────────────────────────────

# Your Immich server URL (no trailing slash)
IMMICH_URL = "http://your-immich-server:2283"

# Your Immich API key (Account Settings → API Keys)
IMMICH_API_KEY = "your-api-key-here"

# Folder to upload from (output of snapchat_memories_organizer.py)
UPLOAD_DIR = Path(__file__).parent / "memories_organized"

# Album name prefix — will become "Snapchat 2016", "Snapchat 2017", etc.
ALBUM_PREFIX = "Snapchat"

# How many files to add to an album per API call (keep under 1000)
ALBUM_BATCH_SIZE = 100

# Progress update every N files
PROGRESS_EVERY = 50

# File extensions to upload
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".mp4", ".mov", ".gif", ".heic", ".webp"}

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


def make_headers():
    return {
        "x-api-key": IMMICH_API_KEY,
        "Accept": "application/json",
    }


def check_server():
    """Verify we can reach the Immich server and the API key works."""
    try:
        r = requests.get(
            f"{IMMICH_URL}/api/users/me",
            headers=make_headers(),
            timeout=10
        )
        if r.status_code == 200:
            user = r.json()
            return True, user.get("name", user.get("email", "unknown"))
        elif r.status_code == 401:
            return False, "Invalid API key"
        else:
            return False, f"HTTP {r.status_code}"
    except requests.exceptions.ConnectionError:
        return False, f"Cannot connect to {IMMICH_URL}"
    except Exception as e:
        return False, str(e)


def get_file_hash(file_path):
    """SHA1 hash of file contents (Immich uses SHA1 for dedup)."""
    sha1 = hashlib.sha1()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha1.update(chunk)
    return sha1.hexdigest()


def get_or_create_album(name, existing_albums):
    """Return album ID for name, creating it if it doesn't exist."""
    if name in existing_albums:
        return existing_albums[name]

    r = requests.post(
        f"{IMMICH_URL}/api/albums",
        headers={**make_headers(), "Content-Type": "application/json"},
        json={"albumName": name, "description": "Imported from Snapchat Memories"},
        timeout=10
    )
    r.raise_for_status()
    album_id = r.json()["id"]
    existing_albums[name] = album_id
    print(f"  📁  Created album: {name}")
    return album_id


def fetch_existing_albums():
    """Fetch all existing albums and return dict: name → id."""
    r = requests.get(
        f"{IMMICH_URL}/api/albums",
        headers=make_headers(),
        timeout=15
    )
    r.raise_for_status()
    return {a["albumName"]: a["id"] for a in r.json()}


def upload_file(file_path, dt):
    """
    Upload a single file to Immich.
    Returns (asset_id, is_duplicate) or raises on error.
    """
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type is None:
        ext = file_path.suffix.lower()
        mime_type = "video/mp4" if ext in {".mp4", ".mov"} else "image/jpeg"

    created_at = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z") if dt else \
        datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    modified_at = created_at

    with open(file_path, "rb") as f:
        response = requests.post(
            f"{IMMICH_URL}/api/assets",
            headers={"x-api-key": IMMICH_API_KEY},
            files={"assetData": (file_path.name, f, mime_type)},
            data={
                "deviceAssetId": file_path.name,
                "deviceId":      "snapchat-memories-importer",
                "fileCreatedAt": created_at,
                "fileModifiedAt": modified_at,
                "isFavorite":    "false",
            },
            timeout=120
        )

    response.raise_for_status()
    result = response.json()
    asset_id = result.get("id")
    is_duplicate = result.get("status") == "duplicate"
    return asset_id, is_duplicate


def add_to_album(album_id, asset_ids):
    """Add a batch of asset IDs to an album."""
    r = requests.put(
        f"{IMMICH_URL}/api/albums/{album_id}/assets",
        headers={**make_headers(), "Content-Type": "application/json"},
        json={"ids": asset_ids},
        timeout=30
    )
    r.raise_for_status()
    return r.json()


def extract_year_from_filename(filename):
    """Extract year from YYYY-MM-DD_HHMMSS.ext filename."""
    m = re.match(r"(\d{4})-\d{2}-\d{2}", filename)
    if m:
        year = int(m.group(1))
        if 2000 <= year <= 2100:
            return year
    return None


def extract_dt_from_filename(filename):
    """Parse datetime from YYYY-MM-DD_HHMMSS.ext filename."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{6})", filename)
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H%M%S"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def main():
    start_time = time.time()

    print()
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║           Snapchat → Immich Uploader                          ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print()

    # Validate config
    if "your-immich-server" in IMMICH_URL or "your-api-key-here" in IMMICH_API_KEY:
        print("❌  Please set IMMICH_URL and IMMICH_API_KEY in the script configuration.")
        sys.exit(1)

    # Check server
    ok, info = check_server()
    if not ok:
        print(f"❌  Could not connect to Immich: {info}")
        print(f"    URL: {IMMICH_URL}")
        sys.exit(1)
    print(f"✓  Immich server  :  {IMMICH_URL}")
    print(f"✓  Logged in as   :  {info}")

    # Check upload dir
    if not UPLOAD_DIR.exists():
        print(f"\n❌  Upload folder not found: {UPLOAD_DIR}")
        print("    Run snapchat_memories_organizer.py first.")
        sys.exit(1)

    # Collect files
    files = sorted([
        f for f in UPLOAD_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ])

    if not files:
        print(f"\n❌  No supported files found in {UPLOAD_DIR}")
        sys.exit(1)

    print(f"✓  Files to upload :  {len(files)}")
    print()

    # Load existing albums
    print("✓  Fetching existing Immich albums...")
    existing_albums = fetch_existing_albums()
    snapchat_albums = {k: v for k, v in existing_albums.items() if k.startswith(ALBUM_PREFIX)}
    if snapchat_albums:
        print(f"   Found existing Snapchat albums: {', '.join(sorted(snapchat_albums.keys()))}")
    print()

    # Process files
    # year → list of asset_ids to add to album
    year_assets = {}

    uploaded = 0
    duplicates = 0
    failed = 0
    failed_list = []

    total = len(files)
    print(f"Uploading {total} files...\n")

    for i, file_path in enumerate(files):
        year = extract_year_from_filename(file_path.name)
        dt = extract_dt_from_filename(file_path.name)

        try:
            asset_id, is_duplicate = upload_file(file_path, dt)

            if asset_id:
                if year:
                    year_assets.setdefault(year, []).append(asset_id)

                if is_duplicate:
                    duplicates += 1
                else:
                    uploaded += 1
            else:
                failed += 1
                failed_list.append(file_path.name)

        except Exception as e:
            failed += 1
            failed_list.append(f"{file_path.name}  ({e})")

        done = uploaded + duplicates + failed
        if done % PROGRESS_EVERY == 0 and done > 0:
            elapsed = time.time() - start_time
            pct = done / total * 100
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  {ts}  [{pct:5.1f}%]  {done:>5} / {total}"
                  f"  |  ↑ {uploaded} new  ⟳ {duplicates} dupes  ✗ {failed} failed"
                  f"  |  ETA ~{eta_str(done, total, elapsed)}")

    # Assign assets to per-year albums
    print()
    print("✓  Creating/updating year albums...")
    album_errors = 0
    for year in sorted(year_assets.keys()):
        album_name = f"{ALBUM_PREFIX} {year}"
        asset_ids = year_assets[year]
        try:
            album_id = get_or_create_album(album_name, existing_albums)
            # Add in batches
            for batch_start in range(0, len(asset_ids), ALBUM_BATCH_SIZE):
                batch = asset_ids[batch_start:batch_start + ALBUM_BATCH_SIZE]
                add_to_album(album_id, batch)
            print(f"  ✓  {album_name}  →  {len(asset_ids)} assets")
        except Exception as e:
            print(f"  ✗  {album_name}  →  ERROR: {e}")
            album_errors += 1

    # Write log
    elapsed_total = time.time() - start_time
    log_path = UPLOAD_DIR / "immich_upload_log.txt"
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("Snapchat → Immich Upload Log\n")
        log.write(f"Completed  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.write(f"Duration   : {fmt_duration(elapsed_total)}\n\n")
        log.write(f"Uploaded (new)  : {uploaded}\n")
        log.write(f"Duplicates      : {duplicates}\n")
        log.write(f"Failed          : {failed}\n")
        log.write(f"Album errors    : {album_errors}\n\n")
        log.write("Albums created/updated:\n")
        for year in sorted(year_assets.keys()):
            log.write(f"  {ALBUM_PREFIX} {year}  →  {len(year_assets[year])} assets\n")
        if failed_list:
            log.write("\nFailed files:\n")
            for name in failed_list:
                log.write(f"  {name}\n")

    # Summary
    print()
    print("═" * 65)
    print(f"  ✅  All done!  ({fmt_duration(elapsed_total)})")
    print(f"      Uploaded (new)  : {uploaded}")
    print(f"      Duplicates      : {duplicates}  (already in Immich, skipped)")
    print(f"      Failed          : {failed}")
    print(f"      Album errors    : {album_errors}")
    print(f"      Log file        : {log_path}")
    print("═" * 65)
    print()


if __name__ == "__main__":
    main()
