"""Environment-backed settings. Secrets are never logged or written back to disk."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ[key] = value


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _origins(raw: str) -> tuple[str, ...]:
    items = []
    for part in raw.split(","):
        origin = part.strip()
        if not origin:
            continue
        if origin == "*":
            raise RuntimeError("CORS_ORIGINS cannot be a wildcard")
        items.append(origin)
    return tuple(items)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    offline_reader_dir: Path
    cors_origins: tuple[str, ...]
    max_recordings: int
    max_upload_bytes: int
    max_duration_sec: int
    groq_api_key: str | None
    groq_transcribe_model: str
    groq_chat_model: str
    groq_timeout_sec: float
    duration_tolerance_sec: float

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lectio.sqlite3"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def provider_configured(self) -> bool:
        return bool(self.groq_api_key)


def load_settings(data_dir: Path | None = None) -> Settings:
    _load_env_file(BACKEND_DIR / ".env")
    resolved_data = Path(data_dir) if data_dir is not None else Path(
        os.environ.get("LECTIO_DATA_DIR") or (BACKEND_DIR / "var")
    )
    reader = Path(
        os.environ.get("LECTIO_OFFLINE_READER_DIR") or (REPO_ROOT / "offline-reader")
    )
    key = os.environ.get("GROQ_API_KEY") or None
    if key is not None:
        key = key.strip() or None
    origins = _origins(
        os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        )
    )
    return Settings(
        data_dir=resolved_data,
        offline_reader_dir=reader,
        cors_origins=origins,
        max_recordings=_int_env("LECTIO_MAX_RECORDINGS", 3),
        max_upload_bytes=_int_env("LECTIO_MAX_UPLOAD_BYTES", 20 * 1024 * 1024),
        max_duration_sec=_int_env("LECTIO_MAX_DURATION_SEC", 180),
        groq_api_key=key,
        groq_transcribe_model=os.environ.get(
            "GROQ_TRANSCRIBE_MODEL", "whisper-large-v3-turbo"
        ),
        groq_chat_model=os.environ.get("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile"),
        groq_timeout_sec=float(os.environ.get("GROQ_TIMEOUT_SEC", "120")),
        duration_tolerance_sec=float(os.environ.get("LECTIO_DURATION_TOLERANCE_SEC", "1.0")),
    )
