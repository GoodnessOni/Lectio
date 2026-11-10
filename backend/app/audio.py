"""Decode, duration, heuristic ranking, and basic noise cleanup via ffmpeg.

Ranking uses simple energy features as a speech/noise *proxy*. It is not a
real voice-activity or lecture-hall quality model. Flags tell the student to
listen before trusting an auto pick.
"""

from __future__ import annotations

import logging
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("lectio.audio")

SAMPLE_RATE = 16000
FFMPEG_TIMEOUT = 30
# Frames for the energy proxy.
FRAME_MS = 30
HOP_MS = 15


class DecodeError(Exception):
    def __init__(self, message: str = "The audio file could not be decoded."):
        self.message = message
        super().__init__(message)


def _run(args: list[str], timeout: int = FFMPEG_TIMEOUT, raw_out: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        timeout=timeout,
        text=not raw_out,
    )


def probe_duration_sec(path: Path) -> float:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    if result.returncode != 0:
        raise DecodeError("The audio file could not be decoded.")
    try:
        duration = float((result.stdout or "").strip())
    except ValueError as exc:
        raise DecodeError("The audio file has no readable duration.") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise DecodeError("The audio file has no usable duration.")
    return duration


def decode_pcm16_mono(path: Path) -> np.ndarray:
    """Return float32 samples in [-1, 1] at 16 kHz mono."""
    try:
        result = _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "pipe:1",
            ],
            raw_out=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise DecodeError("Decoding the audio file timed out.") from exc
    if result.returncode != 0 or not result.stdout:
        raise DecodeError("The audio file could not be decoded.")
    samples = np.frombuffer(result.stdout, dtype=np.int16)
    if samples.size == 0:
        raise DecodeError("The audio file contained no samples.")
    return samples.astype(np.float32) / 32768.0


def _frame_rms(samples: np.ndarray) -> np.ndarray:
    frame = int(SAMPLE_RATE * FRAME_MS / 1000)
    hop = int(SAMPLE_RATE * HOP_MS / 1000)
    if samples.size < frame:
        rms = float(np.sqrt(np.mean(samples**2) + 1e-12))
        return np.array([rms], dtype=np.float32)
    starts = range(0, samples.size - frame + 1, hop)
    values = [
        float(np.sqrt(np.mean(samples[s : s + frame] ** 2) + 1e-12))
        for s in starts
    ]
    return np.asarray(values, dtype=np.float32)


def _db(rms: np.ndarray | float) -> np.ndarray | float:
    return 20.0 * np.log10(np.maximum(rms, 1e-8))


@dataclass
class IntrinsicQuality:
    speech_ratio: float
    noise_level_db: float
    clipping_ratio: float
    coverage_sec: float
    flags: list[str]
    intrinsic_score: float


def measure_intrinsic(samples: np.ndarray, duration_sec: float) -> IntrinsicQuality:
    rms = _frame_rms(samples)
    frame_db = _db(rms)
    noise_level_db = float(np.percentile(frame_db, 20))
    speech_threshold = noise_level_db + 8.0
    speech_ratio = float(np.mean(frame_db >= speech_threshold))
    clipping_ratio = float(np.mean(np.abs(samples) >= 0.99))

    flags: list[str] = []
    if noise_level_db > -30:
        flags.append("noisy")
    if clipping_ratio >= 0.01:
        flags.append("clipping")
    if speech_ratio < 0.40:
        flags.append("low_speech")

    # Map a quieter floor (more negative dB) to a higher score.
    # -60 dB -> 1, -20 dB -> 0.
    noise_score = float(np.clip((-noise_level_db - 20.0) / 40.0, 0.0, 1.0))
    clip_score = float(np.clip(1.0 - clipping_ratio / 0.05, 0.0, 1.0))
    intrinsic = (
        0.40 * speech_ratio
        + 0.30 * noise_score
        + 0.20 * clip_score
        + 0.10 * 1.0  # placeholder; coverage weight applied in rank_set
    )
    return IntrinsicQuality(
        speech_ratio=round(speech_ratio, 4),
        noise_level_db=round(noise_level_db, 1),
        clipping_ratio=round(clipping_ratio, 4),
        coverage_sec=round(float(duration_sec), 1),
        flags=flags,
        intrinsic_score=intrinsic,
    )


def rank_set(
    items: list[tuple[str, IntrinsicQuality]],
) -> dict[str, dict]:
    """Apply relative-duration coverage and produce contract quality objects.

    items: list of (recording_id, intrinsic)
    """
    if not items:
        return {}
    max_cov = max(item.coverage_sec for _, item in items) or 1.0
    qualities: dict[str, dict] = {}
    for rec_id, intrinsic in items:
        coverage_score = float(np.clip(intrinsic.coverage_sec / max_cov, 0.0, 1.0))
        # Replace the 0.10 placeholder with real coverage, keep other weights.
        score = (intrinsic.intrinsic_score - 0.10) + 0.10 * coverage_score
        flags = list(intrinsic.flags)
        if intrinsic.coverage_sec < 0.75 * max_cov:
            flags.append("possibly_incomplete")
        if len(flags) >= 2 or score < 0.35:
            if "suspect" not in flags:
                flags.append("suspect")
        qualities[rec_id] = {
            "score": round(float(np.clip(score, 0.0, 1.0)), 2),
            "speechRatio": intrinsic.speech_ratio,
            "noiseLevelDb": intrinsic.noise_level_db,
            "clippingRatio": intrinsic.clipping_ratio,
            "coverageSec": intrinsic.coverage_sec,
            "flags": flags,
        }
    return qualities


def choose_auto(qualities: dict[str, dict], rec_order: list[str]) -> str:
    def key(rec_id: str):
        q = qualities[rec_id]
        # Higher score wins. Ties: earlier upload (stable).
        return (-q["score"], rec_order.index(rec_id))

    return min(rec_order, key=key)


def auto_explanation(quality: dict) -> str:
    bits = ["Highest heuristic score"]
    if quality.get("flags"):
        bits.append("some quality flags were set")
    else:
        bits.append("less estimated background noise and longest coverage")
    return (
        bits[0]
        + ": "
        + bits[1]
        + ". Heuristic only, please listen and override if wrong."
    )


def manual_explanation() -> str:
    return (
        "This recording was chosen by a class member. "
        "Heuristic scores are a guide only, please listen and override if wrong."
    )


def basic_cleanup(src: Path, dest: Path) -> bool:
    """Apply basic noise reduction. Returns True if a cleaned file was written.

    This is not lecturer-voice isolation. The original file is left untouched.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Prefer FFT denoise + a gentle high-pass. Fall back if a filter is missing.
    filters = [
        "highpass=f=80,afftdn=nr=12:nf=-25",
        "highpass=f=80,anlmdn",
        "highpass=f=80",
    ]
    for filt in filters:
        try:
            result = _run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(src),
                    "-af",
                    filt,
                    "-ac",
                    "1",
                    "-ar",
                    str(SAMPLE_RATE),
                    str(dest),
                ]
            )
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0 and dest.is_file() and dest.stat().st_size > 0:
            return True
        if dest.exists():
            dest.unlink()
    log.warning("basic cleanup skipped; no working ffmpeg filter")
    return False
