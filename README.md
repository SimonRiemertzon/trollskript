## trollskript (photo/video sorter)

Minimal, non-destructive sorter that **copies** media files (images/videos/RAW) into `YYYY/MM/DD/` folders based on metadata dates (via ExifTool). Files with no date go to `unknown_date/`. Sidecars (like `.xmp`, `.aae`) are copied alongside their media. Content duplicates are skipped via **BLAKE3**.

### Dev setup (Linux)
- Install ExifTool (`exiftool` must be on PATH).
- Create venv and install deps:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### Run (dev)
- Put `trollskript.py` inside the folder you want to scan (or run it from there).

```bash
python3 trollskript.py
```

### Windows build (.exe)
- Recommended: build on Windows (or GitHub Actions Windows runner).
- Install Python 3, then:

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --name trollskript trollskript.py
```

- Bundle ExifTool for Windows next to the `.exe` and the script will prefer it (so users don't need to install anything):
  - `exiftool.exe`
  - (and whatever comes with the official ExifTool Windows zip)

### Notes
- Reports are written to `DEST/.trollskript/`:
  - `found_files.txt`, `found_files.json`
  - `report.json`, `duplicates_skipped.json`, `collisions.json` (+ `collisions_applied.json` if applicable)
- Name collisions can optionally be copied to `DEST/conflicts/` with unique filenames.


