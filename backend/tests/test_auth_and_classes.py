from tests.conftest import auth_headers, create_class, make_lecture, upload_recording


def test_create_and_join_same_class_with_invite_token(client):
    created = create_class(client, "Goodness")
    token = created["inviteToken"]
    assert token.startswith("tok_")
    assert len(token) > 20

    joined = client.post(
        "/v1/classes/join",
        json={"inviteToken": token, "displayName": "David"},
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["class"]["id"] == created["id"]
    assert joined.json()["member"]["displayName"] == "David"

    seen = client.get(f"/v1/classes/{created['id']}", headers=auth_headers(token))
    assert seen.status_code == 200
    body = seen.json()
    assert body["class"]["inviteToken"] == token
    assert body["lectures"] == []


def test_missing_or_bad_token_is_401(client):
    created = create_class(client)
    missing = client.get(f"/v1/classes/{created['id']}")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"

    bad = client.get(f"/v1/classes/{created['id']}", headers=auth_headers("tok_notreal"))
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "unauthorized"


def test_cross_class_token_cannot_read_or_fetch_media(client, audio_dir):
    a = create_class(client, "Goodness")
    b = create_class(client, "Other")
    lecture = make_lecture(client, a["inviteToken"], a["id"])
    uploaded = upload_recording(client, a["inviteToken"], lecture["id"], audio_dir["clean"])
    assert uploaded.status_code == 201, uploaded.text
    asset_id = uploaded.json()["recording"]["audioAssetId"]

    leaked = client.get(
        f"/v1/lectures/{lecture['id']}",
        headers=auth_headers(b["inviteToken"]),
    )
    assert leaked.status_code == 404

    media = client.get(f"/v1/media/{asset_id}", headers=auth_headers(b["inviteToken"]))
    assert media.status_code == 404

    no_header = client.get(f"/v1/media/{asset_id}")
    assert no_header.status_code == 401


def test_token_cannot_be_required_from_query_string(client, audio_dir):
    created = create_class(client)
    lecture = make_lecture(client, created["inviteToken"], created["id"])
    uploaded = upload_recording(client, created["inviteToken"], lecture["id"], audio_dir["clean"])
    asset_id = uploaded.json()["recording"]["audioAssetId"]
    # A query parameter must not grant access.
    response = client.get(f"/v1/media/{asset_id}?token={created['inviteToken']}")
    assert response.status_code == 401


def test_member_can_delete_lecture_and_class_from_app_storage(client, audio_dir):
    created = create_class(client)
    token = created["inviteToken"]
    lecture = make_lecture(client, token, created["id"])
    uploaded = upload_recording(client, token, lecture["id"], audio_dir["clean"])
    asset_id = uploaded.json()["recording"]["audioAssetId"]

    deleted = client.delete(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token))
    assert deleted.status_code == 204
    missing = client.get(f"/v1/lectures/{lecture['id']}", headers=auth_headers(token))
    assert missing.status_code == 404
    media = client.get(f"/v1/media/{asset_id}", headers=auth_headers(token))
    assert media.status_code == 404

    removed = client.delete(f"/v1/classes/{created['id']}", headers=auth_headers(token))
    assert removed.status_code == 204
    gone = client.get(f"/v1/classes/{created['id']}", headers=auth_headers(token))
    # Token row is gone, so this is an unauthorized / missing class.
    assert gone.status_code in {401, 404}


def test_classes_are_not_listed_publicly(client):
    create_class(client)
    response = client.get("/v1/classes")
    assert response.status_code in {404, 405}
