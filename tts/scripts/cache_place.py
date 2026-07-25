"""Place carrier-extracted word clips (from gen_carrier_words.py) into the
jingo-tts disk cache under the exact key the service computes, so /say serves
them. Run on the deploy host with the same engine/voice env as the container:

    TTS_ENGINE=polly python3 cache_place.py /path/to/words_dir

The words_dir must contain the clips + a manifest.tsv of "<file>\t<lang>\t<word>".
Keeps the service itself unchanged — this is a build-time cache-population step.

The key and the voice both come from the service's own modules (app.clip_key and
the configured provider) rather than a local copy: an earlier hand-rolled copy of
the key logic here drifted from the service (no Polly engine tier, no RATE, and a
hardcoded Gemini voice), so on a Polly + TTS_RATE box every clip it placed landed
at a key /say never looks up.
"""
import os
import shutil
import sys
import tempfile

# Import the deployed service config so the key matches exactly.
sys.path.insert(0, os.environ.get("APP_DIR", "/opt/libretexts/tts"))
from app import config  # noqa: E402
from app.clip_key import clip_key  # noqa: E402
from app.provider import build_provider  # noqa: E402

src = sys.argv[1]


def _publish(src_file: str, dest: str) -> None:
    """Copy into the cache atomically.

    A plain copy to the final name lets a concurrent /say read a half-written
    file. Stage in the destination directory (same filesystem, so os.replace is
    atomic) and only then swap it into place.
    """
    dest_dir = os.path.dirname(dest)
    os.makedirs(dest_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest_dir, suffix=".tmp")
    os.close(fd)
    try:
        shutil.copyfile(src_file, tmp)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


if __name__ == "__main__":
    provider = build_provider()
    n = 0
    with open(os.path.join(src, "manifest.tsv"), encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            fn, lang, word = line.split("\t")
            voice_id = provider.voice_id(lang) or "default"
            k = clip_key(voice_id, lang, word)
            _publish(os.path.join(src, fn),
                     os.path.join(config.CACHE_DIR, k + ".mp3"))
            print(f"  placed {lang} {word!r} [{voice_id}] -> {k[:12]}…")
            n += 1
    print(f"placed {n} clips into {config.CACHE_DIR} (engine={config.TTS_ENGINE})")
