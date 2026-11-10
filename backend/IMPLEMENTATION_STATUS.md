# Current implementation and limits

This describes the current local Lectio backend. It is tested. It is not a production service.

## What works now

- Local FastAPI app with persistent SQLite and private media files
- Contract v0.1 routes and field names
- Invite-token access for a class, including media and export
- Server-side size, duration, type, and recording-count limits
- ffmpeg decode of mp4/m4a, mp3, wav, webm, and ogg
- Heuristic ranking, then one transcription of the chosen file
- Basic noise cleanup, with the original file kept
- Idempotent process, reprocess with atomic publish, failed reprocess leaves the last good revision
- Notes and questions kept only when they cite real transcript segment ids
- Honest failure when the AI provider is missing or fails; no invented notes
- Export zip packaged only after offline-reader assets are present
- Automated tests with a labelled mock provider (no live API calls in the default test run)

## What is not available yet

- Production login, user accounts, or password reset
- A public website, HTTPS termination, or a configured production host
- Paid storage, backups, or verified deletion at an AI provider
- Live provider calls unless a key is configured in the local environment
- Ranking proven on real lecture-hall recordings (tests use short synthetic audio as a proxy)
- Lecturer-voice isolation
- A finished offline reader interface (those assets live in `offline-reader/` when added)
- Phone-tested offline opening
- Rate limiting, audit logs, or abuse monitoring beyond the current caps
- Streaming media and upload disk-spooling for large production traffic

## Later production work (not claimed now)

- Replace invite tokens with real authentication and authorization
- Host on HTTPS with an explicit CORS origin for the real site
- Confirm provider terms, retention, and a data-deletion path
- Add backups, monitoring, and a defined retention policy
- Load-test uploads and job throughput; consider a real job queue
- Re-evaluate ranking on consented classroom recordings
- Review export behavior on target laptops after the reader ships
- Secret management that is not a plain `.env` file on a laptop
