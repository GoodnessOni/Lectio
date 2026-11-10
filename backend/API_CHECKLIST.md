# API implementation checklist (contract v0.1)

Routes and JSON field names follow `contract.md`. No silent renames.

## Implemented

| Method | Path | Status |
| --- | --- | --- |
| POST | `/v1/classes` | 201 |
| POST | `/v1/classes/join` | 200 |
| GET | `/v1/classes/{classId}` | 200 |
| DELETE | `/v1/classes/{classId}` | 204 |
| POST | `/v1/classes/{classId}/lectures` | 201 |
| GET | `/v1/lectures/{lectureId}` | 200 |
| DELETE | `/v1/lectures/{lectureId}` | 204 |
| POST | `/v1/lectures/{lectureId}/recordings` | 201 multipart |
| POST | `/v1/lectures/{lectureId}/photos` | 201 multipart |
| POST | `/v1/lectures/{lectureId}/process` | 202, idempotent |
| POST | `/v1/lectures/{lectureId}/reprocess` | 202, 409 if running |
| GET | `/v1/lectures/{lectureId}/job` | 200 |
| GET | `/v1/lectures/{lectureId}/export` | 200 zip, or 409 |
| GET | `/v1/media/{assetId}` | 200, token header required |

Error body is always `{ "error": { "code", "message", "retryable" } }`.

Lecture, recording, selection, cleanup, transcript, notes, questions, photos, job, and export objects use the contract names, including `pendingRecordingId`.

Worker order: rank every recording, choose auto or requested id, set pending target, basic cleanup, transcribe that file only, generate notes and questions, validate source segment ids, publish together, set `revision` to 1 on first success.

## Documented behaviour that the contract left open, or honest additions

- `GET /health` returns `{ "ok": true }` so a client can see the server is up. It is not a product route.
- During the first process, `selection.recordingId` is `null` until publish. `pendingRecordingId` is set after the target is chosen. This matches "pending may appear before notes exist."
- `GET /v1/lectures/{id}/job` returns `{ "job": null }` when no job has started.
- A valid token for a different class yields `404`, not `401`, so we do not confirm that the id exists.
- Demo deletion is allowed for any member who has the class invite token. There is no separate owner/admin role in this prototype.
- If a successful revision exists but `offline-reader/` files are not on disk, `export.available` is `false` and `GET .../export` returns `409` with `offline_reader_not_configured`. The backend does not invent an offline UI.
- If there is no successful revision, export returns `409` `export_not_ready`.
- Upload duration allows 1.0 second of container padding on top of the 180 second limit (`LECTIO_DURATION_TOLERANCE_SEC`).
- If basic cleanup fails, the job still continues and `cleanup.applied` is `false`. The original file is kept.
- Draft lectures use empty arrays for `recordings`, `photos`, and `questions`. `notes`, `transcript`, `cleanup`, and `selection` stay `null` until a successful revision (selection may appear earlier once a target is chosen).
- CORS is an exact origin list from `CORS_ORIGINS`. There is no wildcard.
- Ranking is a simple energy, noise-floor, clipping, and relative-duration heuristic. It is not a speech recognizer and has not been tested in a real lecture hall.

## Not implemented, on purpose

- No public class listing route
- No `POST .../selection` route (reprocess with `recordingId` is the only way to change the published pick)
- No production login
- No live Groq call in this increment
