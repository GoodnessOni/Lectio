from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import load_settings
from app.main import create_app
from tests.audio_gen import transcode, write_jpeg, write_png, write_wav
from tests.fakes import ScriptedProvider


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    reader_dir = tmp_path / "offline-reader"
    # Do not inherit a real key if one is later present in the environment.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LECTIO_DATA_DIR", str(data_dir))
    monkeypatch.setenv("LECTIO_OFFLINE_READER_DIR", str(reader_dir))
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    settings = load_settings(data_dir=data_dir)
    # Frozen dataclass: load_settings already used env for reader dir.
    return settings


@pytest.fixture
def provider():
    return ScriptedProvider()


@pytest.fixture
def app(tmp_settings, provider):
    return create_app(settings=tmp_settings, provider=provider, worker_mode="sync")


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def audio_dir(tmp_path):
    folder = tmp_path / "audio"
    folder.mkdir()
    clean = write_wav(folder / "clean.wav", duration=2.4, kind="clean")
    noisy = write_wav(folder / "noisy.wav", duration=1.2, kind="noisy")
    clipped = write_wav(folder / "clipped.wav", duration=2.0, kind="clipped")
    return {"clean": clean, "noisy": noisy, "clipped": clipped, "folder": folder}


def create_class(client, name="Goodness") -> dict:
    response = client.post(
        "/v1/classes",
        json={"courseCode": "MEE 301", "title": "Fluid Mechanics", "createdByDisplayName": name},
    )
    assert response.status_code == 201, response.text
    return response.json()["class"]


def auth_headers(token: str) -> dict:
    return {"X-Invite-Token": token}


def make_lecture(client, token: str, class_id: str) -> dict:
    response = client.post(
        f"/v1/classes/{class_id}/lectures",
        headers=auth_headers(token),
        json={"title": "Week 3: Bernoulli's Equation", "lectureDate": "2026-11-09"},
    )
    assert response.status_code == 201, response.text
    return response.json()["lecture"]


def upload_recording(client, token: str, lecture_id: str, path: Path, uploaded_by="Goodness"):
    with path.open("rb") as handle:
        response = client.post(
            f"/v1/lectures/{lecture_id}/recordings",
            headers=auth_headers(token),
            files={"file": (path.name, handle, "application/octet-stream")},
            data={"uploadedBy": uploaded_by},
        )
    return response
