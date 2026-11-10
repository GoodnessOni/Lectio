# Lectio

Lectio is a class study workspace. It helps students turn one lecture into a shared set of notes they can check against the recording and study later, including when they are offline.

Lectio is under active development.

## Why it is useful

When several students record the same lecture, transcribing every copy costs time and money, and the class can end up with different notes. Lectio groups those recordings into one lecture, ranks them, and transcribes a single chosen recording. The class then shares one set of notes and practice questions, with links back to moments in the recording, and can download a study pack to use without a network.

## Current status

You can run the Lectio API locally from `backend/`. It can create a class, accept an invite, store recordings and board photos, rank recordings, transcribe the chosen file once, generate notes and questions that cite real transcript segments, and package an offline export when the offline reader files are present.

The student web interface is still being built, so there is no public Lectio website yet. This is not a hosted production service.

## Getting started

To run the API on your machine, follow the setup steps in [backend/README.md](backend/README.md). You will need Python 3 and ffmpeg. Transcription and note generation also need an AI provider key in your local environment. Without a key, the server still runs, and processing jobs fail with a clear error instead of inventing notes.

## Repository

| Path | What it is |
| --- | --- |
| `backend/` | Local API, worker, tests, and technical setup |
| `contract.md` | API and data contract for the current design |
| `lecture.fixture.json` | Example lecture object for interface work |
| `frontend/` | Planned student web app |
| `offline-reader/` | Planned offline study viewer assets |

## Developer documentation

Shared field names, routes, and behavior are defined in [contract.md](contract.md). Propose changes there before renaming anything. API setup and operation are in [backend/README.md](backend/README.md). Current coverage and limits are in [backend/API_CHECKLIST.md](backend/API_CHECKLIST.md) and [backend/IMPLEMENTATION_STATUS.md](backend/IMPLEMENTATION_STATUS.md).

## Help

This repository is the project documentation while Lectio is under development. There is no separate support site yet.
