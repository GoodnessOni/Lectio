"""Private filesystem media. Filenames are opaque asset ids only."""

from __future__ import annotations

import re
from pathlib import Path

from .sniff import extension_for_mime

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_]+$")
_SAFE_FILE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9]+)?$")


def asset_rel_path(class_id: str, asset_id: str, mime: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(class_id) or not _SAFE_SEGMENT.fullmatch(asset_id):
        raise ValueError("invalid media path")
    ext = extension_for_mime(mime)
    return f"{class_id}/{asset_id}{ext}"


def resolve(media_dir: Path, rel_path: str) -> Path:
    if not isinstance(rel_path, str) or not rel_path or "\x00" in rel_path:
        raise ValueError("invalid media path")
    if rel_path.startswith("/") or rel_path.startswith("\\") or "\\" in rel_path:
        raise ValueError("invalid media path")
    parts = rel_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid media path")
    if len(parts) == 1:
        if not _SAFE_SEGMENT.fullmatch(parts[0]):
            raise ValueError("invalid media path")
    elif len(parts) == 2:
        if not _SAFE_SEGMENT.fullmatch(parts[0]) or not _SAFE_FILE.fullmatch(parts[1]):
            raise ValueError("invalid media path")
    else:
        raise ValueError("invalid media path")
    path = (media_dir / rel_path).resolve()
    root = media_dir.resolve()
    if root not in path.parents and path != root:
        raise ValueError("invalid media path")
    return path


def write_bytes(media_dir: Path, rel_path: str, data: bytes) -> Path:
    path = resolve(media_dir, rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def delete_path(media_dir: Path, rel_path: str) -> None:
    try:
        path = resolve(media_dir, rel_path)
    except ValueError:
        return
    if path.is_file():
        path.unlink()


def delete_class_dir(media_dir: Path, class_id: str) -> None:
    try:
        folder = resolve(media_dir, class_id)
    except ValueError:
        return
    if folder.is_dir():
        for child in folder.iterdir():
            if child.is_file():
                child.unlink()
        try:
            folder.rmdir()
        except OSError:
            pass
