from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import json
import os
import shutil
import string
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable



# ANSI color codes for terminal output
class Colors:
    """ANSI color codes - works on Windows 10+ and Linux/Mac"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    # Bright/bold colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    ORANGE = "\033[38;5;208m"


def _init_colors() -> None:
    """Enable ANSI colors on Windows."""
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass  # Fallback: colors may not work on older Windows


def cprint(msg: str, color: str = Colors.CYAN, end: str = "\n", flush: bool = False) -> None:
    """Print colored message."""
    print(f"{color}{msg}{Colors.RESET}", end=end, flush=flush)


def cprint_success(msg: str) -> None:
    """Print success message in green."""
    cprint(msg, Colors.GREEN)


def cprint_warn(msg: str) -> None:
    """Print warning message in yellow."""
    cprint(msg, Colors.YELLOW)


def cprint_error(msg: str) -> None:
    """Print error message in red."""
    cprint(msg, Colors.RED)


def cprint_info(msg: str) -> None:
    """Print info message in cyan."""
    cprint(msg, Colors.CYAN)


def cprint_header(msg: str) -> None:
    """Print header message in bold magenta."""
    cprint(msg, Colors.BOLD + Colors.MAGENTA)


SIDECAR_EXTS = {".xmp", ".aae", ".thm", ".dop", ".pp3"}

EXIF_DATE_TAGS_PRIORITY = [
    "DateTimeOriginal",
    "MediaCreateDate",
    "CreateDate",
    "TrackCreateDate",
    "ModifyDate",
]


@dataclass(frozen=True)
class MediaItem:
    src: Path
    sidecars: tuple[Path, ...]
    exif_date: datetime | None
    exif_tag_used: str | None
    mime_type: str | None


@dataclass(frozen=True)
class PlannedCopy:
    src: Path
    dst: Path
    kind: str  # "media" | "sidecar"
    group_id: str


def _script_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _get_volume_label(drive: str) -> str:
    """Get the volume label for a drive on Windows. Returns empty string on failure."""
    if sys.platform != "win32":
        return ""
    volume_name_buf = ctypes.create_unicode_buffer(261)
    result = ctypes.windll.kernel32.GetVolumeInformationW(
        drive, volume_name_buf, 261, None, None, None, None, 0
    )
    return volume_name_buf.value if result else ""


def _get_removable_drives() -> list[tuple[str, str]]:
    """
    Detect removable drives on Windows (USB drives, SD cards).
    Returns list of (drive_path, volume_label) tuples.
    """
    if sys.platform != "win32":
        return []
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in string.ascii_uppercase:
        if bitmask & 1:
            drive = f"{letter}:\\"
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
            # DriveType 2 = DRIVE_REMOVABLE
            if drive_type == 2:
                label = _get_volume_label(drive)
                drives.append((drive, label))
        bitmask >>= 1
    return drives


def _get_subfolders(folder: Path) -> list[Path]:
    """Get list of subfolders in a directory."""
    try:
        return sorted([p for p in folder.iterdir() if p.is_dir()])
    except (PermissionError, FileNotFoundError, OSError):
        return []


def _select_folder(start_path: Path) -> Path | None:
    """
    Interactive folder browser. Lets user navigate into subfolders or select current folder.
    Returns selected path or None if cancelled.
    """
    current = start_path

    while True:
        print()
        print(f"Current folder: {current}")
        subfolders = _get_subfolders(current)

        print("  0. [SELECT THIS FOLDER]")
        if current != start_path:
            print("  b. [GO BACK]")

        if subfolders:
            print()
            print("Subfolders:")
            for i, folder in enumerate(subfolders, 1):
                print(f"  {i}. {folder.name}/")
        else:
            print("  (no subfolders)")
        print()

        max_choice = len(subfolders)
        prompt = f"Select [0-{max_choice}]"
        if current != start_path:
            prompt += ", 'b' to go back"
        prompt += ", or 'q' to quit: "

        choice = input(prompt).strip().lower()

        if choice == "q":
            return None
        if choice == "b" and current != start_path:
            current = current.parent
            continue
        if choice == "0":
            return current

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(subfolders):
                current = subfolders[idx]
            else:
                print(f"Please enter a number between 0 and {max_choice}")
        except ValueError:
            print("Invalid input. Please enter a number or 'q' to quit.")


def _run_interactive_mode() -> tuple[Path, Path] | None:
    """
    Interactive mode for Windows double-click usage.
    Shows welcome message, lists removable drives, prompts user to select one.
    Returns (source_path, dest_path) or None if cancelled/no drives found.
    """
    cprint("=" * 50, Colors.MAGENTA)
    cprint("  TrollSkript - Photo/Video Sorter", Colors.BOLD + Colors.CYAN)
    cprint("=" * 50, Colors.MAGENTA)
    print()
    cprint("This tool copies photos and videos from a removable", Colors.WHITE)
    cprint("drive (USB/SD card) into date-based folders.", Colors.WHITE)
    print()

    dest = _script_dir()
    cprint_info(f"Destination: {dest}")
    print()

    drives = _get_removable_drives()
    if not drives:
        print("No removable drives found!")
        cprint("Please insert a USB drive or SD card and try again.", Colors.YELLOW)
        return None

    cprint("Available removable drives:", Colors.CYAN)
    for i, (drive_path, label) in enumerate(drives, 1):
        display_label = f" ({label})" if label else ""
        print(f"  {i}. {drive_path}{display_label}")
    print()

    while True:
        try:
            choice = input(f"Select drive [1-{len(drives)}] or 'q' to quit: ").strip()
            if choice.lower() == "q":
                cprint("Cancelled.", Colors.YELLOW)
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(drives):
                drive_root = Path(drives[idx][0])
                break
            else:
                print(f"Please enter a number between 1 and {len(drives)}")
        except ValueError:
            print(f"Please enter a number between 1 and {len(drives)} or 'q' to quit")

    # Let user select a subfolder within the drive
    print()
    cprint("Now select the folder to scan for photos/videos.", Colors.CYAN)
    cprint("You can navigate into subfolders or select the current folder.", Colors.WHITE)

    src = _select_folder(drive_root)
    if src is None:
        cprint("Cancelled.", Colors.YELLOW)
        return None

    print()
    cprint_info(f"Source: {src}")
    cprint_info(f"Destination: {dest}")
    print()
    return src, dest


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


EXIFTOOL_VER_URL = "https://exiftool.org/ver.txt"
EXIFTOOL_INSTALL_DIR_NAME = "exiftool"


def _get_exiftool_install_dir() -> Path:
    """Get the common installation directory for ExifTool on Windows."""
    # Use %LOCALAPPDATA%\exiftool (e.g., C:\Users\<user>\AppData\Local\exiftool)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / EXIFTOOL_INSTALL_DIR_NAME
    # Fallback to user home directory
    return Path.home() / ".exiftool"


def _get_exiftool_download_url() -> tuple[str, str]:
    """Fetch the latest ExifTool version and return (url, version)."""
    try:
        with urllib.request.urlopen(EXIFTOOL_VER_URL, timeout=30) as resp:
            version = resp.read().decode("utf-8").strip()
        return f"https://exiftool.org/exiftool-{version}_64.zip", version
    except Exception:
        # Fallback to a known version if we can't fetch the latest
        # This version should be updated periodically to match a recent release
        fallback_version = "13.45"
        return f"https://exiftool.org/exiftool-{fallback_version}_64.zip", fallback_version


def _find_exiftool_exe(search_dir: Path) -> Path | None:
    """Search for ExifTool executable under search_dir. Prefers exiftool.exe over exiftool(-k).exe."""
    # Look for exiftool.exe first (the renamed version that doesn't wait for keypress)
    for exe in search_dir.rglob("exiftool.exe"):
        return exe
    # Fallback to exiftool(-k).exe (the default name in the ZIP, but waits for keypress)
    for exe in search_dir.rglob("exiftool(-k).exe"):
        return exe
    return None


def _download_exiftool_windows(dest_dir: Path) -> Path:
    """Download and extract exiftool for Windows. Returns path to exiftool executable."""
    url, version = _get_exiftool_download_url()
    cprint(f"Downloading ExifTool v{version} from {url}...", Colors.CYAN)

    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(
                f"ExifTool v{version} not found on server (404). "
                f"The version may have been removed from exiftool.org. "
                f"Please download ExifTool manually from https://exiftool.org/ "
                f"and place exiftool.exe in: {dest_dir}"
            )
        raise RuntimeError(f"Failed to download ExifTool: HTTP Error {e.code}")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Network error downloading ExifTool: {e.reason}. "
            f"Please check your internet connection or download manually from https://exiftool.org/"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to download ExifTool: {e}")

    # Create destination directory if it doesn't exist
    dest_dir.mkdir(parents=True, exist_ok=True)

    cprint("Extracting ExifTool...", Colors.CYAN)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Extract everything to preserve DLLs and support files
        zf.extractall(dest_dir)

    # Find the extracted executable
    exe_path = _find_exiftool_exe(dest_dir)
    if exe_path is None:
        raise RuntimeError("No ExifTool executable found after extraction")

    # Rename exiftool(-k).exe to exiftool.exe if needed
    # The (-k) version waits for keypress after running, which hangs subprocess calls
    if "(-k)" in exe_path.name:
        new_path = exe_path.with_name("exiftool.exe")
        try:
            exe_path.rename(new_path)
            exe_path = new_path
            print("Renamed exiftool(-k).exe to exiftool.exe")
        except OSError:
            pass  # If rename fails, we'll use the original name

    cprint_success(f"ExifTool v{version} installed to: {exe_path}")
    return exe_path


_cached_exiftool_path: str | None = None


def _exiftool_path(auto_download: bool = True, interactive: bool = False) -> str:
    """Get path to exiftool. On Windows, prompts user to install if not found."""
    global _cached_exiftool_path
    if _cached_exiftool_path is not None:
        return _cached_exiftool_path

    cprint("Checking for ExifTool...", Colors.CYAN, flush=True)

    # 1. Check common installation directory on Windows
    if sys.platform == "win32":
        install_dir = _get_exiftool_install_dir()
        existing_exe = _find_exiftool_exe(install_dir)
        if existing_exe:
            # Rename exiftool(-k).exe to exiftool.exe if needed
            # The (-k) version waits for keypress after running, which hangs subprocess calls
            if "(-k)" in existing_exe.name:
                new_path = existing_exe.with_name("exiftool.exe")
                try:
                    existing_exe.rename(new_path)
                    print(f"Renamed {existing_exe.name} to exiftool.exe", flush=True)
                    existing_exe = new_path
                except OSError as e:
                    cprint(f"Warning: Could not rename {existing_exe.name}: {e}", Colors.YELLOW, flush=True)
                    cprint("The script may hang. Please manually rename to exiftool.exe", Colors.YELLOW, flush=True)
            cprint(f"Found ExifTool: {existing_exe}", Colors.GREEN, flush=True)
            _cached_exiftool_path = str(existing_exe)
            return _cached_exiftool_path

    # 2. Check if exiftool is in PATH
    if shutil.which("exiftool"):
        cprint("Found ExifTool in PATH", Colors.GREEN, flush=True)
        _cached_exiftool_path = "exiftool"
        return _cached_exiftool_path

    # 3. ExifTool not found - on Windows, offer to install
    if sys.platform == "win32" and auto_download:
        install_dir = _get_exiftool_install_dir()
        print("\n" + "=" * 60, flush=True)
        print("ExifTool is required but not installed.", flush=True)
        print(f"Install location: {install_dir}", flush=True)
        print("=" * 60, flush=True)

        if interactive:
            response = input("\nWould you like to install ExifTool now? [Y/n]: ").strip().lower()
            if response in ("", "y", "yes", "ja", "j"):
                try:
                    exe_path = _download_exiftool_windows(install_dir)
                    _cached_exiftool_path = str(exe_path)
                    return _cached_exiftool_path
                except Exception as e:
                    raise RuntimeError(f"Failed to install ExifTool: {e}")
            else:
                raise RuntimeError(
                    "ExifTool is required to run this script. "
                    "Please install it manually or re-run and accept the installation."
                )
        else:
            # Non-interactive mode: auto-install without prompting
            try:
                exe_path = _download_exiftool_windows(install_dir)
                _cached_exiftool_path = str(exe_path)
                return _cached_exiftool_path
            except Exception as e:
                raise RuntimeError(f"Failed to auto-install ExifTool: {e}")

    # 4. Not on Windows and not in PATH
    raise RuntimeError(
        "ExifTool is required but not found. "
        "Please install it: https://exiftool.org/"
    )


def _run_exiftool_json(paths: list[Path], interactive: bool = False) -> list[dict[str, Any]]:
    if not paths:
        return []

    cmd = [
        _exiftool_path(interactive=interactive),
        "-json",
        "-api",
        "largefilesupport=1",
        "-fast",
        "-charset",
        "filename=utf8",
        "-FileName",
        "-Directory",
        "-MIMEType",
        *[f"-{t}" for t in EXIF_DATE_TAGS_PRIORITY],
        "--",
        *[str(p) for p in paths],
    ]
    try:
        # Separate stdout (JSON) from stderr (warnings)
        # Timeout after 120 seconds per batch to avoid hanging on problematic files
        result = subprocess.run(cmd, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "ExifTool timed out after 120 seconds. This may happen if:\n"
            "  - Using 'exiftool(-k).exe' which waits for keypress (rename to 'exiftool.exe')\n"
            "  - Processing very large or corrupted files"
        )
    except FileNotFoundError:
        raise RuntimeError(
            "ExifTool not found. Install `exiftool` (Linux: apt install libimage-exiftool-perl) "
            "or place `exiftool.exe` next to this script (Windows)."
        )

    # Fail fast if exiftool returned an error
    if result.returncode != 0:
        stderr_msg = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ExifTool failed (exit code {result.returncode}): {stderr_msg}")

    out = result.stdout
    if not out.strip():
        return []

    # Parse JSON, handling potential encoding issues
    try:
        return json.loads(out.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        # Try to clean up the output - sometimes exiftool includes warnings
        text = out.decode("utf-8", errors="replace")
        # Find the JSON array bounds
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return []


def _parse_exif_dt(value: str) -> datetime | None:
    v = value.strip()
    if not v:
        return None
    # common: "2025:01:01 12:34:56" or "2025:01:01 12:34:56+01:00"
    for fmt in ("%Y:%m:%d %H:%M:%S%z", "%Y:%m:%d %H:%M:%S"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    return None


def _pick_best_date(meta: dict[str, Any]) -> tuple[datetime | None, str | None]:
    for tag in EXIF_DATE_TAGS_PRIORITY:
        v = meta.get(tag)
        if isinstance(v, str):
            dt = _parse_exif_dt(v)
            if dt is not None:
                return dt, tag
    return None, None


def _is_media_mime(mime: str | None) -> bool:
    if not mime:
        return False
    return mime.startswith("image/") or mime.startswith("video/")


def _find_sidecars_for(src: Path) -> tuple[Path, ...]:
    base = src.with_suffix("")
    found: list[Path] = []
    for ext in SIDECAR_EXTS:
        p = Path(str(base) + ext)
        if p.exists() and p.is_file():
            found.append(p)
    return tuple(found)


def _walk_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            files.append(Path(dirpath) / fn)
    return files


def _walk_files_excluding(root: Path, exclude_dirs: list[Path]) -> list[Path]:
    ex = [p.resolve() for p in exclude_dirs]
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath).resolve()

        # prune excluded subtrees
        for d in list(dirnames):
            cand = (dp / d).resolve()
            if any(cand == e or str(cand).startswith(str(e) + os.sep) for e in ex):
                dirnames.remove(d)

        for fn in filenames:
            files.append(dp / fn)
    return files


def _batched(it: list[Path], n: int) -> Iterable[list[Path]]:
    for i in range(0, len(it), n):
        yield it[i : i + n]


def discover_media(root: Path, exclude_dirs: list[Path] | None = None, interactive: bool = False) -> list[MediaItem]:
    print("  Walking directory tree...", flush=True)
    all_files = _walk_files_excluding(root, exclude_dirs or [])
    print(f"  Found {len(all_files)} files to analyze", flush=True)
    items: list[MediaItem] = []

    total_batches = (len(all_files) + 199) // 200  # ceiling division
    for batch_num, batch in enumerate(_batched(all_files, 200), 1):
        print(f"  Processing batch {batch_num}/{total_batches}...", end="\r", flush=True)
        metas = _run_exiftool_json(batch, interactive=interactive)
        for meta in metas:
            directory = meta.get("Directory")
            filename = meta.get("FileName")
            if not isinstance(directory, str) or not isinstance(filename, str) or not directory or not filename:
                continue
            src = Path(directory) / filename
            src = src.resolve()
            mime = meta.get("MIMEType")
            if not _is_media_mime(mime):
                continue
            dt, tag_used = _pick_best_date(meta)
            items.append(
                MediaItem(
                    src=src,
                    sidecars=_find_sidecars_for(src),
                    exif_date=dt,
                    exif_tag_used=tag_used,
                    mime_type=mime,
                )
            )
    print()  # newline after progress indicator
    return items


def _folder_for_item(base_out: Path, item: MediaItem) -> Path:
    if item.exif_date is None:
        return base_out / "unknown_date"

    dt = item.exif_date
    # If tz-aware, group by local date in that timezone; if naive, use as-is.
    y, m, d = dt.year, dt.month, dt.day
    return base_out / f"{y:04d}-{m:02d}-{d:02d} -"


def _ensure_unique_path(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem = dst.stem
    suffix = dst.suffix
    parent = dst.parent
    for i in range(1, 10_000):
        cand = parent / f"{stem}_({i}){suffix}"
        if not cand.exists():
            return cand
    raise RuntimeError(f"Could not find a free name for: {dst}")


def _hash_file(path: Path) -> str:
    """Compute SHA-256 hash of a file (streaming, memory-efficient)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_dest_hash_index(dest_root: Path) -> dict[str, list[str]]:
    """
    Returns hash -> [paths...] for files already present in destination.
    """
    idx: dict[str, list[str]] = {}
    if not dest_root.exists():
        return idx

    skip_names = {
        "found_files.txt",
        "found_files.json",
        "report.json",
        "duplicates_skipped.json",
        "collisions.json",
        "collisions_applied.json",
    }
    for p in _walk_files(dest_root):
        if not p.is_file():
            continue
        if p.name in skip_names:
            continue
        try:
            hx = _hash_file(p)
        except OSError:
            continue
        idx.setdefault(hx, []).append(str(p))
    return idx


def plan_copies(items: list[MediaItem], base_out: Path) -> tuple[list[PlannedCopy], set[int]]:
    plans: list[PlannedCopy] = []
    years_with_date: set[int] = set()

    for item in items:
        if item.exif_date is not None:
            years_with_date.add(item.exif_date.year)
        dst_dir = _folder_for_item(base_out, item)

        group_id = hashlib.sha1(str(item.src).encode("utf-8", errors="replace")).hexdigest()[:12]
        plans.append(
            PlannedCopy(
                src=item.src,
                dst=dst_dir / item.src.name,
                kind="media",
                group_id=group_id,
            )
        )
        for sc in item.sidecars:
            plans.append(
                PlannedCopy(
                    src=sc,
                    dst=dst_dir / sc.name,
                    kind="sidecar",
                    group_id=group_id,
                )
            )

    return plans, years_with_date





def _write_found_list(out_dir: Path, items: list[MediaItem]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    found_txt = out_dir / "found_files.txt"
    found_json = out_dir / "found_files.json"

    found_txt.write_text(
        "\n".join(str(i.src) for i in items) + ("\n" if items else ""),
        encoding="utf-8",
    )
    _write_json(
        found_json,
        [
            {
                "src": str(i.src),
                "mime_type": i.mime_type,
                "exif_tag_used": i.exif_tag_used,
                "exif_date": i.exif_date.isoformat() if i.exif_date else None,
                "sidecars": [str(p) for p in i.sidecars],
            }
            for i in items
        ],
    )


def _make_entry(plan: PlannedCopy, **extra: Any) -> dict[str, Any]:
    """Create a report/log entry with common fields from a PlannedCopy."""
    return {"src": str(plan.src), "dst": str(plan.dst), "kind": plan.kind, "group_id": plan.group_id, **extra}


def copy_with_policy(
    plans: list[PlannedCopy],
    dest_hash_index: dict[str, list[str]],
    base_out: Path,
    logs_dir: Path,
    collision_policy: str = "skip",
) -> None:
    """
    Copy files according to plan, handling duplicates and collisions.

    collision_policy: "skip" | "rename" | "conflicts"
        - skip: don't copy files that would overwrite different content
        - rename: add suffix like _(1) to avoid collision
        - conflicts: copy collisions to a separate conflicts/ folder
    """
    report: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []

    # Ensure deterministic: media first, then sidecars
    plans_sorted = sorted(plans, key=lambda p: (p.group_id, 0 if p.kind == "media" else 1, str(p.src)))

    seen_hashes: dict[str, str] = {h: paths[0] for h, paths in dest_hash_index.items() if paths}

    for plan in plans_sorted:
        plan.dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            src_hash = _hash_file(plan.src)
        except OSError as e:
            report.append(_make_entry(plan, status="error", error=str(e)))
            continue

        if src_hash in seen_hashes:
            duplicates.append(_make_entry(plan, existing=seen_hashes[src_hash], hash=src_hash))
            report.append(_make_entry(plan, status="skipped_duplicate", hash=src_hash))
            continue

        if plan.dst.exists():
            try:
                dst_hash = _hash_file(plan.dst)
            except OSError:
                dst_hash = None
            if dst_hash == src_hash:
                seen_hashes[src_hash] = str(plan.dst)
                report.append(_make_entry(plan, status="already_present_same_content", hash=src_hash))
                continue
            collisions.append(_make_entry(plan, src_hash=src_hash, dst_hash=dst_hash))
            report.append(_make_entry(plan, status="collision_deferred", hash=src_hash))
            continue

        shutil.copy2(plan.src, plan.dst)
        seen_hashes[src_hash] = str(plan.dst)
        report.append(_make_entry(plan, status="copied", hash=src_hash))

    logs_dir.mkdir(parents=True, exist_ok=True)
    _write_json(logs_dir / "report.json", report)
    _write_json(logs_dir / "duplicates_skipped.json", duplicates)
    _write_json(logs_dir / "collisions.json", collisions)

    # Handle collisions according to policy
    if collisions:
        cprint(f"Found {len(collisions)} collision(s), applying policy: {collision_policy}", Colors.YELLOW)
        conflicts_dir = base_out / "conflicts"
        if collision_policy == "conflicts":
            conflicts_dir.mkdir(parents=True, exist_ok=True)

        # Track media file renames so sidecars can follow: group_id -> (old_stem, new_stem, new_parent)
        media_renames: dict[str, tuple[str, str, Path]] = {}

        # First pass: process media files to determine renames
        applied: list[dict[str, Any]] = []
        for c in collisions:
            src = Path(c["src"])
            dst = Path(c["dst"])
            src_hash = c["src_hash"]
            kind = c["kind"]
            group_id = c["group_id"]

            if src_hash in seen_hashes:
                applied.append({**c, "final_status": "skipped_duplicate_after_policy", "final_dst": None})
                continue

            if collision_policy == "skip":
                applied.append({**c, "final_status": "skipped_collision", "final_dst": None})
                continue

            # Determine final destination
            if kind == "sidecar" and group_id in media_renames:
                # Sidecar follows its media file's rename
                old_stem, new_stem, new_parent = media_renames[group_id]
                new_name = dst.name.replace(old_stem, new_stem, 1)
                final_dst = new_parent / new_name
                final_dst = _ensure_unique_path(final_dst)
            elif collision_policy == "rename":
                final_dst = _ensure_unique_path(dst)
            else:
                final_dst = _ensure_unique_path(conflicts_dir / dst.name)

            # Track media file renames for sidecars to follow
            if kind == "media" and final_dst.stem != dst.stem:
                media_renames[group_id] = (dst.stem, final_dst.stem, final_dst.parent)

            final_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, final_dst)
            seen_hashes[src_hash] = str(final_dst)
            applied.append({**c, "final_status": "copied_after_collision", "final_dst": str(final_dst)})

        _write_json(logs_dir / "collisions_applied.json", applied)


def parse_args() -> argparse.Namespace | None:
    # Interactive mode: no arguments provided (e.g., double-clicked on Windows)
    if len(sys.argv) == 1:
        result = _run_interactive_mode()
        if result is None:
            return None
        src, dest = result
        return argparse.Namespace(
            src=src,
            dest=dest,
            top_folder=None,
            collision_policy="skip",
            interactive=True,
        )

    parser = argparse.ArgumentParser(
        description="Sort photos/videos into YYYY/MM/DD folders based on EXIF metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python trollskript.py --dest /path/to/sorted
  python trollskript.py --src /photos/unsorted --dest /photos/sorted
  python trollskript.py --dest ./output --top-folder "Vacation2024"
  python trollskript.py --dest ./output --collision-policy rename
""",
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=None,
        help="Source folder to scan (default: folder containing this script)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="Destination folder for sorted media",
    )
    parser.add_argument(
        "--top-folder",
        type=str,
        default=None,
        help="Use a custom top folder name instead of year-based folders (e.g., 'Vacation2024')",
    )
    parser.add_argument(
        "--collision-policy",
        type=str,
        choices=["skip", "rename", "conflicts"],
        default="skip",
        help="How to handle filename collisions: skip (default), rename (add suffix), conflicts (copy to conflicts/)",
    )
    args = parser.parse_args()
    args.interactive = False  # CLI mode is not interactive
    return args


def main() -> int:
    _init_colors()  # Enable ANSI colors on Windows
    args = parse_args()
    if args is None:
        return 0  # User cancelled interactive mode

    # Source: command line or script directory
    src_root = args.src.resolve() if args.src else _script_dir()
    if not src_root.exists():
        cprint_error(f"Error: Source folder does not exist: {src_root}")
        return 1

    dest_root = args.dest.resolve()

    # Determine base output folder
    if args.top_folder:
        base_out = dest_root / args.top_folder
    else:
        base_out = dest_root

    base_out.mkdir(parents=True, exist_ok=True)
    logs_dir = base_out / ".trollskript"

    cprint_info(f"Source: {src_root}")
    cprint_info(f"Destination: {base_out}")
    cprint_info(f"Collision policy: {args.collision_policy}")

    # Exclude destination from scan if it's inside source
    exclude_dirs: list[Path] = []
    try:
        if base_out == src_root or str(base_out).startswith(str(src_root) + os.sep):
            exclude_dirs.append(base_out)
    except Exception:
        pass

    cprint("Scanning for media files...", Colors.CYAN)
    items = discover_media(src_root, exclude_dirs=exclude_dirs, interactive=args.interactive)
    cprint(f"Found {len(items)} media file(s)", Colors.GREEN)

    if not items:
        cprint_warn("No media files found. Exiting.")
        return 0

    _write_found_list(logs_dir, items)

    plans, years_with_date = plan_copies(items, base_out=base_out)

    if years_with_date:
        years_sorted = sorted(years_with_date)
        if len(years_sorted) > 1:
            cprint(f"Note: Multiple years detected: {years_sorted}", Colors.YELLOW)

    cprint("Indexing existing destination files for duplicate detection...", Colors.CYAN)
    dest_index = build_dest_hash_index(base_out)
    cprint(f"Indexed {len(dest_index)} existing file(s)", Colors.GREEN)

    cprint("Copying files (non-destructive)...", Colors.CYAN)
    copy_with_policy(
        plans=plans,
        dest_hash_index=dest_index,
        base_out=base_out,
        logs_dir=logs_dir,
        collision_policy=args.collision_policy,
    )

    cprint_success(f"Done! Reports written to: {logs_dir}")
    return 0


if __name__ == "__main__":
	interactive_mode = len(sys.argv) == 1

	if interactive_mode:
		try:
			exit_code = main()
		except Exception as e:
			print(f"\nError: {e}")
			exit_code = 1
		# Keep console window open when double-clicked on Windows (interactive mode)
		print()
		input("Press Enter to exit...")
		raise SystemExit(exit_code)

	raise SystemExit(main())


