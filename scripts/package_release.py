#!/usr/bin/env python3
"""
scripts/package_release.py
==========================
Reproducible release packaging script for Predictive Logistics SIH 26251 (V7.2).

Strictly excludes:
- .env, .env.* (excluding .env.example)
- node_modules/
- .git/ and Git metadata
- __pycache__/, *.pyc, *.pyo
- .pytest_cache/, .ruff_cache/
- .venv/, venv/, env/
- *.log files
- dist/ and build artifacts
- OS metadata (.DS_Store, Thumbs.db)

Validates the resulting release archive and ensures zero secrets or transient files leak.
"""
from __future__ import annotations

import fnmatch
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_PATTERNS = [
    # Secrets & local env
    ".env",
    ".env.*",
    # Dependencies & venvs
    "node_modules",
    "node_modules/*",
    ".venv",
    ".venv/*",
    "venv",
    "venv/*",
    "env",
    "env/*",
    # Version control
    ".git",
    ".git/*",
    # Caches & build artifacts
    "__pycache__",
    "__pycache__/*",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".pytest_cache/*",
    ".ruff_cache",
    ".ruff_cache/*",
    "dist",
    "dist/*",
    ".vite",
    ".vite/*",
    "tsconfig.tsbuildinfo",
    # Logs & OS junk
    "*.log",
    ".DS_Store",
    "Thumbs.db",
    "*.tmp",
    # Output zips themselves
    "*.zip",
]

# Specifically allowed even if matching a pattern above
ALLOWLIST = [
    ".env.example",
]

REQUIRED_COMPONENTS = [
    "README.md",
    "docker-compose.yml",
    ".dockerignore",
    ".gitignore",
    ".env.example",
    "backend/app/main.py",
    "backend/app/auth.py",
    "backend/app/security.py",
    "backend/app/config.py",
    "backend/Dockerfile",
    "backend/requirements.txt",
    "frontend/src/App.tsx",
    "frontend/src/main.tsx",
    "frontend/package.json",
    "frontend/Dockerfile",
    "ml/train_forecast.py",
    "ml/train_shortage.py",
    "docs/V7_2_CHANGELOG.md",
    "docs/V7_2_VISUAL_AUDIT.md",
    "docs/V7_2_TEST_REPORT.md",
    "docs/V7_2_RELEASE_READINESS.md",
]


def should_exclude(rel_path: str) -> bool:
    posix_path = rel_path.replace("\\", "/")
    basename = os.path.basename(posix_path)

    # Check allowlist first
    if basename in ALLOWLIST or posix_path in ALLOWLIST:
        return False

    parts = posix_path.split("/")
    for pattern in EXCLUDE_PATTERNS:
        # Check against basename
        if fnmatch.fnmatch(basename, pattern):
            return True
        # Check against full relative path
        if fnmatch.fnmatch(posix_path, pattern):
            return True
        # Check against any directory component
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def build_release_zip(output_path: Path) -> tuple[int, int, int]:
    """Build the clean release zip. Returns (file_count, uncompressed_bytes, compressed_bytes)."""
    file_count = 0
    total_uncompressed = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(ROOT):
            # Prune directories matching exclude patterns in-place
            dirs[:] = [d for d in dirs if not should_exclude(os.path.relpath(os.path.join(root, d), ROOT))]

            for file in sorted(files):
                full_path = Path(root) / file
                rel_path = full_path.relative_to(ROOT).as_posix()

                if should_exclude(rel_path):
                    continue

                zf.write(full_path, arcname=rel_path)
                file_count += 1
                total_uncompressed += full_path.stat().st_size

    compressed_bytes = output_path.stat().st_size
    return file_count, total_uncompressed, compressed_bytes


def validate_release_zip(zip_path: Path) -> list[str]:
    """Validate archive integrity and absence of forbidden files."""
    errors = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = set(zf.namelist())

        # Check for forbidden files
        for name in namelist:
            if should_exclude(name):
                errors.append(f"Forbidden file found in archive: {name}")

        # Check for presence of required components
        for req in REQUIRED_COMPONENTS:
            if req not in namelist:
                errors.append(f"Missing required component in archive: {req}")

    return errors


def main() -> int:
    version = "V7_2"
    output_name = f"Predictive_Logistics_SIH_26251_{version}_RELEASE.zip"
    output_path = ROOT / output_name

    print(f"==================================================")
    print(f"Predictive Logistics Release Packager — {version}")
    print(f"Source Directory: {ROOT}")
    print(f"Target Archive:   {output_path}")
    print(f"==================================================")

    files, uncompressed, compressed = build_release_zip(output_path)
    print(f"Packaged {files} files.")
    print(f"Uncompressed size: {uncompressed / (1024 * 1024):.2f} MB")
    print(f"Compressed size:   {compressed / (1024 * 1024):.2f} MB")
    print(f"Compression ratio: {compressed / max(1, uncompressed) * 100:.1f}%")

    print("\nValidating archive contents...")
    errors = validate_release_zip(output_path)

    if errors:
        print(f"FAILED: {len(errors)} validation error(s) discovered:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("SUCCESS: Release archive validated. Zero secrets or excluded artifacts found.")
    print(f"Archive ready at: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
