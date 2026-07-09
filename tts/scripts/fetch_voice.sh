#!/usr/bin/env bash
# Download Piper voice model(s) into ./voices for the jingo-tts service.
# Usage:  ./scripts/fetch_voice.sh [voice_name ...]
# Default: es_MX-ald-medium (the demo Spanish voice).
set -euo pipefail

cd "$(dirname "$0")/.."
VOICES=("${@:-es_MX-ald-medium}")
mkdir -p voices

# Uses piper's own downloader (pip install piper-tts). Runs in an ephemeral
# container so no host Python is required.
docker run --rm -v "$(pwd)/voices:/voices" python:3.11-slim bash -lc "
  pip -q install piper-tts >/dev/null 2>&1
  python -m piper.download_voices ${VOICES[*]} --data-dir /voices
"
echo "Voices in ./voices:"
ls -1 voices/*.onnx 2>/dev/null || echo "  (none — download may have failed)"
