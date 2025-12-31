from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


EXIFTOOL_WIN_URL = "https://exiftool.org/exiftool-13.28_64.zip"


def _download_exiftool_windows(dest_dir: Path) -> Path:
    """Download and extract exiftool for Windows. Returns path to exiftool.exe."""
    print(f"Downloading ExifTool from {EXIFTOOL_WIN_URL}...")
    try:
        with urllib.request.urlopen(EXIFTOOL_WIN_URL, timeout=60) as resp:
            data = resp.read()
    except Exception as e:
        raise RuntimeError(f"Failed to download ExifTool: {e}")

    print("Extracting ExifTool...")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            # The zip contains exiftool(-k).exe, rename to exiftool.exe
            if member.lower().endswith(".exe"):
                exe_data = zf.read(member)
                exe_path = dest_dir / "exiftool.exe"
                exe_path.write_bytes(exe_data)
                print(f"ExifTool installed to: {exe_path}")
                return exe_path
    raise RuntimeError("No .exe found in ExifTool zip")


def _exiftool_path(auto_download: bool = True) -> str:
    """Get path to exiftool. On Windows, auto-downloads if not found."""
    here = _script_dir()
    win_exe = here / "exiftool.exe"

    if win_exe.exists():
        return str(win_exe)

    # On Windows, try to auto-download
    if auto_download and sys.platform == "win32":
        try:
            _download_exiftool_windows(here)
            if win_exe.exists():
                return str(win_exe)
        except Exception as e:
            print(f"Warning: Auto-download of ExifTool failed: {e}")

    return "exiftool"


def _run_exiftool_json(paths: list[Path]) -> list[dict[str, Any]]:
    if not paths:
        return []

    cmd = [
        _exiftool_path(),
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
        result = subprocess.run(cmd, capture_output=True)
        out = result.stdout
    except FileNotFoundError:
        raise RuntimeError(
            "ExifTool not found. Install `exiftool` (Linux: apt install libimage-exiftool-perl) "
            "or place `exiftool.exe` next to this script (Windows)."
        )

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


def discover_media(root: Path, exclude_dirs: list[Path] | None = None) -> list[MediaItem]:
    all_files = _walk_files_excluding(root, exclude_dirs or [])
    items: list[MediaItem] = []

    for batch in _batched(all_files, 200):
        metas = _run_exiftool_json(batch)
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
    return items


def _folder_for_item(base_out: Path, item: MediaItem) -> Path:
    if item.exif_date is None:
        return base_out / "unknown_date"

    dt = item.exif_date
    # If tz-aware, group by local date in that timezone; if naive, use as-is.
    y, m, d = dt.year, dt.month, dt.day
    return base_out / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{d:02d}"


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


def plan_copies(items: list[MediaItem], base_out: Path) -> tuple[list[PlannedCopy], set[int], set[int]]:
    plans: list[PlannedCopy] = []
    years_with_date: set[int] = set()
    years_all: set[int] = set()

    for item in items:
        if item.exif_date is not None:
            years_with_date.add(item.exif_date.year)
        dst_dir = _folder_for_item(base_out, item)
        if item.exif_date is not None:
            years_all.add(item.exif_date.year)

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

    return plans, years_with_date, years_all





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
            report.append(
                {
                    "status": "error",
                    "src": str(plan.src),
                    "dst": str(plan.dst),
                    "error": str(e),
                    "kind": plan.kind,
                    "group_id": plan.group_id,
                }
            )
            continue

        if src_hash in seen_hashes:
            duplicates.append(
                {
                    "src": str(plan.src),
                    "existing": seen_hashes[src_hash],
                    "hash": src_hash,
                    "kind": plan.kind,
                    "group_id": plan.group_id,
                }
            )
            report.append(
                {
                    "status": "skipped_duplicate",
                    "src": str(plan.src),
                    "dst": str(plan.dst),
                    "hash": src_hash,
                    "kind": plan.kind,
                    "group_id": plan.group_id,
                }
            )
            continue

        if plan.dst.exists():
            try:
                dst_hash = _hash_file(plan.dst)
            except OSError:
                dst_hash = None
            if dst_hash == src_hash:
                seen_hashes[src_hash] = str(plan.dst)
                report.append(
                    {
                        "status": "already_present_same_content",
                        "src": str(plan.src),
                        "dst": str(plan.dst),
                        "hash": src_hash,
                        "kind": plan.kind,
                        "group_id": plan.group_id,
                    }
                )
                continue
            collisions.append(
                {
                    "src": str(plan.src),
                    "dst": str(plan.dst),
                    "src_hash": src_hash,
                    "dst_hash": dst_hash,
                    "kind": plan.kind,
                    "group_id": plan.group_id,
                }
            )
            report.append(
                {
                    "status": "collision_deferred",
                    "src": str(plan.src),
                    "dst": str(plan.dst),
                    "hash": src_hash,
                    "kind": plan.kind,
                    "group_id": plan.group_id,
                }
            )
            continue

        shutil.copy2(plan.src, plan.dst)
        seen_hashes[src_hash] = str(plan.dst)
        report.append(
            {
                "status": "copied",
                "src": str(plan.src),
                "dst": str(plan.dst),
                "hash": src_hash,
                "kind": plan.kind,
                "group_id": plan.group_id,
            }
        )

    logs_dir.mkdir(parents=True, exist_ok=True)
    _write_json(logs_dir / "report.json", report)
    _write_json(logs_dir / "duplicates_skipped.json", duplicates)
    _write_json(logs_dir / "collisions.json", collisions)

    # Handle collisions according to policy
    if collisions:
        print(f"Found {len(collisions)} collision(s), applying policy: {collision_policy}")
        conflicts_dir = base_out / "conflicts"
        if collision_policy == "conflicts":
            conflicts_dir.mkdir(parents=True, exist_ok=True)

        applied: list[dict[str, Any]] = []
        for c in collisions:
            src = Path(c["src"])
            dst = Path(c["dst"])
            src_hash = c["src_hash"]
            if src_hash in seen_hashes:
                applied.append({**c, "final_status": "skipped_duplicate_after_policy", "final_dst": None})
                continue

            if collision_policy == "skip":
                applied.append({**c, "final_status": "skipped_collision", "final_dst": None})
                continue

            if collision_policy == "rename":
                final_dst = _ensure_unique_path(dst)
            else:
                final_dst = _ensure_unique_path(conflicts_dir / dst.name)

            final_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, final_dst)
            seen_hashes[src_hash] = str(final_dst)
            applied.append({**c, "final_status": "copied_after_collision", "final_dst": str(final_dst)})

        _write_json(logs_dir / "collisions_applied.json", applied)


def parse_args() -> argparse.Namespace:
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Source: command line or script directory
    src_root = args.src.resolve() if args.src else _script_dir()
    if not src_root.exists():
        print(f"Error: Source folder does not exist: {src_root}")
        return 1

    dest_root = args.dest.resolve()

    # Determine base output folder
    if args.top_folder:
        base_out = dest_root / args.top_folder
    else:
        base_out = dest_root

    base_out.mkdir(parents=True, exist_ok=True)
    logs_dir = base_out / ".trollskript"

    print(f"Source: {src_root}")
    print(f"Destination: {base_out}")
    print(f"Collision policy: {args.collision_policy}")

    # Exclude destination from scan if it's inside source
    exclude_dirs: list[Path] = []
    try:
        if base_out == src_root or str(base_out).startswith(str(src_root) + os.sep):
            exclude_dirs.append(base_out)
    except Exception:
        pass

    print("Scanning for media files...")
    items = discover_media(src_root, exclude_dirs=exclude_dirs)
    print(f"Found {len(items)} media file(s)")

    if not items:
        print("No media files found. Exiting.")
        return 0

    _write_found_list(logs_dir, items)

    plans, years_with_date, _years_all = plan_copies(items, base_out=base_out)

    if years_with_date:
        years_sorted = sorted(years_with_date)
        if len(years_sorted) > 1:
            print(f"Note: Multiple years detected: {years_sorted}")

    print("Indexing existing destination files for duplicate detection...")
    dest_index = build_dest_hash_index(base_out)
    print(f"Indexed {len(dest_index)} existing file(s)")

    print("Copying files (non-destructive)...")
    copy_with_policy(
        plans=plans,
        dest_hash_index=dest_index,
        base_out=base_out,
        logs_dir=logs_dir,
        collision_policy=args.collision_policy,
    )

    print(f"Done! Reports written to: {logs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


