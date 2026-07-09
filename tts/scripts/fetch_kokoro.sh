#!/usr/bin/env bash
# Download the Kokoro-82M ONNX model + combined voice pack into ./kokoro
# for the jingo-tts service (default engine). Apache-2.0; ~325 MB + ~27 MB.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p kokoro
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
curl -L "$BASE/kokoro-v1.0.onnx" -o kokoro/kokoro-v1.0.onnx
curl -L "$BASE/voices-v1.0.bin" -o kokoro/voices-v1.0.bin
echo "Kokoro model in ./kokoro:"
ls -lh kokoro/
