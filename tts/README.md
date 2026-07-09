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
| `TTS_ENGINE` | `kokoro` | `kokoro` or `piper`. |
| `KOKORO_MODEL_PATH` | `/opt/libretexts/tts/kokoro/kokoro-v1.0.onnx` | Kokoro ONNX model. |
| `KOKORO_VOICES_PATH` | `…/voices-v1.0.bin` | Kokoro combined voice pack. |
| `KOKORO_VOICES` | `{"es":"ef_dora","fr":"ff_siwis"}` | Language → Kokoro voice id. |
| `KOKORO_LANG_CODES` | `{"es":"es","fr":"fr-fr"}` | ADAPT lang → espeak lang (they differ for French). |
| `PIPER_VOICE_DIR` / `PIPER_VOICES` | `…/voices` · `{"es":"es_MX-ald-medium"}` | Piper voice dir + map (only if `TTS_ENGINE=piper`). |
| `TTS_DEFAULT_LANG` | `es` | Fallback language. |
| `TTS_CACHE_DIR` | `/opt/libretexts/tts/cache` | Persistent MP3 cache. |
| `TTS_ALLOWED_ORIGIN` | `*` | CORS origin (set to the ADAPT origin in production). |
| `TTS_MAX_CHARS` | `200` | Reject longer input. |
| `TTS_MP3_KBPS` | `96` | MP3 bitrate. |

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
