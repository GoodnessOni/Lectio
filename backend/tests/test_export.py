import json
import zipfile
from io import BytesIO
from pathlib import Path

from tests.audio_gen import write_png
from tests.conftest import auth_headers, create_class, make_lecture, upload_recording


def install_reader(settings, *, include_tag=True, xss_probe=False):
    root = settings.offline_reader_dir
    (root / "assets").mkdir(parents=True, exist_ok=True)
    if include_tag:
        tag = '<script type="application/json" id="lectio-manifest">/* OG fills this */</script>'
    else:
        tag = "<p>missing tag</p>"
    (root / "index.html").write_text(
        "<!doctype html><html><head><link rel='stylesheet' href='assets/reader.css'>"
        "</head><body>" + tag + "<script src='assets/reader.js'></script></body></html>",
        encoding="utf-8",
    )
    (root / "assets" / "reader.js").write_text(
        "document.getElementById('lectio-manifest').textContent;",
        encoding="utf-8",
    )
    (root / "assets" / "reader.css").write_text("body{font-family:sans-serif}", encoding="utf-8")


def test_export_without_reader_is_honest(client, audio_dir, app):
    created = create_class(client)
    token = created["inviteToken"]
    lecture = make_lecture(client, token, created["id"])
    upload_recording(client, token, lecture["id"], audio_dir["clean"])
    client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
    body = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
    assert body["status"] == "ready"
    assert body["export"]["available"] is False
    assert body["export"]["downloadPath"] is None
    response = client.get(f"/v1/lectures/{lecture['id']}/export", headers=auth_headers(token))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "offline_reader_not_configured"


def test_export_zip_uses_relative_media_and_escaped_manifest(client, audio_dir, app, tmp_path):
    install_reader(app.state.settings)
    created = create_class(client)
    token = created["inviteToken"]
    lecture = make_lecture(client, token, created["id"])
    upload_recording(client, token, lecture["id"], audio_dir["clean"])
    photo = write_png(tmp_path / "board.png")
    with photo.open("rb") as handle:
        client.post(
            f"/v1/lectures/{lecture['id']}/photos",
            headers=auth_headers(token),
            files={"file": ("board.png", handle, "image/png")},
            data={"timestampSec": "12", "caption": "Board <script>alert(1)</script>"},
        )
    client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
    body = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
    assert body["export"]["available"] is True

    response = client.get(f"/v1/lectures/{lecture['id']}/export", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip")
    assert "attachment" in response.headers["content-disposition"]

    zf = zipfile.ZipFile(BytesIO(response.content))
    names = zf.namelist()
    for required in ("index.html", "assets/reader.js", "assets/reader.css", "manifest.json"):
        assert required in names
    assert any(n.startswith("audio/original") for n in names)
    assert any(n.startswith("photos/") for n in names)
    # No absolute or parent paths.
    for name in names:
        assert not name.startswith("/")
        assert ".." not in Path(name).parts

    html = zf.read("index.html").decode("utf-8")
    start = html.index('id="lectio-manifest"')
    tag_end = html.index(">", start) + 1
    close = html.index("</script>", tag_end)
    escaped = html[tag_end:close]
    assert "<script" not in escaped
    # The caption contains <script>; it must be escaped in the embedded JSON.
    assert "\\u003c" in escaped
    lecture_obj = json.loads(escaped)
    assert lecture_obj["id"] == lecture["id"]
    assert lecture_obj["recordings"]
    for rec in lecture_obj["recordings"]:
        if rec["selected"]:
            assert rec["audioUrl"].startswith("audio/original")
            assert not rec["audioUrl"].startswith("/v1/")
    if lecture_obj.get("cleanup") and lecture_obj["cleanup"].get("applied"):
        assert lecture_obj["cleanup"]["cleanedAudioUrl"] == "audio/cleaned.wav"
        assert "audio/cleaned.wav" in names
        assert lecture_obj["cleanup"]["originalAudioUrl"].startswith("audio/original")
    for photo_obj in lecture_obj["photos"]:
        assert photo_obj["imageUrl"].startswith("photos/")
        assert photo_obj["imageUrl"] in names

    # The tools copy exists and is JSON, but the reader does not need to fetch it.
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["id"] == lecture_obj["id"]


def test_export_before_success_is_conflict(client, audio_dir):
    created = create_class(client)
    token = created["inviteToken"]
    lecture = make_lecture(client, token, created["id"])
    upload_recording(client, token, lecture["id"], audio_dir["clean"])
    response = client.get(f"/v1/lectures/{lecture['id']}/export", headers=auth_headers(token))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "export_not_ready"
