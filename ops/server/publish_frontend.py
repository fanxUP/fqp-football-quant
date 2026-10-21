#!/usr/bin/env python3
"""Safely publish a built frontend into the fixed Nginx document root."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

WEB_ROOT = Path("/var/www/fqp")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_destination(web_root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"Unsafe frontend build path: {relative}")

    destination = web_root / relative
    current = web_root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise SystemExit(f"Symlink in Nginx web root: {current}")
        if current.exists() and not current.is_dir():
            raise SystemExit(f"Non-directory in Nginx web root: {current}")
        current.mkdir(exist_ok=True)

    if destination.is_symlink():
        raise SystemExit(f"Symlink target in Nginx web root: {destination}")
    return destination


def atomic_copy(source: Path, destination: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def local_entry_assets(index_html: str) -> list[tuple[str, PurePosixPath]]:
    assets: list[tuple[str, PurePosixPath]] = []
    for reference in re.findall(r"""(?:src|href)=["']([^"']+)["']""", index_html):
        parsed = urlsplit(reference)
        path = parsed.path
        if parsed.scheme or parsed.netloc or not path.startswith("/"):
            continue
        if not path.endswith((".js", ".css")):
            continue

        relative = PurePosixPath(unquote(path.lstrip("/")))
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit(f"Unsafe frontend entry reference: {reference}")
        assets.append((reference, relative))
    return assets


def publish(
    source_root: Path,
    web_root: Path,
    *,
    expected_web_root: Path = WEB_ROOT,
) -> int:
    if source_root.is_symlink() or not source_root.is_dir():
        raise SystemExit("Frontend build directory is missing or unsafe")
    if web_root != expected_web_root or web_root.is_symlink() or not web_root.is_dir():
        raise SystemExit("Configured Nginx web root is missing or unsafe")

    index_source = source_root / "index.html"
    if index_source.is_symlink() or not index_source.is_file():
        raise SystemExit("Frontend build has no regular index.html")

    changed = 0
    for source_file in sorted(source_root.rglob("*")):
        if source_file.is_symlink():
            raise SystemExit(f"Symlink in frontend build: {source_file}")
        if source_file.is_dir():
            continue
        if not source_file.is_file():
            raise SystemExit(f"Non-regular file in frontend build: {source_file}")
        if source_file == index_source:
            continue

        relative = source_file.relative_to(source_root)
        destination = safe_destination(web_root, relative)
        if destination.exists() and not destination.is_file():
            raise SystemExit(f"Non-file frontend destination: {destination}")
        if destination.is_file() and digest(source_file) == digest(destination):
            continue

        atomic_copy(source_file, destination)
        os.chmod(destination, stat.S_IMODE(source_file.stat().st_mode))
        changed += 1

    index_html = index_source.read_text(encoding="utf-8")
    for reference, relative in local_entry_assets(index_html):
        relative_path = Path(*relative.parts)
        source_asset = source_root / relative_path
        if source_asset.is_symlink() or not source_asset.is_file():
            raise SystemExit(f"Frontend build is missing a regular entry asset: {reference}")

        destination_asset = safe_destination(web_root, relative_path)
        if destination_asset.is_symlink() or not destination_asset.is_file():
            raise SystemExit(f"Frontend entry asset is missing: {reference}")
        if digest(source_asset) != digest(destination_asset):
            raise SystemExit(f"Frontend entry asset checksum mismatch: {reference}")

    index_destination = safe_destination(web_root, Path("index.html"))
    atomic_copy(index_source, index_destination)
    os.chmod(index_destination, stat.S_IMODE(index_source.stat().st_mode))
    print(f"Published frontend to {web_root}; updated {changed} assets; retained older assets")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("web_root", type=Path)
    args = parser.parse_args(argv)
    publish(args.source, args.web_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
