# jingo-tts — "Hear it" exemplar-audio service

A tiny, self-hosted text-to-speech service that gives ADAPT's `pronunciation`
question a **"Hear it"** button: an exemplar (model) pronunciation a learner can
listen to before recording their own attempt.

It is deliberately open-source and self-hosted — no proprietary cloud TTS —
mirroring the jingo scorer's deployment shape. The synthesis engine is **pluggable**
behind a small provider interface ([`app/provider.py`](app/provider.py)):

| Engine (`TTS_ENGINE`) | License | Notes |
|---|---|---|
| **`kokoro`** (default) | Apache-2.0 | [Kokoro-82M](https://github.com/hexgrad/kokoro) — natural, multilingual; one model + one voice pack cover all languages. |
| `piper` | MIT | [Piper](https://github.com/OHF-Voice/piper1-gpl) — lighter/faster, one voice model per language, more robotic. |
| `gemini` | proprietary | [Google Gemini TTS](https://ai.google.dev/gemini-api/docs/speech-generation) — steered via a "say clearly and slowly" prompt; language auto-detected. **Needs `GEMINI_API_KEY`.** Not open-source — opt-in. Note the `*-preview-tts` models carry a fixed low per-minute rate cap that account tier does not lift. With caching the proprietary call happens once per clip; without a key the service is **cache-only** (serves pre-generated clips, 503 on a miss). |
| `polly` | proprietary | [Amazon Polly](https://aws.amazon.com/polly/) — natural **generative** voices with real production quotas (no preview rate cap): es-MX **Mía** (F) / Andrés (M), fr-FR **Léa** (F) / Rémi (M). **Needs an AWS IAM key pair** (`POLLY_ACCESS_KEY_ID` + `POLLY_SECRET_ACCESS_KEY`, region `us-west-2`). Requests PCM so the common pad→MP3 pipeline applies uniformly. Opt-in; without creds the service is cache-only. |

## Why on-demand instead of pre-made files

LibreTexts language books today attach **pre-generated static MP3s** to each word (batch
TTS uploaded to the CXone file store). That works but means a file per word must be
produced and managed. jingo-tts synthesizes the exemplar **on demand from the same text
that drives the question**, caches it, and serves it — so any word an instructor adds
gets audio for free, with no upload step.

## API

| Route | Description |
|---|---|
| `GET /say?text=<word>&lang=<code>` | Returns `audio/mpeg` of `text` spoken in `lang`. Cached on disk per (engine, voice, text); the first call synthesizes, repeats are served as a static file. |
| `GET /health` | `{ engine, engine_available, languages }`. |

Synthesis path: provider (resident model) → mono float32 → `ffmpeg` → MP3.

## Latency

Measured on the deployment box (CPU-only):

| Engine | Word | Short sentence |
|---|---|---|
| Kokoro (default) | ~0.4–0.5 s cold | ~0.8–0.9 s cold |
| Piper | ~0.08 s | ~0.14 s |
| **any (cached)** | **~1 ms** | **~1 ms** |

Cold latency happens at most **once per word, ever** — and the ADAPT component prefetches
on render and the demo cache is pre-warmed, so in practice the button is instant regardless
of engine. Pick the engine for **quality**, not latency.

## Configuration (environment)

| Var | Default | Meaning |
|---|---|---|
| `TTS_ENGINE` | `kokoro` | `kokoro`, `piper`, `gemini`, or `polly`. |
| `KOKORO_MODEL_PATH` | `/opt/libretexts/tts/kokoro/kokoro-v1.0.onnx` | Kokoro ONNX model. |
| `KOKORO_VOICES_PATH` | `…/voices-v1.0.bin` | Kokoro combined voice pack. |
| `KOKORO_VOICES` | `{"es":"ef_dora","fr":"ff_siwis"}` | Language → Kokoro voice id. |
| `KOKORO_LANG_CODES` | `{"es":"es","fr":"fr-fr"}` | ADAPT lang → espeak lang (they differ for French). |
| `PIPER_VOICE_DIR` / `PIPER_VOICES` | `…/voices` · `{"es":"es_MX-ald-medium"}` | Piper voice dir + map (only if `TTS_ENGINE=piper`). |
| `GEMINI_API_KEY` | — | Google API key (only if `TTS_ENGINE=gemini`). Provide via a project `.env`; never commit it. |
| `GEMINI_MODEL` / `GEMINI_VOICE` | `gemini-2.5-flash-preview-tts` · `Zephyr` | Gemini TTS model + prebuilt voice name. |
| `GEMINI_STYLE` | `"Say clearly and slowly…: "` | Instruction prefix; Gemini voices only the quoted text, which fixes rushed single words. |
| `POLLY_ACCESS_KEY_ID` / `POLLY_SECRET_ACCESS_KEY` | — | AWS IAM key pair (only if `TTS_ENGINE=polly`). Provide via `.env`; never commit. Least-privilege policy: `polly:SynthesizeSpeech` + `polly:DescribeVoices`. |
| `POLLY_REGION` / `POLLY_ENGINE` | `us-west-2` · `generative` | Region (es-MX generative lives in us-west-2) + engine tier (`generative`/`neural`/`standard`). |
| `POLLY_VOICES` / `POLLY_LANG_CODES` | `{"es":"Mia","fr":"Lea"}` · `{"es":"es-MX","fr":"fr-FR"}` | Language → Polly voice + language code. |
| `TTS_RATE` | `1.0` | Pitch-preserving playback tempo applied to **every** engine via ffmpeg `atempo` (`<1` = slower/clearer; part of the cache key, so a change regenerates clips). |
| `TTS_DEFAULT_LANG` | `es` | Fallback language. |
| `TTS_CACHE_DIR` | `/opt/libretexts/tts/cache` | Persistent MP3 cache. |
| `TTS_ALLOWED_ORIGIN` | `*` | CORS origin (set to the ADAPT origin in production). |
| `TTS_MAX_CHARS` | `200` | Reject longer input. |
| `TTS_MP3_KBPS` | `96` | MP3 bitrate. |
| `TTS_SPEED` | `0.8` | Synthesis speed; `<1` is slower/clearer (a single word at 1.0 sounds rushed). |
| `TTS_PAD_LEAD_S` / `TTS_PAD_TRAIL_S` | `0.12` / `0.30` | Silence added before/after the clip. |

> Speed and padding are part of the cache key, so changing them transparently
> invalidates old clips (delete `cache/` and re-warm to regenerate immediately).

## Voices & languages

Default is Spanish **`ef_dora`** (natural female, Latin-American-friendly) and French
**`ff_siwis`**. Kokoro's single voice pack covers many languages, so adding one is just a
`KOKORO_VOICES` (and, if the espeak code differs, `KOKORO_LANG_CODES`) entry — no extra
download. **No model weights are committed to this repo**; fetch at deploy time:

```bash
./scripts/fetch_kokoro.sh          # Kokoro model + voice pack (default engine)
# or, for the Piper engine:
./scripts/fetch_voice.sh es_MX-ald-medium
```

## Single-word quality: carrier extraction (Gemini)

Gemini reads a *lone* word with an unpredictable (sometimes English) accent and
can clip its onset. For the highest quality, generate single words inside a short
**carrier sentence** ("La palabra es _casa_" / "Le mot est _mot_") — which forces
a native accent from context — then cut out just the word using Whisper
word-timestamps. Phrases don't need this (they already carry their own context).

This is a **build-time** step (Whisper is too heavy for per-request runtime):
`scripts/gen_carrier_words.py` produces the clips + a manifest;
`scripts/cache_place.py` drops them into the service cache under the exact key
`/say` computes, so the running service serves them as normal cache hits. A word
added later falls back to direct synthesis until the generator is re-run.

## Run locally

```bash
./scripts/fetch_kokoro.sh
docker compose -f docker-compose.example.yml up -d --build
curl "http://127.0.0.1:8010/say?text=mesa&lang=es" -o mesa.mp3
```

## ADAPT integration

The `pronunciation` question shows the button when ADAPT is configured with a TTS base URL
(`PRONUNCIATION_TTS_URL` → `config('myconfig.pronunciation_tts_url')` → `window.config.pronunciationTtsUrl`
→ `<pronunciation-question :tts-url>`). The component sends only the **target word** (it strips
the `Escucha y repite:` instruction and the `— translation`). Empty URL = button hidden. See
[`../adapt-integration/INTEGRATION.md`](../adapt-integration/INTEGRATION.md).
