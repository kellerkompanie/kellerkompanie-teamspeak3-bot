#!/usr/bin/env python3
"""Deploy script for uploading and installing Debian package on remote host.

Works on Windows, macOS, and Linux.
Usage: python deploy_deb.py <hostname>
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional


def get_latest_deb(dist_dir: Path) -> Optional[Path]:
    """Get the latest .deb file from dist directory."""
    deb_files = list(dist_dir.glob("*.deb"))
    if not deb_files:
        return None
    # Sort by modification time, newest first
    return max(deb_files, key=lambda f: f.stat().st_mtime)


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and return success status."""
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"ERROR: {description}")
        return False
    return True


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy Debian package to remote host",
    )
    parser.add_argument(
        "hostname",
        help="Target hostname (e.g., user@server.example.com)",
    )
    args = parser.parse_args()

    # Get project root (parent of scripts directory)
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent
    dist_dir = project_root / "dist"

    print("=" * 48)
    print("  Kellerkompanie TS3 Bot - Deploy Debian Package")
    print("=" * 48)
    print()

    # Check if dist directory exists
    if not dist_dir.exists():
        print("ERROR: dist directory not found")
        print("Please run build_deb.py first")
        return 1

    # Find the latest .deb file
    deb_file = get_latest_deb(dist_dir)
    if not deb_file:
        print("ERROR: No .deb file found in dist directory")
        print("Please run build_deb.py first")
        return 1

    deb_filename = deb_file.name
    host = args.hostname

    print(f"Latest package: {deb_filename}")
    print(f"Target host: {host}")
    print()

    # Upload the .deb file
    print(f"[1/2] Uploading package to {host}...")
    if not run_command(
        ["scp", str(deb_file), f"{host}:/tmp/{deb_filename}"],
        "Failed to upload package",
    ):
        return 1

    # Install the package using apt (automatically installs dependencies)
    print()
    print(f"[2/2] Installing package on {host}...")
    install_cmd = (
        f"sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a "
        f"apt install --reinstall -f -y /tmp/{deb_filename} && "
        f"rm /tmp/{deb_filename}"
    )
    if not run_command(
        ["ssh", "-t", host, install_cmd],
        "Failed to install package",
    ):
        return 1

    print()
    print("=" * 48)
    print("  Deployment Complete!")
    print("=" * 48)
    print()
    print(f"Package {deb_filename} installed on {host}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
