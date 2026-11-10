# Lectio

Lectio helps a class turn one lecture into a shared set of notes they can check against the recording and study later, even without internet. This is the WaleLab Track 1 prototype due Thursday 12 November 2026 at 9:00 AM Africa/Lagos time.

## Current state

The contract and fixture are in place. The backend in `/backend` is a locally runnable FastAPI service with tests. The frontend in `/frontend` is still David's to create. Offline reader assets in `/offline-reader` are still David's to create. There is no public deploy. Existing Lectio was a deck; this repo is the prototype.

| File | What it is |
| --- | --- |
| `contract.md` | What to build, who builds it, data shapes, proposed routes, screens, and tests |
| `lecture.fixture.json` | Canonical demo Lecture object for frontend mocks |
| `README.md` | How to start, ownership, and Day 1 checklist |
| `backend/` | OG: FastAPI app, worker, tests, and run instructions |

David can keep building against the fixture, then point `VITE_API_BASE_URL` at `http://localhost:8000`. Backend setup is in `backend/README.md`.

## Ownership

David:

- All frontend screens in `/frontend`
- Invite token in the `X-Invite-Token` header only (read share-link `#token=` fragments, never put tokens in query strings or logs)
- Token-authenticated `fetch` of `/v1/media/{assetId}` and the export zip, then Blob object URLs for audio, images, and download; revoke object URLs when done
- In-browser `MediaRecorder` capture (user click, HTTPS or localhost) with Upload as the fallback
- Offline viewer assets, delivered as `offline-reader/index.html`, `offline-reader/assets/reader.js`, and `offline-reader/assets/reader.css`: classic script, no ES module, no `import`, no `fetch`, no CDN; manifest read from a `#lectio-manifest` `application/json` tag via `textContent`; relative media paths only
- Fixture mocks, clearly labelled "Demo fixture"
- Honest empty, loading, and error states

OG:

- Backend, worker, ranking, cleanup, transcription, jobs, storage, `GET /v1/media/{assetId}`, and the export endpoint (first local increment is in `/backend`)
- After David delivers the offline viewer assets, package the zip (inject escaped manifest into the HTML tag, add relative audio and photos, include `manifest.json` as a tools companion only)
- ffmpeg was checked during this backend increment and can encode and decode MP4/M4A, MP3, WAV, WebM, and Ogg on the development machine

Do not change shared field names or routes silently. Propose the change in `contract.md` first.

## Day 1 checklist (David)

1. Read `contract.md` and `lecture.fixture.json`.
2. Scaffold the React + Vite app in `/frontend` when you start coding (it is not in this folder yet).
3. Build Landing, Create class, and Join (pasted token or `#token=` fragment).
4. Build the class workspace and lecture list, including the empty state.
5. Build capture and upload with the required consent checkbox, Record when `MediaRecorder` is available, and Upload otherwise. Enforce the size, duration, and type limits from the contract.
6. Build compare and status: poll `GET /v1/lectures/{id}/job` and stop only when `job.status` is `succeeded` or `failed`. Refresh `GET /v1/lectures/{id}` for `job.stage`, quality, and published notes. Show `pendingRecordingId` as in-flight, not as the source of old notes. Reprocess with `{ "recordingId" }`.
7. Build notes, source highlight, quiz, and photo jump. For live API media, fetch with the header, play from a blob URL, and revoke it later. In fixture mode, use local placeholder blobs or disable playback with a visible note. Label fixture screens "Demo fixture".
8. Build the offline viewer assets as specified above. Leave a placeholder `#lectio-manifest` tag for OG to fill when packaging. Target: extract the zip and open `index.html` on a laptop. Do not claim phone opening until it is tested.
9. Mock `draft`, `processing`, and `failed` states locally. Never invent AI notes when the API or provider is missing.

When the API exists, set `VITE_API_BASE_URL`. Until then, keep mocks behind a clear fixture flag.
