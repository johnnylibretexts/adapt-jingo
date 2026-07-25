# Model acquisition

jingo scores audio with a CTranslate2 (int8) export of
[`facebook/wav2vec2-xlsr-53-espeak-cv-ft`](https://huggingface.co/facebook/wav2vec2-xlsr-53-espeak-cv-ft)
(license **Apache-2.0**). **No model weights are committed to this
repository** — this directory is empty on checkout (`model/*/` is
git-ignored) and the deployer obtains the model at deploy time.

The service expects the converted model at the path pointed to by
`JINGO_ENGINE_MODEL_DIR`, in a directory shaped like:

```
wav2vec2-xlsr-53-espeak-ct2/
├── model.bin
├── config.json
└── vocabulary.json
```

The exact filenames, sizes, and checksums required are pinned in the engine's
manifest: `engine/src/jingo_engine/assets/model-manifest.json`. The engine
verifies a model directory against that manifest before trusting it — see
`jingo_engine.model_assets.verify_model_dir`.

## Option A — the engine's built-in installer (recommended)

The engine package installs a console script, `jingo-engine-model`, and a
matching Python helper, `jingo_engine.model_assets.ensure_model_from_huggingface`.
Both download an explicitly-named archive, extract it, copy the manifest's
required files into place, and verify checksums — nothing is fetched from an
implicit default URL.

Install the engine (this also gets you the CLI):

```bash
pip install ./engine
```

Fetch and install the model into a target directory:

```bash
jingo-engine-model ensure \
  --model-dir /opt/libretexts/jingo/model/wav2vec2-xlsr-53-espeak-ct2 \
  --hf-repo   johnnyrobotai/johnnylingo-jingo-wav2vec2-xlsr-53-espeak-ct2 \
  --hf-filename wav2vec2-xlsr-53-espeak-ct2-v0.2.1.zip \
  --hf-revision main
```

This is a pre-converted CT2 archive (int8, ~261 MB zipped) hosted on Hugging
Face — not the raw `facebook/wav2vec2-xlsr-53-espeak-cv-ft` checkpoint. The
command downloads the archive, extracts it to a temp dir, copies
`model.bin`, `config.json`, and `vocabulary.json` into `--model-dir`, and
verifies each file's size and SHA-256 against the manifest before exiting
`0`. A non-zero exit / `"ok": false` means don't proceed to deploy.

You can also call this from Python (e.g. from an entrypoint script):

```python
from jingo_engine.model_assets import ensure_model_from_huggingface

ensure_model_from_huggingface(
    "/opt/libretexts/jingo/model/wav2vec2-xlsr-53-espeak-ct2",
    repo_id="johnnyrobotai/johnnylingo-jingo-wav2vec2-xlsr-53-espeak-ct2",
    filename="wav2vec2-xlsr-53-espeak-ct2-v0.2.1.zip",
    revision="main",
)
```

To re-verify an already-populated model directory (e.g. after a volume
restore) without re-downloading anything:

```bash
jingo-engine-model verify --model-dir /opt/libretexts/jingo/model/wav2vec2-xlsr-53-espeak-ct2
```

`ensure` is idempotent: if the directory already passes verification, it
reports `"status": "already_present"` and does not re-download.

## Option B — manual download + CTranslate2 conversion

If you'd rather build the CT2 artifact yourself from the original
`facebook/wav2vec2-xlsr-53-espeak-cv-ft` checkpoint instead of installing the
pre-converted archive above:

1. Download the source checkpoint from Hugging Face:

   ```bash
   pip install "huggingface_hub[cli]"
   hf download facebook/wav2vec2-xlsr-53-espeak-cv-ft --local-dir /tmp/wav2vec2-src
   ```

2. Convert to CTranslate2 int8 with the `ct2-transformers-converter` tool
   (installed alongside `ctranslate2`; also available in this repo's
   `.venv/bin/`):

   ```bash
   ct2-transformers-converter \
     --model /tmp/wav2vec2-src \
     --output_dir /opt/libretexts/jingo/model/wav2vec2-xlsr-53-espeak-ct2 \
     --quantization int8
   ```

3. Verify the result against the manifest before pointing the service at it:

   ```bash
   jingo-engine-model verify \
     --model-dir /opt/libretexts/jingo/model/wav2vec2-xlsr-53-espeak-ct2
   ```

   A manual conversion may not byte-match the pinned manifest checksums
   (converter version, quantization details, and `vocabulary.json` ordering
   can all shift the output). If `verify` fails on checksum but the required
   files are present with the right shapes, either update your local
   manifest copy or fall back to Option A for a known-good artifact.

## What the service does with it

Point `JINGO_ENGINE_MODEL_DIR` at the directory produced above (see
`docs/DEPLOYMENT.md`). The FastAPI service (`service/app/main.py`) constructs
`jingo_engine.Engine(EngineConfig(model_dir=...))` at startup; if the model
directory is missing or fails to load, `/health` reports
`engine_available: false` and `/score` falls back to completion credit
(`status: "engine_unavailable"`) rather than failing the request.

## License

- Source model (`facebook/wav2vec2-xlsr-53-espeak-cv-ft`): **Apache-2.0**.
- The converted CT2 artifact is a derived format of that model; it carries
  the same license obligations as the source. It is not redistributed in
  this git repository — only fetched/built at deploy time, as required by
  the engine's `NOTICE.md`.
