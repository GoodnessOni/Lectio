from pathlib import Path

from tests.audio_gen import transcode, write_png, write_wav
from tests.conftest import auth_headers, create_class, make_lecture, upload_recording


def _setup(client):
    created = create_class(client)
    lecture = make_lecture(client, created["inviteToken"], created["id"])
    return created, lecture


def test_accepted_audio_types_are_decoded(client, audio_dir, tmp_path):
    created, lecture = _setup(client)
    token = created["inviteToken"]
    mapping = {
        "wav": audio_dir["clean"],
        "mp3": transcode(audio_dir["clean"], tmp_path / "c.mp3", "mp3"),
        "m4a": transcode(audio_dir["clean"], tmp_path / "c.m4a", "m4a"),
        "ogg": transcode(audio_dir["clean"], tmp_path / "c.ogg", "ogg"),
        "webm": transcode(audio_dir["clean"], tmp_path / "c.webm", "webm"),
    }
    expected_mime = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "ogg": "audio/ogg",
        "webm": "audio/webm",
    }
    # Contract limit is 3 recordings per lecture, so use a fresh lecture per type after the first three.
    first_three = ["wav", "mp3", "m4a"]
    for kind in first_three:
        response = upload_recording(client, token, lecture["id"], mapping[kind])
        assert response.status_code == 201, response.text
        rec = response.json()["recording"]
        assert rec["mimeType"] == expected_mime[kind]
        assert rec["quality"] is None
        assert rec["selected"] is False
        assert rec["durationSec"] > 0
    lecture2 = make_lecture(client, token, created["id"])
    lecture2["id"]  # new lecture
    # Use a different title by posting again? make_lecture uses the same title, that's fine.
    for kind in ["ogg", "webm"]:
        response = upload_recording(client, token, lecture2["id"], mapping[kind])
        assert response.status_code == 201, response.text
        assert response.json()["recording"]["mimeType"] == expected_mime[kind]


def test_rejects_unsupported_type(client, tmp_path):
    created, lecture = _setup(client)
    path = tmp_path / "notes.txt"
    path.write_bytes(b"this is not audio")
    response = upload_recording(client, created["inviteToken"], lecture["id"], path)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_type"


def test_rejects_fourth_recording(client, audio_dir):
    created, lecture = _setup(client)
    token = created["inviteToken"]
    for _ in range(3):
        response = upload_recording(client, token, lecture["id"], audio_dir["clean"])
        assert response.status_code == 201, response.text
    fourth = upload_recording(client, token, lecture["id"], audio_dir["noisy"])
    assert fourth.status_code == 400
    assert fourth.json()["error"]["code"] == "recording_limit"


def test_rejects_oversize_file(client, tmp_settings, tmp_path, audio_dir):
    # Shrink the cap so the test stays small and deterministic.
    object.__setattr__(tmp_settings, "max_upload_bytes", 2000)
    created, lecture = _setup(client)
    # The clean wav is larger than 2000 bytes.
    response = upload_recording(client, created["inviteToken"], lecture["id"], audio_dir["clean"])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file_too_large"


def test_rejects_over_duration(client, tmp_settings, tmp_path):
    object.__setattr__(tmp_settings, "max_duration_sec", 1)
    object.__setattr__(tmp_settings, "duration_tolerance_sec", 0.05)
    created, lecture = _setup(client)
    long_file = write_wav(tmp_path / "long.wav", duration=2.0, kind="clean")
    response = upload_recording(client, created["inviteToken"], lecture["id"], long_file)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "duration_too_long"


def test_photo_upload_and_token_media(client, tmp_path):
    created, lecture = _setup(client)
    token = created["inviteToken"]
    photo = write_png(tmp_path / "board.png")
    with photo.open("rb") as handle:
        response = client.post(
            f"/v1/lectures/{lecture['id']}/photos",
            headers=auth_headers(token),
            files={"file": ("board.png", handle, "image/png")},
            data={"timestampSec": "60", "caption": "Board work"},
        )
    assert response.status_code == 201, response.text
    body = response.json()["photo"]
    assert body["timestampSec"] == 60
    assert body["imageUrl"].startswith("/v1/media/")
    media = client.get(body["imageUrl"], headers=auth_headers(token))
    assert media.status_code == 200
    assert media.headers["content-type"].startswith("image/png")
    assert media.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_storage_uses_opaque_asset_ids(client, audio_dir, app):
    created, lecture = _setup(client)
    response = upload_recording(client, created["inviteToken"], lecture["id"], audio_dir["clean"])
    rec = response.json()["recording"]
    assert rec["fileName"] == "clean.wav"
    asset_id = rec["audioAssetId"]
    media_dir = app.state.settings.media_dir
    stored = list(media_dir.rglob("*"))
    file_paths = [p for p in stored if p.is_file()]
    assert file_paths
    for path in file_paths:
        assert "clean.wav" not in path.name
        assert asset_id in path.name
