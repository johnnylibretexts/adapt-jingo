# jingo.libretexts.dev

Thin FastAPI adapter around `jingo_engine` (johnnylingo-jingo 0.2.1). Scores
pronunciation attempts and returns signed answerJWTs to ADAPT via the WeBWorK
JWT gradeback path.

## Build

The image installs the sibling `engine/` source, so it must be built from the
**repo root** (not from inside `service/`):

```bash
docker build -f service/Dockerfile -t jingo:local .
```

For local/compose use, copy `docker-compose.example.yml` to `docker-compose.yml`
next to a `.env` file providing `WEBWORK_JWT_SECRET` (never commit that file).

## Runtime env
- `JINGO_ENGINE_MODEL_DIR` — path to the CT2 wav2vec2-xlsr-53-espeak-ct2 model dir (required)
- `WEBWORK_JWT_SECRET` — shared with ADAPT webwork gradeback (required; read from ADAPT .env)
- `JINGO_RECORDS_DIR` — per-exercise JSON records + tag_map (default /opt/libretexts/jingo/records)
- `JINGO_ALLOWED_ORIGIN` — CORS origin allowed to call /score (default https://adapt.libretexts.dev)

## Docker network

The compose example attaches the container to an external `adapt_adapt` network
(`networks: [default, adapt_adapt]`), in addition to its own default network.
This is required so the service can resolve ADAPT's `minio` container to fetch
student audio. If the container is created detached from `adapt_adapt`, audio
fetches silently fail (`audio_unreachable`) and scoring falls back to
completion credit — it looks fine but never actually scores. Never recreate
this service without that network attached.

## Endpoints
- `GET /health` → `{engine_available, model_dir, records_dir, contract}`
- `POST /score` `{problemJWT, exercise_id, language, audio_url}` → `{answerJWT, feedback}`

Provisional scoring (contract 1.1). No human-label validation claim.
G2P (phonemizer/espeak) is build-time only — never run in this container.
