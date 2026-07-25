"""Generate high-quality single-word clips for the Gemini engine via a carrier
sentence, so each word gets a native accent from context.

Why: Gemini TTS reads a *lone* word with an unpredictable (sometimes English)
accent, and clips its onset. Putting the word in a short carrier sentence
("La palabra es <word>" / "Le mot est <word>") makes it pronounce the word with
proper Spanish/French accent; we then use Whisper word-timestamps to cut out
just the word at its onset.

Pipeline (build-time, run in a container with ffmpeg + faster-whisper):
  carrier text -> jingo-tts /say (Gemini) -> sentence mp3
              -> faster-whisper word timestamps -> ffmpeg cut at word onset
              -> out/wN.mp3 + manifest.tsv (name, lang, word)

Then `cache_place.py` copies each clip into the service cache under the exact
key the service computes, so /say serves it. Phrases are left to direct
synthesis (they already sound natural — no carrier needed).

Env: OUT_DIR (default /out), TTS_BASE (default https://tts.libretexts.dev).
Edit WORDS for your set. Requests are throttled + retried (Gemini rate-limits
bursts)."""
import os
import re
import subprocess
import time

import requests
from faster_whisper import WhisperModel

BASE = os.environ.get("TTS_BASE", "https://tts.libretexts.dev")
OUT = os.environ.get("OUT_DIR", "/out")
CARR = os.path.join(OUT, "carriers")
os.makedirs(CARR, exist_ok=True)
LEAD, TRAIL, GEN_DELAY = 0.0, 0.12, 6  # cut at onset; small tail; throttle seconds

# (word, lang) — single words only. Phrases stay on direct synthesis.
WORDS = [("ala", "es"), ("eco", "es"), ("iglú", "es"), ("oso", "es"), ("uva", "es"),
         ("perro", "es"), ("pero", "es"), ("gato", "es"), ("casa", "es"), ("libro", "es"),
         ("mesa", "es"), ("agua", "es"), ("sol", "es"),
         ("pâte", "fr"), ("été", "fr"), ("midi", "fr"), ("mot", "fr"),
         ("où", "fr"), ("lune", "fr"), ("tu", "fr"), ("tout", "fr")]
CARRIER = {"es": "La palabra es {w}", "fr": "Le mot est {w}"}


def get_carrier(word, lang, path):
    text = CARRIER[lang].format(w=word)
    backoff, r = 8.0, None
    for _ in range(5):
        r = requests.get(f"{BASE}/say", params={"text": text, "lang": lang}, timeout=60)
        if r.status_code == 200:
            open(path, "wb").write(r.content)
            return r.elapsed.total_seconds()
        time.sleep(backoff); backoff *= 2
    raise RuntimeError(f"carrier failed {word!r}: {r.status_code if r else '??'}")


_m = WhisperModel("base", device="cpu", compute_type="int8")


def _norm(s):
    return re.sub(r"[^\wáéíóúñüàâçèêëîïôûù]", "", s.lower())


def extract(audio, word, lang, out):
    segs, _ = _m.transcribe(audio, language=lang, word_timestamps=True)
    words = [w for s in segs for w in (s.words or [])]
    idx = max((i for i, w in enumerate(words) if _norm(w.word) == _norm(word)),
              default=len(words) - 1)
    w = words[idx]
    start, end = max(0, w.start - LEAD), w.end + TRAIL
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", audio,
                    "-ss", str(start), "-to", str(end), "-b:a", "96k", out], check=True)
    return w.start, w.end


if __name__ == "__main__":
    with open(os.path.join(OUT, "manifest.tsv"), "w", encoding="utf-8") as manifest:
        for i, (word, lang) in enumerate(WORDS):
            cpath = os.path.join(CARR, f"c{i}.mp3")
            secs = get_carrier(word, lang, cpath)
            opath = os.path.join(OUT, f"w{i}.mp3")
            s, e = extract(cpath, word, lang, opath)
            manifest.write(f"w{i}.mp3\t{lang}\t{word}\n"); manifest.flush()
            print(f"  [{i:2d}] {lang} {word!r:10s} -> [{s:.2f}-{e:.2f}]", flush=True)
            if secs > 0.5:
                time.sleep(GEN_DELAY)
    print("DONE")
