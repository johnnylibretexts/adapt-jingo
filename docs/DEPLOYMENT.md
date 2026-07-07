# Deploying jingo

This walks through standing up the jingo scoring service against an existing
ADAPT deployment: obtain the model, place records, build the image, run it
on ADAPT's docker network, front it with a reverse proxy, and smoke-test it.

## Prerequisites

- **Docker** (with Compose) on the host that will run jingo.
- **An existing ADAPT instance**, with:
  - its `adapt_adapt` docker network already created (ADAPT's `docker-compose`
    creates this by default),
  - a running `minio` (or equivalent S3-compatible) container reachable on
    that network — this is where student pronunciation audio is uploaded,
  - a WeBWorK gradeback JWT secret already configured in ADAPT's own `.env`
    (the env var name in ADAPT is `WEBWORK_JWT_SECRET`).
- Enough disk for the model (~300 MB extracted) plus room for transient audio
  in `/tmp` inside the container.

## 1. Obtain the model

See [`model/README.md`](../model/README.md) for the two supported paths (the
engine's built-in `jingo-engine-model` installer, or a manual download +
CTranslate2 conversion). No model weights live in this git repo — you fetch
or build them on the deploy host.

At the end of this step you should have a directory such as:

```
/opt/libretexts/jingo/model/wav2vec2-xlsr-53-espeak-ct2/
├── model.bin
├── config.json
└── vocabulary.json
```

## 2. Place records and configure `.env`

`service/records/` (or your own copy) holds the per-exercise phonetics
records and tag maps the engine scores against — this is provider data, not
secret, but it's specific to the language packs you've imported in ADAPT
(e.g. `es/`, `fr/` subdirectories, plus `tag_map/<language>.json`). Copy or
mount the records tree onto the deploy host, e.g.:

```
/opt/libretexts/jingo/records/
├── es/
├── fr/
└── tag_map/
```

Next to your compose file, create a `.env` (never committed — it's covered
by `.gitignore`) with the required secret:

```bash
# .env  (gitignored — do not commit)
WEBWORK_JWT_SECRET=<same value as ADAPT's WEBWORK_JWT_SECRET>
```

`WEBWORK_JWT_SECRET` must be the **exact same value** ADAPT uses for its own
WeBWorK gradeback JWT signing — jingo's `answerJWT` is verified by ADAPT
using that shared secret (`service/app/jwt_util.py`). Read the value out of
ADAPT's live `.env` on your box; don't invent a new one.

The other `JINGO_*` environment variables the service reads
(`service/app/config.py`, `service/app/audio.py`, `service/app/jwt_util.py`):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `JINGO_ENGINE_MODEL_DIR` | yes | — | Path (inside the container) to the CT2 model directory from step 1 |
| `WEBWORK_JWT_SECRET` | yes | — | Shared HS256 secret for signing `answerJWT`, verified by ADAPT |
| `JINGO_RECORDS_DIR` | no | `/opt/libretexts/jingo/records` | Path (inside the container) to the records tree from above |
| `JINGO_ALLOWED_ORIGIN` | no | `https://adapt.example.org` | CORS origin allowed to call `/score` — set to your ADAPT origin |
| `JINGO_ENGINE_MAX_AUDIO_SECONDS` | no | `20` | Reject/trim attempts longer than this |
| `JINGO_AUDIO_HOST_ALLOWLIST` | no | unset (allow any host) | Comma-separated hostnames the service is allowed to fetch audio from; see Security considerations |
| `JINGO_ANSWER_JWT_TTL_SECONDS` | no | `3600` | `answerJWT` lifetime in seconds |

## 3. Build the image

The image installs the sibling `engine/` source, so **build from the repo
root**, not from inside `service/`:

```bash
cd adapt-jingo
docker build -f service/Dockerfile -t jingo:local .
```

## 4. Run it (docker compose)

Copy the example compose file next to your `.env` and model/records paths:

```bash
cd service
cp docker-compose.example.yml docker-compose.yml
```

Adjust the `environment:` block for your paths/origin, then:

```bash
docker compose up -d
```

## 5. Join the `adapt_adapt` network

This is the step most likely to be missed, and it fails **silently**.

jingo fetches the student's uploaded audio from ADAPT's object storage
(`minio`) before scoring it. That container is only resolvable from
containers attached to ADAPT's `adapt_adapt` docker network. The example
compose file already declares:

```yaml
networks: [default, adapt_adapt]
```

with `adapt_adapt` marked `external: true` (it must already exist — created
by ADAPT's own `docker compose up`, not by this repo). If jingo is ever
recreated without that network attached — e.g. a `docker run` invocation
that skips it, or an override compose file that drops the network list — the
symptom is **not** a crash:

- `/health` still reports `engine_available: true` (the model loaded fine).
- `/score` requests return normally with `status: "audio_unreachable"`, and
  the service falls back to completion credit.
- ADAPT's gradebook looks populated and correct at a glance — the student
  gets credit — but no actual phoneme scoring happened.

If you see a run of `audio_unreachable` in the jingo logs, check
`docker network inspect adapt_adapt` for the jingo container before anything
else. Never recreate the `jingo` container detached from that network.

## 6. Reverse-proxy vhost

jingo's compose binds `127.0.0.1:8000` only — it isn't exposed publicly by
itself. Put a reverse proxy in front for TLS + a stable hostname. Caddy
example:

```
jingo.example.org {
    reverse_proxy 127.0.0.1:8000
}
```

Reload Caddy after adding the block. Adjust the hostname/proxy target for
your actual reverse proxy if you're not using Caddy.

## 7. Point ADAPT at the service

In ADAPT's own configuration, set the pronunciation engine's scoring service
URL to the jingo vhost from step 6, e.g. `https://jingo.example.org`.

Set `JINGO_ALLOWED_ORIGIN` on the jingo side to ADAPT's own public origin
(e.g. `https://adapt.example.org`) — the FastAPI CORS middleware
(`service/app/main.py`) only allows browser calls to `/score` from that
origin. A mismatch here shows up as a CORS rejection in the student's
browser console, not a server-side error.

## 8. Smoke test — `/health`

```bash
curl -s https://jingo.example.org/health | jq .
```

Expect:

```json
{
  "engine_available": true,
  "model_dir": "/opt/libretexts/jingo/model/wav2vec2-xlsr-53-espeak-ct2",
  "records_dir": "/opt/libretexts/jingo/records",
  "contract": "1.1"
}
```

`engine_available: false` means the model directory in step 1 is missing or
failed `jingo_engine` construction — check the container logs and re-run
`jingo-engine-model verify --model-dir ...` from inside (or against) the
mounted path.

## 9. Smoke test — `/score` round trip

`/score` expects a `problemJWT` (opaque to jingo — it's echoed back inside
the signed `answerJWT`, ADAPT is the one that interprets it), an
`exercise_id` that has a matching record under `JINGO_RECORDS_DIR` (e.g.
`es-u1-l1-e1` for the seeded Spanish 1 pack), a `language` code (`es`, `fr`),
and an `audio_url` your jingo container can reach:

```bash
curl -s -X POST https://jingo.example.org/score \
  -H "Content-Type: application/json" \
  -d '{
    "problemJWT": "smoke-test",
    "exercise_id": "es-u1-l1-e1",
    "language": "es",
    "audio_url": "http://minio.internal/bucket/sample.wav"
  }' | jq .
```

A healthy response returns `status: "scored"` with an `overall` score, a
`phoneme_scores` breakdown in `feedback`, and a signed `answerJWT`. Any other
`status` value (`engine_unavailable`, `provider_miss`, `audio_unreachable`,
`unscoreable`) tells you which stage failed — see `service/app/main.py` and
`service/README.md` for what each one means. `provider_miss` on a real
`exercise_id` usually means the records tree from step 2 wasn't mounted or
is missing that language's directory.

## Security considerations

- **Pin `JINGO_AUDIO_HOST_ALLOWLIST` in production.** The `/score` endpoint
  fetches `audio_url` server-side (`service/app/audio.py`). By default this
  allowlist is **unset**, which means the service will fetch from any
  http(s) host — permissive on purpose so the internal `minio` hostname
  works out of the box without extra configuration. Once you know your
  storage host's exact hostname, set `JINGO_AUDIO_HOST_ALLOWLIST` to it
  (comma-separated if you have more than one, e.g. staging + prod minio) to
  close this off as an SSRF vector. Non-http(s) schemes (`file:`, `ftp:`,
  `data:`, ...) are always rejected regardless of this setting.
- **`answerJWT` expiry.** Every signed `answerJWT` carries an `exp` claim
  (`service/app/jwt_util.py`), `iat + JINGO_ANSWER_JWT_TTL_SECONDS`
  (default `3600`). Gradeback happens immediately after scoring in normal
  operation, so the default is generous; lower it if your deployment has
  reason to bound replay windows more tightly.
- **Record/exercise IDs are path-traversal validated.** `language` and
  `exercise_id` from the request body are restricted to a safe charset
  (`[A-Za-z0-9._-]+`, rejecting `.`/`..` and any path separators) before
  being joined into a filesystem path under `JINGO_RECORDS_DIR`
  (`service/app/provider.py`). Don't bypass this by constructing records
  paths yourself outside the provider.
- **Keep `WEBWORK_JWT_SECRET` out of version control.** It's read from
  `.env` (gitignored) and must match ADAPT's own value exactly. Don't put it
  in this repo, in CI config, or in any doc — reference the variable name
  only.
