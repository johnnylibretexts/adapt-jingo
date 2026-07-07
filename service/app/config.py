"""Runtime configuration read from environment. The service fails fast at
import if required vars are missing — a missing model dir or JWT secret is a
deployment error, not a runtime fallback."""
import os

MODEL_DIR = os.environ["JINGO_ENGINE_MODEL_DIR"]
RECORDS_DIR = os.environ.get("JINGO_RECORDS_DIR", "/opt/libretexts/jingo/records")
JWT_SECRET = os.environ["WEBWORK_JWT_SECRET"]  # shared with ADAPT webwork gradeback
ALLOWED_ORIGIN = os.environ.get("JINGO_ALLOWED_ORIGIN", "https://adapt.libretexts.dev")
MAX_AUDIO_SECONDS = float(os.environ.get("JINGO_ENGINE_MAX_AUDIO_SECONDS", "20"))