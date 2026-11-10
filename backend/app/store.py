"""Data access helpers for classes, lectures, jobs, media, and members."""

from __future__ import annotations

from typing import Any

from . import storage
from .db import Database, dumps, loads
from .ids import new_id, new_invite_token, utc_now


def class_by_id(db: Database, class_id: str) -> dict | None:
    row = db.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
    return dict(row) if row else None


def class_by_token(db: Database, token: str) -> dict | None:
    row = db.execute("SELECT * FROM classes WHERE invite_token = ?", (token,)).fetchone()
    return dict(row) if row else None


def create_class(db: Database, course_code: str, title: str, created_by: str) -> dict:
    now = utc_now()
    cls = {
        "id": new_id("cls"),
        "course_code": course_code,
        "title": title,
        "invite_token": new_invite_token(),
        "created_at": now,
    }
    db.execute(
        "INSERT INTO classes(id, course_code, title, invite_token, created_at) VALUES (?,?,?,?,?)",
        (cls["id"], course_code, title, cls["invite_token"], now),
    )
    db.execute(
        "INSERT INTO members(class_id, display_name, created_at) VALUES (?,?,?)",
        (cls["id"], created_by, now),
    )
    return cls


def add_member(db: Database, class_id: str, display_name: str) -> None:
    now = utc_now()
    db.execute(
        "INSERT OR IGNORE INTO members(class_id, display_name, created_at) VALUES (?,?,?)",
        (class_id, display_name, now),
    )


def lectures_for_class(db: Database, class_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT id, title, lecture_date, status, revision, updated_at FROM lectures "
        "WHERE class_id = ? ORDER BY created_at DESC",
        (class_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def lecture_by_id(db: Database, lecture_id: str) -> dict | None:
    row = db.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
    return dict(row) if row else None


def create_lecture(db: Database, class_id: str, title: str, lecture_date: str) -> dict:
    now = utc_now()
    lec = {
        "id": new_id("lec"),
        "class_id": class_id,
        "title": title,
        "lecture_date": lecture_date,
        "status": "draft",
        "revision": 0,
        "created_at": now,
        "updated_at": now,
    }
    db.execute(
        "INSERT INTO lectures(id, class_id, title, lecture_date, status, revision, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (lec["id"], class_id, title, lecture_date, "draft", 0, now, now),
    )
    return lecture_by_id(db, lec["id"]) or lec


def touch_lecture(db: Database, lecture_id: str) -> None:
    db.execute("UPDATE lectures SET updated_at = ? WHERE id = ?", (utc_now(), lecture_id))


def recordings_for(db: Database, lecture_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM recordings WHERE lecture_id = ? ORDER BY sort_index ASC, created_at ASC",
        (lecture_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def recording_by_id(db: Database, recording_id: str) -> dict | None:
    row = db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    return dict(row) if row else None


def photos_for(db: Database, lecture_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM photos WHERE lecture_id = ? ORDER BY timestamp_sec ASC, created_at ASC",
        (lecture_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def asset_by_id(db: Database, asset_id: str) -> dict | None:
    row = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    return dict(row) if row else None


def add_asset(db: Database, asset_id: str, class_id: str, lecture_id: str, kind: str, mime: str, rel_path: str, size_bytes: int) -> dict:
    db.execute(
        "INSERT INTO assets(id, class_id, lecture_id, kind, mime_type, rel_path, size_bytes) "
        "VALUES (?,?,?,?,?,?,?)",
        (asset_id, class_id, lecture_id, kind, mime, rel_path, size_bytes),
    )
    return asset_by_id(db, asset_id)  # type: ignore[return-value]


def add_recording(
    db: Database,
    lecture_id: str,
    uploaded_by: str,
    file_name: str,
    mime_type: str,
    duration_sec: float,
    size_bytes: int,
    asset_id: str,
) -> dict:
    recs = recordings_for(db, lecture_id)
    now = utc_now()
    rec_id = new_id("rec")
    db.execute(
        "INSERT INTO recordings(id, lecture_id, uploaded_by, file_name, mime_type, duration_sec, "
        "size_bytes, quality_json, selected, selection_reason, asset_id, created_at, sort_index) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            rec_id,
            lecture_id,
            uploaded_by,
            file_name,
            mime_type,
            duration_sec,
            size_bytes,
            None,
            0,
            None,
            asset_id,
            now,
            len(recs),
        ),
    )
    touch_lecture(db, lecture_id)
    return recording_by_id(db, rec_id)  # type: ignore[return-value]


def add_photo(
    db: Database,
    lecture_id: str,
    file_name: str,
    mime_type: str,
    timestamp_sec: float,
    caption: str | None,
    asset_id: str,
) -> dict:
    now = utc_now()
    pho_id = new_id("pho")
    db.execute(
        "INSERT INTO photos(id, lecture_id, file_name, mime_type, timestamp_sec, caption, asset_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (pho_id, lecture_id, file_name, mime_type, timestamp_sec, caption, asset_id, now),
    )
    touch_lecture(db, lecture_id)
    return dict(db.execute("SELECT * FROM photos WHERE id = ?", (pho_id,)).fetchone())


def job_by_id(db: Database, job_id: str) -> dict | None:
    row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def latest_job(db: Database, lecture_id: str) -> dict | None:
    row = db.execute(
        "SELECT * FROM jobs WHERE lecture_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (lecture_id,),
    ).fetchone()
    return dict(row) if row else None


def job_is_active(job: dict | None) -> bool:
    return bool(job) and job["status"] in {"queued", "running"}


def create_job(db: Database, lecture_id: str, revision: int, target_recording_id: str | None = None) -> dict:
    now = utc_now()
    job_id = new_id("job")
    db.execute(
        "INSERT INTO jobs(id, lecture_id, status, stage, revision, target_recording_id, error_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (job_id, lecture_id, "queued", "queued", revision, target_recording_id, None, now, now),
    )
    db.execute(
        "UPDATE lectures SET status = ?, current_job_id = ?, error_json = NULL, updated_at = ? WHERE id = ?",
        ("processing", job_id, now, lecture_id),
    )
    return job_by_id(db, job_id)  # type: ignore[return-value]


def update_job(db: Database, job_id: str, **fields: Any) -> dict:
    fields["updated_at"] = utc_now()
    if "error" in fields:
        fields["error_json"] = dumps(fields.pop("error"))
    assignments = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    db.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)
    return job_by_id(db, job_id)  # type: ignore[return-value]


def set_pending(db: Database, lecture_id: str, recording_id: str | None, mode: str | None, explanation: str | None) -> None:
    db.execute(
        "UPDATE lectures SET pending_recording_id = ?, pending_mode = ?, pending_explanation = ?, updated_at = ? WHERE id = ?",
        (recording_id, mode, explanation, utc_now(), lecture_id),
    )


def set_qualities(db: Database, qualities: dict[str, dict]) -> None:
    for rec_id, quality in qualities.items():
        db.execute(
            "UPDATE recordings SET quality_json = ? WHERE id = ?",
            (dumps(quality), rec_id),
        )


def publish_success(
    db: Database,
    lecture: dict,
    job: dict,
    selection: dict,
    cleanup: dict | None,
    transcript: dict,
    notes: dict,
    questions: list,
    selected_recording_id: str,
    selection_reason: str,
    export_size_bytes: int | None,
) -> None:
    now = utc_now()
    db.execute(
        "UPDATE lectures SET status = ?, revision = ?, error_json = NULL, selection_json = ?, "
        "cleanup_json = ?, transcript_json = ?, notes_json = ?, questions_json = ?, "
        "pending_recording_id = NULL, pending_mode = NULL, pending_explanation = NULL, "
        "export_size_bytes = ?, updated_at = ? WHERE id = ?",
        (
            "ready",
            job["revision"],
            dumps(selection),
            dumps(cleanup),
            dumps(transcript),
            dumps(notes),
            dumps(questions),
            export_size_bytes,
            now,
            lecture["id"],
        ),
    )
    db.execute(
        "UPDATE recordings SET selected = 0, selection_reason = NULL WHERE lecture_id = ?",
        (lecture["id"],),
    )
    db.execute(
        "UPDATE recordings SET selected = 1, selection_reason = ? WHERE id = ?",
        (selection_reason, selected_recording_id),
    )
    update_job(db, job["id"], status="succeeded", stage="done", error=None)


def publish_failure(db: Database, lecture: dict, job: dict, error: dict) -> None:
    now = utc_now()
    # Keep published artifacts if a successful revision already exists.
    if lecture["revision"] and lecture["revision"] >= 1:
        status = "ready"
        error_json = None
    else:
        status = "failed"
        error_json = dumps(error)
    db.execute(
        "UPDATE lectures SET status = ?, error_json = ?, pending_recording_id = NULL, "
        "pending_mode = NULL, pending_explanation = NULL, updated_at = ? WHERE id = ?",
        (status, error_json, now, lecture["id"]),
    )
    update_job(db, job["id"], status="failed", error=error)


def set_export_size(db: Database, lecture_id: str, size_bytes: int | None) -> None:
    db.execute(
        "UPDATE lectures SET export_size_bytes = ?, updated_at = ? WHERE id = ?",
        (size_bytes, utc_now(), lecture_id),
    )


def delete_lecture(db: Database, media_dir, lecture_id: str) -> None:
    assets = db.execute("SELECT rel_path FROM assets WHERE lecture_id = ?", (lecture_id,)).fetchall()
    db.execute("DELETE FROM assets WHERE lecture_id = ?", (lecture_id,))
    db.execute("DELETE FROM recordings WHERE lecture_id = ?", (lecture_id,))
    db.execute("DELETE FROM photos WHERE lecture_id = ?", (lecture_id,))
    db.execute("DELETE FROM jobs WHERE lecture_id = ?", (lecture_id,))
    db.execute("DELETE FROM lectures WHERE id = ?", (lecture_id,))
    for row in assets:
        storage.delete_path(media_dir, row["rel_path"])


def delete_class(db: Database, media_dir, class_id: str) -> None:
    lectures = db.execute("SELECT id FROM lectures WHERE class_id = ?", (class_id,)).fetchall()
    for row in lectures:
        delete_lecture(db, media_dir, row["id"])
    db.execute("DELETE FROM members WHERE class_id = ?", (class_id,))
    db.execute("DELETE FROM classes WHERE id = ?", (class_id,))
    storage.delete_class_dir(media_dir, class_id)


def serialize_job(job: dict | None) -> dict | None:
    if job is None:
        return None
    return {
        "id": job["id"],
        "lectureId": job["lecture_id"],
        "status": job["status"],
        "stage": job["stage"],
        "revision": job["revision"],
        "targetRecordingId": job["target_recording_id"],
        "error": loads(job["error_json"]) if job.get("error_json") else None,
    }


def serialize_recording(rec: dict, published_selection: dict | None) -> dict:
    selected = bool(rec["selected"])
    reason = rec["selection_reason"]
    quality = loads(rec["quality_json"])
    return {
        "id": rec["id"],
        "uploadedBy": rec["uploaded_by"],
        "fileName": rec["file_name"],
        "mimeType": rec["mime_type"],
        "durationSec": rec["duration_sec"],
        "sizeBytes": rec["size_bytes"],
        "quality": quality,
        "selected": selected,
        "selectionReason": reason if selected else None,
        "audioAssetId": rec["asset_id"],
        "audioUrl": f"/v1/media/{rec['asset_id']}",
    }


def serialize_photo(photo: dict) -> dict:
    return {
        "id": photo["id"],
        "fileName": photo["file_name"],
        "mimeType": photo["mime_type"],
        "timestampSec": photo["timestamp_sec"],
        "caption": photo["caption"],
        "imageAssetId": photo["asset_id"],
        "imageUrl": f"/v1/media/{photo['asset_id']}",
    }


def serialize_selection(lecture: dict) -> dict | None:
    published = loads(lecture.get("selection_json"))
    pending_id = lecture.get("pending_recording_id")
    if published is None and not pending_id:
        return None
    if published is None:
        return {
            "recordingId": None,
            "pendingRecordingId": pending_id,
            "mode": lecture.get("pending_mode"),
            "explanation": lecture.get("pending_explanation"),
        }
    return {
        "recordingId": published.get("recordingId"),
        "pendingRecordingId": pending_id,
        "mode": published.get("mode") if not pending_id else (lecture.get("pending_mode") or published.get("mode")),
        "explanation": published.get("explanation")
        if not pending_id
        else (lecture.get("pending_explanation") or published.get("explanation")),
    }


def serialize_lecture(
    db: Database,
    lecture: dict,
    *,
    export_available: bool,
    course_code: str,
) -> dict:
    recs = recordings_for(db, lecture["id"])
    photos = photos_for(db, lecture["id"])
    job = None
    if lecture.get("current_job_id"):
        job = job_by_id(db, lecture["current_job_id"])
    if job is None:
        job = latest_job(db, lecture["id"])
    published = loads(lecture.get("selection_json"))
    export = (
        {
            "available": True,
            "sizeBytes": lecture.get("export_size_bytes"),
            "downloadPath": f"/v1/lectures/{lecture['id']}/export",
        }
        if export_available and lecture["revision"] >= 1
        else {"available": False, "sizeBytes": None, "downloadPath": None}
    )
    return {
        "id": lecture["id"],
        "classId": lecture["class_id"],
        "courseCode": course_code,
        "title": lecture["title"],
        "lectureDate": lecture["lecture_date"],
        "status": lecture["status"],
        "revision": lecture["revision"],
        "createdAt": lecture["created_at"],
        "updatedAt": lecture["updated_at"],
        "error": loads(lecture.get("error_json")),
        "job": serialize_job(job),
        "recordings": [serialize_recording(r, published) for r in recs],
        "selection": serialize_selection(lecture),
        "cleanup": loads(lecture.get("cleanup_json")),
        "transcript": loads(lecture.get("transcript_json")),
        "notes": loads(lecture.get("notes_json")),
        "photos": [serialize_photo(p) for p in photos],
        "questions": loads(lecture.get("questions_json")) or [],
        "export": export,
    }
