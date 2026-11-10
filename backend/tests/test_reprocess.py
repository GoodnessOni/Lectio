from app.provider import ProviderError
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import auth_headers, create_class, make_lecture, upload_recording
from tests.fakes import ScriptedProvider, sample_generation, sample_transcript


def test_successful_reprocess_publishes_revision_two(client, provider, audio_dir):
    created = create_class(client)
    token = created["inviteToken"]
    lecture = make_lecture(client, token, created["id"])
    clean = upload_recording(client, token, lecture["id"], audio_dir["clean"])
    noisy = upload_recording(client, token, lecture["id"], audio_dir["noisy"])
    clean_id = clean.json()["recording"]["id"]
    noisy_id = noisy.json()["recording"]["id"]

    first = client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
    assert first.status_code == 202
    ready = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
    assert ready["revision"] == 1
    assert ready["selection"]["recordingId"] == clean_id
    first_heading = ready["notes"]["sections"][0]["heading"]

    # Next generate call should label notes from the overridden recording.
    provider.transcribe_plan = [sample_transcript("B")]
    provider.generate_plan = [lambda t: sample_generation(t, heading_prefix="Revision 2")]

    second = client.post(
        f"/v1/lectures/{lecture['id']}/reprocess",
        headers=auth_headers(token),
        json={"recordingId": noisy_id},
    )
    assert second.status_code == 202, second.text
    updated = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
    assert updated["revision"] == 2
    assert updated["status"] == "ready"
    assert updated["selection"]["recordingId"] == noisy_id
    assert updated["selection"]["mode"] == "manual"
    assert updated["notes"]["sections"][0]["heading"].startswith("Revision 2")
    assert updated["notes"]["sections"][0]["heading"] != first_heading
    assert updated["job"]["revision"] == 2
    assert len(provider.transcribe_calls) == 2


def test_failed_reprocess_keeps_published_revision(tmp_settings, audio_dir):
    provider = ScriptedProvider()
    app = create_app(settings=tmp_settings, provider=provider, worker_mode="sync")
    with TestClient(app) as client:
        created = create_class(client)
        token = created["inviteToken"]
        lecture = make_lecture(client, token, created["id"])
        clean = upload_recording(client, token, lecture["id"], audio_dir["clean"])
        noisy = upload_recording(client, token, lecture["id"], audio_dir["noisy"])
        client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
        ready = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
        assert ready["revision"] == 1
        notes_before = ready["notes"]
        transcript_before = ready["transcript"]
        recording_before = ready["selection"]["recordingId"]

        provider.transcribe_plan = [ProviderError("Transcription failed at the AI provider.", retryable=True)]
        failed = client.post(
            f"/v1/lectures/{lecture['id']}/reprocess",
            headers=auth_headers(token),
            json={"recordingId": noisy.json()["recording"]["id"]},
        )
        assert failed.status_code == 202
        after = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
        assert after["status"] == "ready"
        assert after["revision"] == 1
        assert after["notes"] == notes_before
        assert after["transcript"] == transcript_before
        assert after["selection"]["recordingId"] == recording_before
        assert after["selection"]["pendingRecordingId"] is None
        assert after["job"]["status"] == "failed"
        assert after["job"]["error"]["code"] == "provider_error"
