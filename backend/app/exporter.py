"""Offline zip packaging. The backend never claims a UI it did not receive from David."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

from . import storage, store
from .db import Database
from .errors import AppError
from .sniff import extension_for_mime

READER_FILES = (
    ("index.html", Path("index.html")),
    ("assets/reader.js", Path("assets") / "reader.js"),
    ("assets/reader.css", Path("assets") / "reader.css"),
)


def reader_is_configured(reader_dir: Path) -> bool:
    return all((reader_dir / rel).is_file() for _, rel in READER_FILES)


def escape_manifest_json(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Prevent lecture text from breaking out of the script tag.
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def inject_manifest(html: str, escaped_json: str) -> str:
    start_token = 'id="lectio-manifest"'
    lower = html
    idx = lower.find(start_token)
    if idx < 0:
        # Allow single-quoted attribute as a slight HTML variation.
        start_token = "id='lectio-manifest'"
        idx = lower.find(start_token)
    if idx < 0:
        raise AppError(
            409,
            "offline_reader_invalid",
            "The offline reader is missing the lectio-manifest script tag.",
        )
    # Find the opening tag that contains the id, then its closing tag.
    tag_start = lower.rfind("<script", 0, idx)
    if tag_start < 0:
        raise AppError(
            409,
            "offline_reader_invalid",
            "The offline reader is missing the lectio-manifest script tag.",
        )
    tag_end = lower.find(">", idx)
    close = lower.find("</script>", tag_end)
    if tag_end < 0 or close < 0:
        raise AppError(
            409,
            "offline_reader_invalid",
            "The offline reader manifest tag could not be updated.",
        )
    return html[: tag_end + 1] + escaped_json + html[close:]


def _safe_arcname(name: str) -> str:
    if name.startswith("/") or ".." in Path(name).parts or name.startswith("\\"):
        raise AppError(500, "export_error", "Refusing an unsafe zip path.")
    return name.replace("\\", "/")


def build_offline_lecture(
    db: Database,
    lecture: dict,
    course_code: str,
    media_dir: Path,
) -> dict:
    """Lecture object with relative media paths for the offline pack."""
    # export_available is about the API download, not used inside the pack.
    packed = store.serialize_lecture(db, lecture, export_available=False, course_code=course_code)
    recs = {r["id"]: r for r in store.recordings_for(db, lecture["id"])}
    published = packed.get("selection") or {}
    rec_id = published.get("recordingId")
    rec = recs.get(rec_id) if rec_id else None
    original_name = None
    if rec:
        ext = extension_for_mime(rec["mime_type"]) or ".audio"
        original_name = f"audio/original{ext}"
        for item in packed["recordings"]:
            if item["id"] == rec["id"]:
                item["audioUrl"] = original_name
        if packed.get("cleanup"):
            packed["cleanup"]["originalAudioUrl"] = original_name
    cleaned_name = None
    cleanup = packed.get("cleanup") or {}
    if cleanup.get("applied") and cleanup.get("cleanedAudioAssetId"):
        cleaned_name = "audio/cleaned.wav"
        packed["cleanup"]["cleanedAudioUrl"] = cleaned_name
    photo_names = {}
    for photo in packed["photos"]:
        src = next(p for p in store.photos_for(db, lecture["id"]) if p["id"] == photo["id"])
        ext = extension_for_mime(src["mime_type"]) or ".img"
        name = f"photos/{photo['id']}{ext}"
        photo["imageUrl"] = name
        photo_names[photo["id"]] = (name, src["asset_id"])
    packed["export"] = {"available": False, "sizeBytes": None, "downloadPath": None}
    return {
        "lecture": packed,
        "original_name": original_name,
        "original_asset_id": rec["asset_id"] if rec else None,
        "cleaned_name": cleaned_name,
        "cleaned_asset_id": cleanup.get("cleanedAudioAssetId"),
        "photo_names": photo_names,
    }


def build_zip(
    db: Database,
    lecture: dict,
    course_code: str,
    media_dir: Path,
    reader_dir: Path,
) -> bytes:
    if lecture.get("revision", 0) < 1:
        raise AppError(409, "export_not_ready", "Export is available after a successful process.")
    if not reader_is_configured(reader_dir):
        raise AppError(
            409,
            "offline_reader_not_configured",
            "The offline study pack is not ready yet. The offline reader files have not been added.",
        )
    built = build_offline_lecture(db, lecture, course_code, media_dir)
    escaped = escape_manifest_json(built["lecture"])
    html = (reader_dir / "index.html").read_text(encoding="utf-8")
    html = inject_manifest(html, escaped)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_safe_arcname("index.html"), html.encode("utf-8"))
        for arc, rel in READER_FILES:
            if arc == "index.html":
                continue
            data = (reader_dir / rel).read_bytes()
            zf.writestr(_safe_arcname(arc), data)
        zf.writestr(
            _safe_arcname("manifest.json"),
            json.dumps(built["lecture"], ensure_ascii=False, indent=2).encode("utf-8"),
        )
        if built["original_name"] and built["original_asset_id"]:
            asset = store.asset_by_id(db, built["original_asset_id"])
            path = storage.resolve(media_dir, asset["rel_path"])
            zf.write(path, arcname=_safe_arcname(built["original_name"]))
        if built["cleaned_name"] and built["cleaned_asset_id"]:
            asset = store.asset_by_id(db, built["cleaned_asset_id"])
            if asset:
                path = storage.resolve(media_dir, asset["rel_path"])
                zf.write(path, arcname=_safe_arcname(built["cleaned_name"]))
        for _photo_id, (name, asset_id) in built["photo_names"].items():
            asset = store.asset_by_id(db, asset_id)
            path = storage.resolve(media_dir, asset["rel_path"])
            zf.write(path, arcname=_safe_arcname(name))
        # Refuse any external/absolute names that slipped in.
        for info in zf.infolist():
            _safe_arcname(info.filename)
            if info.filename.startswith("/") or info.filename.startswith("\\"):
                raise AppError(500, "export_error", "Refusing an unsafe zip path.")
    return buffer.getvalue()
