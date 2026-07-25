# built from this dir:  docker build -t jingo-tts:local .
FROM python:3.11-slim

# ffmpeg = MP3 encode; espeak-ng = grapheme->phoneme for Kokoro (es/fr/...).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Models are mounted at runtime (not baked) so the image stays small and voices
# can change without a rebuild; see docker-compose.example.yml.
ENV KOKORO_MODEL_PATH=/opt/libretexts/tts/kokoro/kokoro-v1.0.onnx \
    KOKORO_VOICES_PATH=/opt/libretexts/tts/kokoro/voices-v1.0.bin \
    TTS_CACHE_DIR=/opt/libretexts/tts/cache

EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
