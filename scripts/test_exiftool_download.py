#!/usr/bin/env python3
"""
Test script to verify ExifTool Windows download and extraction works correctly.
Run this on Ubuntu to verify the download/extraction logic before building the Windows exe.

Usage:
    python scripts/test_exiftool_download.py
"""

import sys
import tempfile
from pathlib import Path

# Add parent directory to path so we can import from trollskript
sys.path.insert(0, str(Path(__file__).parent.parent))

from trollskript import (
    _get_exiftool_download_url,
    _download_exiftool_windows,
    _find_exiftool_exe,
)


def test_exiftool_download():
    """Test that ExifTool downloads and extracts correctly with all required files."""
    print("=" * 60)
    print("Testing ExifTool Download and Extraction")
    print("=" * 60)

    # 1. Test URL fetching
    print("\n1. Fetching download URL...")
    url = _get_exiftool_download_url()
    print(f"   URL: {url}")
    assert "exiftool" in url.lower(), "URL should contain 'exiftool'"
    assert url.endswith(".zip"), "URL should end with .zip"
    print("   ✓ URL looks correct")

    # 2. Test download and extraction
    print("\n2. Downloading and extracting to temp directory...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        exe_path = _download_exiftool_windows(tmp_path)
        print(f"   Returned exe path: {exe_path}")
        
        # 3. Verify exe exists
        print("\n3. Verifying executable exists...")
        assert exe_path.exists(), f"Executable should exist at {exe_path}"
        print(f"   ✓ Executable exists: {exe_path}")
        
        # 4. Verify exiftool_files directory exists (contains perl DLLs)
        print("\n4. Checking for exiftool_files directory...")
        exiftool_files_dirs = list(tmp_path.rglob("exiftool_files"))
        if exiftool_files_dirs:
            print(f"   ✓ Found exiftool_files directory: {exiftool_files_dirs[0]}")
        else:
            print("   ⚠ No exiftool_files directory found (may be newer format)")
        
        # 5. Search for perl*.dll files
        print("\n5. Searching for Perl DLLs...")
        dll_files = list(tmp_path.rglob("perl*.dll"))
        if dll_files:
            for dll in dll_files[:5]:  # Show first 5
                print(f"   ✓ Found: {dll.name}")
            if len(dll_files) > 5:
                print(f"   ... and {len(dll_files) - 5} more DLLs")
        else:
            print("   ⚠ No perl*.dll files found")
        
        # 6. List all extracted files
        print("\n6. Listing all extracted files...")
        all_files = list(tmp_path.rglob("*"))
        file_count = len([f for f in all_files if f.is_file()])
        dir_count = len([f for f in all_files if f.is_dir()])
        print(f"   Total: {file_count} files, {dir_count} directories")
        
        # Show some key files
        print("\n   Key files:")
        for f in sorted(all_files)[:20]:
            if f.is_file():
                rel = f.relative_to(tmp_path)
                print(f"   - {rel}")
        if file_count > 20:
            print(f"   ... and {file_count - 20} more files")
        
        # 7. Verify _find_exiftool_exe works
        print("\n7. Testing _find_exiftool_exe()...")
        found_exe = _find_exiftool_exe(tmp_path)
        assert found_exe is not None, "_find_exiftool_exe should find the exe"
        assert found_exe == exe_path, f"Found exe {found_exe} should match returned exe {exe_path}"
        print(f"   ✓ _find_exiftool_exe correctly found: {found_exe}")

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)


if __name__ == "__main__":
    test_exiftool_download()

