"""Place carrier-extracted word clips (from gen_carrier_words.py) into the
jingo-tts disk cache under the exact key the service computes, so /say serves
them. Run on the deploy host with the same engine/voice env as the container:

    TTS_ENGINE=gemini python3 cache_place.py /path/to/words_dir

The words_dir must contain the clips + a manifest.tsv of "<file>\t<lang>\t<word>".
Keeps the service itself unchanged — this is a build-time cache-population step."""
import hashlib
import os
import shutil
import sys

# Import the deployed service config so the key matches exactly.
sys.path.insert(0, os.environ.get("APP_DIR", "/opt/libretexts/tts"))
from app import config  # noqa: E402

src = sys.argv[1]


def clip_key(lang, text):
    render = ""
    if config.TTS_ENGINE == "gemini":
        render = "|" + hashlib.sha256(config.GEMINI_STYLE.encode("utf-8")).hexdigest()[:8]
    sig = f"v2|{config.TTS_ENGINE}|{config.GEMINI_VOICE}|{lang}{render}|{text}"
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    n = 0
    with open(os.path.join(src, "manifest.tsv"), encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            fn, lang, word = line.split("\t")
            k = clip_key(lang, word)
            shutil.copy(os.path.join(src, fn), os.path.join(config.CACHE_DIR, k + ".mp3"))
            print(f"  placed {lang} {word!r} -> {k[:12]}…")
            n += 1
    print(f"placed {n} clips into {config.CACHE_DIR} "
          f"(engine={config.TTS_ENGINE}, voice={config.GEMINI_VOICE})")
