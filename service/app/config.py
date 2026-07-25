"""Runtime configuration read from environment. The service fails fast at
import if required vars are missing — a missing model dir or JWT secret is a
deployment error, not a runtime fallback."""
import os

MODEL_DIR = os.environ["JINGO_ENGINE_MODEL_DIR"]
RECORDS_DIR = os.environ.get("JINGO_RECORDS_DIR", "/opt/libretexts/jingo/records")
JWT_SECRET = os.environ["WEBWORK_JWT_SECRET"]  # shared with ADAPT webwork gradeback
ALLOWED_ORIGIN = os.environ.get("JINGO_ALLOWED_ORIGIN", "https://adapt.example.org")
MAX_AUDIO_SECONDS = float(os.environ.get("JINGO_ENGINE_MAX_AUDIO_SECONDS", "20"))

# Practice-mode (unauthenticated) endpoint guards.
MAX_UPLOAD_BYTES = int(os.environ.get("JINGO_MAX_UPLOAD_BYTES", str(5_000_000)))
PRACTICE_RATE_MAX = int(os.environ.get("JINGO_PRACTICE_RATE_MAX", "20"))
PRACTICE_RATE_WINDOW_S = float(os.environ.get("JINGO_PRACTICE_RATE_WINDOW_S", "60"))