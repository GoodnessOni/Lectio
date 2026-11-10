"""Synthetic audio helpers for tests. These are not real lecture-hall recordings."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(args: list[str]) -> None:
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "ffmpeg failed")



def write_pcm_wav(path: Path, samples, sample_rate: int = 16000) -> Path:
    import wave
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(samples)
    if data.dtype != np.int16:
        data = np.clip(data, -1.0, 1.0)
        data = (data * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(data.tobytes())
    return path

def write_wav(path: Path, *, duration: float, kind: str = "clean") -> Path:
    """Generate a synthetic wav.

    clean: mid-level pulsed tone (speech-energy proxy) and a quiet floor.
    noisy: weaker pulses under loud white noise.
    clipped: very loud tone that hits full scale.
    short: same as clean, caller chooses duration.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "clean":
        # 700 Hz bursts with quiet gaps, amplitude well below clipping.
        filt = (
            "sine=frequency=700:sample_rate=16000,"
            "volume=0.3,"
            f"aloop=loop=-1:size=1600,"
            "afade=t=in:st=0:d=0.01,"
            f"atrim=0:{duration}"
        )
        # Pulsed by multiplying with a slow square-like tremolo.
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=700:sample_rate=16000:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=color=white:amplitude=0.01:sample_rate=16000:duration={duration}",
            "-filter_complex",
            "amemets=0,volume=0.28,agate=threshold=0.0001[a];[1:a][a]amix=inputs=2:duration=first:dropout_transition=0,volume=1",
            str(path),
        ]
        # The filter above is fragile. Use a simpler, reliable graph instead.
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=700:sample_rate=16000:duration={duration},volume=0.28,tremolo=f=5:d=0.8",
            str(path),
        ]
    elif kind == "noisy":
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=700:sample_rate=16000:duration={duration},volume=0.05,tremolo=f=5:d=0.8",
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=color=white:amplitude=0.45:sample_rate=16000:duration={duration}",
            "-filter_complex",
            "amix=inputs=2:duration=first:dropout_transition=0,volume=1.4",
            str(path),
        ]
    elif kind == "clipped":
        import numpy as np

        sample_rate = 16000
        n = int(duration * sample_rate)
        t = np.arange(n) / sample_rate
        # Deliberately force a large fraction of samples onto the rails.
        samples = np.clip(2.5 * np.sin(2 * np.pi * 400 * t), -1.0, 1.0)
        return write_pcm_wav(path, samples, sample_rate)
    else:
        raise ValueError(kind)
    _run(cmd)
    return path


def transcode(src: Path, dest: Path, mime_kind: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mime_kind == "mp3":
        args = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c:a", "libmp3lame", "-b:a", "64k", str(dest)]
    elif mime_kind == "m4a":
        args = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c:a", "aac", "-b:a", "64k", str(dest)]
    elif mime_kind == "ogg":
        args = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c:a", "libvorbis", str(dest)]
    elif mime_kind == "webm":
        args = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c:a", "libopus", "-b:a", "48k", str(dest)]
    elif mime_kind == "wav":
        args = ["ffmpeg", "-y", "-v", "error", "-i", str(src), str(dest)]
    else:
        raise ValueError(mime_kind)
    _run(args)
    return dest


def write_png(path: Path, color: tuple[int, int, int] = (200, 80, 40)) -> Path:
    """Minimal 1x1 or 8x8 PNG, no extra dependencies."""
    import struct
    import zlib

    width = height = 8
    r, g, b = color
    raw = b"".join(b"\x00" + bytes([r, g, b] * width) for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.write_bytes(data)
    return path


def write_jpeg(path: Path) -> Path:
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=32x32",
            "-frames:v",
            "1",
            str(path),
        ]
    )
    return path
