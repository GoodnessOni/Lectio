"""FastAPI application and v0.1 contract routes."""

from __future__ import annotations

import json
import logging
import math
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import audio, exporter, storage, store
from .audio import DecodeError
from .config import Settings, load_settings
from .db import Database
from .errors import (
    AppError,
    app_error_handler,
    http_exception_handler,
    unhandled_error_handler,
)
from .ids import new_id
from .pipeline import JobRunner, Pipeline
from .provider import provider_from_settings
from .sniff import SniffError, sniff_audio, sniff_image
from .store import serialize_job, serialize_lecture, serialize_photo, serialize_recording

log = logging.getLogger("lectio")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INVITE_HEADER = "x-invite-token"
JSON_BODY_MAX = 64 * 1024


class BodyLimitMiddleware:
    """Reject clearly oversized request bodies before handlers buffer them."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        length_header = headers.get("content-length")
        if length_header:
            try:
                length = int(length_header)
            except ValueError:
                length = 0
            if length > self.max_bytes:
                await self._reject(receive, send, already_consumed=False)
                return
        total = 0
        overflow = False

        async def limited_receive():
            nonlocal total, overflow
            message = await receive()
            if overflow:
                return message
            if message["type"] == "http.request":
                total += len(message.get("body") or b"")
                if total > self.max_bytes:
                    overflow = True
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._reject(receive, send, already_consumed=True)

    async def _reject(self, receive, send, already_consumed: bool) -> None:
        if not already_consumed:
            more = True
            while more:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break
                if message["type"] == "http.request":
                    more = bool(message.get("more_body"))
        body = json.dumps(
            {
                "error": {
                    "code": "file_too_large",
                    "message": "The request is larger than the demo upload limit.",
                    "retryable": False,
                }
            }
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode("ascii")],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass


def _clean_text(value: Any, field: str, *, max_len: int, required: bool = True) -> str:
    if value is None:
        if required:
            raise AppError(400, "invalid_request", f"{field} is required.")
        return ""
    if not isinstance(value, str):
        raise AppError(400, "invalid_request", f"{field} must be a string.")
    text = value.strip()
    if required and not text:
        raise AppError(400, "invalid_request", f"{field} is required.")
    if len(text) > max_len:
        raise AppError(400, "invalid_request", f"{field} is too long.")
    return text


def _safe_filename(name: str | None, fallback: str) -> str:
    raw = (name or "").replace("\\", "/").replace("\x00", "")
    base = Path(raw).name.strip()
    if not base or base in {".", ".."}:
        return fallback
    return base[:200]


def _finite_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AppError(400, "invalid_request", f"{field} must be a number.") from exc
    if not math.isfinite(number):
        raise AppError(400, "invalid_request", f"{field} must be a finite number.")
    return number


def _require_token(request: Request) -> str:
    token = request.headers.get(INVITE_HEADER) or request.headers.get("X-Invite-Token")
    if not token or not token.strip():
        raise AppError(401, "unauthorized", "Missing invite token.")
    return token.strip()


def _class_from_token(db: Database, token: str) -> dict:
    cls = store.class_by_token(db, token)
    if cls is None:
        raise AppError(401, "unauthorized", "Invalid invite token.")
    return cls


def _require_class(request: Request, class_id: str) -> dict:
    token = _require_token(request)
    cls = _class_from_token(request.app.state.db, token)
    if cls["id"] != class_id:
        raise AppError(404, "not_found", "Class not found.")
    return cls


def _require_lecture(request: Request, lecture_id: str) -> tuple[dict, dict]:
    token = _require_token(request)
    cls = _class_from_token(request.app.state.db, token)
    lecture = store.lecture_by_id(request.app.state.db, lecture_id)
    if lecture is None or lecture["class_id"] != cls["id"]:
        raise AppError(404, "not_found", "Lecture not found.")
    return cls, lecture


def _lecture_processing(db: Database, lecture: dict) -> bool:
    job = None
    if lecture.get("current_job_id"):
        job = store.job_by_id(db, lecture["current_job_id"])
    return store.job_is_active(job)


def _export_available(settings: Settings, lecture: dict) -> bool:
    return lecture.get("revision", 0) >= 1 and exporter.reader_is_configured(settings.offline_reader_dir)


def _lecture_payload(request: Request, lecture: dict, course_code: str) -> dict:
    settings: Settings = request.app.state.settings
    return serialize_lecture(
        request.app.state.db,
        lecture,
        export_available=_export_available(settings, lecture),
        course_code=course_code,
    )


async def _read_capped(request: Request, upload: UploadFile, max_bytes: int) -> bytes:
    header = request.headers.get("content-length")
    if header:
        try:
            length = int(header)
        except ValueError:
            length = None
        else:
            # Multipart includes extra wrapper bytes; still reject clearly oversized requests.
            if length > max_bytes + (1024 * 1024):
                raise AppError(400, "file_too_large", "The file is larger than the 20 MB demo limit.")
    chunks: list[bytes] = []
    total = 0
    while True:
        piece = await upload.read(64 * 1024)
        if not piece:
            break
        total += len(piece)
        if total > max_bytes:
            raise AppError(400, "file_too_large", "The file is larger than the 20 MB demo limit.")
        chunks.append(piece)
    if total == 0:
        raise AppError(400, "invalid_request", "A file is required.")
    return b"".join(chunks)


async def _optional_json(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    if len(raw) > JSON_BODY_MAX:
        raise AppError(400, "invalid_request", "Request body is too large.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AppError(400, "invalid_request", "Request body must be JSON.") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise AppError(400, "invalid_request", "Request body must be a JSON object.")
    return data


def create_app(
    settings: Settings | None = None,
    provider=None,
    worker_mode: str = "thread",
) -> FastAPI:
    settings = settings or load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    ai = provider if provider is not None else provider_from_settings(settings)
    pipeline = Pipeline(db, settings.media_dir, ai)
    runner = JobRunner(pipeline, mode=worker_mode)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runner.start()
        yield
        runner.stop()
        db.close()

    app = FastAPI(title="Lectio", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.provider = ai
    app.state.runner = runner
    app.state.pipeline = pipeline

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["X-Invite-Token", "Content-Type", "Accept"],
        max_age=600,
    )
    # Multipart wrapper bytes are allowed a 1 MB margin on top of the file cap.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_upload_bytes + (1024 * 1024))
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/v1/classes", status_code=201)
    async def create_class(request: Request):
        body = await _optional_json(request)
        course = _clean_text(body.get("courseCode"), "courseCode", max_len=80)
        title = _clean_text(body.get("title"), "title", max_len=200)
        created_by = _clean_text(body.get("createdByDisplayName"), "createdByDisplayName", max_len=80)
        with db.immediate():
            cls = store.create_class(db, course, title, created_by)
        return {
            "class": {
                "id": cls["id"],
                "courseCode": cls["course_code"],
                "title": cls["title"],
                "inviteToken": cls["invite_token"],
                "createdAt": cls["created_at"],
            }
        }

    @app.post("/v1/classes/join")
    async def join_class(request: Request):
        body = await _optional_json(request)
        token = _clean_text(body.get("inviteToken"), "inviteToken", max_len=200)
        name = _clean_text(body.get("displayName"), "displayName", max_len=80)
        with db.immediate():
            cls = store.class_by_token(db, token)
            if cls is None:
                raise AppError(401, "unauthorized", "Invalid invite token.")
            store.add_member(db, cls["id"], name)
        return {
            "class": {"id": cls["id"], "courseCode": cls["course_code"], "title": cls["title"]},
            "member": {"displayName": name},
        }

    @app.get("/v1/classes/{class_id}")
    def get_class(request: Request, class_id: str):
        cls = _require_class(request, class_id)
        lectures = [
            {
                "id": item["id"],
                "title": item["title"],
                "lectureDate": item["lecture_date"],
                "status": item["status"],
                "revision": item["revision"],
                "updatedAt": item["updated_at"],
            }
            for item in store.lectures_for_class(db, cls["id"])
        ]
        return {
            "class": {
                "id": cls["id"],
                "courseCode": cls["course_code"],
                "title": cls["title"],
                "inviteToken": cls["invite_token"],
            },
            "lectures": lectures,
        }

    @app.delete("/v1/classes/{class_id}", status_code=204)
    def delete_class(request: Request, class_id: str):
        _require_class(request, class_id)
        with db.immediate():
            store.delete_class(db, settings.media_dir, class_id)
        return Response(status_code=204)

    @app.post("/v1/classes/{class_id}/lectures", status_code=201)
    async def create_lecture(request: Request, class_id: str):
        cls = _require_class(request, class_id)
        body = await _optional_json(request)
        title = _clean_text(body.get("title"), "title", max_len=200)
        lecture_date = _clean_text(body.get("lectureDate"), "lectureDate", max_len=32)
        if not DATE_RE.match(lecture_date):
            raise AppError(400, "invalid_request", "lectureDate must be YYYY-MM-DD.")
        with db.immediate():
            lecture = store.create_lecture(db, cls["id"], title, lecture_date)
        # Reload after commit
        lecture = store.lecture_by_id(db, lecture["id"])
        return {"lecture": _lecture_payload(request, lecture, cls["course_code"])}

    @app.get("/v1/lectures/{lecture_id}")
    def get_lecture(request: Request, lecture_id: str):
        cls, lecture = _require_lecture(request, lecture_id)
        return {"lecture": _lecture_payload(request, lecture, cls["course_code"])}

    @app.delete("/v1/lectures/{lecture_id}", status_code=204)
    def delete_lecture(request: Request, lecture_id: str):
        _require_lecture(request, lecture_id)
        with db.immediate():
            store.delete_lecture(db, settings.media_dir, lecture_id)
        return Response(status_code=204)

    @app.post("/v1/lectures/{lecture_id}/recordings", status_code=201)
    async def upload_recording(
        request: Request,
        lecture_id: str,
        file: UploadFile = File(...),
        uploadedBy: str = Form(...),
    ):
        cls, lecture = _require_lecture(request, lecture_id)
        uploaded_by = _clean_text(uploadedBy, "uploadedBy", max_len=80)
        if _lecture_processing(db, lecture):
            raise AppError(409, "lecture_processing", "This lecture is already being processed.")
        recs = store.recordings_for(db, lecture_id)
        if len(recs) >= settings.max_recordings:
            raise AppError(400, "recording_limit", "This lecture already has the maximum of 3 recordings.")
        data = await _read_capped(request, file, settings.max_upload_bytes)
        try:
            mime = sniff_audio(data)
        except SniffError as exc:
            raise AppError(400, "unsupported_type", exc.message) from exc
        # Persist under an opaque name, then decode for duration.
        asset_id = new_id("ast")
        rel = storage.asset_rel_path(cls["id"], asset_id, mime)
        path = storage.write_bytes(settings.media_dir, rel, data)
        try:
            duration = audio.probe_duration_sec(path)
            # Confirm ffmpeg can actually decode samples, not just read a header.
            audio.decode_pcm16_mono(path)
        except DecodeError as exc:
            path.unlink(missing_ok=True)
            raise AppError(400, "unsupported_type", exc.message) from exc
        if duration > settings.max_duration_sec + settings.duration_tolerance_sec:
            path.unlink(missing_ok=True)
            raise AppError(400, "duration_too_long", "Each recording can be at most 3 minutes in this demo.")
        original_name = _safe_filename(file.filename, "recording")
        # Re-check limit inside the write lock so two concurrent uploads cannot sneak a 4th file.
        with db.immediate():
            lecture = store.lecture_by_id(db, lecture_id)
            if lecture is None or lecture["class_id"] != cls["id"]:
                path.unlink(missing_ok=True)
                raise AppError(404, "not_found", "Lecture not found.")
            if _lecture_processing(db, lecture):
                path.unlink(missing_ok=True)
                raise AppError(409, "lecture_processing", "This lecture is already being processed.")
            recs = store.recordings_for(db, lecture_id)
            if len(recs) >= settings.max_recordings:
                path.unlink(missing_ok=True)
                raise AppError(400, "recording_limit", "This lecture already has the maximum of 3 recordings.")
            store.add_asset(db, asset_id, cls["id"], lecture_id, "recording", mime, rel, len(data))
            rec = store.add_recording(
                db,
                lecture_id,
                uploaded_by,
                original_name,
                mime,
                round(duration, 3),
                len(data),
                asset_id,
            )
        return {"recording": serialize_recording(rec, None)}

    @app.post("/v1/lectures/{lecture_id}/photos", status_code=201)
    async def upload_photo(
        request: Request,
        lecture_id: str,
        file: UploadFile = File(...),
        timestampSec: str = Form(...),
        caption: str | None = Form(None),
    ):
        cls, lecture = _require_lecture(request, lecture_id)
        if _lecture_processing(db, lecture):
            raise AppError(409, "lecture_processing", "This lecture is already being processed.")
        timestamp = _finite_float(timestampSec, "timestampSec")
        if timestamp < 0:
            raise AppError(400, "invalid_request", "timestampSec cannot be negative.")
        cap = _clean_text(caption, "caption", max_len=300, required=False) or None
        data = await _read_capped(request, file, settings.max_upload_bytes)
        try:
            mime = sniff_image(data)
        except SniffError as exc:
            raise AppError(400, "unsupported_type", exc.message) from exc
        asset_id = new_id("ast")
        rel = storage.asset_rel_path(cls["id"], asset_id, mime)
        storage.write_bytes(settings.media_dir, rel, data)
        original_name = _safe_filename(file.filename, "photo")
        with db.immediate():
            lecture = store.lecture_by_id(db, lecture_id)
            if lecture is None or lecture["class_id"] != cls["id"]:
                storage.delete_path(settings.media_dir, rel)
                raise AppError(404, "not_found", "Lecture not found.")
            if _lecture_processing(db, lecture):
                storage.delete_path(settings.media_dir, rel)
                raise AppError(409, "lecture_processing", "This lecture is already being processed.")
            store.add_asset(db, asset_id, cls["id"], lecture_id, "photo", mime, rel, len(data))
            photo = store.add_photo(db, lecture_id, original_name, mime, timestamp, cap, asset_id)
        return {"photo": serialize_photo(photo)}

    def _enqueue_process(lecture: dict, recording_id: str | None, *, is_reprocess: bool) -> dict:
        latest = store.latest_job(db, lecture["id"])
        with db.immediate():
            lecture = store.lecture_by_id(db, lecture["id"])
            latest = store.latest_job(db, lecture["id"])
            if store.job_is_active(latest):
                if is_reprocess:
                    raise AppError(409, "lecture_processing", "This lecture is already being processed.")
                return serialize_job(latest)
            if (
                not is_reprocess
                and lecture["status"] == "ready"
                and lecture["revision"] >= 1
            ):
                return serialize_job(latest)
            recs = store.recordings_for(db, lecture["id"])
            if not recs:
                raise AppError(400, "no_recordings", "Upload at least one recording before processing.")
            rec_ids = {r["id"] for r in recs}
            target = recording_id
            mode = None
            explanation = None
            if is_reprocess and target is None:
                if latest and latest.get("target_recording_id"):
                    target = latest["target_recording_id"]
                else:
                    from .db import loads

                    published = loads(lecture.get("selection_json")) or {}
                    target = published.get("recordingId")
            if target is not None and target not in rec_ids:
                raise AppError(400, "invalid_recording", "That recording is not part of this lecture.")
            if target is not None:
                mode = "manual"
                explanation = audio.manual_explanation()
            next_revision = (lecture["revision"] or 0) + 1
            job = store.create_job(db, lecture["id"], next_revision, target)
            if target is not None:
                store.set_pending(db, lecture["id"], target, mode, explanation)
        runner.submit(job["id"])
        return serialize_job(store.job_by_id(db, job["id"]))

    @app.post("/v1/lectures/{lecture_id}/process", status_code=202)
    async def process_lecture(request: Request, lecture_id: str):
        _cls, lecture = _require_lecture(request, lecture_id)
        body = await _optional_json(request)
        recording_id = body.get("recordingId")
        if recording_id is not None:
            recording_id = _clean_text(recording_id, "recordingId", max_len=80)
        job = _enqueue_process(lecture, recording_id, is_reprocess=False)
        return {"job": job}

    @app.post("/v1/lectures/{lecture_id}/reprocess", status_code=202)
    async def reprocess_lecture(request: Request, lecture_id: str):
        _cls, lecture = _require_lecture(request, lecture_id)
        body = await _optional_json(request)
        recording_id = body.get("recordingId")
        if recording_id is not None:
            recording_id = _clean_text(recording_id, "recordingId", max_len=80)
        job = _enqueue_process(lecture, recording_id, is_reprocess=True)
        return {"job": job}

    @app.get("/v1/lectures/{lecture_id}/job")
    def get_job(request: Request, lecture_id: str):
        _cls, lecture = _require_lecture(request, lecture_id)
        job = None
        if lecture.get("current_job_id"):
            job = store.job_by_id(db, lecture["current_job_id"])
        if job is None:
            job = store.latest_job(db, lecture_id)
        return {"job": serialize_job(job)}

    @app.get("/v1/lectures/{lecture_id}/export")
    def export_lecture(request: Request, lecture_id: str):
        cls, lecture = _require_lecture(request, lecture_id)
        data = exporter.build_zip(
            db,
            lecture,
            cls["course_code"],
            settings.media_dir,
            settings.offline_reader_dir,
        )
        with db.immediate():
            store.set_export_size(db, lecture_id, len(data))
        filename = f"lectio-{lecture_id}.zip"
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/v1/media/{asset_id}")
    def get_media(request: Request, asset_id: str):
        token = _require_token(request)
        cls = _class_from_token(db, token)
        asset = store.asset_by_id(db, asset_id)
        if asset is None or asset["class_id"] != cls["id"]:
            raise AppError(404, "not_found", "Asset not found.")
        try:
            path = storage.resolve(settings.media_dir, asset["rel_path"])
        except ValueError as exc:
            raise AppError(404, "not_found", "Asset not found.") from exc
        if not path.is_file():
            raise AppError(404, "not_found", "Asset not found.")
        return Response(content=path.read_bytes(), media_type=asset["mime_type"])

    return app

