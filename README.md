## trollskript (photo/video sorter)

Minimal, non-destructive CLI tool that **copies** media files (images/videos/RAW) into `YYYY/MM/DD/` folders based on metadata dates (via ExifTool). Files with no date go to `unknown_date/`. Sidecars (like `.xmp`, `.aae`) are copied alongside their media. Content duplicates are skipped via SHA-256 hashing.

**Zero Python dependencies** – runs with just Python 3.9+.

### Setup

#### Linux
```bash
# Install ExifTool
sudo apt install libimage-exiftool-perl
```

#### Windows
ExifTool is **auto-downloaded** on first run. No setup needed.

### Usage

```bash
# Basic: scan current folder, sort into destination
python trollskript.py --dest /path/to/sorted

# Specify source folder
python trollskript.py --src /photos/unsorted --dest /photos/sorted

# Use custom top folder instead of year-based folders
python trollskript.py --dest ./output --top-folder "Vacation2024"

# Handle filename collisions by renaming (add suffix like _1)
python trollskript.py --dest ./output --collision-policy rename

# Copy collisions to a separate conflicts/ folder
python trollskript.py --dest ./output --collision-policy conflicts
```

#### Options
| Option | Description |
|--------|-------------|
| `--src` | Source folder to scan (default: folder containing the script) |
| `--dest` | **Required.** Destination folder for sorted media |
| `--top-folder` | Use a custom top folder name instead of year-based folders |
| `--collision-policy` | `skip` (default), `rename`, or `conflicts` |

### Windows build (.exe)
```bash
pip install pyinstaller
pyinstaller --onefile --name trollskript trollskript.py
```

Place `exiftool.exe` next to the built `.exe` (or let it auto-download on first run).

### Notes
- Reports are written to `DEST/.trollskript/`:
  - `found_files.txt`, `found_files.json`
  - `report.json`, `duplicates_skipped.json`, `collisions.json` (+ `collisions_applied.json` if applicable)
- Name collisions can optionally be copied to `DEST/conflicts/` with unique filenames.


