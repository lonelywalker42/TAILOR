#!/usr/bin/env python3
"""Build script for TAILOR — creates standalone executable using PyInstaller."""

import subprocess
import sys
from pathlib import Path


def main():
    """Run PyInstaller to build the TAILOR executable."""
    root = Path(__file__).parent.parent
    spec_file = root / "tailor.spec"

    if not spec_file.exists():
        print(f"Error: Spec file not found at {spec_file}")
        sys.exit(1)

    print("Building TAILOR executable...")
    print(f"Spec file: {spec_file}")
    print()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file),
    ]

    result = subprocess.run(cmd, cwd=root)

    if result.returncode == 0:
        dist_dir = root / "dist" / "TAILOR"
        if dist_dir.exists():
            exe_name = "TAILOR.exe" if sys.platform == "win32" else "TAILOR"
            exe_path = dist_dir / exe_name
            if exe_path.exists():
                size_mb = exe_path.stat().st_size / (1024 * 1024)
                print(f"\nBuild successful!")
                print(f"Executable: {exe_path}")
                print(f"Size: {size_mb:.1f} MB")
            else:
                print(f"\nBuild completed but executable not found at {exe_path}")
        else:
            print(f"\nBuild completed but dist directory not found at {dist_dir}")
    else:
        print(f"\nBuild failed with exit code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
