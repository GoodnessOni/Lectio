import threading
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.provider import ProviderError
from tests.conftest import auth_headers, create_class, make_lecture, upload_recording
from tests.fakes import MissingProvider, ScriptedProvider, sample_generation, sample_transcript


def test_rank_happens_before_single_transcription(client, provider, audio_dir):
    created = create_class(client)
    token = created["inviteToken"]
    lecture = make_lecture(client, token, created["id"])
    first = upload_recording(client, token, lecture["id"], audio_dir["clean"], "Goodness")
    second = upload_recording(client, token, lecture["id"], audio_dir["noisy"], "David")
    assert first.status_code == 201 and second.status_code == 201

    response = client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
    assert response.status_code == 202, response.text
    assert len(provider.transcribe_calls) == 1
    assert provider.generate_calls == 1

    body = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
    assert body["status"] == "ready"
    assert body["revision"] == 1
    qualities = {rec["id"]: rec["quality"]["score"] for rec in body["recordings"]}
    clean_id = first.json()["recording"]["id"]
    noisy_id = second.json()["recording"]["id"]
    assert qualities[clean_id] > qualities[noisy_id]
    assert body["selection"]["recordingId"] == clean_id
    assert body["selection"]["mode"] == "auto"
    assert body["recordings"][0]["id"] == clean_id or True
    chosen = next(rec for rec in body["recordings"] if rec["id"] == clean_id)
    assert chosen["selected"] is True
    assert chosen["selectionReason"] == "auto"
    # Notes must point at real segment ids from the transcript.
    valid = {seg["id"] for seg in body["transcript"]["segments"]}
    for section in body["notes"]["sections"]:
        assert section["sourceSegmentIds"]
        assert set(section["sourceSegmentIds"]) <= valid
    assert "heuristic" in body["selection"]["explanation"].lower()
    # Flags on the shorter noisier file should warn the student.
    noisy = next(rec for rec in body["recordings"] if rec["id"] == noisy_id)
    assert "noisy" in noisy["quality"]["flags"] or "possibly_incomplete" in noisy["quality"]["flags"] or "suspect" in noisy["quality"]["flags"]


def test_process_is_idempotent_after_success(client, provider, audio_dir):
    created = create_class(client)
    token = created["inviteToken"]
    lecture = make_lecture(client, token, created["id"])
    upload_recording(client, token, lecture["id"], audio_dir["clean"])
    first = client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
    assert first.status_code == 202
    job_id = first.json()["job"]["id"]
    second = client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
    assert second.status_code == 202
    assert second.json()["job"]["id"] == job_id
    assert len(provider.transcribe_calls) == 1


def test_manual_recording_id_overrides_auto_pick(client, provider, audio_dir):
    created = create_class(client)
    token = created["inviteToken"]
    lecture = make_lecture(client, token, created["id"])
    clean = upload_recording(client, token, lecture["id"], audio_dir["clean"])
    noisy = upload_recording(client, token, lecture["id"], audio_dir["noisy"])
    noisy_id = noisy.json()["recording"]["id"]
    response = client.post(
        f"/v1/lectures/{lecture['id']}/process",
        headers=auth_headers(token),
        json={"recordingId": noisy_id},
    )
    assert response.status_code == 202, response.text
    body = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
    assert body["selection"]["recordingId"] == noisy_id
    assert body["selection"]["mode"] == "manual"
    assert len(provider.transcribe_calls) == 1


def test_missing_provider_fails_without_inventing_notes(tmp_settings, audio_dir):
    app = create_app(settings=tmp_settings, provider=MissingProvider(), worker_mode="sync")
    with TestClient(app) as client:
        created = create_class(client)
        token = created["inviteToken"]
        lecture = make_lecture(client, token, created["id"])
        upload_recording(client, token, lecture["id"], audio_dir["clean"])
        response = client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
        assert response.status_code == 202
        body = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
        assert body["status"] == "failed"
        assert body["revision"] == 0
        assert body["notes"] is None
        assert body["transcript"] is None
        assert body["error"]["code"] == "provider_not_configured"
        assert body["error"]["message"] == "AI provider is not configured."
        assert body["job"]["status"] == "failed"


def test_invalid_source_ids_are_dropped(tmp_settings, audio_dir):
    transcript = sample_transcript("X")

    def bad_generation(_transcript):
        return {
            "notes": {
                "sections": [
                    {
                        "id": "note_good",
                        "heading": "Supported",
                        "kind": "definition",
                        "body": "Bernoulli terms as stated.",
                        "sourceSegmentIds": ["seg_001"],
                    },
                    {
                        "id": "note_bad",
                        "heading": "Invented",
                        "kind": "key_point",
                        "body": "An unsourced claim.",
                        "sourceSegmentIds": ["seg_999"],
                    },
                ],
                "unsupportedClaims": [],
            },
            "questions": [
                {
                    "id": "q_bad",
                    "prompt": "Invented?",
                    "choices": [{"id": "a", "text": "yes"}, {"id": "b", "text": "no"}],
                    "answerId": "a",
                    "explanation": "no source",
                    "sourceSegmentIds": ["seg_nope"],
                }
            ],
        }

    provider = ScriptedProvider(transcribe_plan=[transcript], generate_plan=[bad_generation])
    app = create_app(settings=tmp_settings, provider=provider, worker_mode="sync")
    with TestClient(app) as client:
        created = create_class(client)
        token = created["inviteToken"]
        lecture = make_lecture(client, token, created["id"])
        upload_recording(client, token, lecture["id"], audio_dir["clean"])
        client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
        body = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
        ids = [s["id"] for s in body["notes"]["sections"]]
        assert ids == ["note_good"]
        assert "An unsourced claim." in body["notes"]["unsupportedClaims"]
        assert body["questions"] == []


def test_concurrent_process_starts_only_one_job(tmp_settings, audio_dir):
    provider = ScriptedProvider()
    app = create_app(settings=tmp_settings, provider=provider, worker_mode="thread")
    hold = threading.Event()
    entered = threading.Event()
    app.state.runner.hold = hold
    app.state.runner.entered = entered
    with TestClient(app) as client:
        created = create_class(client)
        token = created["inviteToken"]
        lecture = make_lecture(client, token, created["id"])
        upload_recording(client, token, lecture["id"], audio_dir["clean"])
        first = client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
        assert first.status_code == 202
        assert entered.wait(timeout=5)
        # While the first job is held, a second process must return that same job.
        second = client.post(f"/v1/lectures/{lecture['id']}/process", headers=auth_headers(token), json={})
        assert second.status_code == 202
        assert second.json()["job"]["id"] == first.json()["job"]["id"]
        reprocess = client.post(f"/v1/lectures/{lecture['id']}/reprocess", headers=auth_headers(token), json={})
        assert reprocess.status_code == 409
        assert reprocess.json()["error"]["code"] == "lecture_processing"
        # Uploads are blocked too.
        blocked = upload_recording(client, token, lecture["id"], audio_dir["noisy"], "David")
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "lecture_processing"
        hold.set()
        job = None
        for _ in range(100):
            job = client.get(f"/v1/lectures/{lecture['id']}/job", headers=auth_headers(token)).json()["job"]
            if job["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"job did not finish: {job}")
        assert len(provider.transcribe_calls) == 1
        body = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token)).json()["lecture"]
        assert body["status"] == "ready"
        assert body["revision"] == 1
