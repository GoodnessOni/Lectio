# Lectio contract v0.1

This file is the technical contract for Lectio: product rules, data shapes, HTTP routes, and acceptance behavior. Shared field names, status values, and routes should not change without agreement. Propose a change in this file, wait for a yes, then add a changelog line.

## Product

Lectio helps a class turn one lecture into a shared set of notes they can check against the recording and study later, even without internet. Students can upload recordings of the same lecture. Lectio ranks them, transcribes a chosen recording once, and produces notes, practice questions, and a downloadable study pack.

## Frontend and backend

Frontend (`/frontend`): React + Vite, mobile-first screens, join and invite, consent, in-browser record plus upload fallback, processing and compare UI, notes with audio source highlight, quiz, blob media playback, empty/loading/error states, and the offline viewer assets (`offline-reader/index.html`, `offline-reader/assets/reader.js`, `offline-reader/assets/reader.css`). The frontend may be developed against `lecture.fixture.json` first. Use `VITE_API_BASE_URL` (local example: `http://localhost:8000`).

Backend and AI (`/backend`): Python FastAPI plus a background worker, storage, quality ranking, basic noise cleanup, once-only transcription, note and question generation, job polling, `GET /v1/media/{assetId}`, and export zip packaging. After the offline viewer assets are present, the backend injects the escaped manifest, adds relative media, and includes `manifest.json` for tools. Secrets stay on the server. Groq is the provisional AI provider, not a promise that it is free or always available. Storage provider and deploy host are not configured yet. The API is intended to be run locally until a host is chosen. The backend requires ffmpeg (or equivalent) to decode every accepted audio type, including WebM and Ogg.

## Current limits (configurable)

Do not promise a full-hour lecture.

- At most 3 recordings per lecture.
- At most 180 seconds (3 minutes) per recording, including in-browser captures.
- At most 20 MB per uploaded or recorded file (audio or photo).
- Accepted audio: `audio/mp4` (.m4a, .mp4), `audio/mpeg` (.mp3), `audio/wav` (.wav), `audio/webm` (.webm), `audio/ogg` (.ogg, .oga). Reject other types clearly.
- Photos: `image/jpeg`, `image/png`, `image/webp`.
- One selected recording is transcribed per process run.

## Core rules

1. Same lecture is a manual grouping. A lecture belongs to one class (the course workspace). People add extra recordings to that lecture. The backend must not guess duplicates or merge lectures.
2. Rank first, transcribe once. The worker scores each recording with simple audio heuristics, chooses one (or uses a requested `recordingId`), then transcribes only that file, so we do not pay to transcribe every copy.
3. Heuristics are a guide, not a guarantee. The UI must say ranking can be wrong, and that the student should listen and override if needed.
4. Process is idempotent. A second Process call returns the existing job and does not start another transcription. To change the published recording or redo work, call Reprocess with an optional `recordingId`. There is no separate selection endpoint. A successful first process sets `revision` to 1. Later successful reprocess runs increment `revision` by 1 and replace transcript, notes, questions, cleanup, and published selection together, in one step.
5. While a job is running, uploads, photo adds, and new reprocess calls return `409` with `error.code` `lecture_processing`. Published artifacts do not change until a job succeeds. A failed reprocess keeps the previous successful revision as published.
6. Cleanup is basic noise reduction, not lecturer-voice isolation. The original file is always kept. The UI can switch between original and cleaned audio.
7. Notes and answers must point at real transcript segment ids. If a point cannot be supported, omit it or list it under `notes.unsupportedClaims`. Never invent a citation.
8. Quiz feedback is precomputed at generation time. The offline pack must not call any AI.

## The Lecture object

Shared shape. The canonical full example is `lecture.fixture.json`. Use these names exactly.

Top-level fields: `id`, `classId`, `courseCode`, `title`, `lectureDate`, `status`, `revision`, `createdAt`, `updatedAt`, `error`, `job`, `recordings`, `selection`, `cleanup`, `transcript`, `notes`, `photos`, `questions`, `export`.

`status`: `draft` | `processing` | `ready` | `failed`.

`revision` is `0` until the first successful process, then `1`, then `2`, and so on.

`error`: `null`, or `{ "code": "string", "message": "string", "retryable": true }`.

`job` is the latest job, or `null` if none has started. Compare UI may read `job.stage` and quality from `GET /v1/lectures/{id}`. Polling start and stop use `GET /v1/lectures/{id}/job` and `job.status` only, not `lecture.status` (that field can lag, and a failed reprocess can leave `lecture.status` as `ready`).

Recording:

```json
{
  "id": "rec_A1",
  "uploadedBy": "Goodness",
  "fileName": "bernoulli_front_row.m4a",
  "mimeType": "audio/mp4",
  "durationSec": 172,
  "sizeBytes": 2810000,
  "quality": {
    "score": 0.82,
    "speechRatio": 0.78,
    "noiseLevelDb": -42,
    "clippingRatio": 0.001,
    "coverageSec": 172,
    "flags": []
  },
  "selected": true,
  "selectionReason": "auto",
  "audioAssetId": "ast_rec_A1",
  "audioUrl": "/v1/media/ast_rec_A1"
}
```

`selectionReason`: `auto` | `manual` | `null` (not in the published selection). `quality` may be `null` until ranking has run, then it may appear on `GET /v1/lectures/{id}` while the job is still running. Scores are heuristic only. `quality.flags` may include `noisy`, `possibly_incomplete`, `clipping`, `low_speech`, `suspect`. If any flag is present, ask the student to listen before trusting the auto pick.

`audioUrl` and other media paths are `GET /v1/media/{assetId}` routes. They are not public files. See Media access below.

`selection` is `null` until a process has chosen a target. After that:

```json
{
  "recordingId": "rec_A1",
  "pendingRecordingId": null,
  "mode": "auto",
  "explanation": "Highest heuristic score: less background noise and longest coverage. Heuristic only, please listen and override if wrong."
}
```

`mode`: `auto` | `manual`. `recordingId` is the published choice (last successful revision). `pendingRecordingId` is the in-flight target during a job, or `null`. Never present published notes as if they came from `pendingRecordingId`. Label notes with the published `revision` and `recordingId`. During the first process (revision 0), quality and `pendingRecordingId` may appear before notes exist.

`cleanup`:

```json
{
  "applied": true,
  "method": "basic_noise_reduction",
  "cleanedAudioAssetId": "ast_rec_A1_clean",
  "originalAudioAssetId": "ast_rec_A1",
  "cleanedAudioUrl": "/v1/media/ast_rec_A1_clean",
  "originalAudioUrl": "/v1/media/ast_rec_A1"
}
```

If cleanup was skipped or failed, `applied` is `false` and the cleaned asset fields are `null`. Original asset fields still point at the kept original.

Transcript segment: `{ "id": "seg_001", "startSec": 0.0, "endSec": 14.2, "text": "..." }`. `transcript` is `null` until a successful revision exists, then `{ "language": "en", "segments": [ ... ] }`.

`notes`: `{ "sections": [ ... ], "unsupportedClaims": [] }`. Section: `{ "id", "heading", "kind", "body", "steps": ["..."], "sourceSegmentIds": ["seg_001"] }`. `kind`: `definition` | `worked_steps` | `key_point`. `steps` is required for `worked_steps`, omitted otherwise. Every section must include at least one `sourceSegmentIds` entry that exists in the transcript.

Photo: `{ "id", "fileName", "mimeType", "timestampSec", "caption", "imageAssetId", "imageUrl" }`. The student sets `timestampSec` on upload. This version does not auto-detect board times. `imageUrl` is `/v1/media/{imageAssetId}`.

Question: `{ "id", "prompt", "choices": [{ "id", "text" }], "answerId", "explanation", "sourceSegmentIds" }`. Feedback uses these fields only.

`export`: `{ "available": true, "sizeBytes": 3400000, "downloadPath": "/v1/lectures/lec_7Qm2Xa/export" }` or `{ "available": false, "sizeBytes": null, "downloadPath": null }`. Download with the invite-token header, then save the blob. Do not put the token in the download URL.

Job:

```json
{
  "id": "job_22K",
  "lectureId": "lec_7Qm2Xa",
  "status": "running",
  "stage": "transcribing",
  "revision": 1,
  "targetRecordingId": "rec_A1",
  "error": null
}
```

`job.status`: `queued` | `running` | `succeeded` | `failed`. `job.stage`: `queued` | `ranking` | `selecting` | `cleaning` | `transcribing` | `generating` | `done`. `job.revision` is the revision that will be published if this job succeeds (1 on the first success). `job.targetRecordingId` is the recording being processed, once chosen.

If a successful revision already exists and a later reprocess fails, keep `lecture.status` as `ready`, keep the previous artifacts, and set `job.status` to `failed` with `job.error`. If no successful revision exists yet, a failed process sets `lecture.status` to `failed`.

## Endpoints (proposed v0.1)

Base URL is not deployed. Local example: `http://localhost:8000`. Until these routes are available, mock them or use the fixture.

Access: send `X-Invite-Token` on every request after create or join, including media and export. Do not put the token in a query string or path. Share links use a URL fragment, for example `/join#token=...`. The frontend reads the fragment and copies it into the header. Tokens are unguessable random values. This is not production auth. There is no login. Classes are not listed publicly. There are no public raw upload paths.

CORS: allow only an explicit origin list (Vite dev origin, later the real site). That list is not configured yet.

Do not log names, tokens, or file names to the browser console. Recordings are private to class members.

### Classes

`POST /v1/classes`

Request: `{ "courseCode": "MEE 301", "title": "Fluid Mechanics", "createdByDisplayName": "Goodness" }`

Response `201`: `{ "class": { "id": "cls_4Hk9Pz", "courseCode": "MEE 301", "title": "Fluid Mechanics", "inviteToken": "tok_...", "createdAt": "2026-11-10T10:00:00Z" } }`

`POST /v1/classes/join`

Request: `{ "inviteToken": "tok_...", "displayName": "David" }`

Response `200`: `{ "class": { "id", "courseCode", "title" }, "member": { "displayName": "David" } }`

`GET /v1/classes/{classId}`

Response `200`: `{ "class": { "id", "courseCode", "title", "inviteToken" }, "lectures": [{ "id", "title", "lectureDate", "status", "revision", "updatedAt" }] }`

No endpoint lists all classes.

### Lectures

`POST /v1/classes/{classId}/lectures`

Request: `{ "title": "Week 3: Bernoulli's Equation", "lectureDate": "2026-11-09" }`

Response `201`: `{ "lecture": { ...Lecture, status "draft", revision 0, job null, empty arrays, selection null } }`

`GET /v1/lectures/{lectureId}`

Response `200`: `{ "lecture": { ...full Lecture } }`. Use this to render compare, quality, published notes, and the current `job.stage`. After ranking, quality may be present while `job.status` is still `running`.

`POST /v1/lectures/{lectureId}/recordings` (multipart)

Fields: `file` (required), `uploadedBy` (required display name).

Response `201`: `{ "recording": { ...Recording, quality null, selected false, selectionReason null } }`

Reject oversize, over-duration, wrong type, or a 4th recording with `400` and `error.code` of `file_too_large`, `duration_too_long`, `unsupported_type`, or `recording_limit`. If `lecture.status` is `processing`, return `409` `lecture_processing`.

`POST /v1/lectures/{lectureId}/photos` (multipart)

Fields: `file`, `timestampSec` (required number), `caption` (optional).

Response `201`: `{ "photo": { ...Photo } }`. Same `409` if processing.

`POST /v1/lectures/{lectureId}/process`

Optional JSON body: `{ "recordingId": "rec_A1" }` or `{}`. If `recordingId` is omitted, the worker auto-picks after ranking. If present, that choice is manual. Idempotent. Response `202`: `{ "job": { ... } }`. If a job is already running, or the lecture already has a successful revision and is `ready`, return the existing job and do not transcribe again.

Worker order: rank every recording (quality becomes visible on GET lecture), choose the highest score unless a `recordingId` was requested, set `selection.pendingRecordingId` and `job.targetRecordingId`, flag weak candidates, basic cleanup on the chosen file, transcribe that file only, generate notes and questions with source segment ids, then publish selection plus artifacts together and set `revision` to 1 on first success.

`POST /v1/lectures/{lectureId}/reprocess`

Optional JSON body: `{ "recordingId": "rec_B2" }`. If `recordingId` is present, that is the new manual target. If omitted, retry `job.targetRecordingId` from the last job, or the published `selection.recordingId` if there was no last target. Response `202`: `{ "job": { ... } }`. Sets `lecture.status` to `processing` and `selection.pendingRecordingId` to the target. Does not change published `selection.recordingId`, notes, transcript, questions, or cleanup until the job succeeds. If a job is already running, return `409` `lecture_processing`. On success, publish the new selection and artifacts in one step and increment `revision`. On failure after a successful revision already exists, leave those artifacts and that revision unchanged.

There is no `POST .../selection`. Changing the published recording is always a reprocess with `recordingId`.

`GET /v1/lectures/{lectureId}/job`

Response `200`: `{ "job": { ... } }`. Poll about every 2 seconds while `job.status` is `queued` or `running`. Stop when `job.status` is `succeeded` or `failed`. Then refresh `GET /v1/lectures/{id}` once.

`GET /v1/lectures/{lectureId}/export`

Requires the invite-token header. Response `200` with `Content-Type: application/zip` and a useful `Content-Disposition` filename, or `409` if no successful revision exists. The frontend fetches this as a blob and downloads it. Do not use a token query param.

`GET /v1/media/{assetId}`

Requires the invite-token header. The token must belong to the class that owns the asset. Response `200` is the raw file with a correct `Content-Type`. `401` if the token is missing or bad. `404` if the asset is unknown or not in that class. No public path, and no token in the query string.

HTML `<audio>` and `<img>` cannot send that header. The frontend must `fetch` with `X-Invite-Token`, `URL.createObjectURL(blob)` for the player or image, and `URL.revokeObjectURL` when leaving the lecture or replacing the blob. Fixture mode may create blobs from short local placeholders, or disable playback with a visible note. Never point `<audio src>` or `<img src>` at `/v1/media/...` directly.

`DELETE /v1/lectures/{lectureId}` and `DELETE /v1/classes/{classId}`

Response `204`. Demo deletion of that lecture, or of the class and its lectures, from our app storage as far as this prototype controls them.

Retention is provisional: data stays until a member deletes it or we take the demo down. We have not verified how long Groq or a future storage host retain copies. Do not claim deletion everywhere.

Errors: `401` bad or missing token; `404` unknown id; `409` wrong state (`lecture_processing`, or export before a successful revision); `400` validation; `500` unexpected. Body: `{ "error": { "code", "message", "retryable" } }`. A missing AI key fails the job with "AI provider is not configured." Never invent notes as a fallback.

## Offline export zip (proposed)

The zip must work after the student extracts it and opens `index.html` in a desktop browser, with no network. A `file://` page cannot reliably `fetch` a sibling `manifest.json` (browsers block it). The reader must not fetch the manifest, must not use ES modules or `import`, and must not load a CDN.

Required zip layout:

```
index.html
assets/reader.js
assets/reader.css
audio/original   (extension matches the source)
audio/cleaned    (omit if cleanup was not applied)
photos/pho_1.jpg
manifest.json    (companion for tools only; the reader must not fetch this)
```

`index.html` must embed the same manifest JSON in a script element, safely escaped, for example by writing `<` as `\u003c` so lecture text cannot close the tag:

```html
<script type="application/json" id="lectio-manifest">{ ...escaped Lecture JSON... }</script>
<script src="assets/reader.js"></script>
```

`reader.js` is a classic bundled script (`<script src>`, no `type="module"`). It reads `document.getElementById("lectio-manifest").textContent` and `JSON.parse`s it. Media URLs in the embedded manifest are relative zip paths such as `audio/original.m4a` and `photos/pho_1.jpg`. The page may use those relative paths on `<audio>` and `<img>` because they are same-folder files, not the API.

The frontend delivers `offline-reader/index.html`, `offline-reader/assets/reader.js`, and `offline-reader/assets/reader.css`, including a placeholder script tag and a comment that the backend will replace the tag body with the escaped manifest. The backend packages the zip after those files are present: inject manifest, copy media, add `manifest.json` as a tools copy.

Current target for offline use: extract the zip and open `index.html` in a laptop browser, including airplane mode. Opening an extracted zip on a phone varies by device and browser. Do not claim that path works until it is tested. A PWA install is optional later and is not promised.

## Frontend screens (mobile-first)

1. Landing. Use the two-sentence product intro above. Buttons: Create class, Join class. Join accepts a pasted token or a `#token=` fragment link.
2. Class workspace. Course name, lecture list with status, Create lecture, Copy invite link (the link uses a `#token=` fragment). Empty state: "No lectures yet. Create one and upload a recording."
3. Lecture capture, upload, and compare. Before any record or upload, a required checkbox: "I have permission from the lecturer and anyone clearly recorded to use this audio and these photos for this class demo." Leave Record and Upload disabled until it is checked. This is a UI consent step, not legal clearance. We do not claim it is. Offer Record and Upload. Record must be started by a user click. It needs a secure context (HTTPS or localhost) and microphone permission. Use `MediaRecorder` with a MIME type the browser actually reports as supported, preferring `audio/mp4` when `MediaRecorder.isTypeSupported` says so, otherwise `audio/webm` or `audio/ogg`. If Record is not available (no API, no permission, insecure page, or no supported MIME), hide or disable it and say to use Upload instead. Check size and duration before send. Upload up to 3 recordings and optional board photos (each photo needs a timestamp in seconds or mm:ss). Start Process. Poll `GET .../job` and stop only when `job.status` is `succeeded` or `failed`. Refresh `GET .../lectures/{id}` to show `job.stage`, quality cards, flags, and the short reason. Highlight the published pick, and show a pending pick separately if `pendingRecordingId` is set. A student may choose another recording and confirm Reprocess (`{ "recordingId" }`). If flags include `possibly_incomplete` or `suspect`, warn them to listen first. Disable upload, record, and reprocess while `job.status` is `queued` or `running`.
4. Notes and quiz. Play published selected audio (toggle original and cleaned when both exist) using blob object URLs from `GET /v1/media/{assetId}`. Revoke those URLs when leaving the screen. Each note section has a source control. Tapping it seeks the audio and highlights the segment text. Photos appear near their timestamp and are tappable to jump there (also via blob URLs). Quiz: choose an answer, then show precomputed correct or incorrect feedback and the explanation. A source control jumps to the segment. Do not fetch new AI text here. If a reprocess is running or has failed, keep showing the published revision and say so clearly.
5. Offline download. Enable the button when `export.available` is true. Fetch the zip with the invite-token header and save the blob. Tell the student to extract the zip and open `index.html` in a laptop browser. Do not promise phone opening until that is tested.

Honest states:

- Loading: show the real `job.stage`, not fake notes.
- Error: show `error.message`, and Retry when `retryable` is true. Retry calls process or reprocess as specified. Do not invent a result.
- Missing API or missing provider: say the backend or AI provider is not configured. Fixture mode is allowed only when labelled "Demo fixture".

## Fixture mocks

`lecture.fixture.json` is a complete `ready` lecture at `revision` 1, with a succeeded job, two recordings (one cleaner m4a, one noisier shorter webm), media endpoint paths, selection with `pendingRecordingId` null, cleanup assets, five segments, three note sections, one photo, two questions, and export metadata. Mark fixture-driven screens "Demo fixture". `/v1/media/...` paths in the fixture are illustrative. Do not treat them as public static files. Do not present fixture text as a live model result.

Also mock locally (not API): `draft` with one unranked recording; `processing` at `stage: "transcribing"` with quality filled and `pendingRecordingId` set, published notes still from the previous revision if `revision` is already 1; `failed` first run with `{ "code": "provider_not_configured", "message": "AI provider is not configured.", "retryable": false }`.

## Acceptance tests

1. Two browsers join the same class with one invite token, open the same lecture, and both see the shared master notes after one process run.
2. Upload or record a cleaner file and a noisier or shorter one, press Process once, confirm only one transcription ran, and confirm the auto pick and notes. Notes must rest on real segments, not invented citations. Audio and photos play only after a token-authenticated media fetch (except clearly labelled fixture blobs).
3. Reprocess with the other `recordingId`, confirm `revision` goes from 1 to 2 only after success, and confirm notes follow the new transcript. During the job, old notes stay visible and are still labelled as the previous recording. A failed reprocess leaves revision 1 in place.
4. Download the zip, extract it, open `index.html` in a laptop browser (including airplane mode), and use notes, audio, photos, and quiz feedback with no network and no `fetch` of `manifest.json`.
5. Trigger an error (oversize file, fourth recording, or missing provider). The UI shows the real error and does not invent notes.

## Changelog

- 2026-11-10: Documentation wording updated so the contract describes the product and API, not a competition or personal assignment. API names, routes, and behavior are unchanged.
- 2026-11-10, later the same day: v0.1 updated. Media endpoint and blob object URLs. Embedded offline manifest (no file:// fetch). Reprocess with optional `recordingId` replaces a separate selection route. Pending vs published selection. Polling stops on `job.status`. In-browser MediaRecorder plus upload fallback, with WebM and Ogg accepted. Offline viewer assets are delivered by the frontend and packaged by the backend.
- 2026-11-10: v0.1 proposed. Contract, README, and `lecture.fixture.json`.
