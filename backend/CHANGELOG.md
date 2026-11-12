# Lectio backend changelog

## 2026-11-10 (Africa/Lagos) - first runnable increment

Built a local FastAPI backend that matches contract v0.1 field names and routes.

Proven by automated tests (25 passed):

- Class create and join with unguessable invite tokens
- `X-Invite-Token` required after create or join, including media and export
- Cross-class access is denied (404 for a valid token from another class)
- Query-string tokens do not grant media access
- Upload limits: type sniffing, ffmpeg decode of mp4/m4a, mp3, wav, webm, and ogg, duration cap, size cap, and a hard maximum of 3 recordings
- Photos accepted as jpeg/png/webp with a student-supplied timestamp
- Storage names are opaque asset ids, not original file names
- Rank-all, then transcribe only the chosen recording (call count is 1)
- Auto pick uses a documented energy heuristic; manual `recordingId` overrides it
- Process is idempotent once a revision is ready
- Concurrent process/reprocess/upload is guarded (409 `lecture_processing`)
- Reprocess success publishes revision 2 in one step
- Failed reprocess keeps revision 1 notes, transcript, and selection
- Missing provider fails the job with "AI provider is not configured." and invents no notes
- Invalid source segment ids are dropped; unsourced note text goes to `unsupportedClaims`
- Export is honest when offline-reader assets are not present (`offline_reader_not_configured`)
- When test reader assets are supplied, the zip embeds an escaped manifest, relative media paths, and `manifest.json`, with no external zip paths
- Member deletion removes the lecture or class from this app's SQLite and media folder

Pending, not claimed as done:

- Student web interface and offline reader assets (`offline-reader/`)
- A live Groq transcription on a real consented lecture recording (no API spend in this increment; provider was not configured in this environment)
- Public deploy, paid storage, or production login
- Real lecture-hall ranking quality (tests use short synthetic audio as a proxy)
- Lecturer-voice isolation (out of scope; cleanup is basic noise reduction only)

Review pass on the same day, still 2026-11-10 (Africa/Lagos):

- Transcript text is passed to the model as delimited untrusted data, with a system instruction not to follow instructions inside it
- Groq transcription parsing now handles verbose_json segment timestamps more carefully, including string numbers
- Question `answerId` values are normalized to strings and must match a choice id, and source segment ids must exist
- Upload filenames are stored as a base name only; media paths must be opaque ids under the class folder
- SQLite access uses a connection lock and fetches rows while that lock is held
- JSON bodies are capped, and a request body limit backs the file-size cap


## 2026-11-10 (later) - documentation wording

Public and technical docs were rewritten to describe Lectio as a product. Competition, deadline, and personal assignment language was removed. API behavior is unchanged.

