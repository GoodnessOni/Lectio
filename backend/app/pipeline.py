"""Once-only processing pipeline: rank, select, clean, transcribe one file, generate, publish."""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

from . import audio, storage, store
from .db import Database
from .errors import AppError
from .ids import new_id
from .provider import ProviderError, ProviderNotConfigured, validate_generation

log = logging.getLogger("lectio.pipeline")


class Pipeline:
    def __init__(self, db: Database, media_dir: Path, provider, export_available_fn=None):
        self.db = db
        self.media_dir = media_dir
        self.provider = provider
        self.export_available_fn = export_available_fn

    def run(self, job_id: str) -> None:
        job = store.job_by_id(self.db, job_id)
        if job is None:
            return
        lecture = store.lecture_by_id(self.db, job["lecture_id"])
        if lecture is None:
            return
        try:
            store.update_job(self.db, job_id, status="running", stage="ranking")
            qualities, recs = self._rank(lecture["id"])
            store.update_job(self.db, job_id, stage="selecting")
            # Reload job: target may already have been requested at enqueue time.
            job = store.job_by_id(self.db, job_id)
            requested = job.get("target_recording_id")
            rec_ids = [r["id"] for r in recs]
            if requested:
                if requested not in rec_ids:
                    raise AppError(400, "invalid_recording", "That recording is not part of this lecture.")
                chosen = requested
                mode = "manual"
                explanation = audio.manual_explanation()
            else:
                chosen = audio.choose_auto(qualities, rec_ids)
                mode = "auto"
                explanation = audio.auto_explanation(qualities[chosen])
            store.set_pending(self.db, lecture["id"], chosen, mode, explanation)
            store.update_job(self.db, job_id, target_recording_id=chosen, stage="cleaning")

            rec = store.recording_by_id(self.db, chosen)
            asset = store.asset_by_id(self.db, rec["asset_id"])
            src = storage.resolve(self.media_dir, asset["rel_path"])

            cleanup = self._cleanup(lecture, rec, src)

            store.update_job(self.db, job_id, stage="transcribing")
            transcript = self.provider.transcribe(src, rec["mime_type"])

            store.update_job(self.db, job_id, stage="generating")
            generated = self.provider.generate(transcript)
            notes, questions = generated["notes"], generated["questions"]
            # Belt and braces: validate again even if the provider already did.
            notes, questions = validate_generation(
                {"notes": notes, "questions": questions}, transcript
            )
            if not notes["sections"]:
                raise ProviderError(
                    "The AI provider returned no notes that could be tied to the transcript.",
                    retryable=True,
                )

            selection = {
                "recordingId": chosen,
                "pendingRecordingId": None,
                "mode": mode,
                "explanation": explanation,
            }
            job = store.job_by_id(self.db, job_id)
            lecture = store.lecture_by_id(self.db, lecture["id"])
            export_size = None
            with self.db.immediate():
                store.publish_success(
                    self.db,
                    lecture,
                    job,
                    selection=selection,
                    cleanup=cleanup,
                    transcript=transcript,
                    notes=notes,
                    questions=questions,
                    selected_recording_id=chosen,
                    selection_reason=mode,
                    export_size_bytes=export_size,
                )
            log.info("job %s published revision %s", job_id, job["revision"])
        except ProviderNotConfigured as exc:
            self._fail(lecture, job_id, exc.error_body())
        except ProviderError as exc:
            self._fail(lecture, job_id, exc.error_body())
        except AppError as exc:
            self._fail(
                lecture,
                job_id,
                {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
            )
        except Exception:
            log.exception("job %s failed unexpectedly", job_id)
            self._fail(
                lecture,
                job_id,
                {
                    "code": "pipeline_error",
                    "message": "Processing failed unexpectedly.",
                    "retryable": True,
                },
            )

    def _rank(self, lecture_id: str) -> tuple[dict, list[dict]]:
        recs = store.recordings_for(self.db, lecture_id)
        if not recs:
            raise AppError(400, "no_recordings", "Upload at least one recording before processing.")
        measured = []
        for rec in recs:
            asset = store.asset_by_id(self.db, rec["asset_id"])
            path = storage.resolve(self.media_dir, asset["rel_path"])
            samples = audio.decode_pcm16_mono(path)
            intrinsic = audio.measure_intrinsic(samples, rec["duration_sec"])
            measured.append((rec["id"], intrinsic))
        qualities = audio.rank_set(measured)
        store.set_qualities(self.db, qualities)
        return qualities, recs

    def _cleanup(self, lecture: dict, rec: dict, src: Path) -> dict:
        clean_id = new_id("ast")
        dest_rel = storage.asset_rel_path(lecture["class_id"], clean_id, "audio/wav")
        dest = storage.resolve(self.media_dir, dest_rel)
        applied = audio.basic_cleanup(src, dest)
        original = {
            "applied": False,
            "method": "basic_noise_reduction",
            "cleanedAudioAssetId": None,
            "originalAudioAssetId": rec["asset_id"],
            "cleanedAudioUrl": None,
            "originalAudioUrl": f"/v1/media/{rec['asset_id']}",
        }
        if not applied:
            return original
        store.add_asset(
            self.db,
            clean_id,
            lecture["class_id"],
            lecture["id"],
            "cleaned",
            "audio/wav",
            dest_rel,
            dest.stat().st_size,
        )
        return {
            "applied": True,
            "method": "basic_noise_reduction",
            "cleanedAudioAssetId": clean_id,
            "originalAudioAssetId": rec["asset_id"],
            "cleanedAudioUrl": f"/v1/media/{clean_id}",
            "originalAudioUrl": f"/v1/media/{rec['asset_id']}",
        }

    def _fail(self, lecture: dict, job_id: str, error: dict) -> None:
        current = store.lecture_by_id(self.db, lecture["id"]) or lecture
        job = store.job_by_id(self.db, job_id)
        if job is None:
            return
        with self.db.immediate():
            store.publish_failure(self.db, current, job, error)
        log.info("job %s failed code=%s", job_id, error.get("code"))


class JobRunner:
    """Background worker with a per-lecture concurrency guard at enqueue time."""

    def __init__(self, pipeline: Pipeline, mode: str = "thread"):
        self.pipeline = pipeline
        self.mode = mode
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Optional test hook: block after entering the worker, before run().
        self.hold: threading.Event | None = None
        self.entered: threading.Event | None = None

    def start(self) -> None:
        if self.mode != "thread":
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lectio-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put("__stop__")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def submit(self, job_id: str) -> None:
        if self.mode == "sync":
            self.pipeline.run(job_id)
            return
        self._queue.put(job_id)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if job_id == "__stop__":
                return
            if self.entered is not None:
                self.entered.set()
            if self.hold is not None:
                self.hold.wait(timeout=30)
            try:
                self.pipeline.run(job_id)
            except Exception:
                log.exception("worker crashed on a job")
