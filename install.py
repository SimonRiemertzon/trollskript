from __future__ import annotations

import io
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


EXIFTOOL_VER_URL = "https://exiftool.org/ver.txt"
_INSTALL_DIR_NAME = "exiftool"


def get_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / _INSTALL_DIR_NAME
    return Path.home() / ".exiftool"


def find_exe(search_dir: Path) -> Path | None:
    for exe in search_dir.rglob("exiftool(-k).exe"):
        return exe
    for exe in search_dir.rglob("exiftool.exe"):
        return exe
    return None


def _fetch_download_url() -> tuple[str, str]:
    try:
        with urllib.request.urlopen(EXIFTOOL_VER_URL, timeout=30) as resp:
            version = resp.read().decode("utf-8").strip()
        return f"https://exiftool.org/exiftool-{version}_64.zip", version
    except Exception:
        fallback = "13.45"
        return f"https://exiftool.org/exiftool-{fallback}_64.zip", fallback


def download_and_install(dest_dir: Path) -> Path:
    url, version = _fetch_download_url()
    print(f"Downloading ExifTool v{version}...")

    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} downloading ExifTool from {url}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    print("Extracting ExifTool...")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest_dir)

    exe = find_exe(dest_dir)
    if exe is None:
        raise RuntimeError("No ExifTool executable found after extraction.")

    print(f"ExifTool v{version} installed to: {exe}")
    return exe


def _detect_package_manager() -> tuple[str, list[str]] | None:
    """
    Detect the system package manager and return (name, install_command).
    Returns None if none found.
    """
    import shutil as _shutil

    candidates = [
        ("apt-get", ["sudo", "apt-get", "install", "-y", "libimage-exiftool-perl"]),
        ("dnf",     ["sudo", "dnf",     "install", "-y", "perl-Image-ExifTool"]),
        ("pacman",  ["sudo", "pacman",  "-S", "--noconfirm", "perl-image-exiftool"]),
        ("zypper",  ["sudo", "zypper",  "install", "-y", "perl-Image-ExifTool"]),
        ("brew",    ["brew", "install", "exiftool"]),
    ]
    for name, cmd in candidates:
        if _shutil.which(name):
            return name, cmd
    return None


def _install_exiftool_unix() -> None:
    """Prompt the user and install ExifTool via the system package manager."""
    result = _detect_package_manager()
    if result is None:
        raise RuntimeError(
            "ExifTool is required but not found, and no supported package manager "
            "was detected.\nInstall it manually: https://exiftool.org/"
        )

    pm_name, cmd = result
    print("\nExifTool is required to read photo/video metadata.")
    print(f"It will be installed using: {' '.join(cmd)}")
    response = input("Would you like to install ExifTool now? [Y/n]: ").strip().lower()
    if response not in ("", "y", "yes"):
        raise RuntimeError("ExifTool is required. Exiting.")

    import subprocess as _subprocess
    ret = _subprocess.call(cmd)
    if ret != 0:
        raise RuntimeError(f"Installation failed (exit code {ret}). Try running manually:\n  {' '.join(cmd)}")
    print("ExifTool installed successfully.")


def ensure_exiftool() -> str:
    """
    Return path to exiftool. Prompts to install if missing, on any platform.
    Raises RuntimeError if not available.
    """
    import shutil as _shutil

    # Check Windows install dir first
    if sys.platform == "win32":
        exe = find_exe(get_install_dir())
        if exe:
            return str(exe)

    # Check PATH
    if _shutil.which("exiftool"):
        return "exiftool"

    if sys.platform == "win32":
        # Windows: prompt and auto-download
        print("\nExifTool is required to read photo/video metadata.")
        print(f"It will be installed to: {get_install_dir()}")
        response = input("Would you like to install ExifTool now? [Y/n]: ").strip().lower()
        if response not in ("", "y", "yes"):
            raise RuntimeError("ExifTool is required. Exiting.")
        return str(download_and_install(get_install_dir()))

    # Linux/macOS: prompt and install via package manager
    _install_exiftool_unix()
    if _shutil.which("exiftool"):
        return "exiftool"
    raise RuntimeError("ExifTool still not found after installation. Try opening a new terminal.")


if __name__ == "__main__":
    try:
        path = download_and_install(get_install_dir())
        print(f"\nDone: {path}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
