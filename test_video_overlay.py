"""
Video Overlay Test
------------------
Standalone version of the video test built into the main script.
Finds the first video+overlay pair, probes dimensions, and runs
a test composite so you can verify it looks correct before the
full run.

Run from your snapchat folder:
    python test_video_overlay.py
"""

import json
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent


def find_tool(name):
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


def get_video_info(ffprobe_path, video_path):
    """
    Returns (stored_w, stored_h, display_w, display_h, rotation).
    Uses two ffprobe queries:
      1. stream width/height + rotate tag
      2. stream_side_data rotation (displaymatrix)
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
        print(f"  ffprobe error: {r1.stderr[:200]}")
        return None, None, None, None, 0

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


def find_first_video_pair():
    for folder in sorted(BASE_DIR.glob("mydata~*")):
        memories = folder / "memories"
        if not memories.is_dir():
            continue
        for f in sorted(memories.iterdir()):
            if f.stem.endswith("-main") and f.suffix.lower() in {".mp4", ".mov"}:
                overlay = f.with_name(f.stem[:-5] + "-overlay.png")
                if overlay.exists():
                    return f, overlay
    return None, None


def main():
    print()
    print("=" * 60)
    print("  Video Overlay Test")
    print("=" * 60)
    print()

    ffmpeg_path  = find_tool("ffmpeg")
    ffprobe_path = find_tool("ffprobe")

    if not ffmpeg_path:
        print("❌  ffmpeg not found")
        print("    Windows : https://ffmpeg.org/download.html or: winget install ffmpeg")
        print("    macOS   : brew install ffmpeg")
        print("    Linux   : sudo apt install ffmpeg")
        return
    if not ffprobe_path:
        ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")

    print(f"✓  ffmpeg  : {ffmpeg_path}")
    print(f"✓  ffprobe : {ffprobe_path}")

    video, overlay = find_first_video_pair()
    if not video:
        print("\n❌  No video+overlay pair found in any mydata~* folder.")
        return

    print(f"\n✓  Video   : {video.name}")
    print(f"✓  Overlay : {overlay.name}")

    print("\n── Video info ──")
    sw, sh, dw, dh, rotate = get_video_info(ffprobe_path, video)
    if sw is None:
        print("❌  Could not read video info")
        return

    print(f"  Stored dimensions  : {sw}x{sh}")
    print(f"  Rotation tag       : {rotate}°")
    print(f"  Display dimensions : {dw}x{dh}  ← overlay scaled to this")

    # Scale overlay to display dimensions — ffmpeg auto-rotates output
    filter_str = f"[1:v]scale={dw}:{dh}[ov];[0:v][ov]overlay=0:0"
    print(f"\n── Filter ──")
    print(f"  {filter_str}")

    out = BASE_DIR / "video_overlay_test_output.mp4"
    cmd = [
        ffmpeg_path, "-y",
        "-i", str(video),
        "-i", str(overlay),
        "-filter_complex", filter_str,
        "-c:v", "libx264",
        "-crf", "28",
        "-preset", "fast",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out)
    ]

    print(f"\n── Running ffmpeg ──\n")
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Print relevant lines only
    for line in result.stderr.splitlines():
        if any(x in line.lower() for x in ["error", "invalid", "warning",
                                             "input #", "output #",
                                             "stream #0:0:", "frame=",
                                             "lsize=", "speed="]):
            print(f"  {line}")

    print()
    if result.returncode == 0 and out.exists():
        size_kb = out.stat().st_size / 1024
        print(f"✅  SUCCESS — {out.name}  ({size_kb:.1f} KB)")
        if size_kb < 100:
            print("⚠   Very small — likely no video frames. Check output above.")
        else:
            print(f"   Open {out.name} and verify:")
            print("     • Video plays correctly (portrait orientation)")
            print("     • Overlay text is visible and correctly positioned")
            print("   If it looks good, you're ready to run the main script!")
    else:
        print(f"❌  FAILED (rc={result.returncode})")
        print("\n── Full ffmpeg output ──")
        for line in result.stderr.splitlines():
            print(f"  {line}")
    print()


if __name__ == "__main__":
    main()
