# Lectio backend

Local FastAPI service for Lectio. It stores class and lecture data, accepts recordings and photos, ranks recordings, transcribes a chosen file once, and generates source-linked notes and questions.

ffmpeg must be on the PATH. The service can decode wav, mp3, m4a/mp4, webm, and ogg.

## Setup

From the `backend` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally if you have a Groq key. Do not commit `.env`. If `GROQ_API_KEY` is empty, process jobs fail honestly with "AI provider is not configured." The server will still run, and class and upload routes still work.

## Run

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Health check: `GET http://127.0.0.1:8000/health`.

A local web app can set `VITE_API_BASE_URL` to `http://localhost:8000`.

Default CORS origins: `http://localhost:5173` and `http://127.0.0.1:5173`. Change `CORS_ORIGINS` for any other exact origin. No wildcard.

Data and uploaded media go to `backend/var/` unless you set `LECTIO_DATA_DIR`.

## Tests

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

Tests use a labelled mock provider. They do not call Groq and do not need a key.

## Offline export

The zip is packaged only after these files exist:

- `offline-reader/index.html` with a `<script type="application/json" id="lectio-manifest">` tag
- `offline-reader/assets/reader.js`
- `offline-reader/assets/reader.css`

The backend injects escaped lecture JSON into that tag, adds relative `audio/` and `photos/` files, and includes `manifest.json` for tools. The reader must not fetch `manifest.json`. Until those files exist, `GET /v1/lectures/{id}/export` returns `409` `offline_reader_not_configured`.

## Deletion and retention

`DELETE` removes the lecture or class from this app's database and media folder only. Retention at an AI provider or a future host has not been verified. Do not claim deletion everywhere.

## Secrets

API credentials stay in environment variables on the server. They are not accepted from the client and are not written into the repository.
